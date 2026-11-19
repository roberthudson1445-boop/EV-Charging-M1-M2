#!/usr/bin/env python3
"""Build a directed demand-to-site distance matrix by inserting virtual points on OSM edges.

This script keeps the existing directed OSMnx graph intact on disk. It works on a copy,
projects the graph, snaps each point to its nearest directed edge geometry, and splits that
edge at a virtual node. A reverse edge is split at the same virtual node only when its
geometry coincides with the selected edge within a small tolerance. No reverse edges are
invented, so one-way restrictions already encoded in the graph are retained.

Outputs are written to a NEW folder/file set. Existing distance matrices and MILP inputs
are never overwritten.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd
from pyproj import Transformer
from shapely.geometry import LineString, Point
from shapely import wkt
from shapely.ops import substring

ROOT = Path(__file__).resolve().parents[1]
SITES_PATH = ROOT / "data" / "derived" / "corridor_candidate_sites.csv"
DEMAND_PATH = ROOT / "data" / "derived" / "traffic_ev_demand_scenarios" / "base" / "demand_points.csv"
GRAPH_PATH = ROOT / "data" / "raw" / "armenia_drive_graph.graphml"
OUT_DIR = ROOT / "data" / "derived" / "network_distance_validation"

DEFAULT_MAX_SNAP_M = 500.0
DEFAULT_REVERSE_MATCH_TOLERANCE_M = 1.0
ENDPOINT_NODE_TOLERANCE_M = 0.1
DEFAULT_SERVICE_LIMIT_KM = 85.0
INELIGIBLE_SENTINEL_KM = 99999.0
FORMER_NODE_REVIEW_IDS = {"M2_C016", "M2_C024", "M2_C025", "M2_C028", "M2_C035"}


def find_column(df: pd.DataFrame, candidates: list[str], label: str) -> str:
    lookup = {str(c).strip().lower(): c for c in df.columns}
    for candidate in candidates:
        if candidate.lower() in lookup:
            return lookup[candidate.lower()]
    raise ValueError(f"Could not identify {label} column. Available columns: {list(df.columns)}")


def load_points() -> pd.DataFrame:
    if not SITES_PATH.exists():
        raise FileNotFoundError(f"Sites CSV not found: {SITES_PATH}")
    if not DEMAND_PATH.exists():
        raise FileNotFoundError(f"Demand CSV not found: {DEMAND_PATH}")

    sites = pd.read_csv(SITES_PATH, encoding="utf-8-sig")
    demands = pd.read_csv(DEMAND_PATH, encoding="utf-8-sig")

    site_id = find_column(sites, ["site_id", "point_id", "id", "name"], "site ID")
    site_route = find_column(sites, ["route_id", "corridor", "route"], "site route ID")
    site_lat = find_column(sites, ["latitude", "lat", "y"], "site latitude")
    site_lon = find_column(sites, ["longitude", "lon", "lng", "x"], "site longitude")

    demand_id = find_column(
        demands,
        ["demand_id", "demand_point_id", "point_id", "location_id", "id", "name"],
        "demand ID",
    )
    demand_route = find_column(demands, ["route_id", "corridor", "route"], "demand route ID")
    demand_lat = find_column(demands, ["latitude", "lat", "y"], "demand latitude")
    demand_lon = find_column(demands, ["longitude", "lon", "lng", "x"], "demand longitude")

    site_rows = pd.DataFrame(
        {
            "point_type": "site",
            "point_id": sites[site_id].astype(str),
            "route_id": sites[site_route].astype(str),
            "latitude": pd.to_numeric(sites[site_lat], errors="coerce"),
            "longitude": pd.to_numeric(sites[site_lon], errors="coerce"),
            "chainage_km": pd.to_numeric(sites.get("chainage_km"), errors="coerce"),
        }
    )
    demand_rows = pd.DataFrame(
        {
            "point_type": "demand",
            "point_id": demands[demand_id].astype(str),
            "route_id": demands[demand_route].astype(str),
            "latitude": pd.to_numeric(demands[demand_lat], errors="coerce"),
            "longitude": pd.to_numeric(demands[demand_lon], errors="coerce"),
            "chainage_km": pd.to_numeric(demands.get("chainage_km"), errors="coerce"),
        }
    )
    points = pd.concat([site_rows, demand_rows], ignore_index=True)
    bad = points[points[["latitude", "longitude"]].isna().any(axis=1)]
    if not bad.empty:
        raise ValueError("Missing/non-numeric point coordinates:\n" + bad.to_string(index=False))
    if points["point_id"].duplicated().any():
        duplicates = points.loc[points["point_id"].duplicated(keep=False), "point_id"].tolist()
        raise ValueError(f"Point IDs must be unique across sites/demand points: {duplicates}")
    return points


def edge_geometry(graph: Any, u: Any, v: Any, key: Any, data: dict[str, Any]):
    geom = data.get("geometry")
    if isinstance(geom, str):
        try:
            geom = wkt.loads(geom)
        except Exception:
            geom = None
    if geom is not None and hasattr(geom, "project") and not geom.is_empty:
        return geom
    nu, nv = graph.nodes[u], graph.nodes[v]
    return LineString([(float(nu["x"]), float(nu["y"])), (float(nv["x"]), float(nv["y"]))])


def add_split(edge_splits: dict, edge_id: tuple, measure: float, node_id: int, x: float, y: float) -> None:
    edge_splits.setdefault(edge_id, []).append(
        {"measure": float(measure), "node_id": int(node_id), "x": float(x), "y": float(y)}
    )


def split_directed_edges(graph: nx.MultiDiGraph, edge_splits: dict) -> nx.MultiDiGraph:
    """Return a copy with each listed directed edge split at its ordered virtual nodes."""
    augmented = graph.copy()
    for (u, v, key), split_rows in edge_splits.items():
        if not augmented.has_edge(u, v, key):
            raise RuntimeError(f"Edge scheduled for splitting is missing: {(u, v, key)}")
        original_data = dict(augmented.get_edge_data(u, v, key))
        geom = edge_geometry(augmented, u, v, key, original_data)
        geom_length = float(geom.length)
        if not math.isfinite(geom_length) or geom_length <= 0:
            raise ValueError(f"Cannot split zero-length edge {(u, v, key)}")
        total_length = float(original_data.get("length", geom_length))
        if not math.isfinite(total_length) or total_length < 0:
            raise ValueError(f"Invalid length on edge {(u, v, key)}: {total_length}")

        # Sort along the geometry in its directed u->v orientation.
        ordered = sorted(split_rows, key=lambda r: (r["measure"], r["node_id"]))
        # Deduplicate an accidental repeated registration of the same virtual node.
        compact = []
        seen = set()
        for row in ordered:
            token = (round(row["measure"], 5), row["node_id"])
            if token not in seen:
                compact.append(row)
                seen.add(token)
        ordered = compact

        augmented.remove_edge(u, v, key)
        for row in ordered:
            nid = row["node_id"]
            if nid not in augmented:
                augmented.add_node(
                    nid,
                    x=float(row["x"]),
                    y=float(row["y"]),
                    street_count=2,
                    virtual=True,
                )

        positions = [(0.0, u)]
        for row in ordered:
            measure = min(max(float(row["measure"]), 0.0), geom_length)
            positions.append((measure, int(row["node_id"])))
        positions.append((geom_length, v))

        for (m0, n0), (m1, n1) in zip(positions[:-1], positions[1:]):
            delta = max(0.0, float(m1 - m0))
            if delta <= 1e-7:
                # Coincident virtual points are not expected in the current inputs.
                # Avoid introducing invalid zero-length edges into Dijkstra routing.
                continue
            part = substring(geom, m0, m1)
            if part.geom_type == "Point":
                # Defensive fallback for degenerate geometry fragments.
                continue
            attrs = dict(original_data)
            attrs["length"] = total_length * (delta / geom_length)
            attrs["geometry"] = part
            attrs["virtual_split_segment"] = True
            augmented.add_edge(n0, n1, **attrs)

    return augmented


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-snap-distance-m", type=float, default=DEFAULT_MAX_SNAP_M)
    parser.add_argument(
        "--reverse-match-tolerance-m",
        type=float,
        default=DEFAULT_REVERSE_MATCH_TOLERANCE_M,
        help="Only split a reverse directed edge when its geometry coincides within this tolerance.",
    )
    parser.add_argument("--service-limit-km", type=float, default=DEFAULT_SERVICE_LIMIT_KM)
    args = parser.parse_args()
    if args.max_snap_distance_m <= 0 or args.reverse_match_tolerance_m < 0 or args.service_limit_km <= 0:
        parser.error("Distance thresholds must be positive (reverse-match tolerance may be zero).")

    print("[1/8] Loading 58 candidate sites and base-scenario demand points...")
    points = load_points()
    sites = points[points["point_type"] == "site"].copy()
    demands = points[points["point_type"] == "demand"].copy()
    print(f"      Sites={len(sites)} | demand points={len(demands)} | total={len(points)}")

    print("[2/8] Loading the original directed OSM graph...")
    if not GRAPH_PATH.exists():
        raise FileNotFoundError(f"Directed GraphML not found: {GRAPH_PATH}")
    graph = ox.io.load_graphml(GRAPH_PATH)
    if not graph.is_directed():
        raise ValueError("Graph is not directed. Refusing to continue.")
    print(f"      Directed graph: {len(graph):,} nodes / {graph.number_of_edges():,} edges")

    print("[3/8] Projecting graph and point coordinates to metres...")
    projected = ox.project_graph(graph)
    projected_crs = projected.graph["crs"]
    to_metric = Transformer.from_crs("EPSG:4326", projected_crs, always_xy=True)
    print(f"      Projected CRS: {projected_crs}")

    print("[4/8] Snapping all 61 points to directed edge geometries...")
    edge_splits: dict[tuple, list[dict]] = {}
    point_node: dict[str, int] = {}
    snap_rows: list[dict] = []
    reverse_edge_split_count = 0
    max_snap = 0.0

    for index, row in enumerate(points.itertuples(index=False)):
        px, py = to_metric.transform(float(row.longitude), float(row.latitude))
        edge_id, snap_distance = ox.distance.nearest_edges(
            projected, X=float(px), Y=float(py), return_dist=True
        )
        u, v, key = edge_id
        data = projected.get_edge_data(u, v, key)
        if data is None:
            raise RuntimeError(f"Nearest edge not found in graph: {edge_id}")
        geom = edge_geometry(projected, u, v, key, data)
        input_point = Point(float(px), float(py))
        measure = float(geom.project(input_point))
        snap_point = geom.interpolate(measure)
        snap_distance = float(snap_distance)
        max_snap = max(max_snap, snap_distance)

        # If the projection falls at an existing endpoint, reuse that real graph node.
        # This avoids creating a virtual node beside an endpoint with no zero-length link.
        # Otherwise create a unique virtual node and split the directed edge.
        reverse_matches = []
        if measure <= ENDPOINT_NODE_TOLERANCE_M:
            routing_node_id = int(u)
            routing_node = Point(float(projected.nodes[u]["x"]), float(projected.nodes[u]["y"]))
            point_connector_m = float(input_point.distance(routing_node))
        elif float(geom.length) - measure <= ENDPOINT_NODE_TOLERANCE_M:
            routing_node_id = int(v)
            routing_node = Point(float(projected.nodes[v]["x"]), float(projected.nodes[v]["y"]))
            point_connector_m = float(input_point.distance(routing_node))
        else:
            virtual_id = -10_000_000 - index
            routing_node_id = virtual_id
            point_connector_m = snap_distance
            if snap_distance <= args.max_snap_distance_m:
                add_split(edge_splits, (u, v, key), measure, virtual_id, snap_point.x, snap_point.y)

                # If the reverse directed edge shares this physical geometry, split it
                # at the same virtual node. This retains existing bidirectional access
                # without inventing reverse edges or connecting separate carriageways.
                reverse_data = projected.get_edge_data(v, u, default={})
                for reverse_key, reverse_attrs in reverse_data.items():
                    reverse_geom = edge_geometry(projected, v, u, reverse_key, reverse_attrs)
                    reverse_measure = float(reverse_geom.project(snap_point))
                    reverse_projection = reverse_geom.interpolate(reverse_measure)
                    separation = float(reverse_projection.distance(snap_point))
                    if separation <= args.reverse_match_tolerance_m:
                        reverse_matches.append((reverse_key, reverse_measure))
                for reverse_key, reverse_measure in reverse_matches:
                    add_split(
                        edge_splits,
                        (v, u, reverse_key),
                        reverse_measure,
                        virtual_id,
                        snap_point.x,
                        snap_point.y,
                    )
                    reverse_edge_split_count += 1
        point_node[str(row.point_id)] = routing_node_id

        snap_rows.append(
            {
                "point_type": row.point_type,
                "point_id": row.point_id,
                "route_id": row.route_id,
                "input_latitude": float(row.latitude),
                "input_longitude": float(row.longitude),
                "chainage_km": row.chainage_km,
                "nearest_edge_u": str(u),
                "nearest_edge_v": str(v),
                "nearest_edge_key": str(key),
                "nearest_edge_osmid": str(data.get("osmid", "")),
                "nearest_edge_highway": str(data.get("highway", "")),
                "nearest_edge_name": str(data.get("name", "")),
                "nearest_edge_oneway": str(data.get("oneway", "")),
                "snap_to_edge_distance_m": snap_distance,
                "point_to_routing_node_connector_m": point_connector_m,
                "snap_edge_fraction_u_to_v": (measure / float(geom.length)) if geom.length else math.nan,
                "routing_node_id": routing_node_id if snap_distance <= args.max_snap_distance_m else "",
                "reverse_coincident_edges_split": len(reverse_matches),
                "snap_status": "OK" if point_connector_m <= args.max_snap_distance_m else "REVIEW_SNAP_TOO_FAR",
            }
        )

    snap_df = pd.DataFrame(snap_rows)
    too_far_points = snap_df[snap_df["point_to_routing_node_connector_m"] > args.max_snap_distance_m]
    if not too_far_points.empty:
        raise RuntimeError(
            "Some point-to-edge connectors exceed the allowed threshold; refusing to create "
            "a complete matrix. Review these points first:\n" + too_far_points.to_string(index=False)
        )

    print(f"      Maximum distance to nearest edge: {max_snap:.1f} m")
    print(f"      Reverse coincident directed edges also split: {reverse_edge_split_count}")

    print("[5/8] Creating a temporary graph with virtual edge nodes...")
    augmented = split_directed_edges(projected, edge_splits)
    print(
        f"      Augmented graph: {len(augmented):,} nodes / "
        f"{augmented.number_of_edges():,} directed edges"
    )
    missing_nodes = [pid for pid, nid in point_node.items() if nid not in augmented]
    if missing_nodes:
        raise RuntimeError(f"Virtual routing nodes missing for points: {missing_nodes}")

    print("[6/8] Running directed Dijkstra searches...")
    demand_distances: dict[str, dict] = {}
    for row in demands.itertuples(index=False):
        source = point_node[str(row.point_id)]
        demand_distances[str(row.point_id)] = nx.single_source_dijkstra_path_length(
            augmented, source=source, weight="length"
        )
    site_distances: dict[str, dict] = {}
    for row in sites.itertuples(index=False):
        source = point_node[str(row.point_id)]
        site_distances[str(row.point_id)] = nx.single_source_dijkstra_path_length(
            augmented, source=source, weight="length"
        )

    snap_lookup = snap_df.set_index("point_id").to_dict(orient="index")
    site_lookup = sites.set_index("point_id").to_dict(orient="index")
    demand_lookup = demands.set_index("point_id").to_dict(orient="index")
    matrix_rows: list[dict] = []
    for demand_id, demand_row in demand_lookup.items():
        for site_id, site_row in site_lookup.items():
            dr = str(demand_row["route_id"])
            sr = str(site_row["route_id"])
            d_snap = float(snap_lookup[demand_id]["point_to_routing_node_connector_m"])
            s_snap = float(snap_lookup[site_id]["point_to_routing_node_connector_m"])
            base = {
                "site_id": site_id,
                "demand_id": demand_id,
                "site_route_id": sr,
                "demand_route_id": dr,
                "route_id": dr if dr == sr else "",
                "site_chainage_km": site_row.get("chainage_km", math.nan),
                "demand_chainage_km": demand_row.get("chainage_km", math.nan),
                "site_snap_distance_m": s_snap,
                "demand_snap_distance_m": d_snap,
                "snap_connector_total_m": s_snap + d_snap,
                "distance_direction": "demand_to_site",
            }
            if dr != sr:
                matrix_rows.append(
                    {
                        **base,
                        "distance_km": INELIGIBLE_SENTINEL_KM,
                        "network_distance_km": math.nan,
                        "distance_site_to_demand_km": math.nan,
                        "directional_asymmetry_km": math.nan,
                        "eligible": False,
                        "status": "INELIGIBLE_CROSS_CORRIDOR",
                    }
                )
                continue

            demand_node = point_node[demand_id]
            site_node = point_node[site_id]
            d_to_s_network_m = demand_distances[demand_id].get(site_node)
            s_to_d_network_m = site_distances[site_id].get(demand_node)
            if d_to_s_network_m is None:
                matrix_rows.append(
                    {
                        **base,
                        "distance_km": INELIGIBLE_SENTINEL_KM,
                        "network_distance_km": math.nan,
                        "distance_site_to_demand_km": (
                            (float(s_to_d_network_m) + s_snap + d_snap) / 1000.0
                            if s_to_d_network_m is not None
                            else math.nan
                        ),
                        "directional_asymmetry_km": math.nan,
                        "eligible": False,
                        "status": "NO_DIRECTED_DEMAND_TO_SITE_PATH",
                    }
                )
                continue

            distance_d_to_s_km = (float(d_to_s_network_m) + d_snap + s_snap) / 1000.0
            distance_s_to_d_km = (
                (float(s_to_d_network_m) + s_snap + d_snap) / 1000.0
                if s_to_d_network_m is not None
                else math.nan
            )
            asymmetry = (
                abs(distance_d_to_s_km - distance_s_to_d_km)
                if math.isfinite(distance_s_to_d_km)
                else math.nan
            )
            matrix_rows.append(
                {
                    **base,
                    "distance_km": distance_d_to_s_km,
                    "network_distance_km": float(d_to_s_network_m) / 1000.0,
                    "distance_site_to_demand_km": distance_s_to_d_km,
                    "directional_asymmetry_km": asymmetry,
                    "eligible": True,
                    "status": "OK",
                }
            )

    matrix = pd.DataFrame(matrix_rows)
    same_corridor = matrix[matrix["site_route_id"] == matrix["demand_route_id"]]
    reachable = same_corridor[same_corridor["status"] == "OK"]
    no_path = same_corridor[same_corridor["status"] == "NO_DIRECTED_DEMAND_TO_SITE_PATH"]
    beyond = reachable[reachable["distance_km"] > args.service_limit_km]
    asymmetric = reachable[reachable["directional_asymmetry_km"] > 1.0]
    max_connector = float(snap_df["point_to_routing_node_connector_m"].max())

    print("[7/8] Writing new matrix and diagnostics (existing outputs remain untouched)...")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    matrix_path = OUT_DIR / "corridor_site_demand_distances_virtual_edge.csv"
    snaps_path = OUT_DIR / "corridor_point_virtual_edge_snap_diagnostics.csv"
    report_path = OUT_DIR / "VIRTUAL_EDGE_DIRECTED_DISTANCE_REPORT.txt"
    matrix.to_csv(matrix_path, index=False, encoding="utf-8-sig")
    snap_df.to_csv(snaps_path, index=False, encoding="utf-8-sig")

    former = snap_df[snap_df["point_id"].isin(FORMER_NODE_REVIEW_IDS)]
    report = [
        "DIRECTED VIRTUAL-EDGE DISTANCE MATRIX VALIDATION",
        "=================================================",
        f"Sites: {len(sites)}",
        f"Demand points: {len(demands)}",
        f"Matrix pairs: {len(matrix)}",
        f"Original directed graph: {len(graph):,} nodes / {graph.number_of_edges():,} edges",
        f"Augmented directed graph: {len(augmented):,} nodes / {augmented.number_of_edges():,} edges",
        f"Projected CRS: {projected_crs}",
        f"Maximum allowed point-to-edge connector: {args.max_snap_distance_m:.1f} m",
        f"Maximum observed point-to-edge connector: {max_connector:.1f} m",
        f"Reverse coincident directed edge splits: {reverse_edge_split_count}",
        f"Maximum service-distance diagnostic: {args.service_limit_km:.1f} km",
        f"Ineligible sentinel: {INELIGIBLE_SENTINEL_KM:.1f} km",
        "",
        "PAIR COUNTS",
        "-----------",
        f"Cross-corridor pairs intentionally ineligible: {int((matrix['status'] == 'INELIGIBLE_CROSS_CORRIDOR').sum())}",
        f"Same-corridor pairs: {len(same_corridor)}",
        f"Reachable directed demand-to-site pairs: {len(reachable)}",
        f"No directed demand-to-site paths: {len(no_path)}",
        f"Reachable pairs beyond {args.service_limit_km:.1f} km: {len(beyond)}",
        f"Reachable pairs with >1 km directional asymmetry: {len(asymmetric)}",
        f"Points with edge snap above threshold: {len(too_far_points)}",
        "",
        "FORMER FIVE NODE-SNAP REVIEW POINTS",
        "-----------------------------------",
    ]
    if former.empty:
        report.append("None found")
    else:
        for r in former.itertuples(index=False):
            report.append(
                f"{r.point_id}: edge distance={r.snap_to_edge_distance_m:.2f} m; "
                f"routing-node connector={r.point_to_routing_node_connector_m:.2f} m; "
                f"edge={r.nearest_edge_u}->{r.nearest_edge_v} (key {r.nearest_edge_key}); "
                f"reverse coincident edges split={r.reverse_coincident_edges_split}"
            )
    report += ["", "ROUTE-LEVEL SUMMARY", "-------------------"]
    for route_id in sorted(same_corridor["site_route_id"].dropna().unique()):
        subset = same_corridor[same_corridor["site_route_id"] == route_id]
        subset_ok = subset[subset["status"] == "OK"]
        if subset_ok.empty:
            report.append(f"{route_id}: no reachable pairs")
        else:
            report.append(
                f"{route_id}: pairs={len(subset)}, reachable={len(subset_ok)}, "
                f"min={subset_ok['distance_km'].min():.2f} km, "
                f"max={subset_ok['distance_km'].max():.2f} km, "
                f"mean={subset_ok['distance_km'].mean():.2f} km"
            )
    report += [
        "",
        "METHOD AND LIMITATIONS",
        "----------------------",
        "- Distances use the directed OSM graph and shortest-path edge length attributes.",
        "- Each point is represented by a virtual node inserted on its nearest directed edge.",
        "- A geometrically coincident reverse edge is split only if it lies within the configured tolerance.",
        "- No new reverse edges are created; existing one-way directionality is preserved.",
        "- Straight-line point-to-routing-node connector distances are added to route distance.",
        "- Points projected at an existing edge endpoint reuse that real graph node.",
        "- These connectors are proximity assumptions, not verified legal driveways or road access links.",
        "- OSM may omit restrictions, access rules, temporary closures, or recently changed roads.",
        "- Cross-corridor pairs are structurally ineligible by the current model design.",
        "- This output is a new validation matrix; it does not replace any existing MILP matrix.",
        "- Review no-path pairs, asymmetry, snap connectors, and sampled route geometry before adoption.",
    ]
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8")

    print(f"      Matrix: {matrix_path.relative_to(ROOT)}")
    print(f"      Snap diagnostics: {snaps_path.relative_to(ROOT)}")
    print(f"      Report: {report_path.relative_to(ROOT)}")
    print("[8/8] Complete")
    print("IMPORTANT: This matrix is for validation only. Do not overwrite MILP inputs until reviewed.")


if __name__ == "__main__":
    main()

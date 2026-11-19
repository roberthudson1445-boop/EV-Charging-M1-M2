#!/usr/bin/env python3
"""Build directed M1/M2 corridor routes from the local Armenia OSM PBF.

Inputs (relative to project root by default):
  data/raw/armenia-latest.osm.pbf
  data/raw/m1_m2_candidate_ways.geojson
  data/raw/official_route_waypoint_snaps.csv

Outputs:
  results/official_corridor_waypoint_anchors.csv
  results/official_corridor_leg_report.csv
  results/official_corridor_route_edges.csv
  results/official_corridor_route_segments.geojson
  results/official_M1_route.geojson
  results/official_M2_route.geojson
  results/official_corridor_summary.csv

The graph is restricted to a buffer around tagged M1/M2 candidate roads. Exact
M1/M2 references receive the lowest routing cost; nearby untagged connector
roads are allowed but penalized and reported. Driving direction restrictions
are applied by Pyrosm when the directed graph is built.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path
from typing import Any

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from pyproj import Transformer
from pyrosm import OSM
from scipy.spatial import cKDTree
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import unary_union

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PBF_DEFAULT = PROJECT_ROOT / "data" / "raw" / "armenia-latest.osm.pbf"
ROADS_DEFAULT = PROJECT_ROOT / "data" / "raw" / "m1_m2_candidate_ways.geojson"
WAYPOINTS_DEFAULT = PROJECT_ROOT / "data" / "raw" / "official_route_waypoint_snaps.csv"
OUTPUT_DEFAULT = PROJECT_ROOT / "results"
METRIC_CRS = "EPSG:32638"  # Armenia's M1/M2 corridor lies in UTM zone 38N.

# The M2 Saralanj override is the OSM neighbourhood near Saravan, Vayots Dzor,
# not one of the unrelated villages named Saralanj elsewhere in Armenia.
MANUAL_OVERRIDES: dict[tuple[str, str], tuple[float, float, str]] = {
    ("M2", "Saralanj"): (
        45.66765,
        39.70999,
        "OSM neighbourhood node 5659256801 (Saralanj near Saravan)",
    ),
    # Use the separate, nearby M2-tagged access-road candidate for Kapan,
    # rather than the large town polygon that snapped to the Syunik point.
    ("M2", "Kapan"): (
        46.404858,
        39.209006,
        "alternate Kapan candidate snap from OSM node 210231290",
    ),
    ("M2", "Syunik"): (
        46.466375,
        39.204966,
        "alternate Syunik candidate snap from OSM node 928504712",
    ),
}

# Generalized-cost multipliers. The reported route length always uses real
# edge lengths, not these weights.
HIGHWAY_FACTOR = {
    "motorway": 4.0,
    "motorway_link": 5.0,
    "trunk": 4.0,
    "trunk_link": 5.0,
    "primary": 4.5,
    "primary_link": 5.5,
    "secondary": 8.0,
    "secondary_link": 9.0,
    "tertiary": 10.0,
    "tertiary_link": 11.0,
    "unclassified": 14.0,
    "residential": 14.0,
    "service": 18.0,
}
OTHER_M_ROUTE_FACTOR = 100.0
DEFAULT_CONNECTOR_FACTOR = 14.0


def say(message: str) -> None:
    print(message, flush=True)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def route_ids_from_refs(*values: Any) -> set[str]:
    """Parse Armenian/Cyrillic/Latin spellings of M-1 and M-2 refs."""
    text = " ".join(clean_text(v) for v in values if clean_text(v))
    text = text.replace("Մ", "M").replace("М", "M").replace("м", "M")
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")
    found = re.findall(r"(?<![A-Z0-9])M\s*-?\s*(\d{1,2})(?!\d)", text.upper())
    return {f"M{x}" for x in found}


def first_text(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return clean_text(next(iter(value), ""))
    return clean_text(value)


def find_column(frame: pd.DataFrame, names: tuple[str, ...], label: str) -> str:
    for name in names:
        if name in frame.columns:
            return name
    raise ValueError(
        f"Could not identify {label} column. Available columns: {list(frame.columns)}"
    )


def project_xy(lon: float, lat: float, transformer: Transformer) -> tuple[float, float]:
    x, y = transformer.transform(lon, lat)
    return float(x), float(y)


def line_parts(geometry: Any) -> list[LineString]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry]
    if isinstance(geometry, MultiLineString):
        return list(geometry.geoms)
    if hasattr(geometry, "geoms"):
        return [g for g in geometry.geoms if isinstance(g, LineString) and not g.is_empty]
    return []


def orient_coordinates(
    geometry: Any,
    source_xy: tuple[float, float],
    target_xy: tuple[float, float],
) -> list[tuple[float, float]]:
    """Return edge coordinates oriented from its graph source to target."""
    parts = line_parts(geometry)
    if not parts:
        return [source_xy, target_xy]
    # For a segmented OSM edge, use the longest part. With nodes=True, edges
    # normally consist of one short LineString, so this is a safe fallback.
    line = max(parts, key=lambda item: item.length)
    coords = [(float(x), float(y)) for x, y, *_ in line.coords]
    if len(coords) < 2:
        return [source_xy, target_xy]
    d_forward = math.dist(coords[0], source_xy) + math.dist(coords[-1], target_xy)
    d_reverse = math.dist(coords[-1], source_xy) + math.dist(coords[0], target_xy)
    if d_reverse < d_forward:
        coords.reverse()
    return coords


def merge_route_coordinates(
    current: list[tuple[float, float]],
    edge_coordinates: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    if not current:
        return list(edge_coordinates)
    if not edge_coordinates:
        return current
    if math.dist(current[-1], edge_coordinates[0]) < 0.00002:
        current.extend(edge_coordinates[1:])
    else:
        # Preserve a visible break if source geometries are not topologically
        # coincident; a connector is never silently fabricated.
        current.extend(edge_coordinates)
    return current


def load_waypoints(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Waypoint CSV not found: {path}")
    df = pd.read_csv(path)
    required = {"route_id", "sequence_order", "waypoint_name", "snap_longitude", "snap_latitude"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Waypoint CSV is missing columns: {sorted(missing)}")

    if "selected_nearest_tagged_way" in df.columns:
        flag = df["selected_nearest_tagged_way"].astype(str).str.lower().isin(
            {"true", "1", "yes"}
        )
        df = df.loc[flag].copy()

    df["route_id"] = df["route_id"].astype(str).str.upper()
    df["sequence_order"] = pd.to_numeric(df["sequence_order"], errors="raise").astype(int)
    df = df.sort_values(["route_id", "sequence_order"]).drop_duplicates(
        ["route_id", "sequence_order"], keep="first"
    )
    df["anchor_longitude"] = pd.to_numeric(df["snap_longitude"], errors="coerce")
    df["anchor_latitude"] = pd.to_numeric(df["snap_latitude"], errors="coerce")
    df["anchor_source"] = "selected nearest tagged M1/M2 road candidate"

    for (route_id, name), (lon, lat, source) in MANUAL_OVERRIDES.items():
        mask = (df["route_id"] == route_id) & (df["waypoint_name"].astype(str) == name)
        if not mask.any():
            if route_id == "M2" and name == "Saralanj":
                new_row = {col: np.nan for col in df.columns}
                new_row.update(
                    {
                        "route_id": "M2",
                        "sequence_order": 15,
                        "waypoint_name": "Saralanj",
                        "anchor_longitude": lon,
                        "anchor_latitude": lat,
                        "anchor_source": source,
                    }
                )
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                continue
            raise ValueError(f"Expected waypoint not found for override: {route_id} {name}")
        df.loc[mask, "anchor_longitude"] = lon
        df.loc[mask, "anchor_latitude"] = lat
        df.loc[mask, "anchor_source"] = source

    df = df.sort_values(["route_id", "sequence_order"]).reset_index(drop=True)
    for route_id in ("M1", "M2"):
        route_rows = df[df.route_id == route_id]
        if route_rows.empty:
            raise ValueError(f"No waypoints found for {route_id}")
        expected = list(range(int(route_rows.sequence_order.min()), int(route_rows.sequence_order.max()) + 1))
        actual = route_rows.sequence_order.tolist()
        if actual != expected:
            raise ValueError(
                f"{route_id} waypoint sequence has missing or repeated orders: {actual}"
            )
    return df


def edge_ref_fields(data: dict[str, Any]) -> tuple[str, str]:
    ref = first_text(data.get("ref"))
    ref_en = first_text(data.get("ref:en"))
    return ref, ref_en


def edge_route_match(data: dict[str, Any], route_id: str) -> bool:
    ref, ref_en = edge_ref_fields(data)
    return route_id in route_ids_from_refs(ref, ref_en)


def edge_factor(data: dict[str, Any], route_id: str) -> float:
    ref, ref_en = edge_ref_fields(data)
    refs = route_ids_from_refs(ref, ref_en)
    if route_id in refs:
        return 1.0
    if refs:
        return OTHER_M_ROUTE_FACTOR
    highway = first_text(data.get("highway")).lower()
    return HIGHWAY_FACTOR.get(highway, DEFAULT_CONNECTOR_FACTOR)


def make_route_graph(
    osm_graph: nx.MultiDiGraph,
    route_id: str,
    route_buffer: Any,
    transformer: Transformer,
) -> tuple[nx.DiGraph, cKDTree, list[Any], dict[Any, tuple[float, float]], dict[Any, float]]:
    """Create a directed, route-weighted simple graph and route-node index."""
    graph = nx.DiGraph()
    route_nodes: set[Any] = set()
    coords: dict[Any, tuple[float, float]] = {}
    route_node_distances: dict[Any, float] = {}

    for node_id, data in osm_graph.nodes(data=True):
        lon = data.get("x", data.get("lon"))
        lat = data.get("y", data.get("lat"))
        if lon is not None and lat is not None:
            coords[node_id] = (float(lon), float(lat))

    for u, v, key, data in osm_graph.edges(keys=True, data=True):
        geom = data.get("geometry")
        if geom is not None and not geom.is_empty:
            try:
                if not geom.intersects(route_buffer):
                    continue
            except Exception:
                pass
        else:
            # Nodes are guaranteed to have coordinates for driving edges.
            if u not in coords or v not in coords:
                continue
            lon_mid = (coords[u][0] + coords[v][0]) / 2
            lat_mid = (coords[u][1] + coords[v][1]) / 2
            mid = Point(lon_mid, lat_mid)
            if not mid.within(route_buffer):
                continue

        try:
            length_m = float(data.get("length", 0.0))
        except (TypeError, ValueError):
            length_m = 0.0
        if not math.isfinite(length_m) or length_m <= 0:
            if geom is not None and not geom.is_empty:
                # Geometry CRS is WGS84; estimate length in the local metric CRS.
                gx = gpd.GeoSeries([geom], crs="EPSG:4326").to_crs(METRIC_CRS).iloc[0]
                length_m = float(gx.length)
            elif u in coords and v in coords:
                ux, uy = project_xy(*coords[u], transformer)
                vx, vy = project_xy(*coords[v], transformer)
                length_m = math.dist((ux, uy), (vx, vy))
        if length_m <= 0 or not math.isfinite(length_m):
            continue

        factor = edge_factor(data, route_id)
        weight = length_m * factor
        edge_record = dict(data)
        edge_record.update(
            {
                "length_m": length_m,
                "weight": weight,
                "route_match": edge_route_match(data, route_id),
                "route_factor": factor,
            }
        )
        previous = graph.get_edge_data(u, v)
        if previous is None or weight < previous["weight"]:
            graph.add_edge(u, v, **edge_record)
        if edge_route_match(data, route_id):
            route_nodes.add(u)
            route_nodes.add(v)

    usable_nodes = [node for node in route_nodes if node in coords]
    if len(usable_nodes) < 2:
        raise RuntimeError(
            f"Could not identify enough {route_id}-tagged network nodes inside its corridor buffer."
        )
    xy = np.asarray(
        [project_xy(*coords[node], transformer) for node in usable_nodes], dtype=float
    )
    tree = cKDTree(xy)
    return graph, tree, usable_nodes, coords, {
        node: 0.0 for node in usable_nodes
    }


def snap_waypoints_to_graph(
    waypoints: pd.DataFrame,
    route_id: str,
    tree: cKDTree,
    route_nodes: list[Any],
    transformer: Transformer,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    subset = waypoints[waypoints.route_id == route_id].sort_values("sequence_order")
    for row in subset.itertuples(index=False):
        lon = float(row.anchor_longitude)
        lat = float(row.anchor_latitude)
        point_xy = project_xy(lon, lat, transformer)
        distance, index = tree.query(point_xy, k=1)
        node_id = route_nodes[int(index)]
        rows.append(
            {
                "route_id": route_id,
                "sequence_order": int(row.sequence_order),
                "waypoint_name": str(row.waypoint_name),
                "anchor_longitude": lon,
                "anchor_latitude": lat,
                "anchor_source": str(row.anchor_source),
                "network_node": node_id,
                "network_snap_distance_m": float(distance),
            }
        )
    return pd.DataFrame(rows)


def get_node_xy(graph: nx.DiGraph, node_id: Any, coords: dict[Any, tuple[float, float]]) -> tuple[float, float]:
    if node_id in coords:
        return coords[node_id]
    data = graph.nodes[node_id]
    return (float(data.get("x", data.get("lon"))), float(data.get("y", data.get("lat"))))


def route_one_corridor(
    route_id: str,
    graph: nx.DiGraph,
    anchors: pd.DataFrame,
    coords: dict[Any, tuple[float, float]],
    transformer: Transformer,
) -> tuple[pd.DataFrame, list[dict[str, Any]], list[tuple[float, float]], dict[str, Any]]:
    leg_rows: list[dict[str, Any]] = []
    edge_rows: list[dict[str, Any]] = []
    route_coordinates: list[tuple[float, float]] = []
    cumulative_m = 0.0
    all_route_km = 0.0
    all_connector_km = 0.0
    all_other_ref_km = 0.0
    completed_legs = 0
    failures = 0

    for i in range(len(anchors) - 1):
        a = anchors.iloc[i]
        b = anchors.iloc[i + 1]
        source = a.network_node
        target = b.network_node
        source_lonlat = get_node_xy(graph, source, coords)
        target_lonlat = get_node_xy(graph, target, coords)
        sx, sy = project_xy(*source_lonlat, transformer)
        tx, ty = project_xy(*target_lonlat, transformer)
        straight_km = math.dist((sx, sy), (tx, ty)) / 1000.0

        try:
            path = nx.shortest_path(graph, source=source, target=target, weight="weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            failures += 1
            leg_rows.append(
                {
                    "route_id": route_id,
                    "leg_order": i + 1,
                    "from_waypoint": a.waypoint_name,
                    "to_waypoint": b.waypoint_name,
                    "status": "NO_DIRECTED_PATH",
                    "straight_distance_km": straight_km,
                    "route_distance_km": np.nan,
                    "tagged_route_km": np.nan,
                    "connector_km": np.nan,
                    "other_M_route_km": np.nan,
                    "tagged_share": np.nan,
                    "detour_ratio": np.nan,
                    "edge_count": 0,
                }
            )
            continue

        leg_distance = 0.0
        leg_route = 0.0
        leg_connector = 0.0
        leg_other = 0.0
        leg_edge_count = 0
        for edge_index, (u, v) in enumerate(zip(path[:-1], path[1:]), start=1):
            data = graph.get_edge_data(u, v)
            if data is None:
                continue
            length_m = float(data["length_m"])
            route_match = bool(data.get("route_match", False))
            ref, ref_en = edge_ref_fields(data)
            refs = route_ids_from_refs(ref, ref_en)
            if route_match:
                leg_route += length_m
                all_route_km += length_m / 1000.0
                edge_class = "tagged_" + route_id
            elif refs:
                leg_other += length_m
                all_other_ref_km += length_m / 1000.0
                edge_class = "other_M_route"
            else:
                leg_connector += length_m
                all_connector_km += length_m / 1000.0
                edge_class = "untagged_connector"

            geom = data.get("geometry")
            source_xy = get_node_xy(graph, u, coords)
            target_xy = get_node_xy(graph, v, coords)
            oriented = orient_coordinates(geom, source_xy, target_xy)
            route_coordinates = merge_route_coordinates(route_coordinates, oriented)

            edge_rows.append(
                {
                    "route_id": route_id,
                    "leg_order": i + 1,
                    "from_waypoint": a.waypoint_name,
                    "to_waypoint": b.waypoint_name,
                    "edge_order_in_leg": edge_index,
                    "from_node": u,
                    "to_node": v,
                    "osm_way_id": first_text(data.get("osmid", data.get("id"))),
                    "ref": ref,
                    "ref_en": ref_en,
                    "highway": first_text(data.get("highway")),
                    "name": first_text(data.get("name")),
                    "edge_class": edge_class,
                    "length_m": length_m,
                    "chainage_start_km": cumulative_m / 1000.0,
                    "chainage_end_km": (cumulative_m + length_m) / 1000.0,
                }
            )
            cumulative_m += length_m
            leg_distance += length_m
            leg_edge_count += 1

        tagged_share = leg_route / leg_distance if leg_distance > 0 else 0.0
        detour_ratio = leg_distance / (straight_km * 1000.0) if straight_km > 0 else np.nan
        status = "OK"
        if tagged_share < 0.50:
            status = "REVIEW_LOW_TAG_SHARE"
        if math.isfinite(detour_ratio) and detour_ratio > 4.5:
            status = "REVIEW_HIGH_DETOUR"
        if float(a.network_snap_distance_m) > 1000 or float(b.network_snap_distance_m) > 1000:
            status = "REVIEW_WAYPOINT_SNAP"

        leg_rows.append(
            {
                "route_id": route_id,
                "leg_order": i + 1,
                "from_waypoint": a.waypoint_name,
                "to_waypoint": b.waypoint_name,
                "status": status,
                "straight_distance_km": straight_km,
                "route_distance_km": leg_distance / 1000.0,
                "tagged_route_km": leg_route / 1000.0,
                "connector_km": leg_connector / 1000.0,
                "other_M_route_km": leg_other / 1000.0,
                "tagged_share": tagged_share,
                "detour_ratio": detour_ratio,
                "edge_count": leg_edge_count,
            }
        )
        completed_legs += 1

    route_km = cumulative_m / 1000.0
    summary = {
        "route_id": route_id,
        "waypoint_count": len(anchors),
        "legs_total": max(len(anchors) - 1, 0),
        "legs_completed": completed_legs,
        "legs_failed": failures,
        "route_distance_km": route_km,
        "tagged_route_km": all_route_km,
        "untagged_connector_km": all_connector_km,
        "other_M_route_km": all_other_ref_km,
        "tagged_share": all_route_km / route_km if route_km else 0.0,
        "status": "COMPLETE" if failures == 0 else "PARTIAL - missing directed legs",
    }
    return pd.DataFrame(leg_rows), edge_rows, route_coordinates, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pbf", type=Path, default=PBF_DEFAULT)
    parser.add_argument("--roads", type=Path, default=ROADS_DEFAULT)
    parser.add_argument("--waypoints", type=Path, default=WAYPOINTS_DEFAULT)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    parser.add_argument("--buffer-km", type=float, default=4.0,
                        help="Road-network buffer around tagged M1/M2 ways (default: 4 km).")
    parser.add_argument("--max-anchor-snap-km", type=float, default=5.0,
                        help="Warn when an anchor must snap farther than this distance.")
    args = parser.parse_args()

    for path in (args.pbf, args.roads, args.waypoints):
        if not path.exists():
            raise FileNotFoundError(f"Required input not found: {path}")
    args.output.mkdir(parents=True, exist_ok=True)

    say("[1/7] Loading official waypoint anchors...")
    waypoints = load_waypoints(args.waypoints)
    say(f"      M1 waypoints: {(waypoints.route_id == 'M1').sum()}; M2 waypoints: {(waypoints.route_id == 'M2').sum()}")

    say("[2/7] Loading M1/M2 reference geometries and building corridor buffers...")
    roads = gpd.read_file(args.roads)
    if roads.crs is None:
        roads = roads.set_crs("EPSG:4326")
    roads = roads.to_crs(METRIC_CRS)
    if "route_id" not in roads.columns:
        raise ValueError("Candidate road GeoJSON must contain route_id.")
    route_buffers: dict[str, Any] = {}
    route_buffers_wgs: dict[str, Any] = {}
    for route_id in ("M1", "M2"):
        route_lines = roads.loc[roads.route_id.astype(str).str.upper() == route_id, "geometry"]
        if route_lines.empty:
            raise ValueError(f"No tagged road geometries found for {route_id}.")
        route_buffers[route_id] = unary_union(route_lines.tolist()).buffer(args.buffer_km * 1000.0)
        route_buffers_wgs[route_id] = gpd.GeoSeries(
            [route_buffers[route_id]], crs=METRIC_CRS
        ).to_crs("EPSG:4326").iloc[0]
        say(f"      {route_id}: {len(route_lines):,} tagged features; buffer={args.buffer_km:.1f} km")
    combined_buffer = unary_union([route_buffers["M1"], route_buffers["M2"]])

    say("[3/7] Reading the directed driving network from the Armenia PBF...")
    osm = OSM(str(args.pbf))
    nodes, edges = osm.get_network(
        network_type="driving",
        nodes=True,
        extra_attributes=["ref", "ref:en", "name"],
    )
    say(f"      OSM driving network: {len(nodes):,} nodes / {len(edges):,} directed source segments")

    say("[4/7] Keeping only road segments near the M1/M2 corridor...")
    edges_metric = edges.to_crs(METRIC_CRS)
    keep_mask = edges_metric.geometry.intersects(combined_buffer)
    corridor_edges = edges.loc[keep_mask].copy()
    del edges_metric, keep_mask
    say(f"      Corridor subnetwork: {len(corridor_edges):,} source segments")
    if corridor_edges.empty:
        raise RuntimeError("No driving-network edges intersect the selected corridor buffer.")

    say("[5/7] Building a directed graph (one-way rules respected)...")
    graph_multi = osm.to_graph(
        nodes,
        corridor_edges,
        graph_type="networkx",
        network_type="driving",
        retain_all=True,
        simplify=False,
        osmnx_compatible=True,
    )
    say(f"      Directed graph: {graph_multi.number_of_nodes():,} nodes / {graph_multi.number_of_edges():,} edges")

    transformer = Transformer.from_crs("EPSG:4326", METRIC_CRS, always_xy=True)
    all_anchor_frames: list[pd.DataFrame] = []
    all_leg_frames: list[pd.DataFrame] = []
    all_edge_rows: list[dict[str, Any]] = []
    all_route_geo_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []

    say("[6/7] Routing each consecutive official waypoint pair...")
    for route_id in ("M1", "M2"):
        say(f"      Preparing {route_id} weighted graph...")
        graph, tree, route_nodes, coords, _ = make_route_graph(
            graph_multi, route_id, route_buffers_wgs[route_id], transformer
        )
        say(f"      {route_id} graph: {graph.number_of_nodes():,} nodes / {graph.number_of_edges():,} directed edges")
        anchors = snap_waypoints_to_graph(
            waypoints, route_id, tree, route_nodes, transformer
        )
        anchors["anchor_snap_warning"] = anchors.network_snap_distance_m > 1000
        if (anchors.network_snap_distance_m > args.max_anchor_snap_km * 1000).any():
            far = anchors.loc[
                anchors.network_snap_distance_m > args.max_anchor_snap_km * 1000,
                ["waypoint_name", "network_snap_distance_m"],
            ]
            say(f"      WARNING: {route_id} anchors farther than {args.max_anchor_snap_km:g} km from a tagged route node:\n{far.to_string(index=False)}")
        all_anchor_frames.append(anchors)

        legs, edge_rows, coords_route, summary = route_one_corridor(
            route_id, graph, anchors, coords, transformer
        )
        all_leg_frames.append(legs)
        all_edge_rows.extend(edge_rows)
        summaries.append(summary)

        if summary["legs_failed"] == 0 and len(coords_route) >= 2:
            route_line = LineString(coords_route)
            all_route_geo_rows.append(
                {
                    "route_id": route_id,
                    "route_distance_km": summary["route_distance_km"],
                    "tagged_share": summary["tagged_share"],
                    "status": summary["status"],
                    "geometry": route_line,
                }
            )
        say(
            f"      {route_id}: {summary['route_distance_km']:.2f} km; "
            f"tagged share {summary['tagged_share']:.1%}; "
            f"{summary['legs_failed']} failed legs"
        )

    say("[7/7] Saving route, chainage, and diagnostic files...")
    anchor_df = pd.concat(all_anchor_frames, ignore_index=True)
    leg_df = pd.concat(all_leg_frames, ignore_index=True)
    edge_df = pd.DataFrame(all_edge_rows)
    summary_df = pd.DataFrame(summaries)

    anchor_df.to_csv(args.output / "official_corridor_waypoint_anchors.csv", index=False, encoding="utf-8-sig")
    leg_df.to_csv(args.output / "official_corridor_leg_report.csv", index=False, encoding="utf-8-sig")
    edge_df.to_csv(args.output / "official_corridor_route_edges.csv", index=False, encoding="utf-8-sig")
    summary_df.to_csv(args.output / "official_corridor_summary.csv", index=False, encoding="utf-8-sig")

    if all_route_geo_rows:
        routes_gdf = gpd.GeoDataFrame(all_route_geo_rows, geometry="geometry", crs="EPSG:4326")
        routes_gdf.to_file(args.output / "official_corridor_route_segments.geojson", driver="GeoJSON")
        for route_id in ("M1", "M2"):
            single = routes_gdf[routes_gdf.route_id == route_id]
            if not single.empty:
                single.to_file(args.output / f"official_{route_id}_route.geojson", driver="GeoJSON")

    print("\nROUTE SUMMARY")
    print(summary_df.to_string(index=False))
    print("\nLEG DIAGNOSTICS")
    print(
        leg_df[[
            "route_id", "leg_order", "from_waypoint", "to_waypoint", "status",
            "route_distance_km", "tagged_share", "detour_ratio",
        ]].to_string(index=False)
    )
    print(f"\nSaved outputs to: {args.output}")
    print("IMPORTANT: These are OSM-derived candidate routes. Review every flagged leg before using chainage in the MILP.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # Keep command-line failures readable for Windows users.
        print(f"ERROR: {exc}", file=sys.stderr)
        raise

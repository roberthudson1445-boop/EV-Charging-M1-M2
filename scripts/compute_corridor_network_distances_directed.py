"""Compute route-aware, direction-respecting distances for the Armenia M1/M2 case.

The model distance is the estimated one-way driving distance from each demand
point to each candidate charging site.  It is computed on the original directed
OSM driving graph, respecting one-way streets.  Straight-line snap connectors
from input coordinates to the nearest graph nodes are reported separately and
added to the driving distance only as a screening approximation.

This script does NOT prove legal/site access.  Review snap diagnostics and
route paths before using the matrix in an investment recommendation.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

INELIGIBLE_DISTANCE_DEFAULT_KM = 99_999.0


def read_points(path: Path, id_column: str) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {id_column, "latitude", "longitude", "route_id"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path.name} is missing required columns: {sorted(missing)}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{path.name} contains no rows")
    seen: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        identifier = (row.get(id_column) or "").strip()
        if not identifier or identifier in seen:
            raise ValueError(f"{path.name}:{row_number}: {id_column} must be non-empty and unique")
        seen.add(identifier)
        try:
            lat = float(row["latitude"])
            lon = float(row["longitude"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{path.name}:{row_number}: invalid latitude/longitude") from exc
        if not math.isfinite(lat) or not -90 <= lat <= 90:
            raise ValueError(f"{path.name}:{row_number}: latitude out of range: {lat}")
        if not math.isfinite(lon) or not -180 <= lon <= 180:
            raise ValueError(f"{path.name}:{row_number}: longitude out of range: {lon}")
        route = (row.get("route_id") or "").strip().upper()
        if route not in {"M1", "M2"}:
            raise ValueError(f"{path.name}:{row_number}: route_id must be M1 or M2, got {route!r}")
        row["route_id"] = route
    return rows


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Geodesic great-circle distance on a spherical Earth, in metres."""
    radius = 6_371_008.8
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * radius * math.asin(min(1.0, math.sqrt(a)))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sites",
        default="data/derived/corridor_candidate_sites.csv",
        help="Candidate sites CSV with site_id, route_id, latitude, longitude",
    )
    parser.add_argument(
        "--demands",
        default="data/derived/traffic_ev_demand_scenarios/base/demand_points.csv",
        help="Demand CSV with demand_id, route_id, latitude, longitude",
    )
    parser.add_argument(
        "--graph",
        default="data/raw/armenia_drive_graph.graphml",
        help="Directed OSMnx driving GraphML built from the Armenia road network",
    )
    parser.add_argument(
        "--output-dir",
        default="data/derived/network_distance_validation",
        help="New output directory; existing model distances are not overwritten",
    )
    parser.add_argument(
        "--max-snap-m",
        type=float,
        default=1000.0,
        help="If either point is farther than this from the nearest driving node, mark pair ineligible",
    )
    parser.add_argument(
        "--service-limit-km",
        type=float,
        default=85.0,
        help="Current model maximum service distance, used only for diagnostic flagging",
    )
    parser.add_argument(
        "--ineligible-distance-km",
        type=float,
        default=INELIGIBLE_DISTANCE_DEFAULT_KM,
        help="Finite sentinel used for cross-corridor, unsnapped, or unreachable pairs",
    )
    args = parser.parse_args()

    if args.max_snap_m <= 0 or args.service_limit_km <= 0 or args.ineligible_distance_km <= args.service_limit_km:
        raise SystemExit("max-snap-m and service-limit-km must be positive; ineligible-distance-km must exceed service limit")

    sites_path = Path(args.sites)
    demands_path = Path(args.demands)
    graph_path = Path(args.graph)
    output_dir = Path(args.output_dir)
    if not graph_path.exists():
        raise FileNotFoundError(
            f"Directed driving graph not found: {graph_path}. Check data/raw for the GraphML created by download_armenia_drive_graph.py."
        )

    print("[1/7] Loading candidate sites and the selected demand scenario...")
    sites = read_points(sites_path, "site_id")
    demands = read_points(demands_path, "demand_id")
    print(f"      Sites={len(sites)} | demand points={len(demands)}")

    try:
        import networkx as nx
        import osmnx as ox
        from pyproj import CRS, Transformer
    except ImportError as exc:
        raise SystemExit('Requires NetworkX, OSMnx and pyproj. Install with: python -m pip install -e ".[geospatial]"') from exc

    print("[2/7] Loading and checking the original directed OSM driving graph...")
    graph = ox.io.load_graphml(filepath=graph_path)
    if not graph.is_directed():
        raise ValueError(
            "The supplied GraphML is undirected. This script deliberately refuses to use it; "
            "provide the original directed OSM driving GraphML so one-way restrictions are respected."
        )
    if graph.number_of_nodes() == 0 or graph.number_of_edges() == 0:
        raise ValueError("The OSM driving graph is empty")
    missing_length = 0
    edge_iter = graph.edges(keys=True, data=True) if graph.is_multigraph() else graph.edges(data=True)
    for edge in edge_iter:
        data = edge[-1]
        if "length" not in data:
            missing_length += 1
            if missing_length >= 10:
                break
    if missing_length:
        raise ValueError("The directed graph has edges without a 'length' attribute; rebuild the OSMnx graph with edge lengths")
    print(f"      Directed graph: {graph.number_of_nodes():,} nodes / {graph.number_of_edges():,} directed edges")

    graph_crs = CRS.from_user_input(graph.graph.get("crs", "EPSG:4326"))
    to_graph = Transformer.from_crs("EPSG:4326", graph_crs, always_xy=True)
    to_wgs84 = Transformer.from_crs(graph_crs, "EPSG:4326", always_xy=True)

    all_points: list[dict[str, Any]] = []
    for kind, rows, id_col in (("site", sites, "site_id"), ("demand", demands, "demand_id")):
        for row in rows:
            all_points.append({
                "kind": kind,
                "point_id": row[id_col],
                "route_id": row["route_id"],
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "chainage_km": row.get("chainage_km", ""),
            })

    print("[3/7] Snapping site and demand coordinates to nearest graph nodes...")
    xs_wgs = np.array([p["longitude"] for p in all_points], dtype=float)
    ys_wgs = np.array([p["latitude"] for p in all_points], dtype=float)
    xs_graph, ys_graph = to_graph.transform(xs_wgs, ys_wgs)
    nearest_nodes = ox.distance.nearest_nodes(graph, X=np.asarray(xs_graph), Y=np.asarray(ys_graph))

    point_info: dict[tuple[str, str], dict[str, Any]] = {}
    snap_rows: list[dict[str, Any]] = []
    for point, node in zip(all_points, nearest_nodes):
        node_data = graph.nodes[node]
        try:
            node_x = float(node_data["x"])
            node_y = float(node_data["y"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Graph node {node!r} lacks valid x/y coordinates") from exc
        node_lon, node_lat = to_wgs84.transform(node_x, node_y)
        snap_m = haversine_m(point["latitude"], point["longitude"], float(node_lat), float(node_lon))
        info = {
            **point,
            "nearest_node_id": str(node),
            "nearest_node_native": node,
            "node_latitude": float(node_lat),
            "node_longitude": float(node_lon),
            "snap_distance_m": snap_m,
            "snap_ok": snap_m <= args.max_snap_m,
        }
        point_info[(point["kind"], point["point_id"])] = info
        snap_rows.append({
            "point_type": point["kind"],
            "point_id": point["point_id"],
            "route_id": point["route_id"],
            "input_latitude": point["latitude"],
            "input_longitude": point["longitude"],
            "nearest_node_id": str(node),
            "nearest_node_latitude": float(node_lat),
            "nearest_node_longitude": float(node_lon),
            "snap_distance_m": round(snap_m, 2),
            "snap_status": "OK" if snap_m <= args.max_snap_m else "REVIEW_SNAP_TOO_FAR",
            "chainage_km": point["chainage_km"],
        })
    print(f"      Points snapped: {len(snap_rows)} | snap threshold={args.max_snap_m:.0f} m")

    print("[4/7] Computing one-to-many directed shortest paths...")
    reverse_graph = graph.reverse(copy=False)
    demand_forward_lengths: dict[str, dict[Any, float]] = {}
    demand_reverse_lengths: dict[str, dict[Any, float]] = {}
    for demand in demands:
        demand_info = point_info[("demand", demand["demand_id"])]
        native_node = demand_info["nearest_node_native"]
        if native_node not in demand_forward_lengths:
            demand_forward_lengths[native_node] = nx.single_source_dijkstra_path_length(graph, native_node, weight="length")
            # Distances from demand to a site on reversed graph correspond to site -> demand in the original graph.
            demand_reverse_lengths[native_node] = nx.single_source_dijkstra_path_length(reverse_graph, native_node, weight="length")

    print("[5/7] Building route-aware site-demand matrix...")
    matrix_rows: list[dict[str, Any]] = []
    counters = defaultdict(int)
    for demand in demands:
        demand_info = point_info[("demand", demand["demand_id"])]
        demand_node = demand_info["nearest_node_native"]
        forward = demand_forward_lengths[demand_node]
        reverse = demand_reverse_lengths[demand_node]
        for site in sites:
            site_info = point_info[("site", site["site_id"])]
            site_node = site_info["nearest_node_native"]
            same_route = site["route_id"] == demand["route_id"]
            status = "OK"
            distance_km = args.ineligible_distance_km
            road_forward_km: float | str = ""
            road_reverse_km: float | str = ""
            distance_reverse_km: float | str = ""
            snap_total_m = demand_info["snap_distance_m"] + site_info["snap_distance_m"]

            if not same_route:
                status = "INELIGIBLE_CROSS_CORRIDOR_PAIR"
                counters["cross_route"] += 1
            elif not demand_info["snap_ok"] or not site_info["snap_ok"]:
                status = "INELIGIBLE_SNAP_TOO_FAR"
                counters["snap_rejected"] += 1
            else:
                if site_node in forward:
                    road_m = float(forward[site_node])
                    road_forward_km = road_m / 1000.0
                    distance_km = (road_m + snap_total_m) / 1000.0
                    status = "OK" if distance_km <= args.service_limit_km else "BEYOND_SERVICE_LIMIT"
                    counters["reachable_demand_to_site"] += 1
                else:
                    status = "NO_DIRECTED_PATH_DEMAND_TO_SITE"
                    counters["unreachable_forward"] += 1

                if site_node in reverse:
                    reverse_m = float(reverse[site_node])
                    road_reverse_km = reverse_m / 1000.0
                    distance_reverse_km = (reverse_m + snap_total_m) / 1000.0
                else:
                    distance_reverse_km = ""

                if isinstance(distance_reverse_km, float) and distance_km < args.ineligible_distance_km:
                    if abs(distance_reverse_km - distance_km) > 1.0:
                        counters["directional_asymmetry_over_1km"] += 1

            matrix_rows.append({
                "site_id": site["site_id"],
                "demand_id": demand["demand_id"],
                "route_id": site["route_id"],
                "demand_route_id": demand["route_id"],
                "distance_km": round(float(distance_km), 6),
                "distance_direction": "demand_to_site_directed_driving",
                "road_distance_demand_to_site_km": round(float(road_forward_km), 6) if road_forward_km != "" else "",
                "distance_site_to_demand_km": round(float(distance_reverse_km), 6) if distance_reverse_km != "" else "",
                "road_distance_site_to_demand_km": round(float(road_reverse_km), 6) if road_reverse_km != "" else "",
                "demand_snap_m": round(float(demand_info["snap_distance_m"]), 2),
                "site_snap_m": round(float(site_info["snap_distance_m"]), 2),
                "combined_snap_connector_km": round(float(snap_total_m) / 1000.0, 6),
                "same_route": same_route,
                "status": status,
                "source": "OpenStreetMap directed driving graph; shortest path respects one-way edges",
                "notes": "distance_km includes straight-line snap connectors; screening estimate only, not verified legal site access or turn-by-turn route.",
            })

    print("[6/7] Writing matrix, snap diagnostics and validation summary...")
    output_dir.mkdir(parents=True, exist_ok=True)
    matrix_path = output_dir / "corridor_site_demand_distances_directed.csv"
    snap_path = output_dir / "corridor_point_snap_diagnostics.csv"
    report_path = output_dir / "DIRECTED_NETWORK_DISTANCE_REPORT.txt"
    fields = list(matrix_rows[0].keys())
    write_csv(matrix_path, matrix_rows, fields)
    write_csv(snap_path, snap_rows, list(snap_rows[0].keys()))

    snap_far = [r for r in snap_rows if r["snap_status"] != "OK"]
    beyond = [r for r in matrix_rows if r["status"] == "BEYOND_SERVICE_LIMIT"]
    no_path = [r for r in matrix_rows if r["status"] == "NO_DIRECTED_PATH_DEMAND_TO_SITE"]
    report_lines = [
        "DIRECTED OSM NETWORK DISTANCE VALIDATION",
        "========================================",
        f"Sites: {len(sites)}",
        f"Demand points: {len(demands)}",
        f"Matrix pairs: {len(matrix_rows)}",
        f"Graph nodes: {graph.number_of_nodes():,}",
        f"Graph directed edges: {graph.number_of_edges():,}",
        f"Distance direction used in distance_km: demand -> charging site",
        f"Maximum allowed snap distance: {args.max_snap_m:.1f} m",
        f"Maximum service distance (diagnostic): {args.service_limit_km:.1f} km",
        f"Ineligible sentinel: {args.ineligible_distance_km:.1f} km",
        "",
        "PAIR COUNTS",
        f"Cross-corridor pairs intentionally ineligible: {counters['cross_route']}",
        f"Pairs rejected due to excessive snap distance: {counters['snap_rejected']}",
        f"Reachable directed demand-to-site pairs: {counters['reachable_demand_to_site']}",
        f"No directed demand-to-site path: {counters['unreachable_forward']}",
        f"Reachable pairs with >1 km directional asymmetry: {counters['directional_asymmetry_over_1km']}",
        f"Pairs beyond 85 km service threshold: {len(beyond)}",
        f"Points with snap distance above threshold: {len(snap_far)}",
        "",
        "POINTS REQUIRING SNAP REVIEW",
    ]
    if snap_far:
        for row in snap_far:
            report_lines.append(
                f"{row['point_type']} {row['point_id']} ({row['route_id']}): {row['snap_distance_m']:.1f} m"
            )
    else:
        report_lines.append("None")
    report_lines += [
        "",
        "UNREACHABLE SAME-CORRIDOR PAIRS",
    ]
    if no_path:
        for row in no_path[:100]:
            report_lines.append(f"{row['demand_id']} -> {row['site_id']}: {row['status']}")
    else:
        report_lines.append("None")
    report_lines += [
        "",
        "IMPORTANT LIMITATIONS",
        "- Snap connectors are straight-line approximations, not confirmed driveways or legal access links.",
        "- The graph is OSM-derived and may omit restrictions or recently changed roads.",
        "- Cross-corridor pairs are structurally ineligible by model design, not physically unreachable.",
        "- distance_km is one-way from demand point to charging site and respects the directed graph.",
        "- Review all snap distances and no-path pairs before replacing any MILP distance matrix.",
        "- Do not overwrite existing scenario distances until this report has been reviewed.",
    ]
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(f"      Matrix pairs written: {len(matrix_rows)}")
    print(f"      Snap points requiring review: {len(snap_far)}")
    print(f"      No directed demand-to-site paths: {len(no_path)}")
    print(f"      >{args.service_limit_km:g} km service pairs: {len(beyond)}")
    print(f"      Output: {matrix_path}")
    print(f"      Snap report: {snap_path}")
    print(f"      Summary: {report_path}")
    print("[7/7] Complete")
    print("IMPORTANT: Review DIRECTED_NETWORK_DISTANCE_REPORT.txt before using these distances in MILP.")


if __name__ == "__main__":
    main()

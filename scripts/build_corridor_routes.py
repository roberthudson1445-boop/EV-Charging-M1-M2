"""Build preliminary directed driving routes between Armenian corridor towns.

Uses a local Geofabrik/OSM PBF and Pyrosm's directed driving graph. The
resulting shortest paths are preliminary OSM network routes, not a substitute
for checking the official M1/M2 alignments or turn restrictions.
"""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import networkx as nx
import pandas as pd
from pyproj import Geod
from pyrosm import OSM
from shapely.geometry import LineString

PBF_PATH = Path("data/raw/armenia-latest.osm.pbf")
SNAP_PATH = Path("data/raw/anchor_network_snap_candidates.csv")
RESULTS_DIR = Path("results")
GEOJSON_PATH = RESULTS_DIR / "corridor_route_legs.geojson"
LEGS_CSV_PATH = RESULTS_DIR / "corridor_leg_distances.csv"
NODES_CSV_PATH = RESULTS_DIR / "corridor_route_nodes.csv"

GEOD = Geod(ellps="WGS84")

EXPECTED_ORDER = {
    "M1": ["Yerevan", "Ashtarak", "Talin", "Maralik", "Gyumri", "Ashotsk", "Bavra"],
    "M2": [
        "Yerevan",
        "Artashat",
        "Areni",
        "Yeghegnadzor",
        "Vayk",
        "Sisian",
        "Goris",
        "Kapan",
        "Kajaran",
        "Meghri",
    ],
}

REF_TOKENS = {
    "M1": {"M-1", "Մ-1", "М-1"},
    "M2": {"M-2", "Մ-2", "М-2"},
}


def normalize_tokens(value: object) -> set[str]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return set()
    if isinstance(value, (list, tuple, set)):
        raw_values = value
    else:
        raw_values = str(value).replace(",", ";").split(";")
    return {str(item).strip().upper() for item in raw_values if str(item).strip()}


def edge_length_and_attributes(graph: nx.MultiDiGraph, u: int, v: int) -> tuple[float, dict]:
    """Return the shortest parallel directed edge, matching NetworkX weight behavior."""
    parallel = graph.get_edge_data(u, v)
    if not parallel:
        raise RuntimeError(f"Path references missing directed edge {u} -> {v}.")
    attributes = min(
        parallel.values(),
        key=lambda attrs: float(attrs.get("length", math.inf)),
    )
    length_m = float(attributes.get("length", math.nan))
    if not math.isfinite(length_m) or length_m < 0:
        raise ValueError(f"Invalid length on edge {u} -> {v}: {length_m}")
    return length_m, attributes


def load_best_anchors() -> dict[str, list[dict]]:
    snaps = pd.read_csv(SNAP_PATH)
    required = {
        "route_id",
        "sequence_order",
        "anchor_name",
        "nearest_drive_node_id",
        "snap_distance_m",
    }
    missing = required - set(snaps.columns)
    if missing:
        raise ValueError(f"Anchor snap file is missing columns: {sorted(missing)}")

    snaps["snap_distance_m"] = pd.to_numeric(snaps["snap_distance_m"], errors="raise")
    best_indices = snaps.groupby(["route_id", "anchor_name"])["snap_distance_m"].idxmin()
    best = snaps.loc[best_indices].copy()

    selected: dict[str, list[dict]] = {}
    for route_id, expected_names in EXPECTED_ORDER.items():
        route_rows = best[best["route_id"] == route_id].sort_values("sequence_order")
        actual_names = route_rows["anchor_name"].tolist()
        if actual_names != expected_names:
            raise ValueError(
                f"{route_id} anchors do not match the expected corridor order. "
                f"Expected {expected_names}; found {actual_names}."
            )
        selected[route_id] = route_rows.to_dict("records")
    return selected


def route_ref_matches(attributes: dict, route_id: str) -> bool:
    refs = normalize_tokens(attributes.get("ref"))
    refs_en = normalize_tokens(attributes.get("ref:en"))
    if refs & REF_TOKENS[route_id]:
        return True
    english_ref = "M-1" if route_id == "M1" else "M-2"
    return english_ref in refs_en


def build_route_leg(
    graph: nx.MultiDiGraph,
    node_coordinates: dict[int, tuple[float, float]],
    route_id: str,
    leg_order: int,
    origin: dict,
    destination: dict,
) -> tuple[dict, dict | None, list[tuple[int, float, dict]] | None]:
    source = int(origin["nearest_drive_node_id"])
    target = int(destination["nearest_drive_node_id"])
    base = {
        "route_id": route_id,
        "leg_order": leg_order,
        "from_anchor": origin["anchor_name"],
        "to_anchor": destination["anchor_name"],
        "from_node_id": source,
        "to_node_id": target,
        "from_snap_distance_m": float(origin["snap_distance_m"]),
        "to_snap_distance_m": float(destination["snap_distance_m"]),
    }

    if source not in graph:
        return ({**base, "status": "source_node_missing"}, None, None)
    if target not in graph:
        return ({**base, "status": "target_node_missing"}, None, None)

    try:
        path = nx.shortest_path(graph, source=source, target=target, weight="length", method="dijkstra")
    except nx.NetworkXNoPath:
        reverse_exists = nx.has_path(graph, target, source)
        status = "no_directed_path_reverse_exists" if reverse_exists else "no_directed_path_either_direction"
        return ({**base, "status": status}, None, None)

    edge_records: list[tuple[int, float, dict]] = []
    total_length_m = 0.0
    tagged_length_m = 0.0
    highway_length_m: defaultdict[str, float] = defaultdict(float)
    class_length_m: defaultdict[str, float] = defaultdict(float)

    for u, v in zip(path[:-1], path[1:]):
        length_m, attrs = edge_length_and_attributes(graph, u, v)
        total_length_m += length_m
        if route_ref_matches(attrs, route_id):
            tagged_length_m += length_m
        highway = attrs.get("highway", "unknown")
        if isinstance(highway, (list, tuple, set)):
            highway = ";".join(map(str, highway))
        highway_length_m[str(highway)] += length_m
        edge_records.append((int(v), length_m, attrs))

    from_lon, from_lat = node_coordinates[source]
    to_lon, to_lat = node_coordinates[target]
    _, _, straight_m = GEOD.inv(from_lon, from_lat, to_lon, to_lat)

    route_share = 100.0 * tagged_length_m / total_length_m if total_length_m else 0.0
    geometry_coords = [node_coordinates[int(node)] for node in path]
    geometry = LineString(geometry_coords) if len(geometry_coords) >= 2 else None

    row = {
        **base,
        "status": "ok",
        "path_edge_count": len(path) - 1,
        "network_distance_km": total_length_m / 1000.0,
        "straight_distance_km": abs(straight_m) / 1000.0,
        "detour_factor": (total_length_m / abs(straight_m)) if abs(straight_m) > 0 else math.nan,
        "matching_route_ref_km": tagged_length_m / 1000.0,
        "matching_route_ref_share_pct": route_share,
        "highway_length_km": "; ".join(
            f"{name}:{length / 1000.0:.3f}" for name, length in sorted(highway_length_m.items())
        ),
    }

    geo_record = {
        **row,
        "geometry": geometry,
    } if geometry is not None else None
    return row, geo_record, edge_records


def main() -> None:
    if not PBF_PATH.exists():
        raise FileNotFoundError(f"PBF file not found: {PBF_PATH}")
    if not SNAP_PATH.exists():
        raise FileNotFoundError(f"Anchor snap candidates not found: {SNAP_PATH}")

    anchors = load_best_anchors()
    print("Loading full OSM driving network from local PBF...")
    osm = OSM(str(PBF_PATH))
    nodes, edges = osm.get_network(
        network_type="driving",
        nodes=True,
        extra_attributes=["ref:en", "name"],
    )
    print(f"Driving nodes: {len(nodes):,}")
    print(f"Driving edges: {len(edges):,}")

    print("Building directed graph (preserving one-way restrictions and all components)...")
    graph = osm.to_graph(
        nodes,
        edges,
        graph_type="networkx",
        network_type="driving",
        retain_all=True,
        osmnx_compatible=False,
        simplify=False,
        progress=True,
    )
    print(f"Graph type: {type(graph).__name__}")
    print(f"Graph nodes: {graph.number_of_nodes():,}")
    print(f"Directed graph edges: {graph.number_of_edges():,}")

    node_coordinates = {
        int(row.id): (float(row.lon), float(row.lat))
        for row in nodes[["id", "lon", "lat"]].itertuples(index=False)
    }

    leg_rows: list[dict] = []
    geo_rows: list[dict] = []
    route_node_rows: list[dict] = []

    for route_id, route_anchors in anchors.items():
        print("\n" + "=" * 65)
        print(f"{route_id} — PRELIMINARY DIRECTED SHORTEST-DRIVING ROUTE")
        print("=" * 65)

        route_leg_results = []
        route_all_legs_ok = True

        for leg_order, (origin, destination) in enumerate(
            zip(route_anchors[:-1], route_anchors[1:]), start=1
        ):
            print(f"Routing {origin['anchor_name']} -> {destination['anchor_name']}...")
            row, geo_record, edge_records = build_route_leg(
                graph,
                node_coordinates,
                route_id,
                leg_order,
                origin,
                destination,
            )
            leg_rows.append(row)
            route_leg_results.append((row, geo_record, edge_records, origin, destination))

            if row["status"] != "ok":
                route_all_legs_ok = False
                print(f"  {row['status']}")
                continue

            geo_rows.append(geo_record)
            print(
                f"  {row['network_distance_km']:.2f} km; "
                f"straight={row['straight_distance_km']:.2f} km; "
                f"M-road ref share={row['matching_route_ref_share_pct']:.1f}%"
            )

        if route_all_legs_ok:
            cumulative_km = 0.0
            first_node_id = int(route_anchors[0]["nearest_drive_node_id"])
            first_lon, first_lat = node_coordinates[first_node_id]
            route_node_rows.append({
                "route_id": route_id,
                "sequence": 0,
                "node_id": first_node_id,
                "longitude": first_lon,
                "latitude": first_lat,
                "chainage_km": 0.0,
                "at_anchor": route_anchors[0]["anchor_name"],
            })

            node_sequence = 0
            for row, _, edge_records, origin, destination in route_leg_results:
                if edge_records is None:
                    continue
                for node_id, length_m, _attrs in edge_records:
                    cumulative_km += length_m / 1000.0
                    node_sequence += 1
                    lon, lat = node_coordinates[node_id]
                    route_node_rows.append({
                        "route_id": route_id,
                        "sequence": node_sequence,
                        "node_id": node_id,
                        "longitude": lon,
                        "latitude": lat,
                        "chainage_km": cumulative_km,
                        "at_anchor": destination["anchor_name"] if node_id == int(destination["nearest_drive_node_id"]) else "",
                    })

            total_route_km = sum(
                row["network_distance_km"] for row, _, _, _, _ in route_leg_results
            )
            print(f"\n{route_id} total concatenated route distance: {total_route_km:.2f} km")
            print("All consecutive city-to-city legs found in the directed graph.")
        else:
            print("\nWARNING: The full corridor sequence is incomplete.")
            print("Do not use cumulative chainage for this route yet.")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(leg_rows).to_csv(LEGS_CSV_PATH, index=False, encoding="utf-8-sig")
    pd.DataFrame(route_node_rows).to_csv(NODES_CSV_PATH, index=False, encoding="utf-8-sig")

    if geo_rows:
        geo = gpd.GeoDataFrame(geo_rows, geometry="geometry", crs="EPSG:4326")
        geo.to_file(GEOJSON_PATH, driver="GeoJSON")

    print("\nSaved outputs:")
    print(" -", LEGS_CSV_PATH)
    print(" -", NODES_CSV_PATH)
    if geo_rows:
        print(" -", GEOJSON_PATH)
    print("\nInterpretation warning:")
    print("These are preliminary shortest driving routes between selected town anchors.")
    print("They must be visually checked against the intended official M1/M2 alignments")
    print("before being treated as corridor chainage for the optimization model.")


if __name__ == "__main__":
    main()

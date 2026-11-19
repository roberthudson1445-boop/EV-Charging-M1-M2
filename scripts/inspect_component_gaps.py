
"""Find nearby endpoints between disconnected M1/M2 components."""

import csv
from itertools import combinations
from pathlib import Path

import geopandas as gpd
import networkx as nx
from pyproj import Geod

INPUT = Path("data/raw/m1_m2_candidate_ways.geojson")
OUTPUT = Path("results/route_component_gaps.csv")

GEOD = Geod(ellps="WGS84")


def point_key(coord):
    return round(float(coord[0]), 7), round(float(coord[1]), 7)


def build_graph(route):
    graph = nx.MultiGraph()

    for row in route.itertuples():
        geometry = row.geometry

        if geometry is None or geometry.is_empty:
            continue

        if geometry.geom_type != "LineString":
            continue

        coords = list(geometry.coords)

        for a, b in zip(coords[:-1], coords[1:]):
            start = point_key(a)
            end = point_key(b)

            if start == end:
                continue

            _, _, meters = GEOD.inv(
                start[0], start[1], end[0], end[1]
            )

            graph.add_edge(
                start,
                end,
                length_km=abs(meters) / 1000.0,
            )

    return graph


def analyze_route(data, route_id):
    route = data[data["route_id"] == route_id]
    graph = build_graph(route)

    components = []

    for nodes in nx.connected_components(graph):
        subgraph = graph.subgraph(nodes)

        endpoints = [
            node for node in subgraph.nodes
            if subgraph.degree(node) == 1
        ]

        components.append({
            "nodes": nodes,
            "endpoints": endpoints,
            "length_km": sum(
                edge["length_km"]
                for _, _, edge in subgraph.edges(data=True)
            ),
        })

    components.sort(
        key=lambda component: component["length_km"],
        reverse=True,
    )

    print(f"\n{'=' * 55}")
    print(f"{route_id} COMPONENT GAP ANALYSIS")
    print(f"{'=' * 55}")
    print("Connected components:", len(components))

    gaps = []

    for (i, comp_a), (j, comp_b) in combinations(
        enumerate(components, start=1), 2
    ):
        best_distance = float("inf")
        best_a = None
        best_b = None

        for a in comp_a["endpoints"]:
            for b in comp_b["endpoints"]:
                _, _, meters = GEOD.inv(
                    a[0], a[1], b[0], b[1]
                )

                distance_km = abs(meters) / 1000.0

                if distance_km < best_distance:
                    best_distance = distance_km
                    best_a = a
                    best_b = b

        if best_a is not None:
            gaps.append({
                "route_id": route_id,
                "component_a": i,
                "component_b": j,
                "distance_km": best_distance,
                "a_lon": best_a[0],
                "a_lat": best_a[1],
                "b_lon": best_b[0],
                "b_lat": best_b[1],
                "length_a_km": comp_a["length_km"],
                "length_b_km": comp_b["length_km"],
            })

    gaps.sort(key=lambda item: item["distance_km"])

    print("\nClosest component endpoint pairs:")

    for gap in gaps[:15]:
        print(
            f"C{gap['component_a']} - C{gap['component_b']}: "
            f"{gap['distance_km']:.3f} km"
        )

    print("\nPairs within 2 km:", sum(
        gap["distance_km"] <= 2.0 for gap in gaps
    ))

    return gaps


def main():
    if not INPUT.exists():
        raise FileNotFoundError(INPUT)

    data = gpd.read_file(INPUT)
    all_gaps = []

    for route_id in ("M1", "M2"):
        all_gaps.extend(analyze_route(data, route_id))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    if all_gaps:
        with OUTPUT.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=list(all_gaps[0].keys()),
            )
            writer.writeheader()
            writer.writerows(all_gaps)

    print(f"\nSaved gap report to: {OUTPUT}")
    print("Distances are endpoint-to-endpoint geodesic distances.")
    print("Nearby endpoints are candidates for manual inspection,")
    print("not automatic proof that road components should be joined.")


if __name__ == "__main__":
    main()

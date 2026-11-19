
"""Analyze connectivity of extracted M1 and M2 OSM road features."""

from pathlib import Path

import geopandas as gpd
import networkx as nx
from pyproj import Geod

INPUT = Path("data/raw/m1_m2_candidate_ways.geojson")
GEOD = Geod(ellps="WGS84")


def point_key(coordinate):
    lon, lat = coordinate[:2]
    return round(float(lon), 7), round(float(lat), 7)


def analyze_route(data, route_id):
    route = data[data["route_id"] == route_id]
    graph = nx.MultiGraph()

    for row in route.itertuples():
        geometry = row.geometry

        if geometry is None or geometry.is_empty:
            continue

        if geometry.geom_type != "LineString":
            continue

        coordinates = list(geometry.coords)
        if len(coordinates) < 2:
            continue

        start = point_key(coordinates[0])
        end = point_key(coordinates[-1])
        length_km = abs(GEOD.geometry_length(geometry)) / 1000

        graph.add_edge(
            start,
            end,
            length_km=length_km,
            way_id=str(row.id),
        )

    components = []

    for nodes in nx.connected_components(graph):
        subgraph = graph.subgraph(nodes)
        length = sum(
            edge["length_km"]
            for _, _, edge in subgraph.edges(data=True)
        )
        components.append((length, subgraph))

    components.sort(key=lambda item: item[0], reverse=True)

    print("\n" + "=" * 55)
    print(f"ROUTE {route_id}")
    print("=" * 55)
    print("Input features:", len(route))
    print("Unique graph nodes:", graph.number_of_nodes())
    print("Graph edges:", graph.number_of_edges())
    print("Connected components:", len(components))

    total_length = sum(length for length, _ in components)
    print(f"Summed edge length: {total_length:.2f} km")

    if components:
        largest_length = components[0][0]
        share = 100 * largest_length / total_length if total_length else 0

        print(f"Largest component: {largest_length:.2f} km")
        print(f"Largest component share: {share:.2f}%")

    print("\nLargest components:")

    for index, (length, subgraph) in enumerate(components[:15], start=1):
        endpoints = sum(
            1 for _, degree in subgraph.degree() if degree == 1
        )

        print(
            f"{index:2}. "
            f"edges={subgraph.number_of_edges():4}, "
            f"nodes={subgraph.number_of_nodes():4}, "
            f"endpoints={endpoints:4}, "
            f"length={length:8.2f} km"
        )


def main():
    if not INPUT.exists():
        raise FileNotFoundError(f"File not found: {INPUT}")

    data = gpd.read_file(INPUT)

    print("Input file:", INPUT)
    print("Total features:", len(data))

    for route_id in ("M1", "M2"):
        analyze_route(data, route_id)


if __name__ == "__main__":
    main()

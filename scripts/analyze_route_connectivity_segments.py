
"""Analyze M1/M2 connectivity at individual geometry-segment level."""

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

        if geometry.geom_type == "LineString":
            lines = [geometry]
        elif geometry.geom_type == "MultiLineString":
            lines = list(geometry.geoms)
        else:
            continue

        for line in lines:
            coordinates = list(line.coords)

            for index, (a, b) in enumerate(
                zip(coordinates[:-1], coordinates[1:])
            ):
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
                    way_id=str(row.id),
                )

    components = []

    for nodes in nx.connected_components(graph):
        subgraph = graph.subgraph(nodes)

        length = sum(
            edge["length_km"]
            for _, _, _, edge in subgraph.edges(
                keys=True, data=True
            )
        )

        way_ids = {
            edge["way_id"]
            for _, _, _, edge in subgraph.edges(
                keys=True, data=True
            )
        }

        components.append((length, subgraph, len(way_ids)))

    components.sort(key=lambda item: item[0], reverse=True)

    print("\n" + "=" * 60)
    print(f"ROUTE {route_id} - SEGMENT-LEVEL CONNECTIVITY")
    print("=" * 60)

    print("Input OSM ways:", len(route))
    print("Unique ways:", route["id"].nunique())
    print("Graph nodes:", graph.number_of_nodes())
    print("Graph segments:", graph.number_of_edges())
    print("Connected components:", len(components))

    total_length = sum(item[0] for item in components)

    print(f"Total segment length: {total_length:.2f} km")

    if components:
        largest_length = components[0][0]
        share = (
            100 * largest_length / total_length
            if total_length > 0 else 0
        )

        print(f"Largest component: {largest_length:.2f} km")
        print(f"Largest component share: {share:.2f}%")

    print("\nLargest components:")

    for index, (length, subgraph, way_count) in enumerate(
        components[:15], start=1
    ):
        endpoints = [
            node for node, degree in subgraph.degree()
            if degree == 1
        ]

        print(
            f"{index:2}. "
            f"segments={subgraph.number_of_edges():5}, "
            f"nodes={subgraph.number_of_nodes():5}, "
            f"ways={way_count:4}, "
            f"endpoints={len(endpoints):4}, "
            f"length={length:8.2f} km"
        )

        for point in endpoints[:4]:
            print(
                f"    endpoint: lon={point[0]:.6f}, "
                f"lat={point[1]:.6f}"
            )


def main():
    if not INPUT.exists():
        raise FileNotFoundError(INPUT)

    data = gpd.read_file(INPUT)

    print("Input file:", INPUT)
    print("Total features:", len(data))

    for route_id in ("M1", "M2"):
        analyze_route(data, route_id)


if __name__ == "__main__":
    main()

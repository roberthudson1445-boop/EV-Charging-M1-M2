
"""Inspect OSM ways associated with disconnected component endpoints."""

from pathlib import Path

import geopandas as gpd
import networkx as nx
import pandas as pd
from pyproj import Geod
from shapely.geometry import Point

INPUT = Path("data/raw/m1_m2_candidate_ways.geojson")
GAPS = Path("results/route_component_gaps.csv")

GEOD = Geod(ellps="WGS84")


def point_key(coord):
    return round(float(coord[0]), 7), round(float(coord[1]), 7)


def get_components(route):
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
                length_km=abs(meters) / 1000,
                way_id=str(row.id),
            )

    components = []

    for nodes in nx.connected_components(graph):
        subgraph = graph.subgraph(nodes)

        length = sum(
            edge["length_km"]
            for _, _, edge in subgraph.edges(data=True)
        )

        way_ids = {
            edge["way_id"]
            for _, _, edge in subgraph.edges(data=True)
        }

        components.append((length, way_ids))

    components.sort(key=lambda item: item[0], reverse=True)
    return components


def inspect_endpoint(route_data, way_ids, lon, lat, label, projected_crs):
    candidates = route_data[
        route_data["id"].astype(str).isin(way_ids)
    ].copy()

    if candidates.empty:
        print(f"    No associated ways found for {label}")
        return

    candidates = candidates.to_crs(projected_crs)
    point = gpd.GeoSeries(
        [Point(lon, lat)], crs="EPSG:4326"
    ).to_crs(projected_crs).iloc[0]

    candidates["distance_m"] = candidates.geometry.distance(point)

    print(f"\n  {label}: ({lon:.7f}, {lat:.7f})")

    columns = [
        "id", "ref", "ref:en", "highway",
        "name", "tag_status", "distance_m"
    ]
    columns = [c for c in columns if c in candidates.columns]

    print(
        candidates.sort_values("distance_m")[columns]
        .head(5)
        .to_string(index=False)
    )


def main():
    if not INPUT.exists() or not GAPS.exists():
        raise FileNotFoundError("Required GeoJSON or gap report is missing.")

    data = gpd.read_file(INPUT)
    gaps = pd.read_csv(GAPS)

    projected_crs = data.estimate_utm_crs()

    for route_id in ("M1", "M2"):
        route = data[data["route_id"] == route_id].copy()
        components = get_components(route)

        route_gaps = gaps[gaps["route_id"] == route_id]
        route_gaps = route_gaps.sort_values("distance_km").head(8)

        print("\n" + "=" * 65)
        print(f"{route_id} — OSM WAY DETAILS AT COMPONENT GAPS")
        print("=" * 65)

        for row in route_gaps.itertuples():
            a = int(row.component_a)
            b = int(row.component_b)

            print(
                f"\nCOMPONENT C{a} - C{b}: "
                f"{row.distance_km * 1000:.1f} metres"
            )

            for component, prefix in ((a, "A"), (b, "B")):
                if component > len(components):
                    continue

                way_ids = components[component - 1][1]

                inspect_endpoint(
                    route,
                    way_ids,
                    getattr(row, f"{prefix.lower()}_lon"),
                    getattr(row, f"{prefix.lower()}_lat"),
                    f"Component C{component}",
                    projected_crs,
                )


if __name__ == "__main__":
    main()


"""Inspect the Pokr Vedi / Khor Virap OSM feature against M2."""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from pyrosm import OSM
from scipy.spatial import cKDTree

PBF = Path("data/raw/armenia-latest.osm.pbf")
CANDIDATES = Path("data/raw/m1_m2_candidate_ways.geojson")
TARGET_ID = 81990328

TRANSFORMER = Transformer.from_crs(
    "EPSG:4326",
    "EPSG:32638",
    always_xy=True,
)


def main():
    print("Loading the OSM place feature...")

    osm = OSM(str(PBF))

    places = osm.get_data_by_custom_criteria(
        custom_filter={"place": ["village"]},
        keep_nodes=True,
        keep_ways=True,
        keep_relations=False,
        extra_attributes=[
            "name:en",
            "name:hy",
            "wikidata",
            "wikipedia",
        ],
    )

    place = places[places["id"].astype(str) == str(TARGET_ID)]

    if len(place) != 1:
        raise ValueError(
            f"Expected one feature with OSM ID {TARGET_ID}; "
            f"found {len(place)}."
        )

    feature = place.iloc[0]
    geometry = feature.geometry

    if geometry is None or geometry.is_empty:
        raise ValueError("The place geometry is empty.")

    representative = geometry.representative_point()

    print("\nOSM place details")
    print("OSM ID:", TARGET_ID)
    print("Name:", feature.get("name"))
    print("English name:", feature.get("name:en"))
    print("Armenian name:", feature.get("name:hy"))
    print("Wikipedia:", feature.get("wikipedia"))
    print("Wikidata:", feature.get("wikidata"))
    print("Geometry type:", geometry.geom_type)
    print("Representative point:")
    print(f"  longitude={representative.x:.7f}")
    print(f"  latitude={representative.y:.7f}")

    print("\nChecking proximity to M2-tagged OSM ways...")

    ways = gpd.read_file(CANDIDATES)
    m2 = ways[ways["route_id"] == "M2"].copy()

    if m2.empty:
        raise ValueError("No M2 candidate ways were found.")

    projected_crs = "EPSG:32638"
    place_projected = gpd.GeoSeries(
        [geometry], crs="EPSG:4326"
    ).to_crs(projected_crs).iloc[0]

    point_projected = gpd.GeoSeries(
        [representative], crs="EPSG:4326"
    ).to_crs(projected_crs).iloc[0]

    m2 = m2.to_crs(projected_crs)
    m2["place_polygon_distance_m"] = m2.geometry.distance(
        place_projected
    )
    m2["representative_point_distance_m"] = m2.geometry.distance(
        point_projected
    )

    columns = [
        "id",
        "ref",
        "ref:en",
        "highway",
        "name",
        "place_polygon_distance_m",
        "representative_point_distance_m",
    ]

    print("\nNearest M2-tagged ways to the place polygon:")
    print(
        m2.sort_values("place_polygon_distance_m")[columns]
        .head(10)
        .to_string(index=False)
    )

    print("\nFinding nearest general driving-network node...")

    nodes, edges = osm.get_network(
        network_type="driving",
        nodes=True,
    )

    node_x, node_y = TRANSFORMER.transform(
        nodes["lon"].to_numpy(dtype=float),
        nodes["lat"].to_numpy(dtype=float),
    )

    tree = cKDTree(np.column_stack([node_x, node_y]))

    distance_m, index = tree.query(
        [point_projected.x, point_projected.y],
        k=1,
    )

    nearest = nodes.iloc[int(index)]

    print("Driving nodes:", len(nodes))
    print("Nearest node ID:", nearest["id"])
    print("Nearest node longitude:", nearest["lon"])
    print("Nearest node latitude:", nearest["lat"])
    print(f"Snap distance: {distance_m:.2f} metres")

    print(
        "\nNote: geometric proximity does not prove that the node "
        "is connected to the intended M2 carriageway."
    )


if __name__ == "__main__":
    main()

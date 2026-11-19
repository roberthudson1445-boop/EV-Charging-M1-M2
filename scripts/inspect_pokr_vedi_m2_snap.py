
"""Find the closest point on an M2-tagged road to the Pokr Vedi OSM polygon."""

from pathlib import Path

import geopandas as gpd
from pyproj import Transformer
from pyrosm import OSM
from shapely.ops import nearest_points

PBF = Path("data/raw/armenia-latest.osm.pbf")
WAYS = Path("data/raw/m1_m2_candidate_ways.geojson")
PLACE_ID = "81990328"

TO_METRIC = Transformer.from_crs(
    "EPSG:4326", "EPSG:32638", always_xy=True
)
TO_WGS84 = Transformer.from_crs(
    "EPSG:32638", "EPSG:4326", always_xy=True
)


def main():
    print("Loading Pokr Vedi / Khor Virap polygon...")

    osm = OSM(str(PBF))
    places = osm.get_data_by_custom_criteria(
        custom_filter={"place": ["village"]},
        keep_nodes=True,
        keep_ways=True,
        keep_relations=False,
        extra_attributes=["name:en", "name:hy", "wikidata", "wikipedia"],
    )

    place = places[places["id"].astype(str) == PLACE_ID]

    if len(place) != 1:
        raise ValueError(f"Expected one OSM place, found {len(place)}")

    polygon = place.geometry.iloc[0]

    print("Loading M2 candidate road geometries...")

    ways = gpd.read_file(WAYS)
    m2 = ways[ways["route_id"] == "M2"].copy()

    place_metric = gpd.GeoSeries(
        [polygon], crs="EPSG:4326"
    ).to_crs("EPSG:32638").iloc[0]

    m2 = m2.to_crs("EPSG:32638")
    m2["distance_m"] = m2.geometry.distance(place_metric)

    nearest = m2.nsmallest(10, "distance_m")

    print("\nClosest M2 road features:")

    for row in nearest.itertuples():
        place_point, road_point = nearest_points(
            place_metric, row.geometry
        )

        lon, lat = TO_WGS84.transform(
            road_point.x, road_point.y
        )

        chainage_on_way_km = row.geometry.project(road_point) / 1000.0

        print(
            f"\nOSM way ID: {row.id}"
            f"\nRef: {row.ref}"
            f"\nRef English: {getattr(row, 'ref_en', '')}"
            f"\nHighway: {row.highway}"
            f"\nName: {row.name}"
            f"\nPolygon-to-road distance: {row.distance_m:.2f} m"
            f"\nNearest point on M2: lon={lon:.7f}, lat={lat:.7f}"
            f"\nDistance along this OSM way from its start: "
            f"{chainage_on_way_km:.4f} km"
        )


if __name__ == "__main__":
    main()

"""Snap official M1/M2 waypoint candidates to the nearest tagged corridor geometry.

This is a review/preprocessing tool. It does not route between waypoints and does
not assert that a nearby settlement boundary is the official access point.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from pyproj import Transformer
from pyrosm import OSM
from shapely.ops import nearest_points

PBF_PATH = Path("data/raw/armenia-latest.osm.pbf")
CANDIDATES_PATH = Path("data/raw/official_route_waypoint_candidates.csv")
ROADS_PATH = Path("data/raw/m1_m2_candidate_ways.geojson")
OUTPUT_PATH = Path("data/raw/official_route_waypoint_snaps.csv")

METRIC_CRS = "EPSG:32638"  # Armenia corridor area, UTM zone 38N.
TO_WGS84 = Transformer.from_crs(METRIC_CRS, "EPSG:4326", always_xy=True)
POKR_VEDI_OSM_ID = "81990328"  # OSM place polygon currently named Khor Virap.


def normalize_osm_id(value: object) -> str:
    """Normalize CSV numeric IDs and Pyrosm IDs to a comparable string."""
    if pd.isna(value):
        return ""
    text = str(value).strip()
    try:
        return str(int(float(text)))
    except (TypeError, ValueError, OverflowError):
        return text


def main() -> None:
    for path in (PBF_PATH, CANDIDATES_PATH, ROADS_PATH):
        if not path.exists():
            raise FileNotFoundError(f"Required input file not found: {path}")

    print("Loading official route waypoint candidates...")
    candidates = pd.read_csv(CANDIDATES_PATH, dtype={"osm_id": str})
    required_candidates = {
        "route_id", "sequence_order", "waypoint_name", "osm_type", "osm_id"
    }
    missing = required_candidates - set(candidates.columns)
    if missing:
        raise ValueError(f"Waypoint CSV is missing columns: {sorted(missing)}")

    candidates = candidates[candidates["route_id"].isin(["M1", "M2"])].copy()
    candidates["osm_id_key"] = candidates["osm_id"].map(normalize_osm_id)
    candidates["osm_type_key"] = candidates["osm_type"].astype(str).str.lower()

    print("Loading matching OSM settlement geometries...")
    osm = OSM(str(PBF_PATH))
    places = osm.get_data_by_custom_criteria(
        custom_filter={"place": ["city", "town", "village", "hamlet"]},
        keep_nodes=True,
        keep_ways=True,
        keep_relations=False,
        extra_attributes=["name:en", "name:hy", "wikidata", "wikipedia"],
    )
    if places.crs is None:
        places = places.set_crs("EPSG:4326")

    places = places.copy()
    places["osm_id_key"] = places["id"].map(normalize_osm_id)
    places["osm_type_key"] = places["osm_type"].astype(str).str.lower()
    place_lookup = {}
    for _, place_row in places.iterrows():
        key = (
            str(place_row["osm_type_key"]).lower(),
            str(place_row["osm_id_key"]),
        )
        place_lookup[key] = place_row

    # Add the government M2 waypoint Pokr Vedi using the verified OSM polygon
    # whose current mapped name is Khor Virap and whose Wikipedia tag is
    # en:Pokr Vedi. Keep both identities explicit in the output.
    if not (
        (candidates["route_id"] == "M2")
        & (candidates["waypoint_name"] == "Pokr Vedi")
    ).any():
        place_match = places[places["osm_id_key"] == POKR_VEDI_OSM_ID]
        if len(place_match) != 1:
            raise ValueError(
                f"Expected one OSM place feature {POKR_VEDI_OSM_ID}; "
                f"found {len(place_match)}."
            )
        place_row = place_match.iloc[0]
        candidates = pd.concat(
            [
                candidates,
                pd.DataFrame(
                    [
                        {
                            "route_id": "M2",
                            "sequence_order": 5,
                            "waypoint_name": "Pokr Vedi",
                            "role": "main_route_waypoint",
                            "osm_type": str(place_row["osm_type"]),
                            "osm_id": POKR_VEDI_OSM_ID,
                            "place_type": str(place_row.get("place", "")),
                            "matched_names": "Khor Virap | Խոր Վիրապ; Wikipedia: en:Pokr Vedi",
                            "longitude": None,
                            "latitude": None,
                            "osm_id_key": POKR_VEDI_OSM_ID,
                            "osm_type_key": str(place_row["osm_type"]).lower(),
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )

    print("Loading tagged M1/M2 road geometries...")
    roads = gpd.read_file(ROADS_PATH)
    if roads.crs is None:
        roads = roads.set_crs("EPSG:4326")
    roads = roads[roads["route_id"].isin(["M1", "M2"])].copy()
    roads = roads.to_crs(METRIC_CRS)

    route_ways: dict[str, list] = {}
    for route_id in ("M1", "M2"):
        route_rows = roads[
            (roads["route_id"] == route_id)
            & roads.geometry.notna()
            & ~roads.geometry.is_empty
        ]
        route_ways[route_id] = [row for _, row in route_rows.iterrows()]
        if not route_ways[route_id]:
            raise ValueError(f"No tagged road geometries found for {route_id}.")

    output_rows: list[dict] = []
    for candidate in candidates.itertuples(index=False):
        route_id = str(candidate.route_id)
        key = (str(candidate.osm_type_key), str(candidate.osm_id_key))
        place = place_lookup.get(key)
        if place is None:
            print(
                f"WARNING: no source geometry for {route_id} "
                f"{candidate.waypoint_name} {key}; skipping candidate."
            )
            continue

        place_geometry = place.geometry
        if place_geometry is None or place_geometry.is_empty:
            print(
                f"WARNING: empty geometry for {route_id} "
                f"{candidate.waypoint_name} {key}; skipping candidate."
            )
            continue

        place_metric = gpd.GeoSeries(
            [place_geometry], crs="EPSG:4326"
        ).to_crs(METRIC_CRS).iloc[0]

        best = None
        for road in route_ways[route_id]:
            road_geometry = road.geometry
            distance_m = float(place_metric.distance(road_geometry))
            if best is None or distance_m < best["snap_distance_m"]:
                _, nearest_road = nearest_points(place_metric, road_geometry)
                lon, lat = TO_WGS84.transform(nearest_road.x, nearest_road.y)
                best = {
                    "snap_distance_m": distance_m,
                    "snap_longitude": float(lon),
                    "snap_latitude": float(lat),
                    "nearest_way_id": normalize_osm_id(road.get("id", "")),
                    "nearest_way_ref": str(road.get("ref", "") or ""),
                    "nearest_way_ref_en": str(road.get("ref:en", "") or ""),
                    "nearest_way_highway": str(road.get("highway", "") or ""),
                    "nearest_way_name": str(road.get("name", "") or ""),
                }

        if best is None:
            continue

        representative = place_geometry.representative_point()
        output_rows.append(
            {
                "route_id": route_id,
                "sequence_order": int(candidate.sequence_order),
                "waypoint_name": str(candidate.waypoint_name),
                "role": str(getattr(candidate, "role", "main_route_waypoint") or "main_route_waypoint"),
                "place_osm_type": str(candidate.osm_type),
                "place_osm_id": normalize_osm_id(candidate.osm_id),
                "place_type": str(candidate.place_type),
                "place_name_en": str(place.get("name:en", "") or ""),
                "place_name_hy": str(place.get("name:hy", "") or ""),
                "place_wikipedia": str(place.get("wikipedia", "") or ""),
                "place_wikidata": str(place.get("wikidata", "") or ""),
                "representative_longitude": float(representative.x),
                "representative_latitude": float(representative.y),
                **best,
            }
        )

    if not output_rows:
        raise RuntimeError("No waypoint candidates could be snapped to tagged roads.")

    output = pd.DataFrame(output_rows)
    output["selected_nearest_tagged_way"] = False
    selected_indices = output.groupby(
        ["route_id", "sequence_order", "waypoint_name"]
    )["snap_distance_m"].idxmin()
    output.loc[selected_indices, "selected_nearest_tagged_way"] = True
    output = output.sort_values(
        ["route_id", "sequence_order", "selected_nearest_tagged_way", "snap_distance_m"],
        ascending=[True, True, False, True],
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    print("\nBest candidate per official waypoint (nearest tagged M1/M2 geometry):")
    selected = output[output["selected_nearest_tagged_way"]]
    columns = [
        "route_id", "sequence_order", "waypoint_name", "place_osm_type",
        "place_osm_id", "place_name_en", "snap_distance_m",
        "nearest_way_id", "nearest_way_highway", "nearest_way_name",
        "snap_longitude", "snap_latitude",
    ]
    print(selected[columns].to_string(index=False))

    print("\nCandidate counts:")
    print(selected.groupby("route_id").size().to_string())

    print("\nSelected snaps farther than 1 km from the tagged corridor:")
    far = selected[selected["snap_distance_m"] > 1000]
    if far.empty:
        print("None")
    else:
        print(far[["route_id", "waypoint_name", "snap_distance_m", "nearest_way_name"]].to_string(index=False))

    print(f"\nSaved all candidates and selected flags to: {OUTPUT_PATH}")
    print("These are geometric nearest-road snaps, not yet verified route access points.")


if __name__ == "__main__":
    main()

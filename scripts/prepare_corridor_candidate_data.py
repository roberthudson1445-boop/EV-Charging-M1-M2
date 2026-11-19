#!/usr/bin/env python3
"""Prepare spatial candidate data from the routed M1/M2 corridors.

Run from project root:
  .\\.venv\\Scripts\\python.exe scripts\\prepare_corridor_candidate_data.py

Reads:
  results/official_M1_route.geojson
  results/official_M2_route.geojson
  results/official_corridor_waypoint_anchors.csv
  data/reference/traffic_counts_historic.csv
  data/reference/evup_public_stations_snapshot_2026-11-18.csv

Writes under data/derived/:
  corridor_candidate_sites.csv
  corridor_demand_location_candidates.csv
  historic_traffic_count_route_locations.csv
  evup_station_geocoding_queue.csv
  corridor_candidate_points.geojson
  README.txt

Important:
- Candidate sites are points sampled on the OSM-derived corridor centreline. They
  are screening locations, NOT verified parcels, grid connection points, or
  safe highway access locations.
- Waypoints are potential demand-location references only. No daily EV demand is
  invented; demand_kwh_day is intentionally blank.
- Historic traffic-count locations are projected using the supplied chainage
  values and an explicit assumption that the chainage origin matches the route
  origin at Yerevan. Verify that convention against the source report before use.
- EVUP rows lack coordinates in the supplied snapshot and are exported to a
  geocoding queue rather than assigned invented coordinates.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, Point, mapping
from shapely.ops import linemerge, transform

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
DATA = ROOT / "data"
DERIVED = DATA / "derived"
ROUTE_FILES = {
    "M1": RESULTS / "official_M1_route.geojson",
    "M2": RESULTS / "official_M2_route.geojson",
}
ANCHORS_FILE = RESULTS / "official_corridor_waypoint_anchors.csv"
TRAFFIC_FILE = DATA / "reference" / "traffic_counts_historic.csv"
EVUP_FILE = DATA / "reference" / "evup_public_stations_snapshot_2026-11-18.csv"

TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32638", always_xy=True).transform
TO_WGS84 = Transformer.from_crs("EPSG:32638", "EPSG:4326", always_xy=True).transform


def read_csv(path: Path, required: set[str]) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Required input file is missing: {path}")
    frame = pd.read_csv(path, encoding="utf-8-sig")
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{path} is missing required columns: {sorted(missing)}")
    return frame


def load_route(route_id: str) -> tuple[LineString, LineString, float]:
    path = ROUTE_FILES[route_id]
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Run scripts/build_official_corridor_routes.py first."
        )
    gdf = gpd.read_file(path)
    if gdf.empty or "geometry" not in gdf:
        raise ValueError(f"No route geometry found in {path}")
    geoms = [geom for geom in gdf.geometry if geom is not None and not geom.is_empty]
    if not geoms:
        raise ValueError(f"Empty route geometry in {path}")
    geom = geoms[0] if len(geoms) == 1 else linemerge(MultiLineString(geoms))
    if isinstance(geom, MultiLineString):
        # A MultiLineString here is not silently concatenated: that could invent
        # chainage across disconnected pieces. Fail with a clear diagnostic.
        raise ValueError(f"{route_id} route is still multipart; inspect {path}")
    if not isinstance(geom, LineString):
        raise TypeError(f"Expected LineString for {route_id}, got {geom.geom_type}")
    metric = transform(TO_UTM, geom)
    length_km = metric.length / 1000.0
    if not math.isfinite(length_km) or length_km <= 0:
        raise ValueError(f"Invalid {route_id} route length: {length_km}")
    return geom, metric, length_km


def point_at_chainage(route_wgs: LineString, route_metric: LineString, chainage_km: float) -> tuple[float, float, float]:
    distance_m = max(0.0, min(float(chainage_km) * 1000.0, route_metric.length))
    point_metric = route_metric.interpolate(distance_m)
    point_wgs = transform(TO_WGS84, point_metric)
    return float(point_wgs.x), float(point_wgs.y), distance_m / 1000.0


def project_anchor(row: pd.Series, route_metric: LineString) -> tuple[float, float, float]:
    lon = float(row["anchor_longitude"])
    lat = float(row["anchor_latitude"])
    p_metric = transform(TO_UTM, Point(lon, lat))
    chainage_m = route_metric.project(p_metric)
    nearest = route_metric.interpolate(chainage_m)
    offset_m = p_metric.distance(nearest)
    return chainage_m / 1000.0, offset_m, chainage_m


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spacing-km", type=float, default=10.0,
                        help="Spacing for uniform centreline screening candidates (default: 10 km).")
    parser.add_argument("--output", type=Path, default=DERIVED,
                        help="Output directory (default: data/derived).")
    args = parser.parse_args()
    if not math.isfinite(args.spacing_km) or args.spacing_km <= 0:
        parser.error("--spacing-km must be a positive number")
    out = args.output
    out.mkdir(parents=True, exist_ok=True)

    print("[1/6] Loading routed M1/M2 geometries...")
    routes: dict[str, tuple[LineString, LineString, float]] = {
        rid: load_route(rid) for rid in ("M1", "M2")
    }
    for rid, (_, _, length) in routes.items():
        print(f"      {rid}: {length:.3f} km")

    print("[2/6] Loading and projecting official waypoint anchors...")
    anchors = read_csv(
        ANCHORS_FILE,
        {"route_id", "sequence_order", "waypoint_name", "anchor_longitude", "anchor_latitude"},
    )
    anchors["route_id"] = anchors.route_id.astype(str).str.upper()
    anchors["sequence_order"] = pd.to_numeric(anchors.sequence_order, errors="raise").astype(int)
    demand_rows: list[dict[str, Any]] = []
    anchor_chainages: dict[str, list[tuple[float, str]]] = {"M1": [], "M2": []}
    for _, row in anchors.sort_values(["route_id", "sequence_order"]).iterrows():
        rid = str(row.route_id)
        if rid not in routes:
            continue
        _, route_metric, length = routes[rid]
        chainage, offset_m, _ = project_anchor(row, route_metric)
        if chainage < -1e-6 or chainage > length + 1e-6:
            raise ValueError(f"Anchor outside {rid} route: {row.waypoint_name}")
        anchor_chainages[rid].append((chainage, str(row.waypoint_name)))
        demand_rows.append({
            "demand_id": f"{rid}_WP_{int(row.sequence_order):02d}",
            "route_id": rid,
            "sequence_order": int(row.sequence_order),
            "demand_name": str(row.waypoint_name),
            "latitude": float(row.anchor_latitude),
            "longitude": float(row.anchor_longitude),
            "chainage_km": round(chainage, 6),
            "route_projection_offset_m": round(offset_m, 2),
            "demand_kwh_day": np.nan,
            "source": "official route waypoint anchor snapped to OSM-derived corridor",
            "data_status": "LOCATION_REFERENCE_ONLY_DEMAND_NOT_ESTIMATED",
        })

    demand_df = pd.DataFrame(demand_rows)
    demand_path = out / "corridor_demand_location_candidates.csv"
    demand_df.to_csv(demand_path, index=False, encoding="utf-8-sig")

    print("[3/6] Creating regularly spaced centreline screening sites...")
    site_rows: list[dict[str, Any]] = []
    geo_features: list[dict[str, Any]] = []
    for rid in ("M1", "M2"):
        route_wgs, route_metric, length = routes[rid]
        distances = list(np.arange(0.0, length, args.spacing_km))
        if not distances or abs(distances[0]) > 1e-9:
            distances.insert(0, 0.0)
        if length - distances[-1] > 1e-6:
            distances.append(length)
        waypoints = sorted(anchor_chainages[rid], key=lambda x: x[0])
        for idx, chainage in enumerate(distances, start=1):
            lon, lat, actual_chainage = point_at_chainage(route_wgs, route_metric, chainage)
            before = [w for km, w in waypoints if km <= actual_chainage]
            after = [w for km, w in waypoints if km >= actual_chainage]
            site_id = f"{rid}_C{idx:03d}"
            row = {
                "site_id": site_id,
                "route_id": rid,
                "latitude": lat,
                "longitude": lon,
                "chainage_km": round(actual_chainage, 6),
                "candidate_type": "uniform_route_centreline_screening_point",
                "spacing_target_km": args.spacing_km,
                "previous_waypoint": before[-1] if before else "",
                "next_waypoint": after[0] if after else "",
                "fixed_cost": np.nan,
                "charger_cost": np.nan,
                "max_chargers": np.nan,
                "grid_capacity_kw": np.nan,
                "power_cost_weight": np.nan,
                "source": "sampled from OSM-derived routed corridor geometry",
                "site_status": "SCREENING_ONLY_ACCESS_LAND_GRID_AND_COSTS_UNVERIFIED",
            }
            site_rows.append(row)
            geo_features.append({
                "geometry": Point(lon, lat),
                "feature_type": "candidate_site",
                "feature_id": site_id,
                "route_id": rid,
                "chainage_km": round(actual_chainage, 6),
                "name": "",
            })
    sites_df = pd.DataFrame(site_rows)
    sites_path = out / "corridor_candidate_sites.csv"
    sites_df.to_csv(sites_path, index=False, encoding="utf-8-sig")

    print("[4/6] Mapping historical traffic stations by supplied chainage...")
    traffic = read_csv(
        TRAFFIC_FILE,
        {"road_id", "count_station", "chainage_km", "year", "total_vehicles_per_day"},
    )
    traffic_rows: list[dict[str, Any]] = []
    for _, row in traffic.iterrows():
        rid = str(row.road_id).upper()
        if rid not in routes:
            continue
        _, route_metric, length = routes[rid]
        source_chainage = float(row.chainage_km)
        if source_chainage < 0 or source_chainage > length:
            status = "OUTSIDE_ROUTE_LENGTH_CHECK_CHAINAGE_REFERENCE"
            lon = lat = np.nan
            route_chainage = np.nan
        else:
            lon, lat, route_chainage = point_at_chainage(*routes[rid][:2], source_chainage)
            status = "APPROXIMATE_CHAINAGE_PROJECTION_VERIFY_SOURCE_ZERO_ORIGIN"
        traffic_rows.append({
            "route_id": rid,
            "road_id": row.road_id,
            "count_station": row.count_station,
            "source_chainage_km": source_chainage,
            "mapped_route_chainage_km": round(route_chainage, 6) if pd.notna(route_chainage) else np.nan,
            "year": int(row.year),
            "light_vehicles_per_day": row.get("light_vehicles_per_day", np.nan),
            "trucks_per_day": row.get("trucks_per_day", np.nan),
            "truck_trailers_per_day": row.get("truck_trailers_per_day", np.nan),
            "total_vehicles_per_day": float(row.total_vehicles_per_day),
            "latitude": lat,
            "longitude": lon,
            "source": row.get("source", ""),
            "mapping_status": status,
        })
        if pd.notna(lon) and pd.notna(lat):
            geo_features.append({
                "geometry": Point(float(lon), float(lat)),
                "feature_type": "historic_traffic_count",
                "feature_id": f"{rid}_{row.count_station}_{int(row.year)}",
                "route_id": rid,
                "chainage_km": round(route_chainage, 6),
                "name": str(row.count_station),
            })
    traffic_df = pd.DataFrame(traffic_rows)
    traffic_path = out / "historic_traffic_count_route_locations.csv"
    traffic_df.to_csv(traffic_path, index=False, encoding="utf-8-sig")

    print("[5/6] Preparing EVUP records for geocoding; no coordinates will be guessed...")
    evup = read_csv(EVUP_FILE, {"station_code", "station_name", "locality", "address"})
    evup_queue = evup.copy()
    evup_queue["latitude"] = np.nan
    evup_queue["longitude"] = np.nan
    evup_queue["geocoding_status"] = "COORDINATES_NOT_PRESENT_IN_SOURCE_NEEDS_GEOCODING"
    evup_queue["route_assignment"] = "UNASSIGNED"
    evup_queue["model_use"] = "EXISTING_STATION_CONTEXT_ONLY_UNTIL_GEOCODED_AND_VERIFIED"
    evup_path = out / "evup_station_geocoding_queue.csv"
    evup_queue.to_csv(evup_path, index=False, encoding="utf-8-sig")

    if geo_features:
        geo = gpd.GeoDataFrame(geo_features, geometry="geometry", crs="EPSG:4326")
        geo.to_file(out / "corridor_candidate_points.geojson", driver="GeoJSON")

    print("[6/6] Writing data-readiness report...")
    total_sites = len(sites_df)
    report = [
        "CORRIDOR CANDIDATE DATA PREPARATION",
        "====================================",
        "",
        f"M1 route length: {routes['M1'][2]:.3f} km",
        f"M2 route length: {routes['M2'][2]:.3f} km",
        f"Candidate centreline sites: {total_sites} (spacing target {args.spacing_km:g} km)",
        f"Waypoint-based demand location references: {len(demand_df)}",
        f"Historical traffic observations mapped: {len(traffic_df)}",
        f"EVUP station records awaiting geocoding: {len(evup_queue)}",
        "",
        "IMPORTANT DATA LIMITATIONS",
        "1. Candidate sites lie on route centreline geometry. They are not verified road exits, parcels, grid connection points, or construction-feasible sites.",
        "2. Waypoint demand locations contain coordinates only. demand_kwh_day is blank because no validated EV energy-demand estimate was provided.",
        "3. Historical traffic counts remain historical (2012/2017/2018 as present in the source). They are not current 2026 AADT observations.",
        "4. Traffic point coordinates assume the source chainage zero is aligned with the routed geometry origin at Yerevan. Verify the ADB chainage convention before using these coordinates as exact.",
        "5. EVUP station coordinates are absent from the input CSV. No locations or corridor assignments were fabricated.",
        "6. These outputs are preprocessing/screening artifacts. Do not pass them directly to the MILP until costs, grid capacities, demand energy, and access distances are validated.",
        "",
        "NEXT REQUIRED REAL INPUTS",
        "- Geocoded coordinates and corridor assignment for existing EVUP stations.",
        "- Current traffic counts or an explicitly documented traffic growth method.",
        "- EV share, charging probability, energy per charging session, and daily demand estimation assumptions with sources.",
        "- Candidate-site land/civil costs, charger costs, grid connection capacity and power costs.",
        "- Road-network access distances from demand locations to candidate sites (not merely straight-line distances).",
    ]
    readme_path = out / "README.txt"
    readme_path.write_text("\n".join(report), encoding="utf-8")

    print("\nPREPARATION SUMMARY")
    print(f"  Candidate centreline sites: {len(sites_df)}")
    print(f"  Demand location references: {len(demand_df)} (energy values intentionally blank)")
    print(f"  Historical traffic rows mapped: {len(traffic_df)}")
    print(f"  EVUP records awaiting geocoding: {len(evup_queue)}")
    print(f"\nSaved outputs to: {out}")
    for filename in (sites_path, demand_path, traffic_path, evup_path, out / "corridor_candidate_points.geojson", readme_path):
        print(f"  - {filename.name}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}")
        raise

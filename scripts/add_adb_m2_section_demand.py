#!/usr/bin/env python3
"""Add a documented ADB-based M2 subsection demand point to all traffic scenarios.

Run from project root:
  .\\.venv\\Scripts\\python.exe scripts\\add_adb_m2_section_demand.py

The added point represents M2 km13.1-28.9, with a reference location at km16.
Its 2026 traffic is an interpolation between ADB's 2025 and 2032 forecasts,
converted to light vehicles using the 2012 subsection vehicle composition.
It is NOT a measured 2026 traffic count.

The script is idempotent: it replaces the same demand_id on repeat runs.
It creates a one-time backup of traffic_ev_demand_scenarios before modifying it.
"""
from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import linemerge, transform

ROOT = Path(__file__).resolve().parents[1]
DERIVED = ROOT / "data" / "derived"
SCENARIO_ROOT = DERIVED / "traffic_ev_demand_scenarios"
SITE_FILE = DERIVED / "corridor_candidate_sites.csv"
ROUTE_FILE = ROOT / "results" / "official_M2_route.geojson"
SUMMARY_FILE = SCENARIO_ROOT / "scenario_summary.csv"
RUNNER_FILE = ROOT / "scripts" / "run_case_study_scenario.py"
BACKUP_ROOT = DERIVED / "traffic_ev_demand_scenarios_backup_before_adb_m2_expansion"
REPORT_FILE = SCENARIO_ROOT / "adb_m2_section_addition_report.json"
DEMAND_ID = "M2_ADB_SECTION_13_1_28_9"
REFERENCE_CHAINAGE_KM = 16.0

# ADB, Armenia North-South Road Corridor Investment Program, Tranche 1
# Completion Report (Jan 2020), Appendix 9, Table 4 and Table 5, p.33.
ADB_2012_TOTAL = 13_942.0
ADB_2012_LIGHT = 10_960.0 + 1_129.0 + 986.0  # cars + pick-ups + minibuses
ADB_2025_TOTAL_FORECAST = 23_200.0
ADB_2032_TOTAL_FORECAST = 28_300.0
BASE_YEAR_FORECAST = 2025
END_YEAR_FORECAST = 2032
PROJECTION_YEAR = 2026

SCENARIOS = ("low", "base", "high")
CROSS_ROUTE_SENTINEL_DEFAULT = 99_999.0


def read_csv(path: Path, required: set[str]) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Required input not found: {path}")
    frame = pd.read_csv(path, encoding="utf-8-sig")
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")
    if frame.empty:
        raise ValueError(f"{path.name} contains no data rows")
    return frame


def load_m2_route_point(chainage_km: float) -> tuple[float, float, float]:
    """Return (latitude, longitude, metric route length km) at route chainage."""
    if not ROUTE_FILE.exists():
        raise FileNotFoundError(
            f"Missing {ROUTE_FILE}. Build official M2 route GeoJSON first."
        )
    payload: Any = json.loads(ROUTE_FILE.read_text(encoding="utf-8"))
    features = payload.get("features") if isinstance(payload, dict) else None
    if not features:
        raise ValueError("official_M2_route.geojson has no GeoJSON features")

    candidates = []
    for feature in features:
        props = feature.get("properties") or {}
        route_tag = str(props.get("route_id", props.get("route", ""))).upper()
        geom_data = feature.get("geometry")
        if not geom_data:
            continue
        geom = shape(geom_data)
        if geom.geom_type in {"LineString", "MultiLineString"}:
            candidates.append((route_tag == "M2", geom.length, geom))
    if not candidates:
        raise ValueError("No LineString/MultiLineString found in M2 route GeoJSON")
    # Prefer an explicitly tagged M2 feature; otherwise this file should contain
    # the M2 geometry only, so use its longest line geometry.
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    geometry = candidates[0][2]
    if geometry.geom_type == "MultiLineString":
        geometry = linemerge(geometry)
    if geometry.geom_type != "LineString":
        raise ValueError(f"Could not reduce M2 route to one LineString: {geometry.geom_type}")

    to_metric = Transformer.from_crs("EPSG:4326", "EPSG:32638", always_xy=True).transform
    to_wgs84 = Transformer.from_crs("EPSG:32638", "EPSG:4326", always_xy=True).transform
    metric = transform(to_metric, geometry)
    length_km = float(metric.length / 1000.0)
    if chainage_km <= 0 or chainage_km >= length_km:
        raise ValueError(
            f"Requested chainage {chainage_km:.3f} km is outside route length {length_km:.3f} km"
        )
    point_metric = metric.interpolate(chainage_km * 1000.0)
    point_wgs84 = transform(to_wgs84, point_metric)
    lon, lat = float(point_wgs84.x), float(point_wgs84.y)
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError("Interpolated M2 reference point has invalid coordinates")
    return lat, lon, length_km


def patch_runner_scope_text() -> bool:
    """Update future generated README/assumption wording without touching solver settings."""
    if not RUNNER_FILE.exists():
        return False
    text = RUNNER_FILE.read_text(encoding="utf-8")
    replacements = {
        '"Two documented historical ATC demand points only; not full-corridor demand."':
            '"Three screened demand scopes: one M1 historical ATC section, one M2 historical ATC section, and one ADB forecast-based M2 km13.1-28.9 subsection; remaining corridor demand is unobserved."',
        '"- Demand points are only the two historic ATC scopes documented in the traffic scenario folders.",':
            '"- Demand scopes: M1 Section 3 historical ATC; M2 km9.3-13.1 historical ATC; and M2 km13.1-28.9 ADB forecast-based subsection reference at km16.",',
        '"- The separate electricity OPEX table uses ENA tariff bounds; energy OPEX is not included in the current MILP objective.",':
            '"- The separate electricity OPEX table uses ENA tariff bounds for the three represented demand scopes; energy OPEX is not included in the current MILP objective.",',
        '"demand_scope": "Two documented historical ATC demand points only; not full-corridor demand.",':
            '"demand_scope": "Three represented scopes: M1 Section 3 ATC, M2 km9.3-13.1 ATC, and ADB forecast-based M2 km13.1-28.9 at km16; the rest of the full corridors remain unobserved.",',
        '"scope_warning": "Only two historic ATC locations are represented as demand points. These results cannot be interpreted as full M1/M2 demand or final Armenia network siting.",':
            '"scope_warning": "Three represented subsections only: M1 Section 3 ATC, M2 km9.3-13.1 ATC, and ADB forecast-based M2 km13.1-28.9. Remaining M1/M2 corridor demand is unobserved; results are not final Armenia network siting.",',
        '"- milp_demand_assignments.csv: assignments and screening distance proxies.",':
            '"- milp_demand_assignments.csv: assignments and screening distance proxies for the three represented demand scopes.",',
    }
    changed = False
    for old, new in replacements.items():
        if old in text:
            text = text.replace(old, new)
            changed = True
    if changed:
        RUNNER_FILE.with_suffix(RUNNER_FILE.suffix + ".pre_adb_scope.bak").write_text(
            RUNNER_FILE.read_text(encoding="utf-8"), encoding="utf-8"
        )
        RUNNER_FILE.write_text(text, encoding="utf-8")
    return changed


def main() -> int:
    print("[1/6] Loading candidate sites and the routed M2 centreline...")
    sites = read_csv(SITE_FILE, {"site_id", "route_id", "chainage_km", "latitude", "longitude"})
    sites["route_id"] = sites["route_id"].astype(str).str.upper().str.strip()
    sites["chainage_km"] = pd.to_numeric(sites["chainage_km"], errors="coerce")
    if sites["chainage_km"].isna().any():
        raise ValueError("Candidate sites contain invalid chainage values")
    m2_sites = sites[sites.route_id == "M2"]
    if m2_sites.empty:
        raise ValueError("No M2 candidate sites found")
    lat, lon, geometry_length_km = load_m2_route_point(REFERENCE_CHAINAGE_KM)
    candidate_span = float(m2_sites.chainage_km.max())
    if abs(candidate_span - geometry_length_km) > 2.0:
        raise ValueError(
            f"M2 route geometry ({geometry_length_km:.3f} km) and candidate chainage "
            f"({candidate_span:.3f} km) differ by more than 2 km; inspect route alignment"
        )
    print(
        f"      M2 km{REFERENCE_CHAINAGE_KM:g}: lat={lat:.6f}, lon={lon:.6f}; "
        f"routed length={geometry_length_km:.3f} km"
    )

    print("[2/6] Calculating the transparent 2026 ADB-based subsection traffic proxy...")
    light_share = ADB_2012_LIGHT / ADB_2012_TOTAL
    annual_growth = (ADB_2032_TOTAL_FORECAST / ADB_2025_TOTAL_FORECAST) ** (
        1.0 / (END_YEAR_FORECAST - BASE_YEAR_FORECAST)
    ) - 1.0
    total_2026 = ADB_2025_TOTAL_FORECAST * (1.0 + annual_growth) ** (
        PROJECTION_YEAR - BASE_YEAR_FORECAST
    )
    light_2026 = total_2026 * light_share
    print(
        f"      ADB 2025 total={ADB_2025_TOTAL_FORECAST:,.0f}; 2032 total={ADB_2032_TOTAL_FORECAST:,.0f}; "
        f"interpolated 2026 total={total_2026:,.1f}; light equivalent={light_2026:,.1f}/day"
    )

    print("[3/6] Creating a one-time backup and validating all three scenario folders...")
    if not SCENARIO_ROOT.exists():
        raise FileNotFoundError(f"Missing scenario root: {SCENARIO_ROOT}")
    if not BACKUP_ROOT.exists():
        shutil.copytree(SCENARIO_ROOT, BACKUP_ROOT)
        print(f"      Backup created: {BACKUP_ROOT}")
    else:
        print(f"      Existing backup retained: {BACKUP_ROOT}")

    scenario_params: dict[str, dict[str, float]] = {}
    for scenario in SCENARIOS:
        folder = SCENARIO_ROOT / scenario
        demand = read_csv(folder / "demand_points.csv", {
            "demand_id", "demand_kwh_day", "route_id", "chainage_km",
            "ev_share_assumption", "charging_probability_assumption", "energy_per_session_kwh_assumption",
        })
        if not (demand.route_id.astype(str).str.upper() == "M1").any():
            raise ValueError(f"{scenario}: expected M1 ATC row not found")
        ref = demand[demand.route_id.astype(str).str.upper() == "M1"].iloc[0]
        scenario_params[scenario] = {
            "ev_share": float(ref.ev_share_assumption),
            "charging_probability": float(ref.charging_probability_assumption),
            "session_kwh": float(ref.energy_per_session_kwh_assumption),
        }

    print("[4/6] Updating demand_points.csv, distances.csv and scenario_summary.csv...")
    summary_frames = []
    scenario_report = {}
    for scenario in SCENARIOS:
        folder = SCENARIO_ROOT / scenario
        demand_path = folder / "demand_points.csv"
        distances_path = folder / "distances.csv"
        demand = pd.read_csv(demand_path, encoding="utf-8-sig")
        distances = pd.read_csv(distances_path, encoding="utf-8-sig")

        params = scenario_params[scenario]
        ev_passages = light_2026 * params["ev_share"]
        sessions = ev_passages * params["charging_probability"]
        demand_kwh = sessions * params["session_kwh"]
        new_demand = {
            "demand_id": DEMAND_ID,
            "demand_kwh_day": demand_kwh,
            "route_id": "M2",
            "demand_name": "ADB forecast M2 km13.1-28.9 (reference at km16)",
            "latitude": lat,
            "longitude": lon,
            "chainage_km": REFERENCE_CHAINAGE_KM,
            "projection_year": PROJECTION_YEAR,
            "latest_observation_year": BASE_YEAR_FORECAST,
            "projected_light_vehicles_per_day": light_2026,
            "ev_share_assumption": params["ev_share"],
            "charging_probability_assumption": params["charging_probability"],
            "energy_per_session_kwh_assumption": params["session_kwh"],
            "route_scope_limit": (
                "M2 km13.1-28.9 subsection only; reference location km16. "
                "2026 traffic interpolated from ADB 2025 and 2032 forecasts, not measured AADT."
            ),
            "traffic_source": (
                "ADB (2020) North-South Road Corridor Tranche 1 Completion Report, "
                "Appendix 9 Table 4 (2012 vehicle composition) and Table 5 (2025/2032 forecasts)."
            ),
            "other_assumptions_status": (
                "ADB_FORECAST_INTERPOLATION_AND_2012_LIGHT_VEHICLE_SHARE; "
                "EV_SHARE_CHARGING_PROBABILITY_AND_SESSION_ENERGY_ARE_SCENARIO_ASSUMPTIONS"
            ),
        }
        # Preserve the scenario CSV schema and replace the same demand_id on reruns.
        demand = demand[demand.demand_id.astype(str) != DEMAND_ID].copy()
        demand = pd.concat([demand, pd.DataFrame([new_demand])], ignore_index=True)
        if demand.demand_id.astype(str).duplicated().any():
            raise ValueError(f"{scenario}: duplicate demand_id after update")
        demand.to_csv(demand_path, index=False, encoding="utf-8-sig")

        # Find the existing cross-route sentinel instead of silently changing it.
        site_routes = sites.set_index("site_id")["route_id"].to_dict()
        existing_cross = distances[
            distances.apply(
                lambda row: site_routes.get(str(row.site_id), "") != str(
                    demand.loc[demand.demand_id.astype(str) == str(row.demand_id), "route_id"].iloc[0]
                ).upper() if str(row.demand_id) in set(demand.demand_id.astype(str)) else False,
                axis=1,
            )
        ]
        if not existing_cross.empty:
            sentinel = float(pd.to_numeric(existing_cross.distance_km, errors="coerce").max())
        else:
            sentinel = CROSS_ROUTE_SENTINEL_DEFAULT
        if not math.isfinite(sentinel) or sentinel < 1000:
            sentinel = CROSS_ROUTE_SENTINEL_DEFAULT

        distances = distances[distances.demand_id.astype(str) != DEMAND_ID].copy()
        new_distance_rows = []
        for site in sites.itertuples(index=False):
            same_route = str(site.route_id).upper() == "M2"
            if same_route:
                distance_km = abs(float(site.chainage_km) - REFERENCE_CHAINAGE_KM)
                distance_type = "SAME_ROUTE_ABSOLUTE_CHAINAGE_SCREENING_PROXY_NOT_VALIDATED_DRIVING_DISTANCE"
                note = "ADB subsection reference at M2 km16; chainage proxy only; validate with directed road-network access routing."
            else:
                distance_km = sentinel
                distance_type = "STRUCTURALLY_INELIGIBLE_CROSS_CORRIDOR_PAIR_SENTINEL_NOT_A_REAL_DISTANCE"
                note = "M1 site cannot serve M2 subsection demand; sentinel is not a measured distance."
            row = {column: np.nan for column in distances.columns}
            row.update({
                "site_id": str(site.site_id),
                "demand_id": DEMAND_ID,
                "distance_km": distance_km,
                "distance_type": distance_type,
                "same_route": same_route,
                "source": "ADB M2 km13.1-28.9 subsection at km16 plus OSM route-centreline chainage proxy",
                "notes": note,
            })
            new_distance_rows.append(row)
        distances = pd.concat([distances, pd.DataFrame(new_distance_rows)], ignore_index=True)
        if distances[["site_id", "demand_id"]].duplicated().any():
            raise ValueError(f"{scenario}: duplicate site-demand pairs after update")
        expected_pairs = len(sites) * len(demand)
        if len(distances) != expected_pairs:
            raise ValueError(
                f"{scenario}: distance matrix has {len(distances)} rows, expected {expected_pairs}"
            )
        distances.to_csv(distances_path, index=False, encoding="utf-8-sig")

        scenario_report[scenario] = {
            "demand_id": DEMAND_ID,
            "route_id": "M2",
            "chainage_km": REFERENCE_CHAINAGE_KM,
            "latitude": lat,
            "longitude": lon,
            "adb_2026_total_aadt_interpolated": total_2026,
            "adb_2026_light_vehicles_equivalent": light_2026,
            "ev_share_assumption": params["ev_share"],
            "charging_probability_assumption": params["charging_probability"],
            "energy_per_session_kwh_assumption": params["session_kwh"],
            "demand_kwh_day": demand_kwh,
            "traffic_status": "ADB_FORECAST_INTERPOLATION_NOT_MEASURED_2026_AADT",
        }
        summary_frames.append(new_demand | {
            "scenario_id": scenario,
            "count_station": "ADB_M2_KM16",
            "baseline_year": 2012,
            "baseline_light_vehicles_per_day": ADB_2012_LIGHT,
            "latest_observation_year": BASE_YEAR_FORECAST,
            "latest_light_vehicles_per_day": np.nan,
            "historical_light_traffic_cagr": np.nan,
            "source_chainage_km": REFERENCE_CHAINAGE_KM,
            "mapped_route_chainage_km": REFERENCE_CHAINAGE_KM,
            "chainage_mapping_status": "ROUTE_GEOMETRY_INTERPOLATION_AT_M2_KM16",
            "expected_ev_passages_per_day": ev_passages,
            "expected_charging_sessions_per_day": sessions,
            "traffic_growth_factor": (1.0 + annual_growth) ** (PROJECTION_YEAR - BASE_YEAR_FORECAST),
            "scenario_annual_traffic_growth": annual_growth,
        })
        assumptions_path = folder / "scenario_assumptions.json"
        if assumptions_path.exists():
            scenario_assumptions = json.loads(assumptions_path.read_text(encoding="utf-8"))
        else:
            scenario_assumptions = {"scenario_id": scenario}
        scenario_assumptions["demand_point_count"] = 3
        scenario_assumptions["additional_adb_m2_subsection_demand"] = {
            "demand_id": DEMAND_ID,
            "route_id": "M2",
            "chainage_km": REFERENCE_CHAINAGE_KM,
            "demand_kwh_day": demand_kwh,
            "source_status": "ADB_FORECAST_INTERPOLATION_NOT_MEASURED_2026_AADT",
            "source_url": "https://www.adb.org/sites/default/files/project-documents/42145/42145-023-pcr-en.pdf",
        }
        assumptions_path.write_text(json.dumps(scenario_assumptions, indent=2) + "\n", encoding="utf-8")
        print(f"      {scenario}: added {demand_kwh:,.2f} kWh/day; total demand points={len(demand)}")

    if SUMMARY_FILE.exists():
        summary = pd.read_csv(SUMMARY_FILE, encoding="utf-8-sig")
        if "demand_id" in summary.columns:
            summary = summary[summary.demand_id.astype(str) != DEMAND_ID]
        additions = pd.DataFrame(summary_frames)
        for col in summary.columns:
            if col not in additions.columns:
                additions[col] = np.nan
        for col in additions.columns:
            if col not in summary.columns:
                summary[col] = np.nan
        summary = pd.concat([summary, additions[summary.columns]], ignore_index=True)
        summary.to_csv(SUMMARY_FILE, index=False, encoding="utf-8-sig")

    print("[5/6] Updating assumptions and provenance notes...")
    assumption_payload = {
        "demand_id": DEMAND_ID,
        "route_id": "M2",
        "subsection": "M2 km13.1-28.9",
        "reference_location_chainage_km": REFERENCE_CHAINAGE_KM,
        "reference_coordinates_lat_lon": [lat, lon],
        "adb_2012_total_vehicles_per_day": ADB_2012_TOTAL,
        "adb_2012_light_vehicle_equivalent_per_day": ADB_2012_LIGHT,
        "adb_2012_light_vehicle_share": light_share,
        "adb_2025_total_aadt_forecast": ADB_2025_TOTAL_FORECAST,
        "adb_2032_total_aadt_forecast": ADB_2032_TOTAL_FORECAST,
        "interpolated_2026_total_aadt": total_2026,
        "interpolated_2026_light_vehicle_equivalent": light_2026,
        "interpolation_method": "Compound annual interpolation from ADB 2025 forecast to ADB 2032 forecast; 2012 subsection light-vehicle composition share applied to projected total traffic.",
        "not_measured_2026": True,
        "scenario_demand_kwh_day": {k: v["demand_kwh_day"] for k, v in scenario_report.items()},
        "source": "ADB (2020), North-South Road Corridor Investment Program Tranche 1 Completion Report, Appendix 9, p.33, Tables 4-5; paragraphs 12-14 explain the section scopes and km16 classified count.",
        "source_url": "https://www.adb.org/sites/default/files/project-documents/42145/42145-023-pcr-en.pdf",
        "scope_warning": "This adds only M2 km13.1-28.9. It does not create full-corridor demand for the remaining M1/M2 sections.",
        "ev_demand_warning": "EV share, charging probability and energy per session are the existing scenario assumptions; applying them uniformly to light-vehicle-equivalent traffic remains a simplification.",
    }
    REPORT_FILE.write_text(json.dumps(assumption_payload, indent=2) + "\n", encoding="utf-8")

    readme_path = SCENARIO_ROOT / "README.txt"
    if readme_path.exists():
        readme = readme_path.read_text(encoding="utf-8")
        readme = readme.replace(
            "Demand points per scenario: 2 (one historical ATC point on M1, one on M2)",
            "Demand points per scenario: 3 (M1 historical ATC; M2 km9.3-13.1 historical ATC; M2 km13.1-28.9 ADB forecast-based subsection reference at km16)",
        )
        marker_start = "\n--- ADB M2 SECTION ADDITION (SCRIPT-GENERATED) ---\n"
        marker_end = "\n--- END ADB M2 SECTION ADDITION ---\n"
        if marker_start in readme and marker_end in readme:
            before = readme.split(marker_start)[0]
            after = readme.split(marker_end, 1)[1]
            readme = before + after
        block = (
            marker_start
            + "Additional demand scope: M2 km13.1-28.9, reference location at km16.\n"
            + f"ADB Table 4 (2012): total={ADB_2012_TOTAL:.0f}, light-vehicle equivalent={ADB_2012_LIGHT:.0f}/day.\n"
            + f"ADB Table 5: 2025 forecast={ADB_2025_TOTAL_FORECAST:.0f}; 2032 forecast={ADB_2032_TOTAL_FORECAST:.0f}.\n"
            + f"2026 total traffic interpolated={total_2026:.1f}; light-vehicle equivalent={light_2026:.1f}/day.\n"
            + "This is an interpolation of ADB forecasts, not an observed 2026 count. EV-share, charging probability and session energy remain scenario assumptions.\n"
            + "M1 Section 3 and M2 km9.3-13.1 remain the two historical ATC scopes. The new M2 subsection is separate and non-overlapping per ADB paragraphs 12-14.\n"
            + "Source: ADB (2020), North-South Road Corridor Investment Program Tranche 1 Completion Report, Appendix 9, p.33, Tables 4-5.\n"
            + "https://www.adb.org/sites/default/files/project-documents/42145/42145-023-pcr-en.pdf\n"
            + marker_end
        )
        readme_path.write_text(readme.rstrip() + "\n" + block, encoding="utf-8")

    runner_patched = patch_runner_scope_text()
    print("[6/6] Complete")
    print(f"      2026 interpolated light-vehicle equivalent: {light_2026:,.1f}/day")
    print("      Added demand (kWh/day):")
    for scenario, row in scenario_report.items():
        print(f"        {scenario:>4}: {row['demand_kwh_day']:,.2f}")
    print(f"      Scenario folders updated: {SCENARIO_ROOT}")
    print(f"      Assumption report: {REPORT_FILE}")
    print(f"      Runner scope text updated: {runner_patched}")
    print("IMPORTANT: M2 demand scope is now three represented locations/sections total across M1/M2, not full corridor-wide demand.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build transparent low/base/high EV charging-demand scenarios from Armenia ATC data.

Run from the project root:
  .\\.venv\\Scripts\\python.exe scripts\\build_traffic_ev_demand_scenarios.py

Reads:
  data/reference/traffic_counts_historic.csv
  data/derived/historic_traffic_count_route_locations.csv
  data/derived/corridor_candidate_sites.csv
  data/derived/milp_corridor_route_lengths.json (optional)

Writes:
  data/derived/traffic_ev_demand_scenarios/<scenario>/demand_points.csv
  data/derived/traffic_ev_demand_scenarios/<scenario>/distances.csv
  data/derived/traffic_ev_demand_scenarios/scenario_summary.csv
  data/derived/traffic_ev_demand_scenarios/site_parameters_template.csv
  data/derived/traffic_ev_demand_scenarios/model_config_template.json
  data/derived/traffic_ev_demand_scenarios/README.txt

Scope and limitations:
- Demand is calculated ONLY at the two historical automatic traffic count (ATC)
  locations, not spread over the entire M1/M2 corridors.
- The ADB report says M1 km20.7 is representative of M1 Section 3, whereas M2
  km9.38 is representative only from the section start to the M15 junction at
  km13.1. Do not extrapolate these two observations over all of M1 or M2.
- 2026 traffic values are scenario projections from 2012-to-latest light-vehicle
  count CAGR, not measured 2026 counts.
- The 2.5% base EV share is a published estimate for personal-use vehicles in
  Armenia (SEI, 2025); low/high values are sensitivity assumptions.
- Charging probability and session energy are explicit analyst assumptions.
- Distances are same-corridor chainage proxies, not verified driving distances.
- Site cost, grid capacity, charger count and installation cost remain blank;
  this script does NOT produce a complete investment MILP case.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DERIVED = DATA / "derived"
TRAFFIC_SOURCE = DATA / "reference" / "traffic_counts_historic.csv"
TRAFFIC_MAPPED = DERIVED / "historic_traffic_count_route_locations.csv"
SITES_SOURCE = DERIVED / "corridor_candidate_sites.csv"
ROUTE_LENGTHS_SOURCE = DERIVED / "milp_corridor_route_lengths.json"
OUTPUT = DERIVED / "traffic_ev_demand_scenarios"

PROJECTION_YEAR_DEFAULT = 2026
BASE_EV_SHARE = 0.025
SCENARIOS: dict[str, dict[str, float | str]] = {
    "low": {
        "ev_share": BASE_EV_SHARE * 0.5,
        "charging_probability": 0.10,
        "energy_per_session_kwh": 20.0,
        "traffic_growth_fraction_of_historical_cagr": 0.0,
        "description": "Conservative sensitivity: half the published EV-share estimate; no traffic growth.",
    },
    "base": {
        "ev_share": BASE_EV_SHARE,
        "charging_probability": 0.20,
        "energy_per_session_kwh": 25.0,
        "traffic_growth_fraction_of_historical_cagr": 0.5,
        "description": "Central planning case: published EV-share estimate; half the recent historical light-traffic CAGR.",
    },
    "high": {
        "ev_share": BASE_EV_SHARE * 2.0,
        "charging_probability": 0.30,
        "energy_per_session_kwh": 30.0,
        "traffic_growth_fraction_of_historical_cagr": 1.0,
        "description": "High sensitivity: twice the published EV-share estimate; full recent historical light-traffic CAGR.",
    },
}
ROUTE_SCOPE = {
    "M1": "ADB: M1 ATC at km20.7 is representative of Section 3 only (project section km11.8-km23.2); not the entire Yerevan-Bavra corridor.",
    "M2": "ADB: M2 ATC at km9.38 is representative only from the section start to the M15 junction at km13.1; not the remainder of M2.",
}


def read_csv(path: Path, required: set[str]) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing required input: {path}")
    df = pd.read_csv(path, encoding="utf-8-sig")
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")
    if df.empty:
        raise ValueError(f"{path.name} contains no data rows")
    return df


def numeric(df: pd.DataFrame, column: str, file_name: str) -> pd.Series:
    values = pd.to_numeric(df[column], errors="coerce")
    if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
        raise ValueError(f"{file_name}: {column} contains missing or non-finite values")
    return values.astype(float)


def load_route_lengths(sites: pd.DataFrame) -> dict[str, float]:
    if ROUTE_LENGTHS_SOURCE.exists():
        payload: Any = json.loads(ROUTE_LENGTHS_SOURCE.read_text(encoding="utf-8"))
        lengths = payload.get("route_lengths_km") if isinstance(payload, dict) else None
        if isinstance(lengths, dict) and lengths:
            return {str(k): float(v) for k, v in lengths.items()}
    # The candidate file includes route start and end candidates. Its max chainage
    # is the full precision route length used by the prior spacing pipeline.
    return {
        str(route): float(group["chainage_km"].max())
        for route, group in sites.groupby("route_id", sort=True)
    }


def load_latest_atc_rows(traffic: pd.DataFrame, mapped: pd.DataFrame) -> list[dict[str, Any]]:
    required_traffic = {
        "road_id", "count_station", "chainage_km", "year",
        "light_vehicles_per_day", "source",
    }
    missing = required_traffic - set(traffic.columns)
    if missing:
        raise ValueError(f"{TRAFFIC_SOURCE.name} is missing columns: {sorted(missing)}")

    t = traffic.copy()
    t["route_id"] = t["road_id"].astype(str).str.strip().str.upper()
    for col in ("year", "chainage_km", "light_vehicles_per_day"):
        t[col] = pd.to_numeric(t[col], errors="coerce")
    t = t.dropna(subset=["year", "chainage_km", "light_vehicles_per_day"])
    t = t[t["route_id"].isin(["M1", "M2"])].copy()
    if t.empty:
        raise ValueError("No usable M1/M2 traffic-count rows were found")

    mapped_required = {"route_id", "count_station", "year", "mapped_route_chainage_km"}
    if not mapped_required.issubset(mapped.columns):
        raise ValueError(
            f"{TRAFFIC_MAPPED.name} must contain columns {sorted(mapped_required)}"
        )
    m = mapped.copy()
    m["route_id"] = m["route_id"].astype(str).str.strip().str.upper()
    m["year"] = pd.to_numeric(m["year"], errors="coerce")
    m["mapped_route_chainage_km"] = pd.to_numeric(
        m["mapped_route_chainage_km"], errors="coerce"
    )

    outputs: list[dict[str, Any]] = []
    for route_id in ("M1", "M2"):
        route = t[t["route_id"] == route_id].copy()
        if route.empty:
            raise ValueError(f"No traffic observations found for {route_id}")
        # Select the most recent row for this route/count-station pair.
        latest = route.sort_values(["year"]).iloc[-1]
        station_id = str(latest["count_station"])
        station_rows = route[route["count_station"].astype(str) == station_id]
        baseline_rows = station_rows[station_rows["year"] == 2012]
        if baseline_rows.empty:
            raise ValueError(
                f"{route_id}/{station_id}: a 2012 observation is required to compute the documented CAGR scenario"
            )
        baseline = baseline_rows.sort_values("year").iloc[-1]
        latest_year = int(latest["year"])
        baseline_year = int(baseline["year"])
        if latest_year <= baseline_year:
            raise ValueError(f"{route_id}: latest traffic year must be after 2012")
        baseline_light = float(baseline["light_vehicles_per_day"])
        latest_light = float(latest["light_vehicles_per_day"])
        if baseline_light <= 0 or latest_light <= 0:
            raise ValueError(f"{route_id}: light-vehicle counts must be positive")
        cagr = (latest_light / baseline_light) ** (1.0 / (latest_year - baseline_year)) - 1.0

        mapped_row = m[
            (m["route_id"] == route_id)
            & (m["count_station"].astype(str) == station_id)
            & (m["year"] == latest_year)
        ]
        if mapped_row.empty:
            raise ValueError(f"No mapped chainage row for {route_id}/{station_id}/{latest_year}")
        mapped_latest = mapped_row.iloc[0]
        chainage = float(mapped_latest["mapped_route_chainage_km"])
        if not math.isfinite(chainage) or chainage < 0:
            raise ValueError(f"Invalid mapped chainage for {route_id}")

        outputs.append({
            "route_id": route_id,
            "demand_id": f"{route_id}_ATC_{station_id}",
            "count_station": station_id,
            "baseline_year": baseline_year,
            "baseline_light_vehicles_per_day": baseline_light,
            "latest_observation_year": latest_year,
            "latest_light_vehicles_per_day": latest_light,
            "historical_light_traffic_cagr": cagr,
            "source_chainage_km": float(latest["chainage_km"]),
            "mapped_route_chainage_km": chainage,
            "latitude": float(mapped_latest["latitude"]) if pd.notna(mapped_latest.get("latitude")) else np.nan,
            "longitude": float(mapped_latest["longitude"]) if pd.notna(mapped_latest.get("longitude")) else np.nan,
            "traffic_source": str(latest.get("source", "")),
            "route_scope_limit": ROUTE_SCOPE[route_id],
            "chainage_mapping_status": str(mapped_latest.get("mapping_status", "")),
        })
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projection-year", type=int, default=PROJECTION_YEAR_DEFAULT)
    parser.add_argument("--service-distance-km", type=float, default=85.0)
    parser.add_argument("--interstation-distance-km", type=float, default=85.0)
    parser.add_argument("--cross-route-distance-km", type=float, default=99999.0)
    args = parser.parse_args()
    if args.projection_year < 2019:
        parser.error("--projection-year must be 2019 or later")
    if args.service_distance_km <= 0 or args.interstation_distance_km <= 0:
        parser.error("Distance thresholds must be positive")
    if args.cross_route_distance_km <= max(args.service_distance_km, 1000):
        parser.error("--cross-route-distance-km must be much larger than the service threshold")

    print("[1/6] Loading traffic records, mapped ATC points and candidate sites...")
    traffic = read_csv(
        TRAFFIC_SOURCE,
        {"road_id", "count_station", "chainage_km", "year", "light_vehicles_per_day", "source"},
    )
    mapped = read_csv(
        TRAFFIC_MAPPED,
        {"route_id", "count_station", "year", "mapped_route_chainage_km"},
    )
    sites = read_csv(
        SITES_SOURCE,
        {"site_id", "route_id", "latitude", "longitude", "chainage_km"},
    )
    sites["route_id"] = sites["route_id"].astype(str).str.strip().str.upper()
    sites["chainage_km"] = numeric(sites, "chainage_km", SITES_SOURCE.name)
    if sites["site_id"].astype(str).duplicated().any():
        raise ValueError("Candidate site_id values must be unique")
    route_lengths = load_route_lengths(sites)
    atc_rows = load_latest_atc_rows(traffic, mapped)
    print(f"      Candidate sites: {len(sites)} | ATC demand points: {len(atc_rows)}")

    print("[2/6] Calculating transparent 2026 traffic projections...")
    summary_rows: list[dict[str, Any]] = []
    scenario_data: dict[str, list[dict[str, Any]]] = {key: [] for key in SCENARIOS}
    for atc in atc_rows:
        years_to_project = args.projection_year - int(atc["latest_observation_year"])
        if years_to_project < 0:
            raise ValueError("Projection year cannot precede the latest traffic observation")
        for scenario_id, params in SCENARIOS.items():
            growth_fraction = float(params["traffic_growth_fraction_of_historical_cagr"])
            annual_growth = float(atc["historical_light_traffic_cagr"]) * growth_fraction
            growth_factor = (1.0 + annual_growth) ** years_to_project
            projected_light = float(atc["latest_light_vehicles_per_day"]) * growth_factor
            ev_share = float(params["ev_share"])
            charging_probability = float(params["charging_probability"])
            session_kwh = float(params["energy_per_session_kwh"])
            ev_passages = projected_light * ev_share
            sessions_day = ev_passages * charging_probability
            demand_kwh_day = sessions_day * session_kwh
            row = {
                "scenario_id": scenario_id,
                "route_id": atc["route_id"],
                "demand_id": atc["demand_id"],
                "count_station": atc["count_station"],
                "demand_name": f"ATC {atc['count_station']}",
                "latitude": atc["latitude"],
                "longitude": atc["longitude"],
                "chainage_km": atc["mapped_route_chainage_km"],
                "demand_kwh_day": demand_kwh_day,
                "light_vehicles_latest_observed_per_day": atc["latest_light_vehicles_per_day"],
                "latest_observation_year": atc["latest_observation_year"],
                "projected_light_vehicles_per_day": projected_light,
                "projection_year": args.projection_year,
                "historical_light_traffic_cagr": atc["historical_light_traffic_cagr"],
                "scenario_annual_traffic_growth": annual_growth,
                "traffic_growth_factor": growth_factor,
                "ev_share_assumption": ev_share,
                "expected_ev_passages_per_day": ev_passages,
                "charging_probability_assumption": charging_probability,
                "expected_charging_sessions_per_day": sessions_day,
                "energy_per_session_kwh_assumption": session_kwh,
                "route_scope_limit": atc["route_scope_limit"],
                "traffic_source": atc["traffic_source"],
                "ev_share_source": "SEI National Comprehensive Green Transition Assessment Report for Armenia, June 2025; 2.5% estimated share of EVs in personal-use vehicles. Low/high are sensitivity multipliers.",
                "other_assumptions_status": "ANALYST_ASSUMPTIONS_FOR_SENSITIVITY_NOT_MEASURED",
                "chainage_mapping_status": atc["chainage_mapping_status"],
                "description": str(params["description"]),
            }
            scenario_data[scenario_id].append(row)
            summary_rows.append(row)

    print("[3/6] Building demand points and screening distance matrices...")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    # Keep a single copy of the site template. Cost/grid fields remain blank.
    site_cols = [
        "site_id", "route_id", "chainage_km", "latitude", "longitude",
        "fixed_cost", "charger_cost", "max_chargers", "grid_capacity_kw",
        "power_cost_weight", "source", "site_status",
    ]
    for col in site_cols:
        if col not in sites.columns:
            sites[col] = np.nan
    site_template = sites[site_cols].sort_values(["route_id", "chainage_km", "site_id"])
    site_template.to_csv(OUTPUT / "site_parameters_template.csv", index=False, encoding="utf-8-sig")

    for scenario_id, rows in scenario_data.items():
        scenario_dir = OUTPUT / scenario_id
        scenario_dir.mkdir(parents=True, exist_ok=True)
        demand_df = pd.DataFrame(rows)
        demand_cols = [
            "demand_id", "demand_kwh_day", "route_id", "demand_name", "latitude", "longitude",
            "chainage_km", "projection_year", "latest_observation_year",
            "projected_light_vehicles_per_day", "ev_share_assumption",
            "charging_probability_assumption", "energy_per_session_kwh_assumption",
            "route_scope_limit", "traffic_source", "other_assumptions_status",
        ]
        demand_df[demand_cols].to_csv(scenario_dir / "demand_points.csv", index=False, encoding="utf-8-sig")

        distance_rows: list[dict[str, Any]] = []
        for site in sites.itertuples(index=False):
            for demand in demand_df.itertuples(index=False):
                same_route = str(site.route_id).upper() == str(demand.route_id).upper()
                if same_route:
                    dist = abs(float(site.chainage_km) - float(demand.chainage_km))
                    distance_type = "SAME_ROUTE_ABSOLUTE_CHAINAGE_SCREENING_PROXY_NOT_VALIDATED_DRIVING_DISTANCE"
                else:
                    # Structural exclusion: the two separately routed corridors
                    # are not allowed to serve one another's demand points.
                    dist = float(args.cross_route_distance_km)
                    distance_type = "STRUCTURALLY_INELIGIBLE_CROSS_CORRIDOR_PAIR_SENTINEL_NOT_A_REAL_DISTANCE"
                distance_rows.append({
                    "site_id": str(site.site_id),
                    "demand_id": str(demand.demand_id),
                    "distance_km": dist,
                    "distance_type": distance_type,
                    "same_route": same_route,
                    "source": "OSM route-centreline chainage proxy",
                    "notes": (
                        "Same-route chainage difference only; validate with directed road-network access routing."
                        if same_route else
                        "Sentinel used only to make this cross-corridor pair ineligible under the service-distance bound; not a measured distance."
                    ),
                })
        distance_df = pd.DataFrame(distance_rows)
        distance_df.to_csv(scenario_dir / "distances.csv", index=False, encoding="utf-8-sig")

        assumptions = {
            "scenario_id": scenario_id,
            "projection_year": int(args.projection_year),
            "max_service_distance_km": float(args.service_distance_km),
            "max_interstation_distance_km": float(args.interstation_distance_km),
            "route_lengths_km": route_lengths,
            "ev_share_assumption": float(SCENARIOS[scenario_id]["ev_share"]),
            "charging_probability_assumption": float(SCENARIOS[scenario_id]["charging_probability"]),
            "energy_per_session_kwh_assumption": float(SCENARIOS[scenario_id]["energy_per_session_kwh"]),
            "traffic_growth_fraction_of_historical_cagr": float(SCENARIOS[scenario_id]["traffic_growth_fraction_of_historical_cagr"]),
            "description": str(SCENARIOS[scenario_id]["description"]),
            "warning": "This is a traffic-counter subsection screening scenario, not a full-corridor demand model or a complete investment case.",
        }
        (scenario_dir / "scenario_assumptions.json").write_text(
            json.dumps(assumptions, indent=2) + "\n", encoding="utf-8"
        )

    print("[4/6] Saving scenario summary and historical-growth diagnostics...")
    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(OUTPUT / "scenario_summary.csv", index=False, encoding="utf-8-sig")
    diag_rows = []
    for atc in atc_rows:
        diag_rows.append({
            "route_id": atc["route_id"],
            "count_station": atc["count_station"],
            "baseline_year": atc["baseline_year"],
            "baseline_light_vehicles_per_day": atc["baseline_light_vehicles_per_day"],
            "latest_year": atc["latest_observation_year"],
            "latest_light_vehicles_per_day": atc["latest_light_vehicles_per_day"],
            "historical_light_traffic_cagr": atc["historical_light_traffic_cagr"],
            "projection_year": args.projection_year,
            "years_projected": args.projection_year - atc["latest_observation_year"],
            "scope_limit": atc["route_scope_limit"],
            "chainage_mapping_status": atc["chainage_mapping_status"],
        })
    pd.DataFrame(diag_rows).to_csv(OUTPUT / "traffic_growth_diagnostics.csv", index=False, encoding="utf-8-sig")

    print("[5/6] Writing configuration template and data-readiness report...")
    config_template = {
        "charger_daily_capacity_kwh": None,
        "max_service_distance_km": float(args.service_distance_km),
        "charger_peak_power_kw": None,
        "budget": None,
        "distance_weight": None,
        "max_interstation_distance_km": float(args.interstation_distance_km),
        "route_lengths_km": route_lengths,
        "power_cost_weight_note": "Site-specific values must be supplied from grid/utility cost evidence.",
        "capital_cost_note": "Do not use blank/assumed site or charger costs as verified Armenia costs.",
    }
    (OUTPUT / "model_config_template.json").write_text(
        json.dumps(config_template, indent=2) + "\n", encoding="utf-8"
    )

    base_rows = summary_df[summary_df["scenario_id"] == "base"]
    lines = [
        "TRAFFIC-BASED EV CHARGING DEMAND SCENARIOS",
        "==========================================",
        f"Projection year: {args.projection_year}",
        f"Candidate sites: {len(sites)}",
        "Demand points per scenario: 2 (one historical ATC point on M1, one on M2)",
        "",
        "BASE SCENARIO DAILY DEMAND (kWh/day):",
    ]
    for r in base_rows.itertuples(index=False):
        lines.append(f"  {r.route_id} / {r.count_station}: {r.demand_kwh_day:.2f} kWh/day")
    lines.extend([
        "",
        "MODEL AND DATA LIMITATIONS:",
        "1. These demand points represent only the traffic-counter locations/sections described below, not all 555 km of the corridors.",
        "2. ADB says M1 km20.7 represents M1 Section 3 only; M2 km9.38 represents only the section start to M15 junction km13.1.",
        "3. Traffic projection to the selected year is a scenario extrapolation using 2012-to-latest light-vehicle CAGR; it is not a measured AADT forecast.",
        "4. Base EV share 2.5% is taken from SEI (2025) as an estimate for personal-use vehicles; low/high apply 0.5x/2x sensitivity multipliers.",
        "5. Charging probabilities (10/20/30%) and session energies (20/25/30 kWh) are analyst assumptions and require validation/sensitivity discussion.",
        "6. EV share is applied to light-vehicle counts only; heavy vehicles are excluded from EV charging demand in this initial scenario.",
        "7. Same-route distances are absolute chainage differences. They are proxies, not validated directed driving distances.",
        "8. Cross-corridor distance rows use a large sentinel only to prohibit cross-route assignment; sentinel values are not real distances.",
        "9. Site fixed costs, charger costs, max charger counts, grid capacities, charger service capacity, and project budget remain unspecified.",
        "10. The files are not yet a complete load_problem_from_csv case. Fill and validate the missing technical/economic parameters first.",
        "",
        "SOURCE NOTES:",
        "- ADB (2020), Armenia: North-South Road Corridor Investment Program Tranche 1, Appendix 9, pp.32-33. ATC records from Armenian Roads Directorate; scope limits in paragraphs 12-14. https://www.adb.org/sites/default/files/project-documents/42145/42145-023-pcr-en.pdf",
        "- SEI (June 2025), National Comprehensive Green Transition Assessment Report for Armenia, pp.234-235: estimated 2.5% EV share in personal-use vehicles. https://www.sei.org/wp-content/uploads/2023/07/nationalcomprehensiveassessment-armenia.pdf",
        "- IEA (2025), Sustainable Transport Policy for Armenia: A Roadmap: 36,000 EV imports during 2019-2024, including 9,528 in 2024; used as market context, not as EV stock/share. https://www.iea.org/reports/sustainable-transport-policy-for-armenia-a-roadmap/sustainable-transport-in-armenia",
        "",
        "NO CLAIM: This is not a verified 2026 demand forecast and not a final investment optimization.",
    ])
    (OUTPUT / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("[6/6] Summary")
    for scenario_id in SCENARIOS:
        frame = summary_df[summary_df.scenario_id == scenario_id]
        total = float(frame.demand_kwh_day.sum())
        print(f"      {scenario_id:>4}: total screening demand = {total:,.1f} kWh/day")
        for row in frame.itertuples(index=False):
            print(f"           {row.route_id}: {row.demand_kwh_day:,.1f} kWh/day | {row.projected_light_vehicles_per_day:,.0f} light vehicles/day")
    print(f"\nSaved outputs to: {OUTPUT}")
    print("      scenario folders: low / base / high")
    print("      scenario_summary.csv")
    print("      traffic_growth_diagnostics.csv")
    print("      site_parameters_template.csv")
    print("      model_config_template.json")
    print("      README.txt")
    print("\nIMPORTANT: demand applies only to the two documented ATC scopes; full-corridor demand remains unobserved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

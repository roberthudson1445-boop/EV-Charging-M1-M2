#!/usr/bin/env python3
"""Prepare and solve an explicitly provisional Armenia corridor MILP screen.

Run from the project root:
  .\\.venv\\Scripts\\python.exe scripts\\run_case_study_screening_milp.py

Solves one base-case route-aware MILP using the base 150-kW DC charger CAPEX
benchmark. It then produces low/base/high demand-capacity and electricity-OPEX
screenings, plus low/base/high charger-CAPEX revaluation of the base layout. This is NOT a full-corridor investment plan: the demand layer has
only two historic traffic-counter locations and site/grid data are assumptions.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DERIVED = ROOT / "data" / "derived"
TRAFFIC_SCENARIO_ROOT = DERIVED / "traffic_ev_demand_scenarios"
SITE_TEMPLATE = DERIVED / "milp_corridor_sites_template.csv"
ROUTE_LENGTHS = DERIVED / "milp_corridor_route_lengths.json"
OUTPUT = DERIVED / "case_study_screening_milp"

# US benchmark values, used only for sensitivity analysis (USD, not Armenia quotes).
# NREL 2024, Table 2, DC 150-kW port:
# low hardware/install = 66,400 + 45,800; high = 102,200 + 94,000.
CHARGER_COST_SCENARIOS: dict[str, dict[str, Any]] = {
    "low": {
        "hardware_usd_per_port": 66_400.0,
        "installation_usd_per_port": 45_800.0,
        "total_usd_per_port": 112_200.0,
    },
    "base": {
        "hardware_usd_per_port": 84_300.0,
        "installation_usd_per_port": 69_900.0,
        "total_usd_per_port": 154_200.0,
    },
    "high": {
        "hardware_usd_per_port": 102_200.0,
        "installation_usd_per_port": 94_000.0,
        "total_usd_per_port": 196_200.0,
    },
}

# Explicit modeling assumptions, not site surveys / utility connection approvals.
FIXED_SITE_COST_USD = 103_000.0  # USDOT example for a six-port 150-kW station.
CHARGER_POWER_KW = 150.0
MAX_CHARGERS_PER_SITE = 6
GRID_CAPACITY_PER_SITE_KW = CHARGER_POWER_KW * MAX_CHARGERS_PER_SITE
DAILY_THROUGHPUT_PER_CHARGER_KWH = 1_000.0  # approx. 6.67 full-load-equivalent hours/day.
MAX_SERVICE_DISTANCE_KM = 85.0  # proposal screening value, not a validated standard.
MAX_INTERSTATION_DISTANCE_KM = 85.0  # analyzed spacing scenario, independent of service distance.
BUDGET_USD = 20_000_000.0  # deliberately nonbinding screen cap, NOT an Armenian project budget.
DISTANCE_WEIGHT = 0.1  # analyst-set objective penalty coefficient; sensitivity required.
POWER_COST_WEIGHT_USD_PER_KW = 0.0  # no local grid-upgrade quote; grid-connection CAPEX excluded.

# ENA tariffs including VAT, official ENA tariff page. These are energy purchase
# tariff bounds, reported separately; they are NOT the public charging sell price.
ELECTRICITY_TARIFFS = [
    {"connection_class": "other_consumers_0.38kV", "period": "day", "tariff_amd_per_kwh": 53.48},
    {"connection_class": "other_consumers_0.38kV", "period": "night", "tariff_amd_per_kwh": 43.48},
    {"connection_class": "consumers_6_10kV", "period": "day", "tariff_amd_per_kwh": 50.48},
    {"connection_class": "consumers_6_10kV", "period": "night", "tariff_amd_per_kwh": 40.48},
]


def read_csv(path: Path, required: set[str]) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing required input: {path}")
    frame = pd.read_csv(path, encoding="utf-8-sig")
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")
    if frame.empty:
        raise ValueError(f"{path.name} has no data rows")
    return frame


def build_case_inputs(
    demand_scenario: str,
    cost_scenario: str,
    site_template: pd.DataFrame,
    route_lengths: dict[str, float],
) -> Path:
    scenario_dir = TRAFFIC_SCENARIO_ROOT / demand_scenario
    demand_source = read_csv(
        scenario_dir / "demand_points.csv", {"demand_id", "demand_kwh_day", "route_id", "chainage_km"}
    )
    distances_source = read_csv(
        scenario_dir / "distances.csv", {"site_id", "demand_id", "distance_km"}
    )
    demand_source["demand_kwh_day"] = pd.to_numeric(demand_source["demand_kwh_day"], errors="coerce")
    if demand_source["demand_kwh_day"].isna().any() or (demand_source["demand_kwh_day"] <= 0).any():
        raise ValueError(f"{demand_scenario}: demand_kwh_day must be positive and numeric")
    if distances_source["distance_km"].isna().any():
        raise ValueError(f"{demand_scenario}: distances.csv has missing distance values")

    sites = site_template.copy()
    sites["fixed_cost"] = FIXED_SITE_COST_USD
    sites["charger_cost"] = float(CHARGER_COST_SCENARIOS[cost_scenario]["total_usd_per_port"])
    sites["max_chargers"] = MAX_CHARGERS_PER_SITE
    sites["grid_capacity_kw"] = GRID_CAPACITY_PER_SITE_KW
    sites["power_cost_weight"] = POWER_COST_WEIGHT_USD_PER_KW
    sites["site_cost_basis"] = "US_BENCHMARK_TRANSFERRED_FOR_SENSITIVITY_ONLY"
    sites["grid_status"] = "ASSUMED_900_KW_PER_SITE_NOT_UTILITY_VERIFIED"

    case_id = f"demand_{demand_scenario}__charger_cost_{cost_scenario}"
    case_dir = OUTPUT / "inputs" / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    sites.to_csv(case_dir / "sites.csv", index=False, encoding="utf-8-sig")
    demand_cols = ["demand_id", "demand_kwh_day"]
    # Keep location/provenance information for reporting while the loader uses required columns.
    demand_source.to_csv(case_dir / "demand_points.csv", index=False, encoding="utf-8-sig")
    distances_source.to_csv(case_dir / "distances.csv", index=False, encoding="utf-8-sig")

    config = {
        "charger_daily_capacity_kwh": DAILY_THROUGHPUT_PER_CHARGER_KWH,
        "max_service_distance_km": MAX_SERVICE_DISTANCE_KM,
        "charger_peak_power_kw": CHARGER_POWER_KW,
        "budget": BUDGET_USD,
        "distance_weight": DISTANCE_WEIGHT,
        "max_interstation_distance_km": MAX_INTERSTATION_DISTANCE_KM,
        "route_lengths_km": route_lengths,
        "currency": "USD",
        "budget_status": "NONBINDING_SCREENING_PLACEHOLDER_NOT_AN_ARMENIA_PROJECT_BUDGET",
        "grid_connection_capex_status": "EXCLUDED_NO_SITE_SPECIFIC_UTILITY_QUOTE",
    }
    (case_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    assumptions = {
        "case_id": case_id,
        "demand_scenario": demand_scenario,
        "charger_cost_scenario": cost_scenario,
        "cost_currency": "USD",
        "fixed_site_cost_usd_per_open_site": FIXED_SITE_COST_USD,
        "fixed_site_cost_source": "USDOT Climate Strategies that Work (2024/2025 edition), citing Chu et al. (2023): $103,000 fixed station cost for an example six-port 150-kW station.",
        "charger_power_kw_per_port": CHARGER_POWER_KW,
        "charger_hardware_usd_per_port": CHARGER_COST_SCENARIOS[cost_scenario]["hardware_usd_per_port"],
        "charger_installation_usd_per_port": CHARGER_COST_SCENARIOS[cost_scenario]["installation_usd_per_port"],
        "charger_total_cost_usd_per_port": CHARGER_COST_SCENARIOS[cost_scenario]["total_usd_per_port"],
        "charger_cost_source": "NREL/TP-5400-88513 (September 2024), Table 2: DC 150-kW hardware and installation low/high; base is midpoint of low/high components.",
        "max_chargers_per_site": MAX_CHARGERS_PER_SITE,
        "grid_capacity_kw_per_site": GRID_CAPACITY_PER_SITE_KW,
        "grid_capacity_status": "ANALYST_ASSUMPTION_6_PORTS_X_150_KW_NOT_A_CONFIRMED_GRID_CONNECTION",
        "charger_daily_capacity_kwh_per_port": DAILY_THROUGHPUT_PER_CHARGER_KWH,
        "throughput_status": "ANALYST_ASSUMPTION_EQUIVALENT_TO_6.67_FULL_POWER_HOURS_PER_DAY",
        "max_service_distance_km": MAX_SERVICE_DISTANCE_KM,
        "max_interstation_distance_km": MAX_INTERSTATION_DISTANCE_KM,
        "budget_usd": BUDGET_USD,
        "budget_status": "NONBINDING_SCREENING_PLACEHOLDER_NOT_AN_ARMENIA_PROJECT_BUDGET",
        "distance_weight": DISTANCE_WEIGHT,
        "distance_weight_status": "ANALYST_SELECTED_COEFFICIENT_REQUIRES_SENSITIVITY_CALIBRATION",
        "power_cost_weight_usd_per_kw": POWER_COST_WEIGHT_USD_PER_KW,
        "power_cost_status": "SET_TO_ZERO_BECAUSE_ARMENIA_SITE_SPECIFIC_GRID_UPGRADE_CAPEX_IS_UNKNOWN; GRID_UPGRADE_COST_EXCLUDED",
        "demand_scope": "Two documented historical ATC demand points only; not full-corridor demand.",
        "distance_scope": "Same-route chainage screening proxies; not validated directed driving distances.",
        "fixed_and_port_cost_boundary_warning": "Fixed site allowance and per-port installation benchmark are sourced from different US cost summaries; potential overlap in generic site-work items cannot be ruled out. Treat as sensitivity inputs, not local bids.",
        "maintenance_status": "Excluded from current MILP objective; USDOT source gives a separate 5-year maintenance estimate of $75,000 for an example six-port station.",
        "utility_upgrades": "Excluded: NREL notes transformer/line-extension costs vary by utility and site and are not included in the cited per-port EVSE cost ranges.",
    }
    (case_dir / "assumptions.json").write_text(json.dumps(assumptions, indent=2) + "\n", encoding="utf-8")
    return case_dir


def main() -> int:
    print("[1/6] Checking generated traffic scenarios and route metadata...")
    sites = read_csv(
        SITE_TEMPLATE,
        {"site_id", "route_id", "chainage_km", "latitude", "longitude"},
    )
    sites["chainage_km"] = pd.to_numeric(sites["chainage_km"], errors="coerce")
    if sites["chainage_km"].isna().any() or sites["site_id"].duplicated().any():
        raise ValueError("Site chainages must be numeric and site_id values unique")
    route_payload = json.loads(ROUTE_LENGTHS.read_text(encoding="utf-8"))
    route_lengths = {str(k): float(v) for k, v in route_payload["route_lengths_km"].items()}
    if not route_lengths or any(not math.isfinite(v) or v <= 0 for v in route_lengths.values()):
        raise ValueError("Invalid route lengths in milp_corridor_route_lengths.json")

    for scenario in ("low", "base", "high"):
        if not (TRAFFIC_SCENARIO_ROOT / scenario / "demand_points.csv").exists():
            raise FileNotFoundError(f"Missing traffic-demand scenario '{scenario}'. Run build_traffic_ev_demand_scenarios.py first.")
    print(f"      Sites={len(sites)} | routes={','.join(sorted(route_lengths))}")

    print("[2/6] Preparing the base-case MILP input directory...")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    case_pairs = [("base", "base")]
    case_dirs: list[tuple[str, str, Path]] = []
    for demand_scenario, cost_scenario in case_pairs:
        case_dir = build_case_inputs(demand_scenario, cost_scenario, sites, route_lengths)
        case_dirs.append((demand_scenario, cost_scenario, case_dir))
    print(f"      Prepared {len(case_dirs)} complete input directory")

    print("[3/6] Loading the route-aware model and solving with SciPy/HiGHS...")
    # Import after input preparation, so a missing package still leaves reviewable inputs.
    try:
        from ev_charging.data_io import load_problem_from_csv
        from ev_charging.model import solve_milp
    except Exception as exc:
        raise RuntimeError(
            "Could not import ev_charging. Run this script using the project's .venv Python interpreter."
        ) from exc

    summary_rows: list[dict[str, Any]] = []
    selected_rows: list[dict[str, Any]] = []
    assignment_rows: list[dict[str, Any]] = []
    capex_sensitivity_rows: list[dict[str, Any]] = []
    for demand_scenario, cost_scenario, case_dir in case_dirs:
        case_id = case_dir.name
        try:
            print(f"      Solving {case_id} (requested MIP gap 1%, time limit 60 s)...", flush=True)
            problem = load_problem_from_csv(case_dir)
            solution = solve_milp(problem, mip_rel_gap=0.01, time_limit_seconds=60.0)
            served_by_site = solution.assignment @ problem.demand_kwh_day
            opened_idx = np.flatnonzero(solution.opened)
            charger_count = int(solution.chargers.sum())
            selected_site_count = int(solution.opened.sum())
            selected_charger_count = int(solution.chargers.sum())
            summary_rows.append({
                "case_id": case_id,
                "demand_scenario": demand_scenario,
                "charger_cost_scenario": cost_scenario,
                "status": "SOLVED_WITHIN_REQUESTED_MIP_GAP",
                "requested_mip_rel_gap": 0.01,
                "achieved_mip_rel_gap": solution.mip_gap,
                "mip_node_count": solution.mip_node_count,
                "objective_value_model_units": solution.objective_value,
                "total_capital_cost_proxy_usd": (
                    solution.objective_breakdown["station_establishment"]
                    + solution.objective_breakdown["charger_installation"]
                ),
                "opened_station_count": selected_site_count,
                "charger_count": selected_charger_count,
                "installed_peak_power_kw": float(solution.power_kw.sum()),
                "total_demand_kwh_day": float(problem.demand_kwh_day.sum()),
                "station_establishment_cost_usd": solution.objective_breakdown["station_establishment"],
                "charger_installation_cost_usd": solution.objective_breakdown["charger_installation"],
                "distance_penalty_component_model_units": solution.objective_breakdown["distance_demand_penalty"],
                "electrical_capacity_cost_usd": solution.objective_breakdown["electrical_capacity_cost"],
                "solver_message": solution.solver_message,
            })
            for alternative_cost_scenario, cost_values in CHARGER_COST_SCENARIOS.items():
                port_cost = float(cost_values["total_usd_per_port"])
                site_cost = selected_site_count * FIXED_SITE_COST_USD
                charger_capex = selected_charger_count * port_cost
                capex_sensitivity_rows.append({
                    "case_id": case_id,
                    "demand_scenario": demand_scenario,
                    "optimized_layout_cost_basis": cost_scenario,
                    "revalued_charger_cost_scenario": alternative_cost_scenario,
                    "opened_station_count_fixed_layout": selected_site_count,
                    "charger_count_fixed_layout": selected_charger_count,
                    "site_fixed_cost_usd": site_cost,
                    "charger_hardware_and_installation_cost_usd": charger_capex,
                    "total_capital_cost_proxy_usd": site_cost + charger_capex,
                    "interpretation": "Post-optimization revaluation of the same selected layout; alternate costs are NOT re-optimized.",
                })
            case_sites = pd.read_csv(case_dir / "sites.csv")
            demand_df = pd.read_csv(case_dir / "demand_points.csv")
            distance_df = pd.read_csv(case_dir / "distances.csv")
            distance_lookup = distance_df.set_index(["site_id", "demand_id"])["distance_km"].to_dict()
            for i in opened_idx:
                selected_rows.append({
                    "case_id": case_id,
                    "route_id": str(case_sites.iloc[i]["route_id"]),
                    "site_id": problem.site_names[i],
                    "chainage_km": float(case_sites.iloc[i]["chainage_km"]),
                    "latitude": float(case_sites.iloc[i]["latitude"]),
                    "longitude": float(case_sites.iloc[i]["longitude"]),
                    "chargers": int(solution.chargers[i]),
                    "reserved_power_kw": float(solution.power_kw[i]),
                    "assigned_demand_kwh_day": float(served_by_site[i]),
                    "site_fixed_cost_usd": float(problem.fixed_cost[i]),
                    "charger_cost_usd_per_port": float(problem.charger_cost[i]),
                    "site_status": str(case_sites.iloc[i].get("site_status", "")),
                })
            for i, site_id in enumerate(problem.site_names):
                for j, demand_id in enumerate(problem.demand_names):
                    fraction = float(solution.assignment[i, j])
                    if fraction > 1e-8:
                        assignment_rows.append({
                            "case_id": case_id,
                            "route_id": str(case_sites.iloc[i]["route_id"]),
                            "site_id": site_id,
                            "demand_id": demand_id,
                            "distance_proxy_km": float(distance_lookup[(site_id, demand_id)]),
                            "assignment_fraction": fraction,
                            "assigned_energy_kwh_day": fraction * float(problem.demand_kwh_day[j]),
                        })
        except Exception as exc:
            selected_site_count = int(solution.opened.sum())
            selected_charger_count = int(solution.chargers.sum())
            summary_rows.append({
                "case_id": case_id,
                "demand_scenario": demand_scenario,
                "charger_cost_scenario": cost_scenario,
                "status": "FAILED",
                "error": f"{type(exc).__name__}: {exc}",
            })
            print(f"      WARNING {case_id}: {type(exc).__name__}: {exc}")

    print("[4/6] Estimating electricity-purchase OPEX bounds separately from CAPEX MILP...")
    tariff_rows: list[dict[str, Any]] = []
    for demand_scenario in ("low", "base", "high"):
        demand_df = pd.read_csv(TRAFFIC_SCENARIO_ROOT / demand_scenario / "demand_points.csv")
        energy_daily = float(pd.to_numeric(demand_df["demand_kwh_day"], errors="raise").sum())
        annual_energy = energy_daily * 365.0
        for tariff in ELECTRICITY_TARIFFS:
            tariff_rows.append({
                "demand_scenario": demand_scenario,
                "connection_class": tariff["connection_class"],
                "period_assumption": f"all_energy_{tariff['period']}_tariff",
                "annual_energy_kwh": annual_energy,
                "tariff_amd_per_kwh_including_vat": tariff["tariff_amd_per_kwh"],
                "annual_energy_purchase_cost_amd": annual_energy * tariff["tariff_amd_per_kwh"],
                "status": "SCOPED_ATC_DEMAND_ONLY_NOT_FULL_CORRIDOR; TARIFF_CLASS_AND_LOAD_PERIOD_UNVERIFIED",
            })

    capacity_rows: list[dict[str, Any]] = []
    spacing_path = DERIVED / "interstation_gap_sensitivity.csv"
    spacing_min: dict[str, int] = {}
    if spacing_path.exists():
        spacing = pd.read_csv(spacing_path)
        spacing = spacing[spacing["max_interstation_distance_km"].astype(float) == MAX_INTERSTATION_DISTANCE_KM]
        if not spacing.empty:
            spacing_min = {
                str(row.route_id): int(row.minimum_selected_sites_for_spacing_only)
                for row in spacing.itertuples(index=False)
                if pd.notna(row.minimum_selected_sites_for_spacing_only)
            }
    for demand_scenario in ("low", "base", "high"):
        demand_df = pd.read_csv(TRAFFIC_SCENARIO_ROOT / demand_scenario / "demand_points.csv")
        for demand in demand_df.itertuples(index=False):
            energy = float(demand.demand_kwh_day)
            route_id = str(demand.route_id)
            min_ports = int(math.ceil(energy / DAILY_THROUGHPUT_PER_CHARGER_KWH))
            capacity_sites = int(math.ceil(min_ports / MAX_CHARGERS_PER_SITE))
            spacing_sites = spacing_min.get(route_id)
            lower_bound_sites = max(capacity_sites, spacing_sites or 0)
            capacity_rows.append({
                "demand_scenario": demand_scenario,
                "route_id": route_id,
                "demand_id": str(demand.demand_id),
                "demand_kwh_day": energy,
                "assumed_kwh_day_per_charger": DAILY_THROUGHPUT_PER_CHARGER_KWH,
                "minimum_chargers_by_energy_only": min_ports,
                "maximum_chargers_per_site_assumption": MAX_CHARGERS_PER_SITE,
                "minimum_sites_by_capacity_only": capacity_sites,
                "spacing_only_minimum_sites_at_85km": spacing_sites,
                "simple_lower_bound_sites_max_of_capacity_and_spacing": lower_bound_sites,
                "status": "CAPACITY_AND_SPACING_LOWER_BOUND_ONLY; NOT_AN_OPTIMAL_LAYOUT; SERVICE_RADIUS_AND_GRID_ACCESS_NOT_VALIDATED",
            })

    print("[5/6] Writing summaries, selected stations, assignments, and assumptions...")
    summary = pd.DataFrame(summary_rows)
    selected = pd.DataFrame(selected_rows)
    assignments = pd.DataFrame(assignment_rows)
    tariffs = pd.DataFrame(tariff_rows)
    summary.to_csv(OUTPUT / "milp_scenario_summary.csv", index=False, encoding="utf-8-sig")
    selected.to_csv(OUTPUT / "milp_selected_sites.csv", index=False, encoding="utf-8-sig")
    assignments.to_csv(OUTPUT / "milp_demand_assignments.csv", index=False, encoding="utf-8-sig")
    tariffs.to_csv(OUTPUT / "electricity_opex_atc_scope.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(capex_sensitivity_rows).to_csv(
        OUTPUT / "capital_cost_sensitivity_fixed_layout.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(capacity_rows).to_csv(
        OUTPUT / "demand_capacity_screening.csv", index=False, encoding="utf-8-sig"
    )

    global_assumptions = {
        "route_lengths_km": route_lengths,
        "max_service_distance_km": MAX_SERVICE_DISTANCE_KM,
        "max_interstation_distance_km": MAX_INTERSTATION_DISTANCE_KM,
        "charger_peak_power_kw": CHARGER_POWER_KW,
        "daily_throughput_kwh_per_charger": DAILY_THROUGHPUT_PER_CHARGER_KWH,
        "max_chargers_per_site": MAX_CHARGERS_PER_SITE,
        "grid_capacity_kw_per_site": GRID_CAPACITY_PER_SITE_KW,
        "fixed_site_cost_usd": FIXED_SITE_COST_USD,
        "budget_usd": BUDGET_USD,
        "distance_weight": DISTANCE_WEIGHT,
        "grid_upgrade_cost_in_objective": False,
        "scope_warning": "Only two historic ATC locations are represented as demand points. These results cannot be interpreted as full M1/M2 demand or final Armenia network siting.",
        "cost_warning": "US 150-kW benchmarks are sensitivity inputs only, not Armenia vendor quotes. Grid upgrade, land, tax/import, maintenance and detailed civil costs are not fully represented.",
        "tariff_source": "ENA official tariff page https://www.ena.am/Info.aspx?id=11&lang=2 ; tariff values shown include VAT.",
        "nrel_source": "NREL/TP-5400-88513 (2024), https://www.nrel.gov/docs/fy24osti/88513.pdf",
        "usdot_source": "USDOT Climate Strategies that Work, cost considerations, https://www.transportation.gov/sites/dot.gov/files/2024-12/EV%20Charging%20Infrastructure%20-%20Climate%20Strategies%20that%20Work.pdf",
    }
    (OUTPUT / "global_assumptions.json").write_text(json.dumps(global_assumptions, indent=2) + "\n", encoding="utf-8")

    readme = [
        "ARMENIA M1/M2 — SCREENING MILP CASES",
        "======================================",
        "Three MILP runs: low/base/high demand at the base charger CAPEX. Then each fixed layout is revalued under low/base/high charger CAPEX without re-optimizing sites/chargers.",
        "All currency values in the MILP capital-cost inputs are USD benchmark values.",
        "",
        "IMPORTANT SCOPE:",
        "- Demand points are only the two historic ATC scopes documented in the traffic scenario folders.",
        "- No full-corridor demand interpolation is performed.",
        "- Distances are same-corridor chainage proxies, not verified road-network driving distances.",
        "- Candidate sites are OSM-derived centreline screening points, not buildable parcel approvals.",
        "",
        "COST / ENGINEERING ASSUMPTIONS:",
        f"- Fixed site allowance: USD {FIXED_SITE_COST_USD:,.0f} per open station (USDOT example for six 150-kW ports; US benchmark).",
        "- DC 150-kW port cost (hardware + installation): NREL 2024 low/base/high values as listed in global_assumptions.json.",
        f"- Six ports per site and {GRID_CAPACITY_PER_SITE_KW:.0f} kW site grid capacity are assumptions, not utility confirmations.",
        f"- {DAILY_THROUGHPUT_PER_CHARGER_KWH:.0f} kWh/day per port is a throughput assumption.",
        "- Grid-upgrade CAPEX is excluded because site-specific ENA connection quotes are unavailable.",
        "- Budget is a nonbinding USD 20m screening placeholder, not a confirmed project budget.",
        "- Distance coefficient is an analyst-set penalty and requires sensitivity calibration.",
        "- The separate electricity OPEX table uses ENA tariff bounds; energy OPEX is not included in the current MILP objective.",
        "- HiGHS is run with a requested 1% relative MIP gap and a 60-second case time limit. Each achieved gap is recorded; do not call a tolerance solution an exact optimum.",
        "- Fixed-site and per-port installation cost boundaries come from separate benchmarks; possible overlap must be reviewed.",
        "",
        "OUTPUTS:",
        "- milp_scenario_summary.csv: composite objective (model units), capital-cost proxy (USD), station/charger counts per run.",
        "- capital_cost_sensitivity_fixed_layout.csv: low/base/high port-cost revaluation of the base optimized layout (no re-optimization under alternative costs).",
        "- demand_capacity_screening.csv: low/base/high throughput and spacing lower bounds, not optimal layouts.",
        "- milp_selected_sites.csv: chosen screening sites, charger counts and power.",
        "- milp_demand_assignments.csv: assignments and screening distance proxies.",
        "- electricity_opex_atc_scope.csv: annual energy purchase cost bounds for the two ATC demand points only.",
        "- inputs/<case_id>/: full input data and explicit assumptions used by each solver run.",
        "",
        "Do not describe these as final Armenia investment results. They are transparent model demonstrations / sensitivity cases until local costs, grid capacity, parcel access and corridor-wide demand are validated.",
    ]
    (OUTPUT / "README.txt").write_text("\n".join(readme) + "\n", encoding="utf-8")

    print("[6/6] Complete")
    optimal = int((summary.get("status", pd.Series(dtype=str)) == "SOLVED_WITHIN_REQUESTED_MIP_GAP").sum())
    print(f"      Base-case MILP solved within requested MIP gap: {optimal}/{len(case_dirs)}")
    if not summary.empty and "status" in summary.columns:
        cols = [c for c in ["case_id", "status", "opened_station_count", "charger_count", "total_capital_cost_proxy_usd", "objective_value_model_units"] if c in summary.columns]
        print(summary[cols].to_string(index=False))
    print("\nSaved outputs to:")
    print(f"      {OUTPUT}")
    print("      Review README.txt and global_assumptions.json before using results in the thesis.")
    return 0 if optimal == len(case_dirs) else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        raise

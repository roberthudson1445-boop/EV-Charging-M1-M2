#!/usr/bin/env python3
"""Prepare and solve an explicitly provisional Armenia corridor MILP screen.

Run from the project root:
  .\\.venv\\Scripts\\python.exe scripts\\run_case_study_screening_milp.py

Solves one selected demand scenario (low, base, high, or Armstat) using the
base 150-kW DC charger CAPEX benchmark. Distances come from the validated
virtual-edge directed OSM matrix and are measured demand -> charging site.
Each run writes to a new directed-network output root, preserving earlier
chainage-proxy results. This remains a screening model, not a full-corridor
investment plan: only three demand scopes are represented and site/grid data
remain assumptions.
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
DIRECTED_DISTANCE_MATRIX = (
    DERIVED / "network_distance_validation" / "corridor_site_demand_distances_virtual_edge.csv"
)
# Keep new directed-network runs separate from the earlier chainage-proxy results.
OUTPUT_ROOT = DERIVED / "case_study_screening_milp_directed_network"
OUTPUT = OUTPUT_ROOT
INELIGIBLE_DISTANCE_KM = 99_999.0
DISTANCE_DIRECTION = "demand_to_site"
DISTANCE_METHOD = "DIRECTED_OSM_SHORTEST_PATH_WITH_VIRTUAL_EDGE_NODES"

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
MIP_REL_GAP = 0.001
TIME_LIMIT_SECONDS = 180.0
VALID_DEMAND_SCENARIOS = ("low", "base", "high", "armstat_ev_share_2_92")

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


def _parse_bool_series(values: pd.Series, column_name: str) -> pd.Series:
    """Parse CSV boolean values strictly; reject ambiguous spellings."""
    truth = {"true": True, "1": True, "yes": True, "false": False, "0": False, "no": False}
    parsed: list[bool] = []
    for value in values:
        if isinstance(value, (bool, np.bool_)):
            parsed.append(bool(value))
            continue
        key = str(value).strip().lower()
        if key not in truth:
            raise ValueError(f"Directed distance matrix column {column_name!r} has invalid boolean {value!r}.")
        parsed.append(truth[key])
    return pd.Series(parsed, index=values.index, dtype=bool)


def load_directed_distance_inputs(
    site_template: pd.DataFrame,
    demand_source: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Validate the directed OSM matrix and create complete MILP distance rows.

    Reachable same-corridor pairs retain their directed demand->site distance.
    Cross-corridor / no-path pairs are represented by a large finite sentinel,
    which keeps the complete matrix shape while making them ineligible under
    the model's 85-km service-distance constraint.
    """
    required = {
        "site_id", "demand_id", "site_route_id", "demand_route_id",
        "distance_direction", "distance_km", "eligible", "status",
    }
    matrix = read_csv(DIRECTED_DISTANCE_MATRIX, required).copy()

    for column in ("site_id", "demand_id", "site_route_id", "demand_route_id"):
        matrix[column] = matrix[column].astype(str).str.strip()
    matrix["distance_direction"] = matrix["distance_direction"].astype(str).str.strip().str.lower()
    matrix["distance_km"] = pd.to_numeric(matrix["distance_km"], errors="coerce")
    matrix["eligible"] = _parse_bool_series(matrix["eligible"], "eligible")

    directions = set(matrix["distance_direction"].dropna().unique())
    if directions != {DISTANCE_DIRECTION}:
        raise ValueError(
            "Directed matrix must contain only distance_direction='demand_to_site'; "
            f"found {sorted(directions)}."
        )
    if matrix[["site_id", "demand_id"]].duplicated().any():
        duplicates = matrix.loc[matrix[["site_id", "demand_id"]].duplicated(), ["site_id", "demand_id"]]
        raise ValueError(f"Directed distance matrix contains duplicate pairs: {duplicates.head().to_dict('records')}")

    expected_sites = set(site_template["site_id"].astype(str).str.strip())
    expected_demands = set(demand_source["demand_id"].astype(str).str.strip())
    actual_sites = set(matrix["site_id"])
    actual_demands = set(matrix["demand_id"])
    if actual_sites != expected_sites:
        raise ValueError(
            "Directed matrix site IDs do not match the current candidate-site template. "
            f"Missing={sorted(expected_sites - actual_sites)[:5]}, "
            f"extra={sorted(actual_sites - expected_sites)[:5]}"
        )
    if actual_demands != expected_demands:
        raise ValueError(
            "Directed matrix demand IDs do not match the selected demand scenario. "
            f"Missing={sorted(expected_demands - actual_demands)}, "
            f"extra={sorted(actual_demands - expected_demands)}"
        )

    expected_site_routes = (
        site_template.assign(site_id=site_template["site_id"].astype(str).str.strip())
        .set_index("site_id")["route_id"].astype(str).str.strip().to_dict()
    )
    expected_demand_routes = (
        demand_source.assign(demand_id=demand_source["demand_id"].astype(str).str.strip())
        .set_index("demand_id")["route_id"].astype(str).str.strip().to_dict()
    )
    mismatched_site_route = matrix.apply(
        lambda row: row["site_route_id"] != expected_site_routes[row["site_id"]], axis=1
    )
    mismatched_demand_route = matrix.apply(
        lambda row: row["demand_route_id"] != expected_demand_routes[row["demand_id"]], axis=1
    )
    if mismatched_site_route.any() or mismatched_demand_route.any():
        raise ValueError("Directed matrix route IDs do not match the current site/demand input files.")

    expected_pairs = len(expected_sites) * len(expected_demands)
    if len(matrix) != expected_pairs:
        raise ValueError(
            f"Directed matrix must contain all {expected_pairs} site-demand pairs; got {len(matrix)}."
        )
    expected_pair_set = {(site, demand) for site in expected_sites for demand in expected_demands}
    actual_pair_set = set(zip(matrix["site_id"], matrix["demand_id"]))
    if actual_pair_set != expected_pair_set:
        missing = list(expected_pair_set - actual_pair_set)[:5]
        extra = list(actual_pair_set - expected_pair_set)[:5]
        raise ValueError(f"Directed matrix pair coverage is incomplete. Missing={missing}; extra={extra}")

    eligible = matrix["eligible"]
    if matrix.loc[eligible, "distance_km"].isna().any():
        raise ValueError("Eligible directed distance rows contain missing/non-numeric distance_km values.")
    if not np.isfinite(matrix.loc[eligible, "distance_km"].to_numpy(dtype=float)).all():
        raise ValueError("Eligible directed distance rows contain non-finite distances.")
    if (matrix.loc[eligible, "distance_km"] < 0).any():
        raise ValueError("Eligible directed distance rows cannot be negative.")
    if (matrix.loc[eligible, "status"].astype(str) != "OK").any():
        raise ValueError("Rows marked eligible must have status='OK'.")
    if (matrix.loc[eligible, "site_route_id"] != matrix.loc[eligible, "demand_route_id"]).any():
        raise ValueError("Cross-corridor pairs cannot be marked eligible.")
    if (matrix.loc[~eligible, "site_route_id"] == matrix.loc[~eligible, "demand_route_id"]).any():
        same_route_ineligible = matrix.loc[
            (~eligible) & (matrix["site_route_id"] == matrix["demand_route_id"]),
            ["site_id", "demand_id", "status"],
        ]
        raise ValueError(
            "Same-corridor pairs are marked ineligible; inspect routing/no-path status before solving: "
            f"{same_route_ineligible.head().to_dict('records')}"
        )

    # Preserve all 174 pairs. The solver's service-distance constraints disallow
    # assignments above 85 km; the sentinel additionally excludes cross-route pairs.
    matrix["model_distance_km"] = np.where(
        eligible, matrix["distance_km"], INELIGIBLE_DISTANCE_KM
    )
    matrix["service_feasible"] = eligible & (matrix["distance_km"] <= MAX_SERVICE_DISTANCE_KM)

    service_counts = (
        matrix.loc[matrix["service_feasible"]]
        .groupby("demand_id").size()
        .reindex(list(expected_demands), fill_value=0)
    )
    if (service_counts == 0).any():
        missing_service = service_counts[service_counts == 0].index.tolist()
        raise ValueError(
            "At least one demand point has no reachable station within the service limit "
            f"of {MAX_SERVICE_DISTANCE_KM:.1f} km: {missing_service}. MILP would be infeasible."
        )

    # Keep input row order aligned with the candidate template and demand file.
    site_order = site_template["site_id"].astype(str).str.strip().tolist()
    demand_order = demand_source["demand_id"].astype(str).str.strip().tolist()
    order = pd.MultiIndex.from_product(
        [site_order, demand_order], names=["site_id", "demand_id"]
    )
    matrix = matrix.set_index(["site_id", "demand_id"]).reindex(order).reset_index()
    if matrix["model_distance_km"].isna().any():
        raise ValueError("Internal error: directed distance matrix could not be aligned to model order.")

    distances_for_model = matrix[["site_id", "demand_id", "model_distance_km"]].rename(
        columns={"model_distance_km": "distance_km"}
    )
    counts_by_demand = {
        str(demand): int(count)
        for demand, count in service_counts.items()
    }
    metrics: dict[str, Any] = {
        "source_file": str(DIRECTED_DISTANCE_MATRIX.relative_to(ROOT)),
        "distance_direction": DISTANCE_DIRECTION,
        "distance_method": DISTANCE_METHOD,
        "matrix_pairs": int(len(matrix)),
        "eligible_reachable_pairs": int(eligible.sum()),
        "ineligible_pairs": int((~eligible).sum()),
        "service_feasible_pairs_within_85km": int(matrix["service_feasible"].sum()),
        "eligible_pairs_over_85km": int((eligible & (matrix["distance_km"] > MAX_SERVICE_DISTANCE_KM)).sum()),
        "service_feasible_pairs_by_demand": counts_by_demand,
        "ineligible_sentinel_km": INELIGIBLE_DISTANCE_KM,
        "maximum_service_distance_km": MAX_SERVICE_DISTANCE_KM,
        "access_connector_limitation": (
            "Virtual edge nodes are inserted on the nearest OSM road edge; the method does not verify a legal/private driveway or parcel access."
        ),
    }
    return distances_for_model, matrix, metrics


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
    demand_source["demand_id"] = demand_source["demand_id"].astype(str).str.strip()
    demand_source["route_id"] = demand_source["route_id"].astype(str).str.strip()
    demand_source["demand_kwh_day"] = pd.to_numeric(demand_source["demand_kwh_day"], errors="coerce")
    if demand_source["demand_kwh_day"].isna().any() or (demand_source["demand_kwh_day"] <= 0).any():
        raise ValueError(f"{demand_scenario}: demand_kwh_day must be positive and numeric")

    distances_source, distance_audit, distance_metrics = load_directed_distance_inputs(
        site_template, demand_source
    )

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
    demand_source.to_csv(case_dir / "demand_points.csv", index=False, encoding="utf-8-sig")
    distances_source.to_csv(case_dir / "distances.csv", index=False, encoding="utf-8-sig")
    distance_audit.to_csv(case_dir / "directed_distance_matrix_audit.csv", index=False, encoding="utf-8-sig")
    (case_dir / "directed_distance_metadata.json").write_text(
        json.dumps(distance_metrics, indent=2) + "\n", encoding="utf-8"
    )

    config = {
        "charger_daily_capacity_kwh": DAILY_THROUGHPUT_PER_CHARGER_KWH,
        "max_service_distance_km": MAX_SERVICE_DISTANCE_KM,
        "charger_peak_power_kw": CHARGER_POWER_KW,
        "budget": BUDGET_USD,
        "distance_weight": DISTANCE_WEIGHT,
        "max_interstation_distance_km": MAX_INTERSTATION_DISTANCE_KM,
        "route_lengths_km": route_lengths,
        "distance_direction": DISTANCE_DIRECTION,
        "distance_method": DISTANCE_METHOD,
        "distance_source_file": distance_metrics["source_file"],
        "ineligible_distance_sentinel_km": INELIGIBLE_DISTANCE_KM,
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
        "demand_scope": "Three screened demand scopes: one M1 historical ATC section, one M2 historical ATC section, and one ADB forecast-based M2 km13.1-28.9 subsection; remaining corridor demand is unobserved.",
        "distance_scope": "One-way shortest-path driving distance from each demand point to a candidate charging site on the directed OSM graph, with virtual points inserted on nearest road-edge geometries.",
        "distance_direction": DISTANCE_DIRECTION,
        "distance_source_file": distance_metrics["source_file"],
        "distance_matrix_pairs": distance_metrics["matrix_pairs"],
        "distance_reachable_pairs": distance_metrics["eligible_reachable_pairs"],
        "distance_service_feasible_pairs": distance_metrics["service_feasible_pairs_within_85km"],
        "distance_service_feasible_pairs_by_demand": distance_metrics["service_feasible_pairs_by_demand"],
        "distance_method": DISTANCE_METHOD,
        "ineligible_distance_sentinel_km": INELIGIBLE_DISTANCE_KM,
        "distance_access_warning": distance_metrics["access_connector_limitation"],
        "distance_network_warning": "OSM may omit restrictions, access rules, temporary closures, or recently changed roads; nearest-edge proximity does not prove legal driveway/site access.",
        "fixed_and_port_cost_boundary_warning": "Fixed site allowance and per-port installation benchmark are sourced from different US cost summaries; potential overlap in generic site-work items cannot be ruled out. Treat as sensitivity inputs, not local bids.",
        "maintenance_status": "Excluded from current MILP objective; USDOT source gives a separate 5-year maintenance estimate of $75,000 for an example six-port station.",
        "utility_upgrades": "Excluded: NREL notes transformer/line-extension costs vary by utility and site and are not included in the cited per-port EVSE cost ranges.",
    }
    (case_dir / "assumptions.json").write_text(json.dumps(assumptions, indent=2) + "\n", encoding="utf-8")
    return case_dir


def main() -> int:
    global OUTPUT
    selected_scenario = sys.argv[1].lower().strip() if len(sys.argv) > 1 else "base"
    if selected_scenario not in VALID_DEMAND_SCENARIOS:
        raise SystemExit(
            "Usage: python scripts\run_case_study_scenario.py "
            "[low|base|high|armstat_ev_share_2_92]"
        )
    # New output namespace: do not overwrite the earlier chainage-proxy results.
    OUTPUT = OUTPUT_ROOT / "scenario_runs" / selected_scenario

    print(f"[1/6] Checking generated {selected_scenario!r} demand scenario and route metadata...")
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

    for scenario in VALID_DEMAND_SCENARIOS:
        if not (TRAFFIC_SCENARIO_ROOT / scenario / "demand_points.csv").exists():
            raise FileNotFoundError(
                f"Missing traffic-demand scenario '{scenario}'. Check the generated scenario folder."
            )
    if not DIRECTED_DISTANCE_MATRIX.exists():
        raise FileNotFoundError(
            "Validated directed distance matrix not found: "
            f"{DIRECTED_DISTANCE_MATRIX}. Run build_directed_virtual_edge_distance_matrix.py first."
        )
    print(f"      Sites={len(sites)} | routes={','.join(sorted(route_lengths))}")
    print(f"      Directed distance source: {DIRECTED_DISTANCE_MATRIX.relative_to(ROOT)}")

    print(f"[2/6] Preparing the {selected_scenario} demand MILP input directory...")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    case_pairs = [(selected_scenario, "base")]
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
            print(
                f"      Solving {case_id} (requested MIP gap {MIP_REL_GAP:.1%}, "
                f"time limit {TIME_LIMIT_SECONDS:.0f} s)...",
                flush=True,
            )
            problem = load_problem_from_csv(case_dir)
            solution = solve_milp(
                problem,
                mip_rel_gap=MIP_REL_GAP,
                time_limit_seconds=TIME_LIMIT_SECONDS,
            )
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
                "requested_mip_rel_gap": MIP_REL_GAP,
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
                "directed_distance_direction": DISTANCE_DIRECTION,
                "eligible_pairs_within_service_distance": int(
                    pd.read_csv(case_dir / "directed_distance_matrix_audit.csv")["service_feasible"].sum()
                ),
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
                            # Keep the legacy column name for downstream compatibility;
                            # the value is now a directed OSM driving distance, not a proxy.
                            "distance_proxy_km": float(distance_lookup[(site_id, demand_id)]),
                            "directed_driving_distance_km": float(distance_lookup[(site_id, demand_id)]),
                            "distance_direction": DISTANCE_DIRECTION,
                            "assignment_fraction": fraction,
                            "assigned_energy_kwh_day": fraction * float(problem.demand_kwh_day[j]),
                        })
        except Exception as exc:
            summary_rows.append({
                "case_id": case_id,
                "demand_scenario": demand_scenario,
                "charger_cost_scenario": cost_scenario,
                "status": "FAILED_OR_NO_ACCEPTED_SOLUTION",
                "error": f"{type(exc).__name__}: {exc}",
            })
            print(f"      WARNING {case_id}: {type(exc).__name__}: {exc}")

    print("[4/6] Estimating electricity-purchase OPEX bounds separately from CAPEX MILP...")
    tariff_rows: list[dict[str, Any]] = []
    for demand_scenario in VALID_DEMAND_SCENARIOS:
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
                "status": "REPRESENTED_DEMAND_SCOPES_NOT_FULL_CORRIDOR; TARIFF_CLASS_AND_LOAD_PERIOD_UNVERIFIED",
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
    for demand_scenario in VALID_DEMAND_SCENARIOS:
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
        "distance_direction": DISTANCE_DIRECTION,
        "distance_method": DISTANCE_METHOD,
        "directed_distance_matrix_source": str(DIRECTED_DISTANCE_MATRIX.relative_to(ROOT)),
        "ineligible_distance_sentinel_km": INELIGIBLE_DISTANCE_KM,
        "distance_weight_units_warning": "The composite objective adds USD cost terms and a distance penalty with analyst-set coefficient; until dimensionally calibrated, objective_value_model_units is not USD.",
        "demand_scenario_solved": selected_scenario,
        "charger_cost_scenario_solved": "base",
        "requested_mip_rel_gap": MIP_REL_GAP,
        "time_limit_seconds": TIME_LIMIT_SECONDS,
        "grid_upgrade_cost_in_objective": False,
        "scope_warning": "Three represented subsections only: M1 Section 3 ATC, M2 km9.3-13.1 ATC, and ADB forecast-based M2 km13.1-28.9. Remaining M1/M2 corridor demand is unobserved; results are not final Armenia network siting.",
        "distance_warning": "Distance is directed demand-to-site OSM shortest-path distance with virtual edge nodes. Cross-corridor/no-path pairs receive a finite 99,999-km sentinel; the 85-km service constraint prevents assignment. Road-edge proximity does not verify legal driveway access.",
        "cost_warning": "US 150-kW benchmarks are sensitivity inputs only, not Armenia vendor quotes. Grid upgrade, land, tax/import, maintenance and detailed civil costs are not fully represented.",
        "tariff_source": "ENA official tariff page https://www.ena.am/Info.aspx?id=11&lang=2 ; tariff values shown include VAT.",
        "nrel_source": "NREL/TP-5400-88513 (2024), https://www.nrel.gov/docs/fy24osti/88513.pdf",
        "usdot_source": "USDOT Climate Strategies that Work, cost considerations, https://www.transportation.gov/sites/dot.gov/files/2024-12/EV%20Charging%20Infrastructure%20-%20Climate%20Strategies%20that%20Work.pdf",
    }
    (OUTPUT / "global_assumptions.json").write_text(json.dumps(global_assumptions, indent=2) + "\n", encoding="utf-8")

    readme = [
        f"ARMENIA M1/M2 — SCREENING MILP CASE ({selected_scenario.upper()} DEMAND)",
        "======================================",
        f"This folder contains one MILP run for the {selected_scenario} demand scenario at base charger CAPEX. Run separately with low, base, high, and armstat_ev_share_2_92. Each run writes to a separate directed-network scenario folder.",
        "All currency values in the MILP capital-cost inputs are USD benchmark values.",
        "",
        "IMPORTANT SCOPE:",
        "- Demand scopes: M1 Section 3 historical ATC; M2 km9.3-13.1 historical ATC; and M2 km13.1-28.9 ADB forecast-based subsection reference at km16.",
        "- No full-corridor demand interpolation is performed.",
        "- Distances are directed OSM shortest-path driving distances from demand points to charging sites, using virtual points inserted on nearest road-edge geometries.",
        "- Cross-corridor / no-directed-path pairs are retained in the complete matrix with a 99,999-km sentinel; the 85-km service-distance constraint excludes them from assignments.",
        "- The nearest road-edge connection is a geometric modelling assumption, not proof of legal/private driveway or parcel access.",
        "- Interstation spacing remains measured using corridor chainage; it is separate from the directed demand-to-site service distance.",
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
        "- The separate electricity OPEX table uses ENA tariff bounds for the three represented demand scopes (including the Armstat-scaled sensitivity); energy OPEX is not included in the current MILP objective.",
        f"- HiGHS is run with a requested {MIP_REL_GAP:.1%} relative MIP gap and a {TIME_LIMIT_SECONDS:.0f}-second case time limit. The achieved gap is recorded; do not call a tolerance solution an exact optimum.",
        "- The composite objective combines USD cost terms with an analyst-set distance penalty. Until the distance coefficient is dimensionally calibrated, objective_value_model_units is not USD; use the separately reported capital-cost proxy for CAPEX comparisons.",
        "- Fixed-site and per-port installation cost boundaries come from separate benchmarks; possible overlap must be reviewed.",
        "",
        "OUTPUTS:",
        "- milp_scenario_summary.csv: this scenario's solver status, achieved gap, composite objective (model units), CAPEX proxy (USD), station and charger counts.",
        "- capital_cost_sensitivity_fixed_layout.csv: low/base/high port-cost revaluation of this demand-optimized layout (no re-optimization under alternative costs).",
        "- demand_capacity_screening.csv: low/base/high throughput and spacing lower bounds, not optimal layouts.",
        "- milp_selected_sites.csv: chosen screening sites, charger counts and power.",
        "- milp_demand_assignments.csv: assignments and directed OSM driving distances for the three represented demand scopes (legacy distance_proxy_km column retained for compatibility).",
        "- inputs/<case_id>/directed_distance_matrix_audit.csv: full 174-pair directed matrix and eligibility/status provenance used by this run.",
        "- electricity_opex_atc_scope.csv: annual energy purchase cost bounds for the represented demand scopes and selected scenario set.",
        "- inputs/<case_id>/: full input data and explicit assumptions used by each solver run.",
        "",
        "Do not describe these as final Armenia investment results. They are transparent model demonstrations / sensitivity cases until local costs, grid capacity, parcel access and corridor-wide demand are validated.",
    ]
    (OUTPUT / "README.txt").write_text("\n".join(readme) + "\n", encoding="utf-8")

    print("[6/6] Complete")
    optimal = int((summary.get("status", pd.Series(dtype=str)) == "SOLVED_WITHIN_REQUESTED_MIP_GAP").sum())
    print(f"      {selected_scenario} demand MILP solved within requested MIP gap: {optimal}/{len(case_dirs)}")
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

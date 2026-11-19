from __future__ import annotations

"""Validate low/base/high and Armstat M1/M2 screening MILP outputs.

Run from project root:
    .venv\\Scripts\\python.exe scripts\\validate_all_case_study_scenarios.py

This checks numerical/model consistency only. It does not establish real-world
traffic demand, parcel suitability, road access, utility capacity, or local CAPEX.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

SCENARIOS = ("low", "base", "high", "armstat_ev_share_2_92")
TOL = 1e-5


def find_input_dir(run_dir: Path) -> Path:
    candidates = sorted(p.parent for p in run_dir.rglob("config.json"))
    for folder in candidates:
        if all((folder / f).exists() for f in ("sites.csv", "demand_points.csv", "distances.csv")):
            return folder
    raise FileNotFoundError(f"Could not find complete MILP inputs beneath {run_dir}")


def near(a: float, b: float, tol: float = TOL) -> bool:
    return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(a)), abs(float(b)))


def validate_one(
    name: str,
    run_dir: Path,
    candidate_sites: pd.DataFrame,
    route_lengths: dict[str, float],
) -> tuple[dict, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    summary_path = run_dir / "milp_scenario_summary.csv"
    selected_path = run_dir / "milp_selected_sites.csv"
    assignments_path = run_dir / "milp_demand_assignments.csv"
    assumptions_path = run_dir / "global_assumptions.json"
    for p in (summary_path, selected_path, assignments_path, assumptions_path):
        if not p.exists():
            raise FileNotFoundError(f"{name}: missing required file {p}")

    summary_df = pd.read_csv(summary_path)
    selected = pd.read_csv(selected_path)
    assignments = pd.read_csv(assignments_path)
    assumptions = json.loads(assumptions_path.read_text(encoding="utf-8"))
    input_dir = find_input_dir(run_dir)
    demands = pd.read_csv(input_dir / "demand_points.csv")
    distances = pd.read_csv(input_dir / "distances.csv")

    if len(summary_df) != 1:
        errors.append(f"Expected one summary row; found {len(summary_df)}")
        summary = summary_df.iloc[0].to_dict() if len(summary_df) else {}
    else:
        summary = summary_df.iloc[0].to_dict()

    if selected.empty:
        errors.append("No selected sites in output")
    if selected["site_id"].duplicated().any():
        errors.append("Duplicate site_id in selected-site output")

    max_gap = float(assumptions["max_interstation_distance_km"])
    max_service = float(assumptions["max_service_distance_km"])
    charger_kw = float(assumptions["charger_peak_power_kw"])
    daily_per_charger = float(assumptions["daily_throughput_kwh_per_charger"])
    max_chargers = int(assumptions["max_chargers_per_site"])
    grid_capacity = float(assumptions["grid_capacity_kw_per_site"])
    requested_gap = float(summary.get("requested_mip_rel_gap", np.nan))
    achieved_gap = float(summary.get("achieved_mip_rel_gap", np.nan))

    # Candidate-site identity and corridor membership.
    candidate_lookup = candidate_sites.set_index("site_id")
    for row in selected.itertuples(index=False):
        if row.site_id not in candidate_lookup.index:
            errors.append(f"Selected site {row.site_id} is not in candidate-site source")
            continue
        c = candidate_lookup.loc[row.site_id]
        if str(c["route_id"]) != str(row.route_id):
            errors.append(f"{row.site_id}: selected route_id does not match candidate source")
        if not near(row.chainage_km, c["chainage_km"], 1e-7):
            errors.append(f"{row.site_id}: selected chainage does not match candidate source")

    # Check selected-site spacing, including route endpoints.
    spacing_rows = []
    for route, route_len in route_lengths.items():
        route_selected = selected.loc[selected["route_id"] == route].sort_values("chainage_km")
        if route_selected.empty:
            errors.append(f"{route}: no selected stations")
            continue
        chainages = route_selected["chainage_km"].astype(float).to_numpy()
        gaps = np.diff(np.r_[0.0, chainages, float(route_len)])
        route_max = float(np.max(gaps))
        spacing_rows.append((route, route_max))
        if np.any(gaps < -TOL):
            errors.append(f"{route}: negative chainage gap detected")
        if route_max > max_gap + TOL:
            errors.append(f"{route}: maximum route gap {route_max:.3f} km exceeds {max_gap:.3f} km")

    # Station/charger/power consistency.
    if (selected["chargers"] < 1).any() or (selected["chargers"] > max_chargers).any():
        errors.append(f"Charger count outside [1, {max_chargers}] at one or more stations")
    if not np.allclose(selected["reserved_power_kw"], selected["chargers"] * charger_kw, atol=TOL):
        errors.append("Reserved power does not equal charger_count * charger_peak_power_kw")
    if (selected["reserved_power_kw"] > grid_capacity + TOL).any():
        errors.append("One or more stations exceed assumed grid capacity")

    # Every demand point must be fully assigned, and assignments must be eligible.
    demand_ids = set(demands["demand_id"].astype(str))
    assignment_ids = set(assignments["demand_id"].astype(str))
    missing_demand_assignments = demand_ids - assignment_ids
    if missing_demand_assignments:
        errors.append(f"Demand points without any assignment: {sorted(missing_demand_assignments)}")
    assigned_fraction = assignments.groupby("demand_id")["assignment_fraction"].sum()
    for demand_id in demand_ids:
        frac = float(assigned_fraction.get(demand_id, 0.0))
        if not near(frac, 1.0, 1e-6):
            errors.append(f"{demand_id}: assignment fractions sum to {frac:.8f}, not 1")

    selected_map = selected.set_index("site_id")
    demand_map = demands.set_index("demand_id")["demand_kwh_day"].astype(float).to_dict()
    dist_lookup = distances.set_index(["site_id", "demand_id"])["distance_km"].to_dict()
    recomputed_site_load = {str(site_id): 0.0 for site_id in selected["site_id"]}
    for row in assignments.itertuples(index=False):
        if row.site_id not in selected_map.index:
            errors.append(f"Assignment references unopened/unknown site {row.site_id}")
            continue
        if row.demand_id not in demand_map:
            errors.append(f"Assignment references unknown demand point {row.demand_id}")
            continue
        expected_distance = dist_lookup.get((row.site_id, row.demand_id))
        if expected_distance is None:
            errors.append(f"Missing distance pair for {row.site_id}/{row.demand_id}")
        else:
            if not near(row.distance_proxy_km, expected_distance, 1e-6):
                errors.append(f"{row.site_id}/{row.demand_id}: assignment distance does not match input matrix")
            if float(row.distance_proxy_km) > max_service + TOL:
                errors.append(f"{row.site_id}/{row.demand_id}: assigned beyond service limit")
        croute = str(candidate_lookup.loc[row.site_id]["route_id"])
        droute = str(demands.set_index("demand_id").loc[row.demand_id]["route_id"])
        if croute != droute:
            errors.append(f"Cross-corridor assignment {row.site_id} ({croute}) -> {row.demand_id} ({droute})")
        fraction = float(row.assignment_fraction)
        if fraction < -TOL or fraction > 1.0 + TOL:
            errors.append(f"Invalid assignment fraction for {row.site_id}/{row.demand_id}: {fraction}")
        recomputed_site_load[row.site_id] += float(row.assigned_energy_kwh_day)

    for row in selected.itertuples(index=False):
        expected_load = recomputed_site_load.get(row.site_id, 0.0)
        if not near(row.assigned_demand_kwh_day, expected_load, 1e-6):
            errors.append(f"{row.site_id}: selected-site assigned energy does not match assignment rows")
        capacity = int(row.chargers) * daily_per_charger
        if expected_load > capacity + TOL:
            errors.append(f"{row.site_id}: assigned energy {expected_load:.3f} exceeds throughput {capacity:.3f}")

    # Capital cost consistency using the reported site-level unit costs.
    capex = float((selected["site_fixed_cost_usd"] + selected["chargers"] * selected["charger_cost_usd_per_port"]).sum())
    reported_capex = float(summary.get("total_capital_cost_proxy_usd", np.nan))
    if not near(capex, reported_capex, 1e-7):
        errors.append(f"CAPEX recomputation ${capex:,.2f} != summary ${reported_capex:,.2f}")

    # Aggregate checks.
    station_count = len(selected)
    charger_count = int(selected["chargers"].sum())
    if station_count != int(summary.get("opened_station_count", -1)):
        errors.append("Selected-site row count does not match summary station count")
    if charger_count != int(summary.get("charger_count", -1)):
        errors.append("Selected-site charger total does not match summary")
    if not np.isfinite(achieved_gap) or achieved_gap > requested_gap + 1e-12:
        errors.append(f"Achieved MIP gap {achieved_gap} exceeds requested gap {requested_gap}")

    zero_demand = int((selected["assigned_demand_kwh_day"] <= TOL).sum())
    if zero_demand:
        warnings.append(f"{zero_demand} selected station(s) receive zero demand in current represented demand set; spacing-only role is possible")
    warnings.append("Demand points are only the represented historic/ADB subsection scopes; not full-corridor demand")
    warnings.append("Distances are same-corridor chainage proxies, not verified directed driving distances")
    warnings.append("Candidate points, land/buildability, road access, grid connection and local CAPEX remain unverified")

    return ({
        "scenario": name,
        "status": "PASS" if not errors else "FAIL",
        "station_count": station_count,
        "charger_count": charger_count,
        "installed_peak_power_kw": float(selected["reserved_power_kw"].sum()),
        "total_demand_kwh_day": float(demands["demand_kwh_day"].sum()),
        "capex_proxy_usd": capex,
        "achieved_mip_gap": achieved_gap,
        "max_route_gap_km": max((g for _, g in spacing_rows), default=np.nan),
        "zero_demand_stations": zero_demand,
        "demand_point_count": len(demands),
    }, errors, warnings)


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    derived = project / "data" / "derived"
    runs_root = derived / "case_study_screening_milp" / "scenario_runs"
    candidate_path = derived / "corridor_candidate_sites.csv"
    lengths_path = derived / "milp_corridor_route_lengths.json"
    if not candidate_path.exists() or not lengths_path.exists():
        raise FileNotFoundError("Missing corridor_candidate_sites.csv or milp_corridor_route_lengths.json")

    candidates = pd.read_csv(candidate_path)
    raw_lengths = json.loads(lengths_path.read_text(encoding="utf-8"))
    lengths = raw_lengths.get("route_lengths_km", raw_lengths) if isinstance(raw_lengths, dict) else raw_lengths
    lengths = {str(k): float(v) for k, v in lengths.items() if k in {"M1", "M2"}}
    if set(lengths) != {"M1", "M2"}:
        raise ValueError(f"Could not read M1/M2 route lengths from {lengths_path}: {raw_lengths}")
    report_rows: list[dict] = []
    all_errors: list[str] = []
    all_warnings: list[tuple[str, str]] = []

    print("M1/M2 SCREENING MILP — FOUR-SCENARIO POST-SOLVE VALIDATION")
    print("Structural/numerical audit only; not real-world feasibility certification.\n")
    for scenario in SCENARIOS:
        run_dir = runs_root / scenario
        if not run_dir.exists():
            all_errors.append(f"{scenario}: result directory missing ({run_dir})")
            continue
        result, errors, warnings = validate_one(scenario, run_dir, candidates, lengths)
        report_rows.append(result)
        print(
            f"{scenario.upper()}: {result['status']} | stations={result['station_count']} "
            f"| chargers={result['charger_count']} | CAPEX=${result['capex_proxy_usd']:,.0f} "
            f"| max route gap={result['max_route_gap_km']:.2f} km "
            f"| MIP gap={result['achieved_mip_gap']:.4%} "
            f"| demand points={result['demand_point_count']}"
        )
        for err in errors:
            all_errors.append(f"{scenario}: {err}")
            print(f"  ERROR: {err}")
        for warning in warnings:
            all_warnings.append((scenario, warning))
            print(f"  WARNING: {warning}")
        print()

    report_path = derived / "case_study_screening_milp" / "four_scenario_validation_report.csv"
    pd.DataFrame(report_rows).to_csv(report_path, index=False)
    text_path = derived / "case_study_screening_milp" / "four_scenario_validation_report.txt"
    lines = [
        "M1/M2 SCREENING MILP — FOUR-SCENARIO VALIDATION",
        "Structural/numerical checks only; not real-world feasibility certification.",
        "",
    ]
    for row in report_rows:
        lines.append(
            f"{row['scenario']}: {row['status']}; stations={row['station_count']}; "
            f"chargers={row['charger_count']}; CAPEX_proxy_USD={row['capex_proxy_usd']:.2f}; "
            f"achieved_MIP_gap={row['achieved_mip_gap']:.8f}; "
            f"max_route_gap_km={row['max_route_gap_km']:.4f}; "
            f"demand_points={row['demand_point_count']}"
        )
    lines.extend(["", "ERRORS:"] + (all_errors or ["None"]))
    lines.extend(["", "WARNINGS:"] + [f"{s}: {w}" for s, w in all_warnings])
    text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Saved report: {report_path}")
    print(f"Saved report: {text_path}")
    if all_errors:
        print("\nONE OR MORE SCENARIOS FAILED THE STRUCTURAL/NUMERICAL AUDIT.")
        return 1
    if len(report_rows) != len(SCENARIOS):
        print("\nAUDIT INCOMPLETE: one or more scenario folders were missing.")
        return 1
    print("\nALL FOUR AVAILABLE SCENARIOS PASSED THE STRUCTURAL / NUMERICAL AUDIT.")
    print("This does not validate full-corridor demand, parcel access, land, grid connection, road access or local costs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

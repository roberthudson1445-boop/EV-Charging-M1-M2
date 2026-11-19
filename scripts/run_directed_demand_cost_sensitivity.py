#!/usr/bin/env python3
"""Run directed-network demand x charger-CAPEX sensitivity (12 combinations).

The four demand scenarios at BASE charger cost already exist in
case_study_screening_milp_directed_network/scenario_runs/<scenario>.
This script reuses those base-cost outputs read-only and performs the 8
additional optimizations at LOW and HIGH charger-port CAPEX. It then combines
all 12 demand/cost combinations into comparison tables.

Run from project root:
  .\\.venv\\Scripts\\python.exe scripts\\run_directed_demand_cost_sensitivity.py

Outputs are written to data/derived/directed_demand_cost_sensitivity/.
No existing scenario outputs are overwritten.
"""
from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DERIVED = ROOT / "data" / "derived"
RUNNER_PATH = ROOT / "scripts" / "run_case_study_scenario.py"
BASE_RESULTS_ROOT = DERIVED / "case_study_screening_milp_directed_network" / "scenario_runs"
OUTPUT_ROOT = DERIVED / "directed_demand_cost_sensitivity"

DEMAND_SCENARIOS = ("low", "base", "high", "armstat_ev_share_2_92")
COST_SCENARIOS = ("low", "base", "high")
NON_BASE_COSTS = ("low", "high")
MIP_REL_GAP = 0.001
TIME_LIMIT_SECONDS = 180.0


def load_runner_module():
    if not RUNNER_PATH.exists():
        raise FileNotFoundError(
            f"Directed case-study runner not found: {RUNNER_PATH}. "
            "Make sure the updated run_case_study_scenario.py is in scripts/."
        )
    spec = importlib.util.spec_from_file_location("directed_case_study_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load directed runner from {RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_one_row(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Required baseline output not found: {path}")
    frame = pd.read_csv(path)
    if len(frame) != 1:
        raise ValueError(f"Expected exactly one result row in {path}, found {len(frame)}")
    return frame.iloc[0].to_dict()


def validate_run(
    scenario: str,
    cost_scenario: str,
    solution: Any,
    problem: Any,
    assignments: pd.DataFrame,
    expected_gap: float,
) -> None:
    if solution.mip_gap is None or not np.isfinite(float(solution.mip_gap)):
        raise ValueError(f"{scenario}/{cost_scenario}: solver did not report a finite MIP gap")
    if float(solution.mip_gap) > expected_gap + 1e-12:
        raise ValueError(
            f"{scenario}/{cost_scenario}: achieved MIP gap {solution.mip_gap:.6%} "
            f"exceeds requested {expected_gap:.6%}"
        )
    if not np.allclose(np.asarray(solution.assignment).sum(axis=0), 1.0, atol=1e-7):
        raise ValueError(f"{scenario}/{cost_scenario}: demand assignment fractions do not sum to 1")
    if not assignments.empty:
        if (assignments["directed_driving_distance_km"] > float(problem.max_service_distance_km) + 1e-8).any():
            raise ValueError(f"{scenario}/{cost_scenario}: an assigned pair exceeds service distance")
        selected = set(problem.site_names[i] for i in np.flatnonzero(solution.opened))
        if not set(assignments["site_id"]).issubset(selected):
            raise ValueError(f"{scenario}/{cost_scenario}: assignment uses a site not selected")
        sums = assignments.groupby("demand_id")["assignment_fraction"].sum()
        if len(sums) != len(problem.demand_names) or not np.allclose(sums.to_numpy(), 1.0, atol=1e-7):
            raise ValueError(f"{scenario}/{cost_scenario}: written assignment totals do not cover every demand point")
        delivered = assignments.groupby("demand_id")["assigned_energy_kwh_day"].sum()
        demand_lookup = dict(zip(problem.demand_names, problem.demand_kwh_day))
        for demand_id, energy in demand_lookup.items():
            if not math.isclose(float(delivered.get(demand_id, 0.0)), float(energy), rel_tol=1e-7, abs_tol=1e-5):
                raise ValueError(f"{scenario}/{cost_scenario}: assigned energy does not match {demand_id}")


def copy_base_cost_results(scenario: str) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    run_dir = BASE_RESULTS_ROOT / scenario
    summary = read_one_row(run_dir / "milp_scenario_summary.csv")
    selected_path = run_dir / "milp_selected_sites.csv"
    assignment_path = run_dir / "milp_demand_assignments.csv"
    if not selected_path.exists() or not assignment_path.exists():
        raise FileNotFoundError(f"Baseline site/assignment outputs are incomplete for {scenario}: {run_dir}")
    selected = pd.read_csv(selected_path)
    assignments = pd.read_csv(assignment_path)
    summary["demand_scenario"] = scenario
    summary["charger_cost_scenario"] = "base"
    summary["source_run"] = "EXISTING_DIRECTED_BASE_COST_RUN_READ_ONLY"
    selected["demand_scenario"] = scenario
    selected["charger_cost_scenario"] = "base"
    assignments["demand_scenario"] = scenario
    assignments["charger_cost_scenario"] = "base"
    # Normalize the distance column name for all combined rows.
    if "directed_driving_distance_km" not in assignments.columns:
        if "distance_proxy_km" not in assignments.columns:
            raise ValueError(f"Base assignment file lacks a distance column: {assignment_path}")
        assignments["directed_driving_distance_km"] = assignments["distance_proxy_km"]
    return summary, selected, assignments


def solve_additional_case(
    runner: Any,
    scenario: str,
    cost_scenario: str,
    site_template: pd.DataFrame,
    route_lengths: dict[str, float],
    load_problem_from_csv: Any,
    solve_milp: Any,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    case_dir = runner.build_case_inputs(scenario, cost_scenario, site_template, route_lengths)
    problem = load_problem_from_csv(case_dir)
    solution = solve_milp(
        problem,
        mip_rel_gap=MIP_REL_GAP,
        time_limit_seconds=TIME_LIMIT_SECONDS,
    )
    served_by_site = solution.assignment @ problem.demand_kwh_day
    opened_idx = np.flatnonzero(solution.opened)
    selected_names = {problem.site_names[i] for i in opened_idx}

    sites = pd.read_csv(case_dir / "sites.csv", encoding="utf-8-sig")
    demand_frame = pd.read_csv(case_dir / "demand_points.csv", encoding="utf-8-sig")
    distance_frame = pd.read_csv(case_dir / "distances.csv", encoding="utf-8-sig")
    distance_lookup = distance_frame.set_index(["site_id", "demand_id"])["distance_km"].to_dict()

    selected_rows: list[dict[str, Any]] = []
    for i in opened_idx:
        selected_rows.append({
            "case_id": case_dir.name,
            "demand_scenario": scenario,
            "charger_cost_scenario": cost_scenario,
            "route_id": str(sites.iloc[i]["route_id"]),
            "site_id": problem.site_names[i],
            "chainage_km": float(sites.iloc[i]["chainage_km"]),
            "latitude": float(sites.iloc[i]["latitude"]),
            "longitude": float(sites.iloc[i]["longitude"]),
            "chargers": int(solution.chargers[i]),
            "reserved_power_kw": float(solution.power_kw[i]),
            "assigned_demand_kwh_day": float(served_by_site[i]),
            "site_fixed_cost_usd": float(problem.fixed_cost[i]),
            "charger_cost_usd_per_port": float(problem.charger_cost[i]),
            "site_status": str(sites.iloc[i].get("site_status", "")),
        })

    assignment_rows: list[dict[str, Any]] = []
    for i, site_id in enumerate(problem.site_names):
        for j, demand_id in enumerate(problem.demand_names):
            fraction = float(solution.assignment[i, j])
            if fraction > 1e-8:
                assignment_rows.append({
                    "case_id": case_dir.name,
                    "demand_scenario": scenario,
                    "charger_cost_scenario": cost_scenario,
                    "route_id": str(sites.iloc[i]["route_id"]),
                    "site_id": site_id,
                    "demand_id": demand_id,
                    "directed_driving_distance_km": float(distance_lookup[(site_id, demand_id)]),
                    "distance_direction": "demand_to_site",
                    "assignment_fraction": fraction,
                    "assigned_energy_kwh_day": fraction * float(problem.demand_kwh_day[j]),
                })
    assignment_frame = pd.DataFrame(assignment_rows)
    validate_run(scenario, cost_scenario, solution, problem, assignment_frame, MIP_REL_GAP)

    capex = (
        float(solution.objective_breakdown["station_establishment"])
        + float(solution.objective_breakdown["charger_installation"])
    )
    summary = {
        "case_id": case_dir.name,
        "demand_scenario": scenario,
        "charger_cost_scenario": cost_scenario,
        "status": "SOLVED_AND_VALIDATED",
        "requested_mip_rel_gap": MIP_REL_GAP,
        "achieved_mip_rel_gap": float(solution.mip_gap),
        "mip_node_count": solution.mip_node_count,
        "opened_station_count": int(np.sum(solution.opened)),
        "charger_count": int(np.sum(solution.chargers)),
        "installed_peak_power_kw": float(np.sum(solution.power_kw)),
        "total_demand_kwh_day": float(np.sum(problem.demand_kwh_day)),
        "station_establishment_cost_usd": float(solution.objective_breakdown["station_establishment"]),
        "charger_installation_cost_usd": float(solution.objective_breakdown["charger_installation"]),
        "total_capital_cost_proxy_usd": capex,
        "objective_value_model_units": float(solution.objective_value),
        "distance_direction": "demand_to_site",
        "distance_source": str(runner.DIRECTED_DISTANCE_MATRIX.relative_to(ROOT)),
        "assigned_pairs_count": int(len(assignment_frame)),
        "selected_site_ids": ";".join(sorted(selected_names)),
        "source_run": "NEW_OPTIMIZATION_AT_ALTERNATIVE_CHARGER_COST",
        "solver_message": str(solution.solver_message),
    }

    run_output = OUTPUT_ROOT / "runs" / case_dir.name
    run_output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([summary]).to_csv(run_output / "milp_scenario_summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(selected_rows).to_csv(run_output / "milp_selected_sites.csv", index=False, encoding="utf-8-sig")
    assignment_frame.to_csv(run_output / "milp_demand_assignments.csv", index=False, encoding="utf-8-sig")
    (run_output / "assumptions.json").write_text(
        (case_dir / "assumptions.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return summary, pd.DataFrame(selected_rows), assignment_frame


def main() -> int:
    if OUTPUT_ROOT.exists() and any(OUTPUT_ROOT.iterdir()):
        raise FileExistsError(
            f"Output folder already exists and is not empty: {OUTPUT_ROOT}. "
            "Move/rename it before rerunning; existing sensitivity results will not be overwritten."
        )
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    runner = load_runner_module()
    runner.OUTPUT = OUTPUT_ROOT

    site_template = runner.read_csv(
        runner.SITE_TEMPLATE,
        {"site_id", "route_id", "chainage_km", "latitude", "longitude"},
    )
    site_template["chainage_km"] = pd.to_numeric(site_template["chainage_km"], errors="coerce")
    if site_template["chainage_km"].isna().any() or site_template["site_id"].duplicated().any():
        raise ValueError("Candidate-site template has invalid or duplicate site IDs/chainage.")
    route_payload = json.loads(runner.ROUTE_LENGTHS.read_text(encoding="utf-8"))
    route_lengths = {str(k): float(v) for k, v in route_payload["route_lengths_km"].items()}
    if not runner.DIRECTED_DISTANCE_MATRIX.exists():
        raise FileNotFoundError(f"Directed matrix not found: {runner.DIRECTED_DISTANCE_MATRIX}")

    for scenario in DEMAND_SCENARIOS:
        demand_file = runner.TRAFFIC_SCENARIO_ROOT / scenario / "demand_points.csv"
        if not demand_file.exists():
            raise FileNotFoundError(f"Demand data missing for scenario {scenario}: {demand_file}")

    # Import installed package after confirming project files, matching the normal runner.
    try:
        from ev_charging.data_io import load_problem_from_csv
        from ev_charging.model import solve_milp
    except Exception as exc:
        raise RuntimeError("Could not import ev_charging; run with the project's .venv Python.") from exc

    print("DIRECTED DEMAND x CHARGER-CAPEX SENSITIVITY")
    print("===========================================")
    print("Demand scenarios:", ", ".join(DEMAND_SCENARIOS))
    print("Charger cost scenarios:", ", ".join(COST_SCENARIOS))
    print("Service distance=85 km; interstation spacing=85 km (chainage); directed matrix fixed.")
    print("The 4 existing base-cost runs are reused read-only; 8 alternative-cost cases will be optimized.")
    print(f"Output: {OUTPUT_ROOT.relative_to(ROOT)}")

    summaries: list[dict[str, Any]] = []
    selected_frames: list[pd.DataFrame] = []
    assignment_frames: list[pd.DataFrame] = []

    # Reuse the four previously solved directed/base-cost runs without changing them.
    for scenario in DEMAND_SCENARIOS:
        summary, selected, assignments = copy_base_cost_results(scenario)
        summaries.append(summary)
        selected_frames.append(selected)
        assignment_frames.append(assignments)

    total_new = len(DEMAND_SCENARIOS) * len(NON_BASE_COSTS)
    completed = 0
    for scenario in DEMAND_SCENARIOS:
        for cost_scenario in NON_BASE_COSTS:
            completed += 1
            label = f"{scenario} / {cost_scenario} charger cost"
            print(f"\n[{completed}/{total_new}] Preparing and solving {label}...")
            try:
                result, selected, assignments = solve_additional_case(
                    runner,
                    scenario,
                    cost_scenario,
                    site_template,
                    route_lengths,
                    load_problem_from_csv,
                    solve_milp,
                )
                summaries.append(result)
                selected_frames.append(selected)
                assignment_frames.append(assignments)
                print(
                    f"  PASS: {result['opened_station_count']} stations, "
                    f"{result['charger_count']} chargers, "
                    f"CAPEX ${result['total_capital_cost_proxy_usd']:,.0f}, "
                    f"MIP gap {result['achieved_mip_rel_gap']:.4%}"
                )
            except Exception as exc:
                summaries.append({
                    "case_id": f"demand_{scenario}__charger_cost_{cost_scenario}",
                    "demand_scenario": scenario,
                    "charger_cost_scenario": cost_scenario,
                    "status": "FAILED",
                    "error": f"{type(exc).__name__}: {exc}",
                    "source_run": "NEW_OPTIMIZATION_AT_ALTERNATIVE_CHARGER_COST",
                })
                print(f"  FAIL: {type(exc).__name__}: {exc}")

    summary_frame = pd.DataFrame(summaries)
    selected_frame = pd.concat(selected_frames, ignore_index=True) if selected_frames else pd.DataFrame()
    assignment_frame = pd.concat(assignment_frames, ignore_index=True) if assignment_frames else pd.DataFrame()

    # Make the output deterministic and easy to compare.
    demand_order = {name: i for i, name in enumerate(DEMAND_SCENARIOS)}
    cost_order = {name: i for i, name in enumerate(COST_SCENARIOS)}
    summary_frame["_demand_order"] = summary_frame["demand_scenario"].map(demand_order)
    summary_frame["_cost_order"] = summary_frame["charger_cost_scenario"].map(cost_order)
    summary_frame = summary_frame.sort_values(["_demand_order", "_cost_order"]).drop(
        columns=["_demand_order", "_cost_order"]
    )
    summary_frame.to_csv(OUTPUT_ROOT / "directed_demand_cost_sensitivity_summary.csv", index=False, encoding="utf-8-sig")
    selected_frame.to_csv(OUTPUT_ROOT / "directed_demand_cost_sensitivity_selected_sites.csv", index=False, encoding="utf-8-sig")
    assignment_frame.to_csv(OUTPUT_ROOT / "directed_demand_cost_sensitivity_assignments.csv", index=False, encoding="utf-8-sig")

    report_lines = [
        "# Directed-network demand and charger-CAPEX sensitivity",
        "",
        "All 12 demand/cost combinations use the same directed OSM virtual-edge distance matrix.",
        "Four base-cost runs are reused from the already validated directed-network scenarios; eight low/high cost runs are newly optimized.",
        "Service distance is fixed at 85 km; interstation spacing is fixed at 85 km and remains chainage-based.",
        "Only charger-port hardware plus installation cost changes between low/base/high cost cases.",
        "",
        "| Demand | Charger cost | Status | Stations | Chargers | CAPEX proxy (USD) | MIP gap |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for row in summary_frame.to_dict("records"):
        status = str(row.get("status", ""))
        stations = row.get("opened_station_count", "")
        chargers = row.get("charger_count", "")
        capex = row.get("total_capital_cost_proxy_usd", "")
        gap = row.get("achieved_mip_rel_gap", "")
        try:
            capex_text = f"{float(capex):,.0f}"
        except (TypeError, ValueError):
            capex_text = str(capex)
        try:
            gap_text = f"{float(gap):.4%}"
        except (TypeError, ValueError):
            gap_text = str(gap)
        report_lines.append(
            f"| {row.get('demand_scenario')} | {row.get('charger_cost_scenario')} | {status} | {stations} | {chargers} | {capex_text} | {gap_text} |"
        )
    report_lines += [
        "",
        "## Interpretation safeguards",
        "",
        "- These are conditional screening-model results, not construction-ready investment recommendations.",
        "- Low/base/high charger costs are transferred US benchmark values, not Armenian vendor bids.",
        "- Fixed site cost, six-port maximum, 900-kW site grid allowance, throughput, 85-km service distance, 85-km chainage spacing, and distance penalty are held fixed.",
        "- Demand scopes remain three represented subsections; unobserved corridor demand is not modeled.",
        "- Grid-upgrade CAPEX, land acquisition, maintenance and other local costs remain outside the current objective.",
        "- The composite objective includes an analyst-set distance penalty and should not be interpreted as USD; CAPEX proxy is reported separately.",
        "- Existing four base-cost outputs are read-only inputs to the comparison and are not modified.",
        "",
        "## Files",
        "",
        "- `directed_demand_cost_sensitivity_summary.csv`",
        "- `directed_demand_cost_sensitivity_selected_sites.csv`",
        "- `directed_demand_cost_sensitivity_assignments.csv`",
        "- `inputs/`: full model-input folders for the eight newly optimized low/high cost combinations.",
        "- `runs/`: per-case solver summaries, selected sites, assignments, and assumptions for those eight cases.",
    ]
    (OUTPUT_ROOT / "DIRECTED_DEMAND_COST_SENSITIVITY.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print("\nSAVED")
    print("  ", OUTPUT_ROOT / "directed_demand_cost_sensitivity_summary.csv")
    print("  ", OUTPUT_ROOT / "directed_demand_cost_sensitivity_selected_sites.csv")
    print("  ", OUTPUT_ROOT / "directed_demand_cost_sensitivity_assignments.csv")
    print("  ", OUTPUT_ROOT / "DIRECTED_DEMAND_COST_SENSITIVITY.md")
    print("\nSUMMARY")
    cols = [
        "demand_scenario", "charger_cost_scenario", "status", "opened_station_count",
        "charger_count", "total_capital_cost_proxy_usd", "achieved_mip_rel_gap",
    ]
    present = [c for c in cols if c in summary_frame.columns]
    print(summary_frame[present].to_string(index=False))
    failed = int((summary_frame["status"].astype(str).str.contains("FAILED")).sum())
    print(f"\nCompleted combinations: {len(summary_frame) - failed}/12; failed: {failed}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

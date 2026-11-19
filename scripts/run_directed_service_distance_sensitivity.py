#!/usr/bin/env python3
"""Run a directed-road MILP sensitivity analysis for service-distance limits.

Run from the project root with the project's virtual environment:
    .\\.venv\\Scripts\\python.exe scripts\\run_directed_service_distance_sensitivity.py

The script reruns the BASE demand scenario at several maximum service-distance
limits. It reuses the project's current case builder and MILP solver, but writes
all generated inputs and outputs into a new, separate sensitivity folder.
Existing scenario results are not overwritten.
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
SCRIPTS = ROOT / "scripts"
OUTPUT_ROOT = ROOT / "data" / "derived" / "directed_service_distance_sensitivity"
SCENARIO = "base"
COST_SCENARIO = "base"
SERVICE_DISTANCE_LIMITS_KM = (50.0, 60.0, 70.0, 80.0, 85.0, 90.0, 100.0, 120.0)


def load_runner_module():
    runner_path = SCRIPTS / "run_case_study_scenario.py"
    if not runner_path.exists():
        raise FileNotFoundError(f"Scenario runner not found: {runner_path}")
    spec = importlib.util.spec_from_file_location("case_study_runner_for_sensitivity", runner_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load scripts/run_case_study_scenario.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    runner = load_runner_module()
    from ev_charging.data_io import load_problem_from_csv
    from ev_charging.model import solve_milp

    print("DIRECTED SERVICE-DISTANCE SENSITIVITY — BASE DEMAND")
    print("===================================================")
    print(f"Scenario: {SCENARIO} | charger cost: {COST_SCENARIO}")
    print(f"Service-distance limits (km): {', '.join(map(str, SERVICE_DISTANCE_LIMITS_KM))}")
    print("Interstation maximum remains fixed at the project's 85-km setting.")
    print("All runs are written to a new sensitivity folder; existing results are untouched.\n")

    sites = runner.read_csv(
        runner.SITE_TEMPLATE,
        {"site_id", "route_id", "chainage_km", "latitude", "longitude"},
    )
    sites["chainage_km"] = pd.to_numeric(sites["chainage_km"], errors="coerce")
    if sites["chainage_km"].isna().any() or sites["site_id"].duplicated().any():
        raise ValueError("Candidate site data has invalid/duplicate IDs or chainages.")
    route_payload = json.loads(runner.ROUTE_LENGTHS.read_text(encoding="utf-8"))
    route_lengths = {str(k): float(v) for k, v in route_payload["route_lengths_km"].items()}

    # Fail early unless the updated scenario builder explicitly uses the new matrix.
    builder_source = (SCRIPTS / "run_case_study_scenario.py").read_text(encoding="utf-8")
    if "corridor_site_demand_distances_virtual_edge.csv" not in builder_source:
        raise RuntimeError(
            "The current run_case_study_scenario.py does not appear to reference the "
            "directed virtual-edge distance matrix. Refusing to run sensitivity on legacy distances."
        )

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    summary_rows: list[dict[str, Any]] = []
    assignment_rows: list[dict[str, Any]] = []
    selected_rows: list[dict[str, Any]] = []

    for limit in SERVICE_DISTANCE_LIMITS_KM:
        label = f"service_{int(limit)}km" if float(limit).is_integer() else f"service_{limit:g}km"
        run_dir = OUTPUT_ROOT / SCENARIO / label
        run_dir.mkdir(parents=True, exist_ok=True)
        runner.OUTPUT = run_dir
        runner.MAX_SERVICE_DISTANCE_KM = float(limit)

        print(f"[{label}] Preparing inputs...", flush=True)
        case_dir = runner.build_case_inputs(SCENARIO, COST_SCENARIO, sites, route_lengths)

        # Confirm that every case received the requested threshold and directed matrix.
        config = json.loads((case_dir / "config.json").read_text(encoding="utf-8"))
        if not math.isclose(float(config["max_service_distance_km"]), float(limit), abs_tol=1e-9):
            raise ValueError(f"Wrong service-distance limit written for {label}.")
        assumptions = json.loads((case_dir / "assumptions.json").read_text(encoding="utf-8"))
        distance_source = str(assumptions.get("directed_distance_matrix_source", ""))
        if "corridor_site_demand_distances_virtual_edge.csv" not in distance_source:
            raise ValueError(f"{label} is not using the directed virtual-edge distance matrix.")

        print(f"[{label}] Solving (MIP gap target {runner.MIP_REL_GAP:.1%})...", flush=True)
        try:
            problem = load_problem_from_csv(case_dir)
            solution = solve_milp(
                problem,
                mip_rel_gap=runner.MIP_REL_GAP,
                time_limit_seconds=runner.TIME_LIMIT_SECONDS,
            )
            assignment = np.asarray(solution.assignment, dtype=float)
            served_by_site = assignment @ problem.demand_kwh_day
            opened_idx = np.flatnonzero(solution.opened)
            selected_site_count = int(np.asarray(solution.opened, dtype=bool).sum())
            charger_count = int(np.asarray(solution.chargers, dtype=int).sum())
            distance_frame = pd.read_csv(case_dir / "distances.csv")
            distance_lookup = distance_frame.set_index(["site_id", "demand_id"])["distance_km"].to_dict()
            direction_lookup = (
                distance_frame.set_index(["site_id", "demand_id"])["distance_direction"].to_dict()
                if "distance_direction" in distance_frame.columns
                else {}
            )

            fraction_sums = assignment.sum(axis=0)
            assigned_pairs = []
            max_assigned_distance = 0.0
            for i, site_id in enumerate(problem.site_names):
                if bool(solution.opened[i]):
                    selected_rows.append({
                        "scenario": SCENARIO,
                        "service_distance_limit_km": limit,
                        "site_id": site_id,
                        "route_id": str(sites.set_index("site_id").loc[site_id, "route_id"]),
                        "chainage_km": float(sites.set_index("site_id").loc[site_id, "chainage_km"]),
                        "chargers": int(solution.chargers[i]),
                        "installed_power_kw": float(solution.power_kw[i]),
                        "assigned_demand_kwh_day": float(served_by_site[i]),
                    })
                for j, demand_id in enumerate(problem.demand_names):
                    fraction = float(assignment[i, j])
                    if fraction > 1e-8:
                        distance = float(distance_lookup[(site_id, demand_id)])
                        max_assigned_distance = max(max_assigned_distance, distance)
                        assigned_pairs.append({
                            "scenario": SCENARIO,
                            "service_distance_limit_km": limit,
                            "site_id": site_id,
                            "demand_id": demand_id,
                            "directed_demand_to_site_distance_km": distance,
                            "distance_direction": direction_lookup.get((site_id, demand_id), "demand_to_site"),
                            "assignment_fraction": fraction,
                            "assigned_energy_kwh_day": fraction * float(problem.demand_kwh_day[j]),
                        })
            assignment_rows.extend(assigned_pairs)

            station_cost = float(solution.objective_breakdown["station_establishment"])
            charger_cost = float(solution.objective_breakdown["charger_installation"])
            max_fraction_error = float(np.max(np.abs(fraction_sums - 1.0)))
            all_distances_within_limit = all(
                row["directed_demand_to_site_distance_km"] <= limit + 1e-7
                for row in assigned_pairs
            )
            summary_rows.append({
                "scenario": SCENARIO,
                "service_distance_limit_km": limit,
                "status": "SOLVED",
                "mip_gap": float(solution.mip_gap),
                "opened_station_count": selected_site_count,
                "charger_count": charger_count,
                "installed_peak_power_kw": float(np.asarray(solution.power_kw, dtype=float).sum()),
                "total_demand_kwh_day": float(problem.demand_kwh_day.sum()),
                "total_capital_cost_proxy_usd": station_cost + charger_cost,
                "objective_value_model_units": float(solution.objective_value),
                "assigned_pair_count": len(assigned_pairs),
                "max_assignment_fraction_sum_error": max_fraction_error,
                "max_assigned_distance_km": max_assigned_distance,
                "all_assigned_distances_within_limit": all_distances_within_limit,
                "all_demand_fully_assigned": max_fraction_error <= 1e-6,
                "solver_message": str(solution.solver_message),
                "run_directory": str(run_dir),
            })
            print(
                f"[{label}] PASS: {selected_site_count} stations, {charger_count} chargers, "
                f"CAPEX proxy ${station_cost + charger_cost:,.0f}, gap {float(solution.mip_gap):.4%}",
                flush=True,
            )
        except Exception as exc:
            summary_rows.append({
                "scenario": SCENARIO,
                "service_distance_limit_km": limit,
                "status": f"FAILED_OR_INFEASIBLE: {type(exc).__name__}: {exc}",
                "run_directory": str(run_dir),
            })
            print(f"[{label}] FAILED: {type(exc).__name__}: {exc}", flush=True)

    summary = pd.DataFrame(summary_rows)
    assignments = pd.DataFrame(assignment_rows)
    selected = pd.DataFrame(selected_rows)
    summary_path = OUTPUT_ROOT / "base_service_distance_sensitivity_summary.csv"
    assignment_path = OUTPUT_ROOT / "base_service_distance_sensitivity_assignments.csv"
    selected_path = OUTPUT_ROOT / "base_service_distance_sensitivity_selected_sites.csv"
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    assignments.to_csv(assignment_path, index=False, encoding="utf-8-sig")
    selected.to_csv(selected_path, index=False, encoding="utf-8-sig")

    lines = [
        "# Directed-network service-distance sensitivity — Base demand",
        "",
        "The service-distance limit varies; directed demand-to-site OSM distances and all other model assumptions are held fixed.",
        "The interstation maximum remains 85 km and continues to use route chainage.",
        "The model is a screening case for three represented demand scopes, not a full-corridor investment plan.",
        "",
        "| Service limit (km) | Status | Stations | Chargers | CAPEX proxy (USD) | MIP gap |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for row in summary_rows:
        if row.get("status") == "SOLVED":
            lines.append(
                f"| {row['service_distance_limit_km']:g} | SOLVED | {row['opened_station_count']} | "
                f"{row['charger_count']} | {row['total_capital_cost_proxy_usd']:,.0f} | {row['mip_gap']:.4%} |"
            )
        else:
            lines.append(f"| {row['service_distance_limit_km']:g} | {row.get('status','FAILED')} | — | — | — | — |")
    lines += [
        "",
        "## Interpretation safeguards",
        "",
        "- A shorter maximum service distance can make the model infeasible if any demand point has no eligible open site or insufficient eligible capacity.",
        "- Changes in station counts and CAPEX are conditional on the current assumptions, including US benchmark CAPEX and the analyst-set distance penalty.",
        "- This varies the demand-to-site service limit only; it does not vary the interstation spacing limit.",
        "- The results remain provisional because demand is represented by three subsections and road-edge proximity does not establish legal driveway access.",
        "",
        f"CSV summary: `{summary_path.relative_to(ROOT)}`",
    ]
    report_path = OUTPUT_ROOT / "BASE_SERVICE_DISTANCE_SENSITIVITY.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\nSAVED")
    print(f"  {summary_path.relative_to(ROOT)}")
    print(f"  {assignment_path.relative_to(ROOT)}")
    print(f"  {selected_path.relative_to(ROOT)}")
    print(f"  {report_path.relative_to(ROOT)}")
    print("\nSUMMARY")
    display_cols = [
        "service_distance_limit_km", "status", "opened_station_count", "charger_count",
        "total_capital_cost_proxy_usd", "mip_gap",
    ]
    existing_cols = [col for col in display_cols if col in summary.columns]
    print(summary[existing_cols].to_string(index=False))
    return 0 if not summary.empty and (summary["status"] == "SOLVED").all() else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise

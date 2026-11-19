#!/usr/bin/env python3
"""Validate all four directed-network MILP scenario outputs.

Run from the project root with:
  .\\.venv\\Scripts\\python.exe scripts\\validate_directed_scenario_outputs.py

This script reads outputs only and writes a validation CSV. It does not modify
MILP inputs, solver results, or previous scenario folders.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "data" / "derived" / "case_study_screening_milp_directed_network" / "scenario_runs"
SCENARIOS = ("low", "base", "high", "armstat_ev_share_2_92")
REQUESTED_GAP = 0.001
MAX_SERVICE_KM = 85.0
TOL = 1e-6


def read_csv(path: Path, required: set[str]) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing expected output: {path}")
    df = pd.read_csv(path, encoding="utf-8-sig")
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} missing columns: {sorted(missing)}")
    return df


def main() -> int:
    print("DIRECTED NETWORK MILP OUTPUT VALIDATION")
    print("=======================================")
    rows: list[dict[str, object]] = []
    failures: list[str] = []

    for scenario in SCENARIOS:
        folder = RUN_ROOT / scenario
        print(f"\n[{scenario.upper()}]")
        summary = read_csv(folder / "milp_scenario_summary.csv", {
            "status", "achieved_mip_rel_gap", "opened_station_count", "charger_count",
            "installed_peak_power_kw", "total_capital_cost_proxy_usd", "total_demand_kwh_day",
        })
        selected = read_csv(folder / "milp_selected_sites.csv", {"site_id", "chargers"})
        assignments = read_csv(folder / "milp_demand_assignments.csv", {
            "site_id", "demand_id", "directed_driving_distance_km", "distance_direction",
            "assignment_fraction", "assigned_energy_kwh_day",
        })

        case_dirs = list((folder / "inputs").glob("demand_*__charger_cost_base"))
        if len(case_dirs) != 1:
            raise ValueError(f"Expected one generated input case in {folder / 'inputs'}, found {len(case_dirs)}")
        demand = read_csv(case_dirs[0] / "demand_points.csv", {"demand_id", "demand_kwh_day"})

        if len(summary) != 1:
            failures.append(f"{scenario}: expected one summary row, found {len(summary)}")
            continue
        sr = summary.iloc[0]
        gap = float(sr["achieved_mip_rel_gap"])
        status_ok = sr["status"] == "SOLVED_WITHIN_REQUESTED_MIP_GAP"
        gap_ok = np.isfinite(gap) and gap <= REQUESTED_GAP + 1e-12
        station_count_ok = len(selected) == int(sr["opened_station_count"])
        charger_count_ok = int(pd.to_numeric(selected["chargers"]).sum()) == int(sr["charger_count"])

        expected_demands = set(demand["demand_id"].astype(str))
        assigned_demands = set(assignments["demand_id"].astype(str))
        demand_set_ok = expected_demands == assigned_demands
        frac_by_demand = assignments.groupby("demand_id")["assignment_fraction"].sum()
        fractions_ok = demand_set_ok and bool(np.allclose(
            frac_by_demand.reindex(sorted(expected_demands)).to_numpy(dtype=float), 1.0, atol=TOL, rtol=0.0
        ))
        direction_ok = bool(assignments["distance_direction"].astype(str).eq("demand_to_site").all())
        distances = pd.to_numeric(assignments["directed_driving_distance_km"], errors="coerce")
        distance_ok = bool(distances.notna().all() and np.isfinite(distances).all()
                           and (distances >= 0).all() and (distances <= MAX_SERVICE_KM + TOL).all())
        selected_ids = set(selected["site_id"].astype(str))
        assignment_sites_ok = set(assignments["site_id"].astype(str)).issubset(selected_ids)

        demand_lookup = demand.assign(demand_id=demand["demand_id"].astype(str)).set_index("demand_id")["demand_kwh_day"].astype(float)
        assignment_energy = assignments.groupby("demand_id")["assigned_energy_kwh_day"].sum()
        energy_ok = demand_set_ok and bool(np.allclose(
            assignment_energy.reindex(sorted(expected_demands)).to_numpy(dtype=float),
            demand_lookup.reindex(sorted(expected_demands)).to_numpy(dtype=float),
            atol=1e-4, rtol=1e-8,
        ))
        total_demand_ok = abs(float(demand["demand_kwh_day"].sum()) - float(sr["total_demand_kwh_day"])) <= 1e-4

        checks = {
            "solver_status": status_ok,
            "mip_gap_le_0.1pct": gap_ok,
            "selected_station_count": station_count_ok,
            "selected_charger_count": charger_count_ok,
            "all_demand_points_assigned": demand_set_ok,
            "assignment_fraction_sums_to_1": fractions_ok,
            "direction_is_demand_to_site": direction_ok,
            "assigned_distances_le_85km": distance_ok,
            "assignments_only_to_selected_sites": assignment_sites_ok,
            "assigned_energy_matches_demand": energy_ok,
            "summary_demand_matches_input": total_demand_ok,
        }
        for name, passed in checks.items():
            print(f"  {'PASS' if passed else 'FAIL'}  {name}")
            if not passed:
                failures.append(f"{scenario}: {name}")

        row = {
            "scenario": scenario,
            "status": sr["status"],
            "achieved_mip_rel_gap": gap,
            "opened_station_count": int(sr["opened_station_count"]),
            "charger_count": int(sr["charger_count"]),
            "installed_peak_power_kw": float(sr["installed_peak_power_kw"]),
            "total_capital_cost_proxy_usd": float(sr["total_capital_cost_proxy_usd"]),
            "total_demand_kwh_day": float(sr["total_demand_kwh_day"]),
            "assignment_count": len(assignments),
            **checks,
        }
        rows.append(row)
        print(f"  Result: {row['opened_station_count']} stations, {row['charger_count']} chargers, "
              f"CAPEX proxy ${row['total_capital_cost_proxy_usd']:,.0f}, MIP gap {gap:.4%}")

        # Print relevant recorded assumptions without assuming all keys exist.
        assumptions_path = folder / "global_assumptions.json"
        readme_path = folder / "README.txt"
        if assumptions_path.exists():
            assumptions = json.loads(assumptions_path.read_text(encoding="utf-8"))
            relevant = {k: v for k, v in assumptions.items()
                        if any(token in k.lower() for token in ("distance", "scope", "mip", "scenario"))}
            print("  Recorded assumptions:")
            for key, value in relevant.items():
                print(f"    {key}: {value}")
        else:
            failures.append(f"{scenario}: missing global_assumptions.json")
        if not readme_path.exists():
            failures.append(f"{scenario}: missing README.txt")

    if rows:
        report_path = RUN_ROOT / "DIRECTED_SCENARIO_VALIDATION.csv"
        pd.DataFrame(rows).to_csv(report_path, index=False, encoding="utf-8-sig")
        print(f"\nValidation CSV: {report_path.relative_to(ROOT)}")

    print("\nFINAL STATUS")
    if failures:
        print(f"FAILED: {len(failures)} issue(s)")
        for item in failures:
            print(f"  - {item}")
        return 2
    print("PASS: all four directed-network scenario outputs passed all checks.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise

#!/usr/bin/env python3
"""Audit low/base/high Armenia M1/M2 screening MILP scenario outputs.

Run from the project root:
  .\\.venv\\Scripts\\python.exe scripts\\validate_case_study_scenarios.py

This is a post-solve consistency audit. It does not validate OSM alignment,
real traffic demand, land access, utility capacity, or local cost assumptions.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_ROOT = ROOT / "data" / "derived" / "case_study_screening_milp" / "scenario_runs"
CANDIDATE_PATH = ROOT / "data" / "derived" / "corridor_candidate_sites.csv"
OUTPUT_DIR = ROOT / "data" / "derived" / "case_study_screening_milp"
OUTPUT_CSV = OUTPUT_DIR / "scenario_validation_report.csv"
SCENARIOS = ("low", "base", "high")
ROUTES = ("M1", "M2")
TOL = 1e-5


def fail(message: str, errors: list[str]) -> None:
    errors.append(message)


def main() -> int:
    if not CANDIDATE_PATH.exists():
        print(f"ERROR: missing {CANDIDATE_PATH}")
        return 2
    candidates = pd.read_csv(CANDIDATE_PATH)
    required_candidate = {"site_id", "route_id", "chainage_km"}
    if not required_candidate.issubset(candidates.columns):
        print(f"ERROR: {CANDIDATE_PATH.name} missing columns {sorted(required_candidate - set(candidates.columns))}")
        return 2
    route_lengths = candidates.groupby("route_id")["chainage_km"].max().to_dict()

    reports: list[dict[str, object]] = []
    all_errors: list[str] = []
    print("M1/M2 SCREENING MILP — POST-SOLVE VALIDATION")
    print("Checks: route spacing, charger/power consistency, assignments, capacity, objective and CAPEX")
    print("This does not establish real-world corridor-wide feasibility.\n")

    for scenario in SCENARIOS:
        folder = SCENARIO_ROOT / scenario
        summary_path = folder / "milp_scenario_summary.csv"
        sites_path = folder / "milp_selected_sites.csv"
        assignments_path = folder / "milp_demand_assignments.csv"
        if not all(p.exists() for p in (summary_path, sites_path, assignments_path)):
            fail(f"{scenario}: missing one or more expected output CSVs in {folder}", all_errors)
            continue

        summary_df = pd.read_csv(summary_path)
        sites = pd.read_csv(sites_path)
        assignments = pd.read_csv(assignments_path)
        if len(summary_df) != 1:
            fail(f"{scenario}: expected one summary row, found {len(summary_df)}", all_errors)
            continue
        summary = summary_df.iloc[0]
        errors: list[str] = []
        warnings: list[str] = []

        # Read scenario-specific assumptions when present.
        assumptions_path = folder / "global_assumptions.json"
        assumptions: dict[str, object] = {}
        if assumptions_path.exists():
            try:
                assumptions = json.loads(assumptions_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                warnings.append(f"Could not parse global_assumptions.json: {exc}")
        max_gap = float(assumptions.get("max_interstation_distance_km", 85.0))
        max_service = float(assumptions.get("max_service_distance_km", 85.0))
        max_chargers = int(assumptions.get("max_chargers_per_site", 6))
        grid_capacity = float(assumptions.get("grid_capacity_kw_per_site", 900.0))
        charger_kw = float(assumptions.get("charger_peak_power_kw", 150.0))
        daily_throughput = float(assumptions.get("daily_throughput_kwh_per_charger", 1000.0))

        required_sites = {
            "route_id", "site_id", "chainage_km", "chargers", "reserved_power_kw",
            "assigned_demand_kwh_day", "site_fixed_cost_usd", "charger_cost_usd_per_port",
        }
        required_assignments = {
            "route_id", "site_id", "demand_id", "distance_proxy_km",
            "assignment_fraction", "assigned_energy_kwh_day",
        }
        if not required_sites.issubset(sites.columns):
            fail(f"{scenario}: selected-sites CSV missing columns {sorted(required_sites - set(sites.columns))}", errors)
        if not required_assignments.issubset(assignments.columns):
            fail(f"{scenario}: demand-assignments CSV missing columns {sorted(required_assignments - set(assignments.columns))}", errors)
        if errors:
            for e in errors:
                print(f"ERROR [{scenario}]: {e}")
                all_errors.append(e)
            continue

        if sites["site_id"].duplicated().any():
            fail(f"{scenario}: duplicate selected site_id values", errors)
        if (sites["chargers"] < 1).any() or (sites["chargers"] > max_chargers).any():
            fail(f"{scenario}: charger count outside [1, {max_chargers}]", errors)
        if not np.allclose(sites["reserved_power_kw"], sites["chargers"] * charger_kw, atol=TOL):
            fail(f"{scenario}: reserved power is not chargers × {charger_kw:g} kW", errors)
        if (sites["reserved_power_kw"] > grid_capacity + TOL).any():
            fail(f"{scenario}: at least one site exceeds assumed grid capacity {grid_capacity:g} kW", errors)

        # Check route-endpoint and inter-station gaps independently by corridor.
        max_observed_gap = 0.0
        route_gap_text: list[str] = []
        for route in ROUTES:
            length = route_lengths.get(route)
            route_sites = sites.loc[sites["route_id"] == route].sort_values("chainage_km")
            if length is None or route_sites.empty:
                fail(f"{scenario}: no route length or selected station for {route}", errors)
                continue
            chainages = route_sites["chainage_km"].astype(float).to_numpy()
            if np.any(chainages < -TOL) or np.any(chainages > float(length) + TOL):
                fail(f"{scenario}: {route} selected station chainage outside route bounds", errors)
            gaps = np.diff(np.concatenate(([0.0], chainages, [float(length)])))
            route_max = float(np.max(gaps))
            max_observed_gap = max(max_observed_gap, route_max)
            route_gap_text.append(f"{route}={route_max:.2f} km")
            if route_max > max_gap + TOL:
                fail(f"{scenario}: {route} maximum endpoint/inter-station gap {route_max:.3f} km exceeds {max_gap:g} km", errors)

        # Check assignment fractions per demand; the files contain only eligible/positive pairs.
        if assignments.empty:
            fail(f"{scenario}: demand assignment file is empty", errors)
            assignment_total = 0.0
        else:
            fraction_sums = assignments.groupby(["route_id", "demand_id"])["assignment_fraction"].sum()
            for key, value in fraction_sums.items():
                if not math.isclose(float(value), 1.0, rel_tol=0, abs_tol=1e-5):
                    fail(f"{scenario}: assignment fractions for {key} sum to {value:.8f}, not 1", errors)
            if (assignments["distance_proxy_km"] > max_service + TOL).any():
                fail(f"{scenario}: at least one demand assignment exceeds service-distance limit {max_service:g} km", errors)
            if not set(assignments["site_id"]).issubset(set(sites["site_id"])):
                fail(f"{scenario}: assignments reference a site not listed as selected", errors)
            assignment_by_site = assignments.groupby("site_id")["assigned_energy_kwh_day"].sum()
            selected_by_site = sites.set_index("site_id")["assigned_demand_kwh_day"]
            for site_id, energy in assignment_by_site.items():
                if site_id in selected_by_site.index and not math.isclose(float(energy), float(selected_by_site.loc[site_id]), rel_tol=1e-6, abs_tol=1e-4):
                    fail(f"{scenario}: assigned energy mismatch at {site_id}", errors)
            charger_lookup = sites.set_index("site_id")["chargers"]
            for site_id, energy in assignment_by_site.items():
                capacity = float(charger_lookup.loc[site_id]) * daily_throughput
                if float(energy) > capacity + TOL:
                    fail(f"{scenario}: {site_id} assigned {energy:.2f} kWh/day exceeds throughput capacity {capacity:.2f}", errors)
            assignment_total = float(assignments["assigned_energy_kwh_day"].sum())

        selected_assigned_total = float(sites["assigned_demand_kwh_day"].sum())
        summary_demand = float(summary.get("total_demand_kwh_day", selected_assigned_total))
        if not math.isclose(selected_assigned_total, summary_demand, rel_tol=1e-6, abs_tol=1e-3):
            fail(f"{scenario}: selected-site assigned energy does not match summary total demand", errors)
        if not math.isclose(assignment_total, summary_demand, rel_tol=1e-6, abs_tol=1e-3):
            fail(f"{scenario}: demand-assignment energy does not match summary total demand", errors)

        # Recompute capex from the selected-site records.
        capex = float(sites["site_fixed_cost_usd"].sum() + (sites["chargers"] * sites["charger_cost_usd_per_port"]).sum())
        reported_capex = float(summary["total_capital_cost_proxy_usd"])
        if not math.isclose(capex, reported_capex, rel_tol=1e-7, abs_tol=0.05):
            fail(f"{scenario}: recomputed CAPEX ${capex:,.2f} != summary ${reported_capex:,.2f}", errors)

        requested_gap = float(summary["requested_mip_rel_gap"])
        achieved_gap = float(summary["achieved_mip_rel_gap"])
        status = str(summary["status"])
        if "SOLVED_WITHIN_REQUESTED_MIP_GAP" not in status or achieved_gap > requested_gap + 1e-10:
            fail(f"{scenario}: solver status/gap does not satisfy requested MIP gap", errors)

        # Zero-demand stations are expected when retained solely for spatial spacing.
        zero_demand_stations = int((sites["assigned_demand_kwh_day"] <= TOL).sum())
        if zero_demand_stations:
            warnings.append(f"{zero_demand_stations} selected station(s) receive zero demand in this two-ATC-point model; likely spacing-only stations")
        if len(assignments.groupby("demand_id")) < 2:
            warnings.append("Fewer than two demand points represented; not a corridor-wide demand model")
        warnings.append("Demand is limited to the two historic ATC scopes; distances are chainage proxies and candidate sites are not buildability-verified")

        row: dict[str, object] = {
            "scenario": scenario,
            "status": status,
            "requested_mip_gap": requested_gap,
            "achieved_mip_gap": achieved_gap,
            "opened_stations": int(len(sites)),
            "chargers": int(sites["chargers"].sum()),
            "installed_power_kw": float(sites["reserved_power_kw"].sum()),
            "demand_kwh_day": summary_demand,
            "capex_proxy_usd_recomputed": capex,
            "max_route_gap_km": max_observed_gap,
            "route_max_gaps": "; ".join(route_gap_text),
            "zero_demand_stations": zero_demand_stations,
            "validation": "PASS" if not errors else "FAIL",
            "errors": " | ".join(errors),
            "warnings": " | ".join(warnings),
        }
        reports.append(row)
        print(f"{scenario.upper()}: {'PASS' if not errors else 'FAIL'} | stations={len(sites)} | chargers={int(sites['chargers'].sum())} | CAPEX=${capex:,.0f} | max route gap={max_observed_gap:.2f} km | MIP gap={achieved_gap:.4%}")
        for warning in warnings:
            print(f"  WARNING: {warning}")
        for error in errors:
            print(f"  ERROR: {error}")
        all_errors.extend(f"{scenario}: {e}" for e in errors)

    if not reports:
        print("ERROR: no scenario could be validated")
        return 2
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(reports).to_csv(OUTPUT_CSV, index=False)
    print(f"\nSaved validation report: {OUTPUT_CSV}")
    if all_errors:
        print(f"\nVALIDATION FAILED: {len(all_errors)} issue(s) detected")
        return 1
    print("\nALL AVAILABLE SCENARIOS PASSED THE STRUCTURAL / NUMERICAL AUDIT.")
    print("This does not validate real-world demand, route access, land, grid connection, or local costs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

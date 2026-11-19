#!/usr/bin/env python3
"""Create and prepare an Armstat-based EV-share sensitivity scenario.

Run from the EV-Charging-M1-M2 project root:
  .\\.venv\\Scripts\\python.exe scripts\\create_armstat_ev_share_sensitivity.py

This creates a separate traffic scenario cloned from `base`, changes only the
EV-share assumption using Armstat's registered passenger-car EV share as of
2025-11-01, and creates a dedicated MILP runner copied from the user's current
runner. The original base data, runner, and results are not overwritten.

Important: registered fleet share is used only as an alternative proxy for
EV share in traffic. It is not a direct measurement of EV share at M1/M2 ATC
locations or of corridor traffic.
"""
from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_ROOT = ROOT / "data" / "derived" / "traffic_ev_demand_scenarios"
BASE_DIR = SCENARIO_ROOT / "base"
NEW_SCENARIO = "armstat_ev_share_2_92"
NEW_DIR = SCENARIO_ROOT / NEW_SCENARIO
SUMMARY_PATH = SCENARIO_ROOT / "scenario_summary.csv"
RUNNER_PATH = ROOT / "scripts" / "run_case_study_scenario.py"
NEW_RUNNER_PATH = ROOT / "scripts" / "run_case_study_armstat_sensitivity.py"
NOTE_PATH = SCENARIO_ROOT / "ARMSTAT_EV_SHARE_SENSITIVITY.txt"
SUMMARY_BACKUP_PATH = SCENARIO_ROOT / "scenario_summary_before_armstat_ev_share.csv"
SITE_TEMPLATE_PATH = ROOT / "data" / "derived" / "milp_corridor_sites_template.csv"

# Armstat registered passenger cars, as of 2025-11-01:
# 23,759 pure EV passenger cars / 812,634 registered passenger cars.
ARMSTAT_EV_PASSENGER_CARS = 23_759
ARMSTAT_ALL_PASSENGER_CARS = 812_634
ARMSTAT_EV_SHARE = ARMSTAT_EV_PASSENGER_CARS / ARMSTAT_ALL_PASSENGER_CARS
REFERENCE_SEI_EV_SHARE = 0.025
SCALING_FACTOR = ARMSTAT_EV_SHARE / REFERENCE_SEI_EV_SHARE


def require_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Required project file not found: {path}")


def prepare_scenario() -> None:
    require_file(BASE_DIR / "demand_points.csv")
    require_file(BASE_DIR / "distances.csv")
    require_file(BASE_DIR / "scenario_assumptions.json")
    require_file(SUMMARY_PATH)
    require_file(RUNNER_PATH)
    require_file(SITE_TEMPLATE_PATH)

    if NEW_DIR.exists():
        raise FileExistsError(
            f"Target scenario already exists: {NEW_DIR}\n"
            "It was not overwritten. Rename or archive it manually before rerunning."
        )
    if NEW_RUNNER_PATH.exists():
        raise FileExistsError(
            f"Dedicated runner already exists: {NEW_RUNNER_PATH}\n"
            "It was not overwritten. Rename or archive it manually before rerunning."
        )
    if SUMMARY_BACKUP_PATH.exists():
        raise FileExistsError(
            f"Summary backup already exists: {SUMMARY_BACKUP_PATH}\n"
            "It was not overwritten. Check the previous run before retrying."
        )

    print("[1/5] Validating the official Armstat ratio and the base scenario...")
    demand = pd.read_csv(BASE_DIR / "demand_points.csv", encoding="utf-8-sig")
    required = {"demand_id", "demand_kwh_day", "route_id", "ev_share_assumption"}
    missing = required - set(demand.columns)
    if missing:
        raise ValueError(f"base/demand_points.csv missing columns: {sorted(missing)}")
    old_share = pd.to_numeric(demand["ev_share_assumption"], errors="coerce")
    if old_share.isna().any() or not (old_share.sub(REFERENCE_SEI_EV_SHARE).abs() < 1e-9).all():
        raise ValueError(
            "Expected all base rows to use EV share 0.025. "
            f"Observed values: {sorted(old_share.dropna().unique().tolist())}"
        )
    old_demand = pd.to_numeric(demand["demand_kwh_day"], errors="coerce")
    if old_demand.isna().any() or (old_demand <= 0).any():
        raise ValueError("Base demand_kwh_day values must all be positive numeric values.")

    runner_text = RUNNER_PATH.read_text(encoding="utf-8")
    allowed_line = 'VALID_DEMAND_SCENARIOS = ("low", "base", "high")'
    if runner_text.count(allowed_line) != 1:
        raise ValueError(
            "Could not safely locate the expected VALID_DEMAND_SCENARIOS line in "
            f"{RUNNER_PATH}. No project files were changed."
        )
    loop_line = 'for demand_scenario in ("low", "base", "high"):'
    loop_count = runner_text.count(loop_line)
    if loop_count != 2:
        raise ValueError(
            "Expected two low/base/high reporting loops in the runner, but found "
            f"{loop_count}. No project files were changed."
        )

    print("[2/5] Creating a separate scenario folder (base files remain unchanged)...")
    shutil.copytree(BASE_DIR, NEW_DIR)
    demand["demand_kwh_day"] = old_demand * SCALING_FACTOR
    demand["ev_share_assumption"] = ARMSTAT_EV_SHARE
    if "other_assumptions_status" in demand.columns:
        demand["other_assumptions_status"] = demand["other_assumptions_status"].astype(str) + "; ARMSTAT_REGISTERED_PASSENGER_EV_SHARE_SENSITIVITY"
    demand.to_csv(NEW_DIR / "demand_points.csv", index=False, encoding="utf-8-sig")

    assumptions_path = NEW_DIR / "scenario_assumptions.json"
    assumptions = json.loads(assumptions_path.read_text(encoding="utf-8"))
    assumptions.update({
        "scenario_id": NEW_SCENARIO,
        "ev_share_assumption": ARMSTAT_EV_SHARE,
        "description": (
            "Alternative sensitivity using Armstat's registered pure-EV passenger-car "
            "share as of 2025-11-01; all other base-scenario assumptions are held constant."
        ),
        "ev_share_reference": {
            "registered_pure_ev_passenger_cars": ARMSTAT_EV_PASSENGER_CARS,
            "all_registered_passenger_cars": ARMSTAT_ALL_PASSENGER_CARS,
            "date": "2025-11-01",
            "share_fraction_unrounded": ARMSTAT_EV_SHARE,
            "share_percent_unrounded": ARMSTAT_EV_SHARE * 100.0,
            "share_percent_rounded": round(ARMSTAT_EV_SHARE * 100.0, 2),
            "source_url": "https://www.armstat.am/file/article/sv_09_25r_6200.pdf",
            "interpretation_warning": (
                "This is the registered passenger-car fleet share, not a direct "
                "measurement of the EV share of vehicles passing either M1/M2 traffic counter. "
                "It is used only as an alternative scenario proxy."
            ),
        },
        "scaling_from_sei_base_share": {
            "reference_sei_share_fraction": REFERENCE_SEI_EV_SHARE,
            "scaling_factor": SCALING_FACTOR,
            "all_other_base_assumptions_held_constant": True,
        },
    })
    if "additional_adb_m2_subsection_demand" in assumptions:
        adb = assumptions["additional_adb_m2_subsection_demand"]
        if isinstance(adb, dict) and "demand_kwh_day" in adb:
            adb["demand_kwh_day"] = float(adb["demand_kwh_day"]) * SCALING_FACTOR
            adb["ev_share_assumption"] = ARMSTAT_EV_SHARE
    assumptions_path.write_text(json.dumps(assumptions, indent=2) + "\n", encoding="utf-8")

    # Add the alternative scenario rows to the top-level provenance table.
    summary = pd.read_csv(SUMMARY_PATH, encoding="utf-8-sig")
    if "scenario_id" not in summary.columns or "demand_kwh_day" not in summary.columns:
        raise ValueError("scenario_summary.csv is missing scenario_id or demand_kwh_day columns.")
    base_rows = summary[summary["scenario_id"].astype(str) == "base"].copy()
    if base_rows.empty:
        raise ValueError("No base rows found in scenario_summary.csv.")
    base_rows["scenario_id"] = NEW_SCENARIO
    base_rows["demand_kwh_day"] = pd.to_numeric(base_rows["demand_kwh_day"], errors="raise") * SCALING_FACTOR
    if "ev_share_assumption" in base_rows.columns:
        base_rows["ev_share_assumption"] = ARMSTAT_EV_SHARE
    for col in ("expected_ev_passages_per_day", "expected_charging_sessions_per_day"):
        if col in base_rows.columns:
            base_rows[col] = pd.to_numeric(base_rows[col], errors="coerce") * SCALING_FACTOR
    if "description" in base_rows.columns:
        base_rows["description"] = assumptions["description"]
    shutil.copy2(SUMMARY_PATH, SUMMARY_BACKUP_PATH)
    summary = summary[summary["scenario_id"].astype(str) != NEW_SCENARIO]
    summary = pd.concat([summary, base_rows], ignore_index=True)
    summary.to_csv(SUMMARY_PATH, index=False, encoding="utf-8-sig")

    note_lines = [
        "ARMSTAT REGISTERED EV SHARE — ALTERNATIVE DEMAND SENSITIVITY",
        "============================================================",
        f"Registered pure-EV passenger cars: {ARMSTAT_EV_PASSENGER_CARS:,}",
        f"All registered passenger cars: {ARMSTAT_ALL_PASSENGER_CARS:,}",
        f"Reference date: 2025-11-01",
        f"Calculated share: {ARMSTAT_EV_SHARE * 100:.6f}% (reported as {ARMSTAT_EV_SHARE * 100:.2f}%)",
        f"Previous SEI base share: {REFERENCE_SEI_EV_SHARE * 100:.2f}%",
        f"Demand scaling factor: {SCALING_FACTOR:.8f}",
        "Only EV share was changed; base traffic, charging probability, session energy, ADB subsection projection, and distance matrix were retained.",
        "Interpretation: registered fleet composition is a proxy, not an observed EV passage share at M1/M2 counters.",
        "The ADB M2 km13.1-28.9 demand remains forecast-derived/interpolated, not measured AADT in 2026.",
        "All route distances remain same-route chainage screening proxies, not verified driving distances.",
        "Source: Armstat, registered vehicles by fuel type as of 2025-11-01:",
        "https://www.armstat.am/file/article/sv_09_25r_6200.pdf",
    ]
    NOTE_PATH.write_text("\n".join(note_lines) + "\n", encoding="utf-8")

    print(f"      Official ratio: {ARMSTAT_EV_SHARE * 100:.6f}% (rounded 2.92%)")
    print(f"      Scaling factor relative to 2.5%: {SCALING_FACTOR:.8f}")
    print("      Demand points and values:")
    for row in demand.itertuples(index=False):
        print(f"        {row.demand_id}: {row.demand_kwh_day:,.2f} kWh/day")
    print(f"      Total: {demand['demand_kwh_day'].sum():,.2f} kWh/day")

    print("[3/5] Creating a dedicated MILP runner without changing the original runner...")
    patched_runner = runner_text.replace(
        allowed_line,
        'VALID_DEMAND_SCENARIOS = ("low", "base", "high", "armstat_ev_share_2_92")',
    )
    patched_runner = patched_runner.replace(
        loop_line,
        'for demand_scenario in ("low", "base", "high", "armstat_ev_share_2_92"):',
    )
    # Correct stale scope wording in the copied runner only.
    replacements = {
        "Two documented historical ATC demand points only; not full-corridor demand.": (
            "Three demand references: M1 historical ATC, M2 km9.3-13.1 historical ATC, "
            "and ADB forecast-derived M2 km13.1-28.9 subsection at km16; not full-corridor demand."
        ),
        "Only two historic ATC locations are represented as demand points. These results cannot be interpreted as full M1/M2 demand or final Armenia network siting.": (
            "Three demand references are represented: two historical ATC scopes and one ADB forecast-derived M2 subsection. "
            "These results are not full M1/M2 demand or final Armenia network siting."
        ),
        "- Demand points are only the two historic ATC scopes documented in the traffic scenario folders.": (
            "- Demand points represent two historic ATC scopes plus one ADB forecast-derived M2 km13.1-28.9 subsection reference at km16; they do not represent full-corridor demand."
        ),
        "- electricity_opex_atc_scope.csv: annual energy purchase cost bounds for the two ATC demand points only.": (
            "- electricity_opex_atc_scope.csv: annual energy purchase cost bounds for the three represented demand references only."
        ),
        "SCOPED_ATC_DEMAND_ONLY_NOT_FULL_CORRIDOR": "SCOPED_DEMAND_REFERENCES_NOT_FULL_CORRIDOR",
    }
    for old, new in replacements.items():
        patched_runner = patched_runner.replace(old, new)
    NEW_RUNNER_PATH.write_text(patched_runner, encoding="utf-8")

    print("[4/5] Verifying the generated scenario and dedicated runner...")
    check = pd.read_csv(NEW_DIR / "demand_points.csv", encoding="utf-8-sig")
    check_share = pd.to_numeric(check["ev_share_assumption"], errors="coerce")
    if check.empty or check_share.isna().any() or not (check_share.sub(ARMSTAT_EV_SHARE).abs() < 1e-10).all():
        raise RuntimeError("Generated EV-share scenario failed its validation.")
    dist = pd.read_csv(NEW_DIR / "distances.csv", encoding="utf-8-sig")
    site_template = pd.read_csv(SITE_TEMPLATE_PATH, encoding="utf-8-sig")
    expected_sites = int(site_template["site_id"].astype(str).nunique())
    expected_pairs = expected_sites * len(check)
    if len(dist) != expected_pairs or dist["site_id"].astype(str).nunique() != expected_sites:
        raise RuntimeError(
            f"Distance matrix has {len(dist)} rows; expected {expected_pairs} "
            f"({expected_sites} sites x {len(check)} demand points)."
        )
    if not NEW_RUNNER_PATH.is_file():
        raise RuntimeError("Dedicated runner file was not created.")
    verify = NEW_RUNNER_PATH.read_text(encoding="utf-8")
    if NEW_SCENARIO not in verify or "MIP_REL_GAP = 0.001" not in verify or "TIME_LIMIT_SECONDS = 180.0" not in verify:
        # Do not force solver settings: report the copied configuration instead.
        print("      NOTE: copied runner retains its existing MIP gap/time settings.")
    print(f"      Scenario CSV: {len(check)} demand points; distance rows={len(dist)}")

    print("[5/5] Complete")
    print(f"      New scenario folder: {NEW_DIR}")
    print(f"      Dedicated runner: {NEW_RUNNER_PATH}")
    print(f"      Provenance note: {NOTE_PATH}")
    print(f"      scenario_summary backup: {SUMMARY_BACKUP_PATH}")
    print("      Original base scenario and original runner were not overwritten.")
    print("\nNEXT COMMAND:")
    print("  .\\.venv\\Scripts\\python.exe scripts\\run_case_study_armstat_sensitivity.py armstat_ev_share_2_92")


def main() -> int:
    prepare_scenario()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        raise

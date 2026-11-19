#!/usr/bin/env python3
"""Compare legacy chainage-screening MILP runs with directed-network runs.

Run from the repository root:
  .\\.venv\\Scripts\\python.exe scripts\\compare_legacy_and_directed_scenarios.py

Reads, but never modifies, the old and directed scenario output folders.
Writes a combined CSV and Markdown report under the directed scenario root.
"""
from __future__ import annotations

from pathlib import Path
import math
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OLD_ROOT = ROOT / "data" / "derived" / "case_study_screening_milp" / "scenario_runs"
NEW_ROOT = ROOT / "data" / "derived" / "case_study_screening_milp_directed_network" / "scenario_runs"
SCENARIOS = ("low", "base", "high", "armstat_ev_share_2_92")
SUMMARY_NAME = "milp_scenario_summary.csv"

METRICS = {
    "opened_station_count": "stations",
    "charger_count": "chargers",
    "installed_peak_power_kw": "installed_peak_power_kw",
    "total_capital_cost_proxy_usd": "capex_proxy_usd",
    "total_demand_kwh_day": "demand_kwh_day",
    "achieved_mip_rel_gap": "mip_gap",
}


def read_one(root: Path, scenario: str, label: str) -> dict[str, object] | None:
    path = root / scenario / SUMMARY_NAME
    if not path.exists():
        print(f"  NOTE {label}: no summary found for {scenario}: {path}")
        return None
    frame = pd.read_csv(path)
    if frame.empty:
        print(f"  NOTE {label}: summary is empty for {scenario}: {path}")
        return None
    row = frame.iloc[0]
    result: dict[str, object] = {"scenario": scenario, f"{label}_status": row.get("status", "")}
    for source, target in METRICS.items():
        result[f"{label}_{target}"] = pd.to_numeric(pd.Series([row.get(source)]), errors="coerce").iloc[0]
    result[f"{label}_summary_path"] = str(path.relative_to(ROOT))
    return result


def fmt(value: object, digits: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    return f"{number:,.{digits}f}"


def main() -> int:
    if not NEW_ROOT.exists():
        raise FileNotFoundError(f"Directed output folder not found: {NEW_ROOT}")
    rows: list[dict[str, object]] = []
    print("LEGACY vs DIRECTED-NETWORK MILP COMPARISON")
    print("==========================================")
    for scenario in SCENARIOS:
        old = read_one(OLD_ROOT, scenario, "legacy")
        new = read_one(NEW_ROOT, scenario, "directed")
        if old is None and new is None:
            continue
        row: dict[str, object] = {"scenario": scenario}
        if old:
            row.update(old)
        if new:
            row.update(new)
        for metric in METRICS.values():
            old_value = pd.to_numeric(pd.Series([row.get(f"legacy_{metric}")]), errors="coerce").iloc[0]
            new_value = pd.to_numeric(pd.Series([row.get(f"directed_{metric}")]), errors="coerce").iloc[0]
            row[f"delta_{metric}"] = new_value - old_value if pd.notna(old_value) and pd.notna(new_value) else float("nan")
            row[f"pct_delta_{metric}"] = (
                (new_value - old_value) / old_value * 100.0
                if pd.notna(old_value) and pd.notna(new_value) and old_value != 0
                else float("nan")
            )
        rows.append(row)

    if not rows:
        print("ERROR: No scenario summaries were found.")
        return 2

    comparison = pd.DataFrame(rows)
    out_csv = NEW_ROOT / "legacy_vs_directed_scenario_comparison.csv"
    comparison.to_csv(out_csv, index=False, encoding="utf-8-sig")

    display_cols = [
        "scenario",
        "legacy_stations", "directed_stations", "delta_stations",
        "legacy_chargers", "directed_chargers", "delta_chargers",
        "legacy_capex_proxy_usd", "directed_capex_proxy_usd", "delta_capex_proxy_usd",
        "legacy_mip_gap", "directed_mip_gap",
    ]
    available = [c for c in display_cols if c in comparison.columns]
    print("\nMAIN COMPARISON")
    print(comparison[available].to_string(index=False))

    lines = [
        "# Legacy vs directed-network MILP comparison",
        "",
        "The legacy results use the earlier chainage-based distance screening matrix. The directed results use the directed OSM shortest-path matrix with virtual edge nodes.",
        "",
        "| Scenario | Legacy stations | Directed stations | Legacy chargers | Directed chargers | Legacy CAPEX proxy (USD) | Directed CAPEX proxy (USD) | CAPEX change (USD) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {scenario} | {ls} | {ds} | {lc} | {dc} | {lcap} | {dcap} | {delta} |".format(
                scenario=row["scenario"],
                ls=fmt(row.get("legacy_stations"), 0),
                ds=fmt(row.get("directed_stations"), 0),
                lc=fmt(row.get("legacy_chargers"), 0),
                dc=fmt(row.get("directed_chargers"), 0),
                lcap=fmt(row.get("legacy_capex_proxy_usd"), 0),
                dcap=fmt(row.get("directed_capex_proxy_usd"), 0),
                delta=fmt(row.get("delta_capex_proxy_usd"), 0),
            )
        )
    lines += [
        "",
        "## Interpretation notes",
        "",
        "- This is a comparison of screening-model outputs, not evidence that either layout is construction-ready.",
        "- CAPEX proxy uses the same benchmark cost assumptions only if the legacy and directed scenario input assumptions match; inspect each scenario's assumptions before interpreting cost changes.",
        "- Service assignment now uses directed demand-to-site OSM distances. Interstation spacing remains based on route chainage in the present formulation.",
        "- Demand coverage is limited to the three represented demand subsections; unobserved corridor demand is not modeled.",
        "- OSM edge proximity does not confirm legal driveway access, land availability, or utility connection capacity.",
        "- MIP gaps and solver statuses are recorded in the CSV; compare only runs with accepted solver statuses.",
        "",
        f"CSV: `{out_csv.relative_to(ROOT)}`",
    ]
    out_md = NEW_ROOT / "legacy_vs_directed_scenario_comparison.md"
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nCSV saved: {out_csv}")
    print(f"Report saved: {out_md}")
    print("Original scenario outputs were read only; no prior results were changed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise

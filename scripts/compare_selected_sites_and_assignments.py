#!/usr/bin/env python3
"""Compare selected station locations and demand assignments: legacy vs directed MILP.

Run from the repository root:
  .\\.venv\\Scripts\\python.exe scripts\\compare_selected_sites_and_assignments.py

Reads, but never modifies, the legacy and directed scenario outputs. Writes
comparison CSV/Markdown files under the directed scenario_runs folder.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

SCENARIOS = ("low", "base", "high", "armstat_ev_share_2_92")
LEGACY_ROOT = Path("data/derived/case_study_screening_milp/scenario_runs")
DIRECTED_ROOT = Path("data/derived/case_study_screening_milp_directed_network/scenario_runs")
SITE_COLUMNS = {
    "site_id", "route_id", "chainage_km", "latitude", "longitude",
    "chargers", "reserved_power_kw", "assigned_demand_kwh_day",
}
ASSIGNMENT_COLUMNS = {"site_id", "demand_id", "assignment_fraction", "assigned_energy_kwh_day"}


def read_required_csv(path: Path, required: set[str]) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Missing file: {path}")
    frame = pd.read_csv(path, encoding="utf-8-sig")
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{path} is missing columns: {sorted(missing)}")
    if frame.empty:
        raise ValueError(f"{path} has no rows")
    return frame


def normalize_sites(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    out = frame.copy()
    if out["site_id"].isna().any() or out["site_id"].astype(str).str.strip().eq("").any():
        raise ValueError(f"{label}: site_id contains blank values")
    if out["site_id"].duplicated().any():
        dupes = out.loc[out["site_id"].duplicated(), "site_id"].astype(str).tolist()
        raise ValueError(f"{label}: duplicate site_id values: {dupes}")
    for col in ("chainage_km", "latitude", "longitude", "chargers", "reserved_power_kw", "assigned_demand_kwh_day"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
        if out[col].isna().any():
            raise ValueError(f"{label}: {col} contains missing/non-numeric values")
    out["site_id"] = out["site_id"].astype(str).str.strip()
    out["route_id"] = out["route_id"].astype(str).str.strip()
    return out


def normalize_assignments(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    out = frame.copy()
    for col in ("site_id", "demand_id"):
        out[col] = out[col].astype(str).str.strip()
    for col in ("assignment_fraction", "assigned_energy_kwh_day"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
        if out[col].isna().any():
            raise ValueError(f"{label}: {col} contains missing/non-numeric values")
    if out.duplicated(["site_id", "demand_id"]).any():
        raise ValueError(f"{label}: duplicate (site_id, demand_id) assignment rows")
    if "distance_proxy_km" in out.columns:
        out["distance_proxy_km"] = pd.to_numeric(out["distance_proxy_km"], errors="coerce")
    else:
        out["distance_proxy_km"] = float("nan")
    if "directed_driving_distance_km" in out.columns:
        out["reported_driving_distance_km"] = pd.to_numeric(out["directed_driving_distance_km"], errors="coerce")
    else:
        out["reported_driving_distance_km"] = out["distance_proxy_km"]
    return out


def fmt_num(value: Any, digits: int = 2) -> str:
    if pd.isna(value):
        return "—"
    return f"{float(value):,.{digits}f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-root", type=Path, default=LEGACY_ROOT)
    parser.add_argument("--directed-root", type=Path, default=DIRECTED_ROOT)
    args = parser.parse_args()

    site_detail: list[pd.DataFrame] = []
    site_summary: list[dict[str, Any]] = []
    assignment_detail: list[pd.DataFrame] = []
    markdown_sections: list[str] = [
        "# Selected station and demand-assignment comparison",
        "",
        "Legacy = chainage-based screening distances. Directed = directed OSM shortest-path distances with virtual edge nodes.",
        "",
        "The script reads existing result files only; it does not rerun MILP or change either set of outputs.",
        "",
    ]

    for scenario in SCENARIOS:
        legacy_dir = args.legacy_root / scenario
        directed_dir = args.directed_root / scenario
        legacy_sites_path = legacy_dir / "milp_selected_sites.csv"
        directed_sites_path = directed_dir / "milp_selected_sites.csv"
        legacy_assign_path = legacy_dir / "milp_demand_assignments.csv"
        directed_assign_path = directed_dir / "milp_demand_assignments.csv"

        legacy_sites = normalize_sites(read_required_csv(legacy_sites_path, SITE_COLUMNS), f"legacy/{scenario}")
        directed_sites = normalize_sites(read_required_csv(directed_sites_path, SITE_COLUMNS), f"directed/{scenario}")
        legacy_assign = normalize_assignments(read_required_csv(legacy_assign_path, ASSIGNMENT_COLUMNS), f"legacy assignments/{scenario}")
        directed_assign = normalize_assignments(read_required_csv(directed_assign_path, ASSIGNMENT_COLUMNS), f"directed assignments/{scenario}")

        l = legacy_sites.set_index("site_id", drop=False)
        d = directed_sites.set_index("site_id", drop=False)
        all_ids = sorted(set(l.index) | set(d.index))
        scenario_rows: list[dict[str, Any]] = []
        for site_id in all_ids:
            in_l = site_id in l.index
            in_d = site_id in d.index
            old = l.loc[site_id] if in_l else None
            new = d.loc[site_id] if in_d else None
            status = "retained" if in_l and in_d else ("legacy_only" if in_l else "directed_only")
            row = {
                "scenario": scenario,
                "site_id": site_id,
                "selection_status": status,
                "route_id_legacy": old["route_id"] if in_l else "",
                "route_id_directed": new["route_id"] if in_d else "",
                "chainage_km_legacy": old["chainage_km"] if in_l else float("nan"),
                "chainage_km_directed": new["chainage_km"] if in_d else float("nan"),
                "latitude_legacy": old["latitude"] if in_l else float("nan"),
                "longitude_legacy": old["longitude"] if in_l else float("nan"),
                "latitude_directed": new["latitude"] if in_d else float("nan"),
                "longitude_directed": new["longitude"] if in_d else float("nan"),
                "chargers_legacy": old["chargers"] if in_l else 0,
                "chargers_directed": new["chargers"] if in_d else 0,
                "delta_chargers_directed_minus_legacy": (new["chargers"] if in_d else 0) - (old["chargers"] if in_l else 0),
                "assigned_demand_legacy_kwh_day": old["assigned_demand_kwh_day"] if in_l else 0.0,
                "assigned_demand_directed_kwh_day": new["assigned_demand_kwh_day"] if in_d else 0.0,
                "delta_assigned_demand_kwh_day": (new["assigned_demand_kwh_day"] if in_d else 0.0) - (old["assigned_demand_kwh_day"] if in_l else 0.0),
                "reserved_power_legacy_kw": old["reserved_power_kw"] if in_l else 0.0,
                "reserved_power_directed_kw": new["reserved_power_kw"] if in_d else 0.0,
            }
            if in_l and in_d:
                # Both should refer to the same candidate site; report any unexpected coordinate drift.
                row["coordinate_difference_m"] = 111_000.0 * (((new["latitude"] - old["latitude"]) ** 2 + ((new["longitude"] - old["longitude"]) * 0.75) ** 2) ** 0.5)
            else:
                row["coordinate_difference_m"] = float("nan")
            scenario_rows.append(row)
        site_detail.append(pd.DataFrame(scenario_rows))

        old_ids, new_ids = set(l.index), set(d.index)
        old_chargers = int(round(legacy_sites["chargers"].sum()))
        new_chargers = int(round(directed_sites["chargers"].sum()))
        site_summary.append({
            "scenario": scenario,
            "legacy_selected_stations": len(old_ids),
            "directed_selected_stations": len(new_ids),
            "retained_sites": len(old_ids & new_ids),
            "legacy_only_sites_removed": len(old_ids - new_ids),
            "directed_only_sites_added": len(new_ids - old_ids),
            "legacy_chargers": old_chargers,
            "directed_chargers": new_chargers,
            "delta_chargers": new_chargers - old_chargers,
            "legacy_assigned_energy_kwh_day": float(legacy_sites["assigned_demand_kwh_day"].sum()),
            "directed_assigned_energy_kwh_day": float(directed_sites["assigned_demand_kwh_day"].sum()),
        })

        la = legacy_assign.set_index(["site_id", "demand_id"])
        da = directed_assign.set_index(["site_id", "demand_id"])
        pairs = sorted(set(la.index) | set(da.index))
        arows = []
        for site_id, demand_id in pairs:
            old_present = (site_id, demand_id) in la.index
            new_present = (site_id, demand_id) in da.index
            old = la.loc[(site_id, demand_id)] if old_present else None
            new = da.loc[(site_id, demand_id)] if new_present else None
            old_fraction = float(old["assignment_fraction"]) if old_present else 0.0
            new_fraction = float(new["assignment_fraction"]) if new_present else 0.0
            old_energy = float(old["assigned_energy_kwh_day"]) if old_present else 0.0
            new_energy = float(new["assigned_energy_kwh_day"]) if new_present else 0.0
            arows.append({
                "scenario": scenario,
                "site_id": site_id,
                "demand_id": demand_id,
                "legacy_assigned": old_present,
                "directed_assigned": new_present,
                "legacy_distance_km": float(old["distance_proxy_km"]) if old_present else float("nan"),
                "directed_distance_km": float(new["reported_driving_distance_km"]) if new_present else float("nan"),
                "legacy_assignment_fraction": old_fraction,
                "directed_assignment_fraction": new_fraction,
                "delta_assignment_fraction": new_fraction - old_fraction,
                "legacy_energy_kwh_day": old_energy,
                "directed_energy_kwh_day": new_energy,
                "delta_energy_kwh_day": new_energy - old_energy,
                "assignment_status": "retained" if old_present and new_present else ("legacy_only" if old_present else "directed_only"),
            })
        assignment_detail.append(pd.DataFrame(arows))

        retained = sorted(old_ids & new_ids)
        removed = sorted(old_ids - new_ids)
        added = sorted(new_ids - old_ids)
        markdown_sections.extend([
            f"## {scenario}",
            "",
            f"- Retained selected sites ({len(retained)}): {', '.join(retained) if retained else 'None'}",
            f"- Legacy-only sites removed ({len(removed)}): {', '.join(removed) if removed else 'None'}",
            f"- Directed-only sites added ({len(added)}): {', '.join(added) if added else 'None'}",
            f"- Chargers: {old_chargers} legacy → {new_chargers} directed",
            "",
            "### Selected-site details",
            "",
            "| Site | Status | Chainage (km) | Legacy chargers | Directed chargers | Legacy demand (kWh/day) | Directed demand (kWh/day) |",
            "|---|---|---:|---:|---:|---:|---:|",
        ])
        for row in scenario_rows:
            chainage = row["chainage_km_directed"] if pd.notna(row["chainage_km_directed"]) else row["chainage_km_legacy"]
            markdown_sections.append(
                f"| {row['site_id']} | {row['selection_status']} | {fmt_num(chainage)} | "
                f"{int(row['chargers_legacy'])} | {int(row['chargers_directed'])} | "
                f"{fmt_num(row['assigned_demand_legacy_kwh_day'])} | {fmt_num(row['assigned_demand_directed_kwh_day'])} |"
            )
        markdown_sections.append("")

    detail_df = pd.concat(site_detail, ignore_index=True)
    summary_df = pd.DataFrame(site_summary)
    assignment_df = pd.concat(assignment_detail, ignore_index=True)

    # Coordinate values should be unchanged because site IDs represent the same candidate points.
    moved = detail_df[detail_df["coordinate_difference_m"].fillna(0) > 1.0]
    if not moved.empty:
        print("WARNING: candidate coordinates differ by more than 1 m for retained site IDs:")
        print(moved[["scenario", "site_id", "coordinate_difference_m"]].to_string(index=False))
    else:
        print("PASS: retained site coordinates match within 1 m.")

    out_dir = args.directed_root
    out_dir.mkdir(parents=True, exist_ok=True)
    detail_path = out_dir / "selected_site_location_comparison.csv"
    summary_path = out_dir / "selected_site_comparison_summary.csv"
    assignment_path = out_dir / "demand_assignment_comparison.csv"
    report_path = out_dir / "selected_site_and_assignment_comparison.md"
    detail_df.to_csv(detail_path, index=False, encoding="utf-8-sig")
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
    assignment_df.to_csv(assignment_path, index=False, encoding="utf-8-sig")

    markdown_sections.extend([
        "## Interpretation and limitations",
        "",
        "- A retained site is selected in both solutions; a legacy-only site is removed in the directed solution; a directed-only site is newly selected.",
        "- Candidate coordinates are copied from the site template; the coordinate comparison checks that the same site ID still means the same candidate point.",
        "- Assignment differences should be interpreted alongside the demand-point scope and the model's 85-km directed demand-to-site service limit.",
        "- Interstation spacing remains chainage-based, not directed road-distance-based.",
        "- The results remain screening-model outputs: three represented demand scopes, OSM-based access approximations, assumed grid capacity and US benchmark CAPEX. They are not construction-ready recommendations.",
        "",
        "## Output files",
        "",
        f"- `{detail_path.as_posix()}`",
        f"- `{summary_path.as_posix()}`",
        f"- `{assignment_path.as_posix()}`",
    ])
    report_path.write_text("\n".join(markdown_sections) + "\n", encoding="utf-8")

    print("\nSELECTED SITE COMPARISON SUMMARY")
    print("================================")
    cols = ["scenario", "legacy_selected_stations", "directed_selected_stations", "retained_sites", "legacy_only_sites_removed", "directed_only_sites_added", "legacy_chargers", "directed_chargers", "delta_chargers"]
    print(summary_df[cols].to_string(index=False))
    print("\nASSIGNMENT COMPARISON")
    print("=====================")
    assign_summary = assignment_df.groupby("scenario", as_index=False).agg(
        legacy_assignment_pairs=("legacy_assigned", "sum"),
        directed_assignment_pairs=("directed_assigned", "sum"),
        retained_assignment_pairs=("assignment_status", lambda x: int((x == "retained").sum())),
        changed_energy_pairs_kwh_day=("delta_energy_kwh_day", lambda x: float(x.abs().sum())),
    )
    print(assign_summary.to_string(index=False))
    print("\nSAVED")
    print(f"  {detail_path}")
    print(f"  {summary_path}")
    print(f"  {assignment_path}")
    print(f"  {report_path}")
    print("\nLegacy and directed source outputs were read only; neither was modified.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        raise

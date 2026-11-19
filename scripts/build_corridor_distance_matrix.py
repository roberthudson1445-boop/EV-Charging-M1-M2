#!/usr/bin/env python3
"""Build a screening distance matrix and corridor adjacency data.

Run from the project root:
  .\\.venv\\Scripts\\python.exe scripts\\build_corridor_distance_matrix.py

Inputs (created by prepare_corridor_candidate_data.py):
  data/derived/corridor_candidate_sites.csv
  data/derived/corridor_demand_location_candidates.csv

Outputs (data/derived):
  corridor_site_demand_distances_screening.csv
  corridor_candidate_site_adjacency.csv
  corridor_demand_coverage_screening.csv
  corridor_distance_matrix_README.txt

IMPORTANT:
The distances are corridor-chainage screening proxies, not verified driving
network paths from real demand centroids to buildable sites. Demand rows are
waypoint location references; their demand_kwh_day values remain blank.
This script intentionally does not modify data/templates or claim that the
screening data are ready for a real MILP run.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DERIVED = ROOT / "data" / "derived"
SITES_FILE = DERIVED / "corridor_candidate_sites.csv"
DEMAND_FILE = DERIVED / "corridor_demand_location_candidates.csv"


def read_required(path: Path, required: set[str]) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Run scripts/prepare_corridor_candidate_data.py first."
        )
    df = pd.read_csv(path, encoding="utf-8-sig")
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} lacks required columns: {sorted(missing)}")
    if df.empty:
        raise ValueError(f"{path.name} contains no rows.")
    return df


def numeric_column(df: pd.DataFrame, column: str, filename: str) -> pd.Series:
    result = pd.to_numeric(df[column], errors="coerce")
    bad = result.isna() | ~np.isfinite(result.to_numpy(dtype=float))
    if bad.any():
        examples = df.loc[bad, [column]].head(5).to_dict("records")
        raise ValueError(f"Invalid {column} values in {filename}: {examples}")
    return result.astype(float)


def clean_route(value: Any) -> str:
    route = str(value).strip().upper()
    if route not in {"M1", "M2"}:
        raise ValueError(f"Unexpected route_id {value!r}; expected M1 or M2.")
    return route


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-service-distance-km", type=float, default=85.0,
        help="Provisional screening radius from the diploma proposal (default: 85 km)."
    )
    parser.add_argument(
        "--output", type=Path, default=DERIVED,
        help="Output directory (default: data/derived)."
    )
    args = parser.parse_args()
    if not math.isfinite(args.max_service_distance_km) or args.max_service_distance_km <= 0:
        parser.error("--max-service-distance-km must be a positive finite value")

    out = args.output
    out.mkdir(parents=True, exist_ok=True)

    print("[1/5] Loading candidate sites and waypoint demand references...")
    sites = read_required(
        SITES_FILE,
        {"site_id", "route_id", "chainage_km", "latitude", "longitude"},
    )
    demand = read_required(
        DEMAND_FILE,
        {"demand_id", "route_id", "chainage_km", "route_projection_offset_m", "demand_kwh_day"},
    )
    sites["route_id"] = sites["route_id"].map(clean_route)
    demand["route_id"] = demand["route_id"].map(clean_route)
    sites["chainage_km"] = numeric_column(sites, "chainage_km", SITES_FILE.name)
    demand["chainage_km"] = numeric_column(demand, "chainage_km", DEMAND_FILE.name)
    demand["route_projection_offset_m"] = numeric_column(
        demand, "route_projection_offset_m", DEMAND_FILE.name
    )
    if (demand["route_projection_offset_m"] < 0).any():
        raise ValueError("Demand projection offsets cannot be negative.")
    if sites["site_id"].duplicated().any():
        dupes = sites.loc[sites.site_id.duplicated(), "site_id"].tolist()
        raise ValueError(f"Duplicate site_id values: {dupes[:10]}")
    if demand["demand_id"].duplicated().any():
        dupes = demand.loc[demand.demand_id.duplicated(), "demand_id"].tolist()
        raise ValueError(f"Duplicate demand_id values: {dupes[:10]}")

    print("[2/5] Computing same-corridor chainage distance proxies...")
    distance_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    route_lengths: dict[str, float] = {}
    for route_id in ("M1", "M2"):
        route_sites = sites.loc[sites.route_id == route_id].sort_values("chainage_km")
        route_demands = demand.loc[demand.route_id == route_id].sort_values("chainage_km")
        if route_sites.empty or route_demands.empty:
            raise ValueError(
                f"Missing candidate sites or demand references for {route_id}: "
                f"sites={len(route_sites)}, demand={len(route_demands)}"
            )
        if route_sites["chainage_km"].duplicated().any():
            raise ValueError(f"Duplicate site chainages detected on {route_id}.")
        route_lengths[route_id] = float(route_sites.chainage_km.max())
        for d in route_demands.itertuples(index=False):
            offset_km = float(d.route_projection_offset_m) / 1000.0
            values: list[tuple[str, float, float]] = []
            for s in route_sites.itertuples(index=False):
                along_km = abs(float(s.chainage_km) - float(d.chainage_km))
                proxy_km = along_km + offset_km
                values.append((str(s.site_id), along_km, proxy_km))
                distance_rows.append({
                    "route_id": route_id,
                    "site_id": str(s.site_id),
                    "demand_id": str(d.demand_id),
                    "distance_km": round(proxy_km, 6),
                    "along_corridor_chainage_km": round(along_km, 6),
                    "demand_projection_offset_km": round(offset_km, 6),
                    "distance_basis": "ABS_CHAINAGE_DIFFERENCE_PLUS_STRAIGHT_LINE_PROJECTION_OFFSET",
                    "distance_status": "SCREENING_PROXY_NOT_VERIFIED_DRIVING_DISTANCE",
                    "notes": "Demand point is a corridor waypoint reference, not a measured EV demand centroid.",
                })
            nearest_site, nearest_along, nearest_proxy = min(values, key=lambda x: x[2])
            eligible = [v for v in values if v[2] <= args.max_service_distance_km + 1e-9]
            demand_energy = getattr(d, "demand_kwh_day", np.nan)
            energy_is_missing = pd.isna(demand_energy)
            coverage_rows.append({
                "route_id": route_id,
                "demand_id": str(d.demand_id),
                "demand_name": str(getattr(d, "demand_name", "")),
                "chainage_km": round(float(d.chainage_km), 6),
                "demand_projection_offset_m": round(float(d.route_projection_offset_m), 2),
                "nearest_candidate_site_id": nearest_site,
                "nearest_along_corridor_km": round(nearest_along, 6),
                "nearest_distance_proxy_km": round(nearest_proxy, 6),
                "candidate_sites_within_threshold": len(eligible),
                "screened_within_threshold": bool(eligible),
                "screening_threshold_km": args.max_service_distance_km,
                "demand_kwh_day_missing": bool(energy_is_missing),
                "coverage_status": "LOCATION_SCREENING_ONLY_NO_VALIDATED_DEMAND_VALUE",
            })

    distances_df = pd.DataFrame(distance_rows)
    coverage_df = pd.DataFrame(coverage_rows)
    distances_path = out / "corridor_site_demand_distances_screening.csv"
    coverage_path = out / "corridor_demand_coverage_screening.csv"
    distances_df.to_csv(distances_path, index=False, encoding="utf-8-sig")
    coverage_df.to_csv(coverage_path, index=False, encoding="utf-8-sig")

    print("[3/5] Building consecutive candidate-site spacing table...")
    adjacency_rows: list[dict[str, Any]] = []
    for route_id in ("M1", "M2"):
        route_sites = sites.loc[sites.route_id == route_id].sort_values("chainage_km")
        records = list(route_sites.itertuples(index=False))
        for index, (left, right) in enumerate(zip(records, records[1:]), start=1):
            gap = float(right.chainage_km) - float(left.chainage_km)
            adjacency_rows.append({
                "route_id": route_id,
                "sequence_order": index,
                "upstream_site_id": str(left.site_id),
                "downstream_site_id": str(right.site_id),
                "upstream_chainage_km": round(float(left.chainage_km), 6),
                "downstream_chainage_km": round(float(right.chainage_km), 6),
                "candidate_spacing_km": round(gap, 6),
                "status": "CANDIDATE_GRID_SPACING_NOT_SELECTED_STATION_GAP",
            })
    adjacency_df = pd.DataFrame(adjacency_rows)
    adjacency_path = out / "corridor_candidate_site_adjacency.csv"
    adjacency_df.to_csv(adjacency_path, index=False, encoding="utf-8-sig")

    print("[4/5] Checking screening coverage and data limitations...")
    total_covered = int(coverage_df.screened_within_threshold.sum())
    total_demands = len(coverage_df)
    missing_energy = int(coverage_df.demand_kwh_day_missing.sum())
    max_gap = adjacency_df.groupby("route_id").candidate_spacing_km.max().to_dict()
    report = [
        "CORRIDOR DISTANCE MATRIX — SCREENING OUTPUT",
        "============================================",
        "",
        f"Candidate sites: {len(sites)}",
        f"Waypoint demand-location references: {len(demand)}",
        f"Site-to-reference rows: {len(distances_df)}",
        f"Provisional service-distance threshold used for screening: {args.max_service_distance_km:.2f} km",
        f"References with >=1 candidate inside threshold: {total_covered}/{total_demands}",
        f"References with missing demand_kwh_day: {missing_energy}/{total_demands}",
        f"Maximum spacing between adjacent candidate grid points: M1={max_gap.get('M1', float('nan')):.3f} km; M2={max_gap.get('M2', float('nan')):.3f} km",
        "",
        "INTERPRETATION AND LIMITATIONS",
        "1. distance_km is an along-corridor chainage proxy plus the demand point's straight-line offset to the corridor geometry.",
        "2. It is NOT a driving-network shortest path from a real settlement centroid or customer catchment to a buildable charging site.",
        "3. Demand rows are official-waypoint location references; they are not validated demand centroids and have no demand energy values.",
        "4. The 85 km default is a provisional screening threshold from the diploma proposal, not a validated engineering service-distance standard.",
        "5. Candidate adjacency reports spacing in the candidate grid only. It does not represent selected-station gaps and must not be imposed as such in the MILP.",
        "6. Costs, charger limits, grid capacity, site access, land feasibility, and demand energy remain unverified.",
        "7. Outputs are kept in data/derived and do not overwrite data/templates.",
        "",
        "NEXT MODELING REQUIREMENTS",
        "- Geocode and verify real demand centroids or define justified traffic-based demand zones.",
        "- Route each real demand centroid to each feasible site over the directed road network.",
        "- Obtain current traffic data and documented EV share / charging probability / session-energy assumptions.",
        "- Validate site feasibility, land/civil cost, grid connection and station power limits.",
        "- Add a separate max_interstation_distance_km parameter only after its value is justified; do not conflate it with max_service_distance_km.",
    ]
    readme_path = out / "corridor_distance_matrix_README.txt"
    readme_path.write_text("\n".join(report) + "\n", encoding="utf-8")

    print("[5/5] Saved outputs:")
    for p in (distances_path, adjacency_path, coverage_path, readme_path):
        print(f"      {p}")
    print("\nSUMMARY")
    print(f"  Distance matrix rows: {len(distances_df)}")
    print(f"  Candidate adjacency rows: {len(adjacency_df)}")
    print(f"  Location references screened: {total_covered}/{total_demands} within {args.max_service_distance_km:g} km")
    print(f"  Missing demand energy values: {missing_energy}/{total_demands}")
    print("  NOTE: distances are screening proxies, not validated driving distances.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}")
        raise

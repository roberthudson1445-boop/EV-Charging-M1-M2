"""Solve spacing-only corridor station layouts as a binary MILP.

This is a deliberately separate, geometry-only experiment. It minimizes the
number of selected INTERIOR candidate station sites on each corridor while
requiring every route segment between the route boundaries and consecutive
selected stations to be no longer than a scenario threshold.

It does NOT optimize demand assignment, costs, charger numbers, grid capacity,
land access, or station feasibility. It must not be interpreted as the final
EV charging investment plan.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

DEFAULT_GAPS_KM = (50.0, 60.0, 70.0, 80.0, 85.0, 90.0, 100.0, 120.0)
REQUIRED_COLUMNS = {"site_id", "route_id", "chainage_km"}
EPS = 1e-8


def solve_route_spacing_milp(
    route_sites: pd.DataFrame,
    route_id: str,
    route_length_km: float,
    max_gap_km: float,
) -> dict[str, Any]:
    """Minimize open interior candidate sites subject to maximum-gap rules."""
    if not np.isfinite(route_length_km) or route_length_km <= 0:
        raise ValueError(f"{route_id}: route length must be positive and finite.")
    if not np.isfinite(max_gap_km) or max_gap_km <= 0:
        raise ValueError("max_gap_km must be positive and finite.")

    ordered = route_sites.sort_values(["chainage_km", "site_id"]).reset_index(drop=True)
    positions_all = ordered["chainage_km"].to_numpy(dtype=float)
    if len(positions_all) < 2:
        raise ValueError(f"{route_id}: at least start and end candidate points are required.")
    if abs(positions_all[0]) > 1e-5:
        raise ValueError(f"{route_id}: candidate sites must include chainage 0 as route start.")
    if abs(positions_all[-1] - route_length_km) > 1e-4:
        raise ValueError(
            f"{route_id}: maximum candidate chainage {positions_all[-1]:.6f} km "
            f"does not match route length {route_length_km:.6f} km."
        )
    if np.any(np.diff(positions_all) <= EPS):
        raise ValueError(f"{route_id}: candidate chainages must be strictly increasing and unique.")

    # Route start/end are boundaries, not station candidates. This matches the
    # previously generated spacing-only dynamic-programming interpretation.
    interior = ordered[
        (ordered["chainage_km"] > EPS)
        & (ordered["chainage_km"] < route_length_km - EPS)
    ].reset_index(drop=True)
    n = len(interior)
    pos = interior["chainage_km"].to_numpy(dtype=float)

    # If a route itself is no longer than the permitted gap, no interior
    # station is required by the spacing-only condition.
    if route_length_km <= max_gap_km + EPS:
        selected = interior.iloc[0:0].copy()
        return _make_route_result(
            route_id, route_length_km, max_gap_km, ordered, interior, selected,
            solver_message="No interior station required: route length <= maximum gap.",
            solver_status=0,
        )

    # With a route longer than the gap, there must be at least one site within
    # D of the start and at least one within D of the end.
    start_candidates = np.flatnonzero(pos <= max_gap_km + EPS).tolist()
    end_candidates = np.flatnonzero((route_length_km - pos) <= max_gap_km + EPS).tolist()
    if not start_candidates or not end_candidates:
        return {
            "route_id": route_id,
            "max_interstation_distance_km": max_gap_km,
            "route_length_km": route_length_km,
            "candidate_sites_total": len(ordered),
            "interior_candidates": n,
            "spacing_only_feasible": False,
            "selected_station_count": pd.NA,
            "selected_site_ids": "",
            "selected_chainages_km": "",
            "max_segment_km": pd.NA,
            "start_gap_km": pd.NA,
            "end_gap_km": pd.NA,
            "solver_status": "infeasible_boundary_coverage",
            "solver_message": "No candidate within the maximum gap of a route boundary.",
        }

    # Binary variables y_i indicate which interior candidate sites are opened.
    # Objective: minimize sum(y_i).
    objective = np.ones(n, dtype=float)
    integrality = np.ones(n, dtype=np.int32)
    bounds = Bounds(np.zeros(n), np.ones(n))

    rows: list[dict[int, float]] = []
    lower: list[float] = []
    upper: list[float] = []

    # Boundary coverage constraints: at least one selected site within D from
    # each endpoint. A single site may satisfy both when the intervals overlap.
    rows.append({i: 1.0 for i in start_candidates})
    lower.append(1.0)
    upper.append(np.inf)
    rows.append({i: 1.0 for i in end_candidates})
    lower.append(1.0)
    upper.append(np.inf)

    # For every pair too far apart to be consecutive, if both are open then at
    # least one candidate between them must also be open:
    # y_i + y_j - sum(y_k, i<k<j) <= 1.
    # This is an exact no-large-gap condition on the sorted discrete sites.
    for i in range(n):
        for j in range(i + 1, n):
            if pos[j] - pos[i] > max_gap_km + EPS:
                row = {i: 1.0, j: 1.0}
                for k in range(i + 1, j):
                    row[k] = -1.0
                rows.append(row)
                lower.append(-np.inf)
                upper.append(1.0)

    rr: list[int] = []
    cc: list[int] = []
    vv: list[float] = []
    for r, entries in enumerate(rows):
        for c, value in entries.items():
            if value != 0.0:
                rr.append(r)
                cc.append(c)
                vv.append(value)
    matrix = coo_matrix((vv, (rr, cc)), shape=(len(rows), n)).tocsr()

    result = milp(
        c=objective,
        integrality=integrality,
        bounds=bounds,
        constraints=LinearConstraint(matrix, np.asarray(lower), np.asarray(upper)),
        options={"disp": False},
    )
    if result.x is None or result.status != 0:
        return {
            "route_id": route_id,
            "max_interstation_distance_km": max_gap_km,
            "route_length_km": route_length_km,
            "candidate_sites_total": len(ordered),
            "interior_candidates": n,
            "spacing_only_feasible": False,
            "selected_station_count": pd.NA,
            "selected_site_ids": "",
            "selected_chainages_km": "",
            "max_segment_km": pd.NA,
            "start_gap_km": pd.NA,
            "end_gap_km": pd.NA,
            "solver_status": str(result.status),
            "solver_message": str(result.message),
        }

    chosen = np.flatnonzero(np.asarray(result.x) >= 0.5)
    selected = interior.iloc[chosen].copy()
    return _make_route_result(
        route_id,
        route_length_km,
        max_gap_km,
        ordered,
        interior,
        selected,
        solver_message=str(result.message),
        solver_status=int(result.status),
    )


def _make_route_result(
    route_id: str,
    route_length_km: float,
    max_gap_km: float,
    ordered: pd.DataFrame,
    interior: pd.DataFrame,
    selected: pd.DataFrame,
    *,
    solver_message: str,
    solver_status: int | str,
) -> dict[str, Any]:
    positions = selected["chainage_km"].to_numpy(dtype=float)
    full_chainages = np.concatenate(([0.0], positions, [route_length_km]))
    segment_gaps = np.diff(full_chainages)
    max_segment = float(np.max(segment_gaps)) if len(segment_gaps) else 0.0
    feasible = bool(max_segment <= max_gap_km + 1e-6)
    return {
        "route_id": route_id,
        "max_interstation_distance_km": max_gap_km,
        "route_length_km": route_length_km,
        "candidate_sites_total": len(ordered),
        "interior_candidates": len(interior),
        "spacing_only_feasible": feasible,
        "selected_station_count": len(selected),
        "selected_site_ids": ";".join(selected["site_id"].astype(str).tolist()),
        "selected_chainages_km": ";".join(f"{x:.6f}" for x in positions),
        "max_segment_km": max_segment,
        "start_gap_km": float(segment_gaps[0]),
        "end_gap_km": float(segment_gaps[-1]),
        "solver_status": solver_status,
        "solver_message": solver_message,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        default="data/derived/milp_corridor_sites_template.csv",
        help="Route-aware candidate-site template CSV.",
    )
    parser.add_argument(
        "--route-lengths",
        default="data/derived/milp_corridor_route_lengths.json",
        help="JSON route lengths created by prepare_milp_corridor_inputs.py.",
    )
    parser.add_argument(
        "--output-dir", default="data/derived", help="Output directory."
    )
    parser.add_argument(
        "--gaps", nargs="+", type=float, default=list(DEFAULT_GAPS_KM),
        help="Maximum station-to-station/boundary gap scenarios in kilometres.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    lengths_path = Path(args.route_lengths)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("[1/5] Loading candidate sites and route lengths...")
    if not input_path.exists():
        raise FileNotFoundError(f"Candidate-site input not found: {input_path}")
    if not lengths_path.exists():
        raise FileNotFoundError(f"Route-length JSON not found: {lengths_path}")
    sites = pd.read_csv(input_path)
    missing = REQUIRED_COLUMNS - set(sites.columns)
    if missing:
        raise ValueError(f"Input CSV is missing columns: {sorted(missing)}")
    if sites.empty:
        raise ValueError("Candidate-site input contains no rows.")
    if sites["site_id"].isna().any() or sites["site_id"].duplicated().any():
        raise ValueError("site_id values must be present and globally unique.")
    sites["route_id"] = sites["route_id"].astype(str).str.strip()
    sites["site_id"] = sites["site_id"].astype(str).str.strip()
    sites["chainage_km"] = pd.to_numeric(sites["chainage_km"], errors="coerce")
    if sites["chainage_km"].isna().any() or not np.isfinite(sites["chainage_km"]).all():
        raise ValueError("chainage_km must contain finite numeric values.")
    if (sites["chainage_km"] < 0).any():
        raise ValueError("chainage_km values must be non-negative.")

    # Read the documented {"route_lengths_km": {...}} layout explicitly.
    import json
    payload = json.loads(lengths_path.read_text(encoding="utf-8"))
    route_lengths = payload.get("route_lengths_km")
    if not isinstance(route_lengths, dict) or not route_lengths:
        raise ValueError("route-length JSON must contain a non-empty 'route_lengths_km' object.")

    routes_in_sites = set(sites["route_id"].unique())
    if routes_in_sites != set(route_lengths):
        raise ValueError(
            "Route IDs in CSV and JSON do not match: "
            f"CSV={sorted(routes_in_sites)}, JSON={sorted(route_lengths)}"
        )

    gaps = sorted(set(float(g) for g in args.gaps))
    if not gaps or any(not np.isfinite(g) or g <= 0 for g in gaps):
        raise ValueError("All gap thresholds must be finite and positive.")
    print(f"      {len(sites)} candidate sites | routes={', '.join(sorted(routes_in_sites))}")

    print("[2/5] Solving binary spacing MILP for each route and threshold...")
    solution_rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []
    for route_id in sorted(route_lengths):
        route_sites = sites[sites["route_id"] == route_id].copy()
        route_length = float(route_lengths[route_id])
        for gap in gaps:
            result = solve_route_spacing_milp(route_sites, route_id, route_length, gap)
            solution_rows.append(result)
            if result["spacing_only_feasible"] and result["selected_station_count"]:
                selected_ids = result["selected_site_ids"].split(";")
                selected_positions = [float(x) for x in result["selected_chainages_km"].split(";")]
                for order, (site_id, chainage) in enumerate(zip(selected_ids, selected_positions), start=1):
                    match = route_sites.loc[route_sites["site_id"] == site_id].iloc[0]
                    detail_rows.append({
                        "route_id": route_id,
                        "max_interstation_distance_km": gap,
                        "selection_order": order,
                        "site_id": site_id,
                        "chainage_km": chainage,
                        "latitude": match.get("latitude", np.nan),
                        "longitude": match.get("longitude", np.nan),
                    })

    solutions = pd.DataFrame(solution_rows)
    details = pd.DataFrame(detail_rows, columns=[
        "route_id", "max_interstation_distance_km", "selection_order",
        "site_id", "chainage_km", "latitude", "longitude",
    ])

    print("[3/5] Comparing with previous dynamic-programming sensitivity counts...")
    dp_path = output_dir / "interstation_gap_sensitivity.csv"
    if dp_path.exists():
        dp = pd.read_csv(dp_path)
        if {"route_id", "max_interstation_distance_km", "minimum_selected_sites_for_spacing_only"}.issubset(dp.columns):
            dp = dp[["route_id", "max_interstation_distance_km", "minimum_selected_sites_for_spacing_only"]].rename(
                columns={"minimum_selected_sites_for_spacing_only": "dynamic_programming_count"}
            )
            solutions = solutions.merge(dp, on=["route_id", "max_interstation_distance_km"], how="left")
            solutions["counts_match_previous_dp"] = (
                solutions["selected_station_count"].astype("Float64")
                == pd.to_numeric(solutions["dynamic_programming_count"], errors="coerce").astype("Float64")
            )
        else:
            solutions["dynamic_programming_count"] = pd.NA
            solutions["counts_match_previous_dp"] = pd.NA
    else:
        solutions["dynamic_programming_count"] = pd.NA
        solutions["counts_match_previous_dp"] = pd.NA

    print("[4/5] Saving MILP results and selected-site details...")
    solutions_path = output_dir / "corridor_spacing_milp_solutions.csv"
    details_path = output_dir / "corridor_spacing_milp_selected_sites.csv"
    solutions.to_csv(solutions_path, index=False)
    details.to_csv(details_path, index=False)

    lines = [
        "CORRIDOR SPACING-ONLY BINARY MILP",
        "==================================",
        f"Input sites: {input_path}",
        f"Route lengths: {lengths_path}",
        "Objective: minimize number of selected interior candidate stations.",
        "Constraints: route start to first station, consecutive stations, and last station to route end all <= D.",
        "Route start and end are boundaries, not selectable stations.",
        "The model excludes demand, service coverage, charger count, investment cost, land, and grid constraints.",
        "Therefore, results are geometric spacing lower bounds, not the full EV charging MILP solution.",
        "",
        "Results:",
    ]
    for row in solutions.itertuples(index=False):
        count = getattr(row, "selected_station_count")
        lines.append(
            f"  {row.route_id} | D={row.max_interstation_distance_km:g} km | "
            f"feasible={row.spacing_only_feasible} | selected={count} | "
            f"max segment={row.max_segment_km} km | DP match={getattr(row, 'counts_match_previous_dp')}"
        )
    readme_path = output_dir / "corridor_spacing_milp_README.txt"
    readme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("[5/5] Summary")
    for gap in gaps:
        subset = solutions[solutions["max_interstation_distance_km"] == gap]
        counts = subset["selected_station_count"].tolist()
        total = int(sum(int(x) for x in counts if pd.notna(x))) if subset["spacing_only_feasible"].all() else "INFEASIBLE"
        match = bool(subset["counts_match_previous_dp"].fillna(False).all()) if "counts_match_previous_dp" in subset else False
        print(f"      D={gap:>5g} km | per-route={counts} | total={total} | matches previous DP={match}")

    print("\nSaved:")
    for path in (solutions_path, details_path, readme_path):
        print(f"      {path}")
    print("\nIMPORTANT: these are spacing-only MILP results, not investment-plan results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

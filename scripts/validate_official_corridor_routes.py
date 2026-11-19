#!/usr/bin/env python3
"""Validate the OSM-derived M1/M2 corridor route outputs.

Run from the project root:
  .\\.venv\\Scripts\\python.exe scripts\\validate_official_corridor_routes.py

Reads:
  results/official_corridor_route_edges.csv
  results/official_corridor_leg_report.csv
  results/official_corridor_waypoint_anchors.csv

Writes:
  results/official_corridor_validation.txt
  results/official_corridor_leg_review.csv

This is a diagnostic only. It does not alter the route or claim that OSM data
is an authoritative survey of the official highway alignment.
"""
from __future__ import annotations

from pathlib import Path
import math
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
EDGES_FILE = RESULTS / "official_corridor_route_edges.csv"
LEGS_FILE = RESULTS / "official_corridor_leg_report.csv"
ANCHORS_FILE = RESULTS / "official_corridor_waypoint_anchors.csv"


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Required route output is missing: {path}")
    return pd.read_csv(path, encoding="utf-8-sig")


def main() -> int:
    edges = read_csv(EDGES_FILE)
    legs = read_csv(LEGS_FILE)
    anchors = read_csv(ANCHORS_FILE)

    edge_required = {
        "route_id", "leg_order", "edge_order_in_leg", "from_node", "to_node",
        "edge_class", "length_m", "chainage_start_km", "chainage_end_km",
    }
    leg_required = {
        "route_id", "leg_order", "from_waypoint", "to_waypoint", "status",
        "route_distance_km", "tagged_share", "detour_ratio",
    }
    anchor_required = {"route_id", "sequence_order", "waypoint_name", "network_snap_distance_m"}
    for label, frame, required in (
        ("edge", edges, edge_required), ("leg", legs, leg_required),
        ("anchor", anchors, anchor_required),
    ):
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"{label} file is missing columns: {sorted(missing)}")

    lines: list[str] = []
    review_rows: list[dict] = []
    errors: list[str] = []
    warnings: list[str] = []
    lines.append("OFFICIAL CORRIDOR ROUTE VALIDATION")
    lines.append("Diagnostic checks only; OSM-derived routes require map/official-alignment review.")
    lines.append("")

    for route_id in ("M1", "M2"):
        route_edges = edges.loc[edges.route_id.astype(str).str.upper() == route_id].copy()
        route_legs = legs.loc[legs.route_id.astype(str).str.upper() == route_id].copy()
        route_anchors = anchors.loc[anchors.route_id.astype(str).str.upper() == route_id].copy()
        if route_edges.empty:
            errors.append(f"{route_id}: no route edges found")
            continue

        route_edges["chainage_start_km"] = pd.to_numeric(route_edges.chainage_start_km, errors="coerce")
        route_edges["chainage_end_km"] = pd.to_numeric(route_edges.chainage_end_km, errors="coerce")
        route_edges["length_m"] = pd.to_numeric(route_edges.length_m, errors="coerce")
        route_edges = route_edges.sort_values(["chainage_start_km", "chainage_end_km"]).reset_index(drop=True)

        total_km = float(route_edges.length_m.sum() / 1000.0)
        tagged_km = float(route_edges.loc[route_edges.edge_class == f"tagged_{route_id}", "length_m"].sum() / 1000.0)
        other_m_km = float(route_edges.loc[route_edges.edge_class == "other_M_route", "length_m"].sum() / 1000.0)
        connector_km = float(route_edges.loc[route_edges.edge_class == "untagged_connector", "length_m"].sum() / 1000.0)
        tagged_share = tagged_km / total_km if total_km else 0.0

        chainage_gaps = []
        node_breaks = []
        bad_lengths = []
        for i, row in route_edges.iterrows():
            if not (math.isfinite(row.chainage_start_km) and math.isfinite(row.chainage_end_km) and math.isfinite(row.length_m)):
                bad_lengths.append(int(i))
                continue
            measured_km = row.length_m / 1000.0
            chainage_km = row.chainage_end_km - row.chainage_start_km
            if abs(measured_km - chainage_km) > 0.002:
                bad_lengths.append(int(i))
            if i > 0:
                prev = route_edges.iloc[i - 1]
                gap = row.chainage_start_km - prev.chainage_end_km
                if abs(gap) > 1e-6:
                    chainage_gaps.append((i, float(gap)))
                if str(prev.to_node) != str(row.from_node):
                    node_breaks.append((i, str(prev.to_node), str(row.from_node)))

        snap_max = float(pd.to_numeric(route_anchors.network_snap_distance_m, errors="coerce").max()) if not route_anchors.empty else float("nan")
        snap_far = route_anchors.loc[pd.to_numeric(route_anchors.network_snap_distance_m, errors="coerce") > 1000, ["waypoint_name", "network_snap_distance_m"]]

        lines.append(f"{route_id}: {total_km:.3f} km | tagged {tagged_share:.2%} | connectors {connector_km:.3f} km | other M roads {other_m_km:.3f} km")
        lines.append(f"  edges={len(route_edges)}, legs={len(route_legs)}, anchors={len(route_anchors)}, max anchor snap={snap_max:.1f} m")
        lines.append(f"  chainage discontinuities={len(chainage_gaps)}, node discontinuities={len(node_breaks)}, edge length inconsistencies={len(bad_lengths)}")

        if chainage_gaps:
            errors.append(f"{route_id}: {len(chainage_gaps)} chainage discontinuities")
        if node_breaks:
            errors.append(f"{route_id}: {len(node_breaks)} graph node discontinuities")
        if bad_lengths:
            errors.append(f"{route_id}: {len(bad_lengths)} edge length/chainage inconsistencies")
        if not snap_far.empty:
            warnings.append(f"{route_id}: {len(snap_far)} waypoint anchor(s) are more than 1 km from a tagged-route node")
            lines.append("  anchors > 1 km from tagged-route node:")
            for r in snap_far.itertuples(index=False):
                lines.append(f"    {r.waypoint_name}: {float(r.network_snap_distance_m):.1f} m")

        for row in route_legs.itertuples(index=False):
            detour = float(row.detour_ratio) if pd.notna(row.detour_ratio) else float("nan")
            share = float(row.tagged_share) if pd.notna(row.tagged_share) else float("nan")
            flags = []
            if math.isfinite(detour) and detour > 1.5:
                flags.append("detour_ratio>1.5")
            if math.isfinite(share) and share < 0.90:
                flags.append("tagged_share<90%")
            if str(row.status) != "OK":
                flags.append(f"route_status={row.status}")
            review_rows.append({
                "route_id": route_id,
                "leg_order": int(row.leg_order),
                "from_waypoint": row.from_waypoint,
                "to_waypoint": row.to_waypoint,
                "status": row.status,
                "route_distance_km": row.route_distance_km,
                "tagged_share": share,
                "detour_ratio": detour,
                "review_flags": "; ".join(flags),
            })

        high_detours = route_legs.loc[pd.to_numeric(route_legs.detour_ratio, errors="coerce") > 1.5]
        low_tagged = route_legs.loc[pd.to_numeric(route_legs.tagged_share, errors="coerce") < 0.90]
        if not high_detours.empty:
            warnings.append(f"{route_id}: {len(high_detours)} leg(s) have detour ratio > 1.5")
        if not low_tagged.empty:
            warnings.append(f"{route_id}: {len(low_tagged)} leg(s) have tagged-road share < 90%")
        lines.append("")

    review = pd.DataFrame(review_rows)
    review.to_csv(RESULTS / "official_corridor_leg_review.csv", index=False, encoding="utf-8-sig")

    lines.append("ERRORS")
    lines.extend([f"- {x}" for x in errors] or ["- None detected by structural checks"])
    lines.append("")
    lines.append("WARNINGS / MANUAL REVIEW")
    lines.extend([f"- {x}" for x in warnings] or ["- None"])
    lines.append("")
    lines.append("Legs flagged for review (detour > 1.5, tagged share < 90%, or non-OK status):")
    flagged = review.loc[review.review_flags.astype(str) != ""]
    if flagged.empty:
        lines.append("- None")
    else:
        for r in flagged.itertuples(index=False):
            lines.append(
                f"- {r.route_id} {r.from_waypoint} -> {r.to_waypoint}: "
                f"{float(r.route_distance_km):.2f} km, detour={float(r.detour_ratio):.2f}, "
                f"tagged={float(r.tagged_share):.1%} [{r.review_flags}]"
            )

    report = "\n".join(lines)
    (RESULTS / "official_corridor_validation.txt").write_text(report, encoding="utf-8")
    print(report)
    print(f"\nSaved: {RESULTS / 'official_corridor_validation.txt'}")
    print(f"Saved: {RESULTS / 'official_corridor_leg_review.csv'}")
    return 1 if errors else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise

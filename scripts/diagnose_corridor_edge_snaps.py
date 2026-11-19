#!/usr/bin/env python3
"""Diagnose candidate/demand point proximity to actual directed OSM edge geometries.

This is a diagnostic only: it does not modify the routing graph or the MILP distance
matrix. It compares nearest-node snapping (from the existing report) with nearest
edge-geometry snapping on a projected copy of the same simplified directed graph.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

import osmnx as ox
import pandas as pd
from pyproj import Transformer
from shapely.geometry import LineString, Point
from shapely import wkt

ROOT = Path(__file__).resolve().parents[1]
SITES_PATH = ROOT / "data" / "derived" / "corridor_candidate_sites.csv"
DEMAND_PATH = ROOT / "data" / "derived" / "traffic_ev_demand_scenarios" / "base" / "demand_points.csv"
GRAPH_PATH = ROOT / "data" / "raw" / "armenia_drive_graph.graphml"
OUT_DIR = ROOT / "data" / "derived" / "network_distance_validation"
REVIEW_THRESHOLD_M = 500.0


def find_column(df: pd.DataFrame, candidates: list[str], label: str) -> str:
    lookup = {str(c).strip().lower(): c for c in df.columns}
    for candidate in candidates:
        if candidate.lower() in lookup:
            return lookup[candidate.lower()]
    raise ValueError(
        f"Could not identify {label} column. Available columns: {list(df.columns)}"
    )


def clean_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ";".join(str(v) for v in value)
    return str(value)


def load_points() -> pd.DataFrame:
    if not SITES_PATH.exists():
        raise FileNotFoundError(f"Sites CSV not found: {SITES_PATH}")
    if not DEMAND_PATH.exists():
        raise FileNotFoundError(f"Demand CSV not found: {DEMAND_PATH}")

    sites = pd.read_csv(SITES_PATH, encoding="utf-8-sig")
    demands = pd.read_csv(DEMAND_PATH, encoding="utf-8-sig")

    site_id = find_column(sites, ["site_id", "point_id", "id", "name"], "site ID")
    site_route = find_column(sites, ["route_id", "corridor", "route"], "site route ID")
    site_lat = find_column(sites, ["latitude", "lat", "y"], "site latitude")
    site_lon = find_column(sites, ["longitude", "lon", "lng", "x"], "site longitude")

    demand_id = find_column(
        demands,
        ["demand_id", "demand_point_id", "point_id", "location_id", "id", "name"],
        "demand ID",
    )
    demand_route = find_column(
        demands, ["route_id", "corridor", "route"], "demand route ID"
    )
    demand_lat = find_column(demands, ["latitude", "lat", "y"], "demand latitude")
    demand_lon = find_column(
        demands, ["longitude", "lon", "lng", "x"], "demand longitude"
    )

    site_rows = pd.DataFrame(
        {
            "point_type": "site",
            "point_id": sites[site_id].astype(str),
            "route_id": sites[site_route].astype(str),
            "latitude": pd.to_numeric(sites[site_lat], errors="coerce"),
            "longitude": pd.to_numeric(sites[site_lon], errors="coerce"),
            "chainage_km": pd.to_numeric(sites.get("chainage_km"), errors="coerce"),
        }
    )
    demand_rows = pd.DataFrame(
        {
            "point_type": "demand",
            "point_id": demands[demand_id].astype(str),
            "route_id": demands[demand_route].astype(str),
            "latitude": pd.to_numeric(demands[demand_lat], errors="coerce"),
            "longitude": pd.to_numeric(demands[demand_lon], errors="coerce"),
            "chainage_km": pd.to_numeric(demands.get("chainage_km"), errors="coerce"),
        }
    )
    points = pd.concat([site_rows, demand_rows], ignore_index=True)
    bad = points[points[["latitude", "longitude"]].isna().any(axis=1)]
    if not bad.empty:
        raise ValueError(
            "Some source points have missing/non-numeric coordinates:\n"
            + bad.to_string(index=False)
        )
    return points


def edge_geometry(graph: Any, u: Any, v: Any, key: Any, data: dict[str, Any]):
    geom = data.get("geometry")
    if isinstance(geom, str):
        try:
            geom = wkt.loads(geom)
        except Exception:
            geom = None
    if geom is not None and hasattr(geom, "project"):
        return geom
    nu = graph.nodes[u]
    nv = graph.nodes[v]
    return LineString([(float(nu["x"]), float(nu["y"])), (float(nv["x"]), float(nv["y"]))])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-threshold-m", type=float, default=REVIEW_THRESHOLD_M)
    args = parser.parse_args()

    print("[1/6] Loading input candidate and demand points...")
    points = load_points()
    print(f"      Sites={int((points.point_type == 'site').sum())} | demand points={int((points.point_type == 'demand').sum())}")

    print("[2/6] Loading the existing simplified directed graph...")
    if not GRAPH_PATH.exists():
        raise FileNotFoundError(f"GraphML not found: {GRAPH_PATH}")
    graph = ox.io.load_graphml(GRAPH_PATH)
    if not graph.is_directed():
        raise ValueError("Graph is not directed; refusing to continue.")
    print(f"      Directed graph: {len(graph):,} nodes / {graph.number_of_edges():,} edges")

    print("[3/6] Projecting graph to metric coordinates...")
    projected = ox.project_graph(graph)
    projected_crs = projected.graph["crs"]
    to_metric = Transformer.from_crs("EPSG:4326", projected_crs, always_xy=True)
    to_wgs84 = Transformer.from_crs(projected_crs, "EPSG:4326", always_xy=True)
    print(f"      Projected CRS: {projected_crs}")

    print("[4/6] Finding nearest directed edge geometries...")
    records: list[dict[str, Any]] = []
    for row in points.itertuples(index=False):
        px, py = to_metric.transform(float(row.longitude), float(row.latitude))
        edge_id, snap_distance = ox.distance.nearest_edges(
            projected, X=float(px), Y=float(py), return_dist=True
        )
        u, v, key = edge_id
        data = projected.get_edge_data(u, v, key)
        if data is None:
            raise RuntimeError(f"Nearest edge disappeared: {(u, v, key)}")
        geom = edge_geometry(projected, u, v, key, data)
        point = Point(float(px), float(py))
        along = float(geom.project(point))
        geom_length = float(geom.length)
        fraction = (along / geom_length) if geom_length > 0 else math.nan
        snap_point = geom.interpolate(along)
        snap_lon, snap_lat = to_wgs84.transform(float(snap_point.x), float(snap_point.y))

        records.append(
            {
                "point_type": row.point_type,
                "point_id": row.point_id,
                "route_id": row.route_id,
                "input_latitude": float(row.latitude),
                "input_longitude": float(row.longitude),
                "chainage_km": row.chainage_km,
                "nearest_edge_u": str(u),
                "nearest_edge_v": str(v),
                "nearest_edge_key": str(key),
                "nearest_edge_osmid": clean_value(data.get("osmid")),
                "nearest_edge_name": clean_value(data.get("name")),
                "nearest_edge_highway": clean_value(data.get("highway")),
                "nearest_edge_oneway": clean_value(data.get("oneway")),
                "nearest_edge_access": clean_value(data.get("access")),
                "edge_length_attribute_m": float(data.get("length", math.nan)),
                "edge_geometry_length_m": geom_length,
                "fraction_along_edge_u_to_v": fraction,
                "nearest_edge_latitude": float(snap_lat),
                "nearest_edge_longitude": float(snap_lon),
                "snap_to_edge_distance_m": float(snap_distance),
                "snap_status": (
                    "REVIEW_EDGE_DISTANCE" if float(snap_distance) > args.review_threshold_m else "OK"
                ),
            }
        )

    result = pd.DataFrame(records)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = OUT_DIR / "corridor_point_edge_snap_diagnostics.csv"
    out_txt = OUT_DIR / "EDGE_SNAP_DIAGNOSTIC_REPORT.txt"
    result.to_csv(out_csv, index=False, encoding="utf-8-sig")

    review = result[result["snap_to_edge_distance_m"] > args.review_threshold_m]
    former_five = {"M2_C016", "M2_C024", "M2_C025", "M2_C028", "M2_C035"}
    old_five = result[result["point_id"].isin(former_five)]
    report = [
        "DIRECTED OSM EDGE-GEOMETRY SNAP DIAGNOSTIC",
        "===========================================",
        f"Points checked: {len(result)}",
        f"Graph: {len(graph):,} nodes / {graph.number_of_edges():,} directed edges",
        f"Projected CRS: {projected_crs}",
        f"Review threshold: {args.review_threshold_m:.1f} m",
        f"Points above review threshold: {len(review)}",
        "",
        "FORMER FIVE NODE-SNAP REVIEW POINTS",
        "-----------------------------------",
    ]
    if old_five.empty:
        report.append("None of the five IDs were found in the point inputs.")
    else:
        for r in old_five.itertuples(index=False):
            report.append(
                f"{r.point_id}: edge distance={r.snap_to_edge_distance_m:.1f} m; "
                f"edge={r.nearest_edge_u}->{r.nearest_edge_v} (key {r.nearest_edge_key}); "
                f"highway={r.nearest_edge_highway}; name={r.nearest_edge_name}"
            )
    report += ["", "ALL POINTS ABOVE REVIEW THRESHOLD", "----------------------------------"]
    if review.empty:
        report.append("None")
    else:
        for r in review.itertuples(index=False):
            report.append(
                f"{r.point_type} {r.point_id} ({r.route_id}): "
                f"{r.snap_to_edge_distance_m:.1f} m"
            )
    report += [
        "",
        "INTERPRETATION",
        "--------------",
        "This report measures distance to the nearest projected directed edge geometry,",
        "not distance to the nearest graph node. A large previous node snap may therefore",
        "have been caused by graph simplification rather than a misplaced candidate point.",
        "This diagnostic does NOT create legal driveway/access links and does NOT modify",
        "the routing graph or the MILP distance matrix. A routing graph with correctly",
        "inserted virtual points on directed edges is still needed before final distances",
        "can be adopted in the MILP.",
    ]
    out_txt.write_text("\n".join(report) + "\n", encoding="utf-8")

    print("[5/6] Writing edge-snap results...")
    print(f"      Points checked: {len(result)}")
    print(f"      Points above {args.review_threshold_m:.0f} m: {len(review)}")
    print(f"      Former five node-snap review points above threshold: {len(old_five[old_five.snap_to_edge_distance_m > args.review_threshold_m]) if not old_five.empty else 0}")
    print(f"      CSV: {out_csv.relative_to(ROOT)}")
    print(f"      Report: {out_txt.relative_to(ROOT)}")
    print("[6/6] Complete")
    print("IMPORTANT: This is a proximity diagnostic only; do not use it as a MILP distance matrix.")


if __name__ == "__main__":
    main()

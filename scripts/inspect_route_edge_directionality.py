#!/usr/bin/env python3
"""Inspect OSM one-way tags and reverse-edge geometry for asymmetric route pairs."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import osmnx as ox
import pandas as pd
from shapely.geometry import LineString
from shapely import wkt

ROOT = Path(__file__).resolve().parents[1]
GRAPH_PATH = ROOT / "data" / "raw" / "armenia_drive_graph.graphml"
DATA_DIR = ROOT / "data" / "derived" / "network_distance_validation"
MATRIX_PATH = DATA_DIR / "corridor_site_demand_distances_virtual_edge.csv"
SNAPS_PATH = DATA_DIR / "corridor_point_virtual_edge_snap_diagnostics.csv"
REPORT_PATH = DATA_DIR / "EDGE_DIRECTIONALITY_REVIEW.txt"


def as_node_id(value: Any) -> Any:
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def as_key(value: Any) -> Any:
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def get_geom(graph, u, v, key, data):
    geom = data.get("geometry")
    if isinstance(geom, str):
        try:
            geom = wkt.loads(geom)
        except Exception:
            geom = None
    if geom is not None and not geom.is_empty:
        return geom
    nu, nv = graph.nodes[u], graph.nodes[v]
    return LineString([(float(nu["x"]), float(nu["y"])), (float(nv["x"]), float(nv["y"]))])


def brief(value: Any, limit: int = 100) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def main() -> None:
    for path in (GRAPH_PATH, MATRIX_PATH, SNAPS_PATH):
        if not path.exists():
            raise FileNotFoundError(f"Required file not found: {path}")

    print("[1/4] Loading graph and previous diagnostics...")
    graph = ox.io.load_graphml(GRAPH_PATH)
    matrix = pd.read_csv(MATRIX_PATH)
    snaps = pd.read_csv(SNAPS_PATH, dtype={"nearest_edge_u": str, "nearest_edge_v": str, "nearest_edge_key": str})
    projected = ox.project_graph(graph)
    snap_by_id = snaps.set_index("point_id").to_dict(orient="index")

    print("[2/4] Checking reverse-edge existence and geometric coincidence...")
    edge_info: dict[str, dict] = {}
    for row in snaps.itertuples(index=False):
        pid = str(row.point_id)
        u = as_node_id(row.nearest_edge_u)
        v = as_node_id(row.nearest_edge_v)
        key = as_key(row.nearest_edge_key)
        data = projected.get_edge_data(u, v, key)
        if data is None:
            edge_info[pid] = {"error": f"Selected edge not found: {u}->{v} key={key}"}
            continue
        geom = get_geom(projected, u, v, key, data)
        reverse_rows = []
        for reverse_key, reverse_data in (projected.get_edge_data(v, u, default={}) or {}).items():
            reverse_geom = get_geom(projected, v, u, reverse_key, reverse_data)
            hausdorff = float(geom.hausdorff_distance(reverse_geom))
            reverse_rows.append((reverse_key, reverse_data, hausdorff))
        coincident = [r for r in reverse_rows if r[2] <= 1.0]
        edge_info[pid] = {
            "u": u,
            "v": v,
            "key": key,
            "oneway": data.get("oneway"),
            "oneway_tag": data.get("oneway_tag"),
            "reversed": data.get("reversed"),
            "highway": data.get("highway"),
            "name": data.get("name"),
            "length": data.get("length"),
            "reverse_count": len(reverse_rows),
            "coincident_reverse_count": len(coincident),
            "best_reverse_hausdorff_m": min((r[2] for r in reverse_rows), default=None),
            "coincident_reverse_details": [
                {
                    "key": r[0],
                    "oneway": r[1].get("oneway"),
                    "oneway_tag": r[1].get("oneway_tag"),
                    "reversed": r[1].get("reversed"),
                    "hausdorff_m": r[2],
                }
                for r in coincident
            ],
        }

    print("[3/4] Summarizing OSM tags and the 12 largest directional differences...")
    def tag_label(pid: str) -> str:
        value = edge_info.get(str(pid), {}).get("oneway_tag", "<missing>")
        return brief(value)

    oneway_tag_counts = snaps["point_id"].astype(str).map(tag_label)
    tag_summary = oneway_tag_counts.value_counts(dropna=False).to_dict()
    top = matrix[matrix["eligible"].astype(bool)].nlargest(12, "directional_asymmetry_km")
    selected_ids = set(top["site_id"].astype(str)) | set(top["demand_id"].astype(str))

    lines = [
        "DIRECTED EDGE / OSM ONEWAY TAG REVIEW",
        "=====================================",
        f"Directed graph: {len(graph):,} nodes / {graph.number_of_edges():,} edges",
        f"Points checked: {len(snaps)}",
        "",
        "IMPORTANT ATTRIBUTE NOTE",
        "------------------------",
        "The field 'oneway' is Pyrosm/OSMnx graph metadata. The original OSM textual tag is 'oneway_tag'.",
        "Do not interpret 'oneway=True' alone as proof that the source OSM way is tagged one-way.",
        "Reverse-edge existence and geometric coincidence are checked independently below.",
        "",
        "OSM oneway_tag counts among the 61 snapped edges:",
    ]
    for tag, count in tag_summary.items():
        lines.append(f"  {brief(tag)}: {count}")

    lines += ["", "TOP 12 ASYMMETRIC PAIRS", "-----------------------"]
    for r in top.itertuples(index=False):
        lines.append(
            f"{r.site_id} <- {r.demand_id}: demand->site={r.distance_km:.2f} km; "
            f"site->demand={r.distance_site_to_demand_km:.2f} km; "
            f"asymmetry={r.directional_asymmetry_km:.2f} km"
        )

    lines += ["", "SELECTED EDGE DETAILS FOR POINTS IN THOSE PAIRS", "-----------------------------------------------"]
    for pid in sorted(selected_ids):
        info = edge_info.get(pid, {})
        lines.append(f"\n{pid}:")
        if "error" in info:
            lines.append(f"  ERROR: {info['error']}")
            continue
        lines.append(f"  edge: {info['u']} -> {info['v']} (key={info['key']})")
        lines.append(f"  highway={brief(info['highway'])}; length={info['length']}")
        lines.append(f"  oneway={brief(info['oneway'])}; oneway_tag={brief(info['oneway_tag'])}; reversed={brief(info['reversed'])}")
        lines.append(f"  reverse directed edges with same endpoints: {info['reverse_count']}")
        lines.append(f"  geometrically coincident reverse edges (<=1m Hausdorff): {info['coincident_reverse_count']}")
        lines.append(f"  nearest reverse-edge Hausdorff distance (m): {info['best_reverse_hausdorff_m']}")
        for rev in info["coincident_reverse_details"]:
            lines.append(
                f"    reverse key={rev['key']}: oneway={brief(rev['oneway'])}; "
                f"oneway_tag={brief(rev['oneway_tag'])}; reversed={brief(rev['reversed'])}; "
                f"Hausdorff={rev['hausdorff_m']:.3f}m"
            )

    lines += [
        "",
        "INTERPRETATION GUIDE",
        "--------------------",
        "- oneway_tag=yes/-1 (or equivalent) supports an OSM one-way interpretation.",
        "- A reverse edge with coincident geometry supports two-way travel on the same physical road segment.",
        "- No coincident reverse edge can mean a one-way road OR a separate carriageway/parallel road; inspect tags and map geometry.",
        "- Even if these checks look consistent, actual station driveway/legal access remains unverified.",
        "- This report is diagnostic only and does not alter the distance matrix or MILP inputs.",
    ]

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"      OSM oneway_tag counts: {tag_summary}")
    print(f"      Unique points reviewed among top 12 pairs: {len(selected_ids)}")
    print("[4/4] Complete")
    print(f"      Report: {REPORT_PATH.relative_to(ROOT)}")
    print("IMPORTANT: Review oneway_tag and reverse-edge geometry; do not infer one-way status from 'oneway=True' alone.")


if __name__ == "__main__":
    main()

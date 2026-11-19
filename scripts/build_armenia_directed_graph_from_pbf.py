"""Build an OSMnx-compatible directed Armenia driving graph from a local PBF.

The graph is generated offline from the Geofabrik Armenia extract using Pyrosm.
It preserves directed driving restrictions (including OSM one-way tags), keeps
all connected components, and saves GraphML for the corridor distance script.

Default input:  data/raw/armenia-latest.osm.pbf
Default output: data/raw/armenia_drive_graph.graphml
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pbf",
        default="data/raw/armenia-latest.osm.pbf",
        help="Local Armenia .osm.pbf extract",
    )
    parser.add_argument(
        "--output",
        default="data/raw/armenia_drive_graph.graphml",
        help="Output directed GraphML path",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing GraphML output",
    )
    parser.add_argument(
        "--no-simplify",
        action="store_true",
        help="Keep original road segments instead of simplifying the graph",
    )
    args = parser.parse_args()

    pbf_path = Path(args.pbf)
    output_path = Path(args.output)
    if not pbf_path.exists():
        raise FileNotFoundError(
            f"Local OSM PBF not found: {pbf_path}. Expected the Armenia extract "
            "downloaded earlier as data/raw/armenia-latest.osm.pbf."
        )
    if pbf_path.stat().st_size < 1_000_000:
        raise ValueError(f"PBF file looks unexpectedly small: {pbf_path.stat().st_size} bytes")
    if output_path.exists() and not args.overwrite:
        raise FileExistsError(
            f"Output already exists: {output_path}. Use --overwrite only if you intend to rebuild it."
        )

    try:
        import osmnx as ox
        from pyrosm import OSM
    except ImportError as exc:
        raise SystemExit(
            'Missing geospatial dependency. Run: .\\.venv\\Scripts\\python.exe -m pip install -e ".[geospatial]" '
            'and install pyrosm if needed.'
        ) from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(output_path.stem + ".tmp.graphml")
    if temp_path.exists():
        temp_path.unlink()

    print("[1/5] Opening local Armenia PBF (no Overpass download required)...", flush=True)
    print(f"      PBF: {pbf_path} ({pbf_path.stat().st_size / (1024 * 1024):.1f} MiB)", flush=True)
    osm = OSM(str(pbf_path))

    print("[2/5] Building the directed driving graph with Pyrosm...", flush=True)
    print("      One-way restrictions are respected; all components are retained.", flush=True)
    graph = osm.get_graph(
        network_type="driving",
        graph_type="networkx",
        retain_all=True,
        osmnx_compatible=True,
        simplify=not args.no_simplify,
    )
    if graph is None:
        raise RuntimeError("Pyrosm returned an empty driving graph from the PBF.")
    if not graph.is_directed():
        raise RuntimeError("Pyrosm returned an undirected graph; refusing to save it.")
    if graph.number_of_nodes() == 0 or graph.number_of_edges() == 0:
        raise RuntimeError("The generated driving graph is empty.")

    print(
        f"      Graph: {graph.number_of_nodes():,} nodes / "
        f"{graph.number_of_edges():,} directed edges",
        flush=True,
    )

    print("[3/5] Validating graph coordinates and edge lengths...", flush=True)
    for node_id, data in graph.nodes(data=True):
        if "x" not in data or "y" not in data:
            raise ValueError(f"Graph node {node_id!r} is missing OSMnx x/y coordinates.")
        x, y = float(data["x"]), float(data["y"])
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError(f"Graph node {node_id!r} has non-finite coordinates.")
        if not (-180 <= x <= 180 and -90 <= y <= 90):
            raise ValueError(f"Graph node {node_id!r} coordinates are outside EPSG:4326 bounds.")

    edge_count = 0
    missing_lengths = 0
    invalid_lengths = 0
    if graph.is_multigraph():
        edge_iterator = graph.edges(keys=True, data=True)
    else:
        edge_iterator = graph.edges(data=True)
    for edge in edge_iterator:
        data = edge[-1]
        edge_count += 1
        if "length" not in data:
            missing_lengths += 1
            continue
        try:
            length = float(data["length"])
        except (TypeError, ValueError):
            invalid_lengths += 1
            continue
        if not math.isfinite(length) or length < 0:
            invalid_lengths += 1
    if missing_lengths or invalid_lengths:
        raise ValueError(
            f"Invalid edge lengths: missing={missing_lengths}, invalid={invalid_lengths}. "
            "Rebuild the graph from the PBF before routing."
        )

    # Pyrosm's OSMnx-compatible graph normally includes this already. Set a
    # safe explicit CRS only when absent, because nearest_nodes requires it.
    if not graph.graph.get("crs"):
        graph.graph["crs"] = "EPSG:4326"
    crs_text = str(graph.graph["crs"])
    if "4326" not in crs_text and "WGS 84" not in crs_text:
        raise ValueError(
            f"Expected an EPSG:4326 graph for longitude/latitude points; got crs={crs_text!r}."
        )

    print(f"      Validated {graph.number_of_nodes():,} node coordinates and {edge_count:,} edge lengths.", flush=True)
    print(f"      Directed={graph.is_directed()} | CRS={crs_text} | simplified={not args.no_simplify}", flush=True)

    print("[4/5] Saving OSMnx-compatible GraphML...", flush=True)
    # OSMnx's writer handles geometry attributes as WKT and is preferable to
    # raw NetworkX GraphML serialization for OSMnx-compatible street graphs.
    ox.io.save_graphml(graph, filepath=temp_path)
    if not temp_path.exists() or temp_path.stat().st_size == 0:
        raise RuntimeError("GraphML output was not created correctly.")
    if output_path.exists() and args.overwrite:
        output_path.unlink()
    temp_path.replace(output_path)

    print("[5/5] Complete", flush=True)
    print(f"      Saved: {output_path}", flush=True)
    print(f"      File size: {output_path.stat().st_size / (1024 * 1024):.1f} MiB", flush=True)
    print("      The graph is directed; the next script can now use it.", flush=True)
    print("      Build this graph from the PBF again only when the OSM extract changes.", flush=True)


if __name__ == "__main__":
    main()

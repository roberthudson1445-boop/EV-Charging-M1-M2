"""Download an OpenStreetMap driving graph for road-distance calculations.

This is an optional, network-intensive step. It downloads the road graph for
an entire place query (default: Armenia), stores it as GraphML, and records
OpenStreetMap attribution and extraction metadata.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--place", default="Armenia", help="OSM place query")
    parser.add_argument(
        "--output",
        default="data/raw/armenia_drive_graph.graphml",
        help="GraphML output path",
    )
    parser.add_argument("--network-type", default="drive", choices=["drive", "drive_service"])
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing graph")
    args = parser.parse_args()

    try:
        import osmnx as ox
    except ImportError as exc:
        raise SystemExit(
            'OSMnx is not installed. Run: python -m pip install -e ".[geospatial]"'
        ) from exc

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata_path = output.with_suffix(".metadata.json")
    if output.exists() and not args.overwrite:
        raise SystemExit(f"Output already exists: {output}. Use --overwrite to replace it.")

    print(f"Downloading OSM {args.network_type!r} graph for {args.place!r}...")
    print("A country-scale graph can be large and may take time to download.")
    graph = ox.graph.graph_from_place(
        args.place,
        network_type=args.network_type,
        simplify=True,
        retain_all=True,
    )
    ox.io.save_graphml(graph, filepath=output)
    metadata = {
        "downloaded_utc": datetime.now(timezone.utc).isoformat(),
        "place_query": args.place,
        "network_type": args.network_type,
        "node_count": int(graph.number_of_nodes()),
        "edge_count": int(graph.number_of_edges()),
        "osm_attribution": "© OpenStreetMap contributors",
        "license": "Open Database License (ODbL)",
        "source": "https://www.openstreetmap.org/copyright",
        "warning": (
            "This is a volunteered road-network extract. Inspect M1/M2 route continuity, "
            "road access, turn restrictions, and current realignments before using distances. "
            "It contains no traffic, EV demand, charger, or substation-capacity measurements."
        ),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Saved graph with {graph.number_of_nodes()} nodes and {graph.number_of_edges()} edges to {output}")
    print(f"Saved provenance metadata to {metadata_path}")


if __name__ == "__main__":
    main()

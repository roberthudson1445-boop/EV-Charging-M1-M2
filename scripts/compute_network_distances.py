"""Compute a complete site-to-demand road-distance matrix from an OSM graph.

Input CSVs require site_id/latitude/longitude and demand_id/latitude/longitude.
Distances are shortest paths on an undirected copy of the OSM driving graph,
so they are preliminary road-distance approximations, not directional route
or turn-by-turn travel-time estimates.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np


def _load_points(path: Path, id_column: str) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {id_column, "latitude", "longitude"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{path.name} contains no point rows.")

    ids = [row[id_column].strip() for row in rows]
    if any(not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError(f"{path.name} must contain non-empty unique {id_column} values.")
    for row in rows:
        try:
            lat = float(row["latitude"])
            lon = float(row["longitude"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{path.name} has non-numeric latitude/longitude.") from exc
        if not np.isfinite(lat) or not -90 <= lat <= 90:
            raise ValueError(f"{path.name} contains an invalid latitude: {lat}")
        if not np.isfinite(lon) or not -180 <= lon <= 180:
            raise ValueError(f"{path.name} contains an invalid longitude: {lon}")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data/raw", help="Directory containing sites.csv and demand_points.csv")
    parser.add_argument("--graph", default="data/raw/armenia_drive_graph.graphml", help="OSMnx GraphML path")
    parser.add_argument("--output", default="data/raw/distances.csv", help="Output distance matrix CSV")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output")
    args = parser.parse_args()

    try:
        import networkx as nx
        import osmnx as ox
    except ImportError as exc:
        raise SystemExit(
            'Network distance generation requires OSMnx. Run: python -m pip install -e ".[geospatial]"'
        ) from exc

    directory = Path(args.data_dir)
    sites = _load_points(directory / "sites.csv", "site_id")
    demands = _load_points(directory / "demand_points.csv", "demand_id")
    graph_path = Path(args.graph)
    if not graph_path.exists():
        raise FileNotFoundError(f"OSM graph not found: {graph_path}. Download it first.")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not args.overwrite:
        raise SystemExit(f"Output already exists: {output}. Use --overwrite to replace it.")

    graph = ox.io.load_graphml(filepath=graph_path)
    undirected = ox.convert.to_undirected(graph)

    all_points = sites + demands
    X = np.array([float(row["longitude"]) for row in all_points], dtype=float)
    Y = np.array([float(row["latitude"]) for row in all_points], dtype=float)
    nearest = ox.distance.nearest_nodes(graph, X=X, Y=Y)
    site_nodes = nearest[: len(sites)]
    demand_nodes = nearest[len(sites) :]

    rows: list[dict[str, object]] = []
    for site_index, site in enumerate(sites):
        for demand_index, demand in enumerate(demands):
            try:
                meters = nx.shortest_path_length(
                    undirected,
                    source=site_nodes[site_index],
                    target=demand_nodes[demand_index],
                    weight="length",
                )
            except nx.NetworkXNoPath as exc:
                raise ValueError(
                    f"No drivable path between site {site['site_id']} and demand {demand['demand_id']}."
                ) from exc
            rows.append(
                {
                    "site_id": site["site_id"],
                    "demand_id": demand["demand_id"],
                    "distance_km": float(meters) / 1000.0,
                    "source": "OpenStreetMap driving graph; undirected shortest path",
                    "notes": "Preliminary network distance; verify snap points and route access.",
                }
            )

    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["site_id", "demand_id", "distance_km", "source", "notes"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} site-demand road distances to {output}")
    print("Review the snapped nodes and route access before using this matrix in the MILP.")


if __name__ == "__main__":
    main()

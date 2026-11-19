
"""Find the nearest driving-network node for each corridor-town candidate."""

from pathlib import Path

import numpy as np
import pandas as pd
from pyrosm import OSM
from pyproj import Transformer
from scipy.spatial import cKDTree

PBF = Path("data/raw/armenia-latest.osm.pbf")
ANCHORS = Path("data/raw/corridor_place_anchor_candidates.csv")
OUTPUT = Path("data/raw/anchor_network_snap_candidates.csv")

# Armenia lies within UTM zone 38N.
TRANSFORMER = Transformer.from_crs(
    "EPSG:4326", "EPSG:32638", always_xy=True
)


def main():
    if not PBF.exists() or not ANCHORS.exists():
        raise FileNotFoundError("PBF or anchor candidate CSV is missing.")

    print("Loading corridor-town candidates...")
    anchors = pd.read_csv(ANCHORS)

    print("Loading the local driving network...")
    osm = OSM(str(PBF))
    nodes, edges = osm.get_network(
        network_type="driving",
        nodes=True,
    )

    required = {"id", "lon", "lat"}
    missing = required - set(nodes.columns)

    if missing:
        raise ValueError(f"Driving nodes missing columns: {sorted(missing)}")

    print("Driving network nodes:", len(nodes))
    print("Driving network edges:", len(edges))

    # Project node coordinates into metres for distance calculations.
    node_x, node_y = TRANSFORMER.transform(
        nodes["lon"].to_numpy(dtype=float),
        nodes["lat"].to_numpy(dtype=float),
    )

    tree = cKDTree(np.column_stack([node_x, node_y]))

    results = []

    for row in anchors.itertuples(index=False):
        x, y = TRANSFORMER.transform(
            float(row.longitude), float(row.latitude)
        )

        distance_m, index = tree.query([x, y], k=1)
        nearest = nodes.iloc[int(index)]

        results.append({
            "route_id": row.route_id,
            "sequence_order": int(row.sequence_order),
            "anchor_name": row.anchor_name,
            "place_osm_type": row.osm_type,
            "place_osm_id": row.osm_id,
            "place_type": row.place_type,
            "anchor_longitude": float(row.longitude),
            "anchor_latitude": float(row.latitude),
            "nearest_drive_node_id": int(nearest["id"]),
            "nearest_drive_longitude": float(nearest["lon"]),
            "nearest_drive_latitude": float(nearest["lat"]),
            "snap_distance_m": float(distance_m),
        })

    result = pd.DataFrame(results)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT, index=False, encoding="utf-8-sig")

    print("\nAll candidate snap distances:")
    print(
        result.sort_values(
            ["route_id", "sequence_order", "snap_distance_m"]
        ).to_string(index=False)
    )

    best = (
        result.sort_values("snap_distance_m")
        .drop_duplicates(["route_id", "anchor_name"])
        .sort_values(["route_id", "sequence_order"])
    )

    print("\nBest candidate for each corridor location:")
    print(
        best[
            [
                "route_id",
                "sequence_order",
                "anchor_name",
                "place_osm_type",
                "place_osm_id",
                "nearest_drive_node_id",
                "snap_distance_m",
            ]
        ].to_string(index=False)
    )

    print("\nSaved:", OUTPUT)
    print(
        "Note: nearest driving node is a geometric snap, "
        "not proof of a correct highway-route connection."
    )


if __name__ == "__main__":
    main()

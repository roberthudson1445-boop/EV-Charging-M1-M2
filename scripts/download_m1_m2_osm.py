"""Download OSM-tagged M1/M2 road features for GIS inspection.

Requires the optional geospatial dependency: pip install -e ".[geospatial]".
This downloads OSM road geometries only. It does not identify charging sites,
substations, demand points, or traffic volumes.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _tag_matches(value: Any, targets: set[str]) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple, set)):
        return any(_tag_matches(item, targets) for item in value)
    parts = {part.strip() for part in str(value).replace(",", ";").split(";")}
    return bool(parts & targets)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--place", default="Armenia", help="OSM place query (default: Armenia)")
    parser.add_argument(
        "--output",
        default="data/raw/m1_m2_osm_features.geojson",
        help="Output GeoJSON path",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite an existing output")
    args = parser.parse_args()

    try:
        import osmnx as ox
    except ImportError as exc:
        raise SystemExit(
            'OSMnx is not installed. Run: python -m pip install -e ".[geospatial]"'
        ) from exc

    targets = {"M-1", "M-2", "Մ-1", "Մ-2", "М-1", "М-2"}
    tags = {
        "ref:en": ["M-1", "M-2"],
        "ref": ["M-1", "M-2", "Մ-1", "Մ-2", "М-1", "М-2"],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata_path = output.with_suffix(".metadata.json")
    if output.exists() and not args.overwrite:
        raise SystemExit(f"Output already exists: {output}. Use --overwrite to replace it.")

    print(f"Querying OpenStreetMap features for {args.place!r}...")
    features = ox.features_from_place(args.place, tags=tags)
    if features.empty:
        raise SystemExit("The OSM query returned no features. Check the place query or route tags.")

    if "highway" not in features.columns:
        raise SystemExit("OSM query returned no highway-tagged features.")
    roads = features[features["highway"].notna()].copy()
    roads = roads[roads.geometry.geom_type.isin(["LineString", "MultiLineString"])].copy()

    has_ref = "ref" in roads.columns
    has_ref_en = "ref:en" in roads.columns
    if not has_ref and not has_ref_en:
        raise SystemExit(
            "The returned highway features contain neither 'ref' nor 'ref:en' tags. "
            "Inspect the OSM query or use another documented road-network source."
        )

    mask = None
    if has_ref:
        mask = roads["ref"].apply(lambda value: _tag_matches(value, targets))
    if has_ref_en:
        ref_en_mask = roads["ref:en"].apply(
            lambda value: _tag_matches(value, {"M-1", "M-2"})
        )
        mask = ref_en_mask if mask is None else (mask | ref_en_mask)
    roads = roads.loc[mask].copy()

    if roads.empty:
        raise SystemExit(
            "The query returned features but no highway ways tagged M-1/M-2. "
            "Inspect OSM tags or use the documented main-roads GIS dataset instead."
        )

    roads.to_file(output, driver="GeoJSON")
    metadata = {
        "downloaded_utc": datetime.now(timezone.utc).isoformat(),
        "place_query": args.place,
        "osm_tags_query": tags,
        "feature_count": int(len(roads)),
        "osm_attribution": "© OpenStreetMap contributors",
        "license": "Open Database License (ODbL)",
        "source": "https://www.openstreetmap.org/copyright",
        "warning": (
            "Road features are OSM-derived and require manual inspection for route continuity, "
            "current alignments, and completeness. This file contains no traffic or electrical data."
        ),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Saved {len(roads)} tagged road features to {output}")
    print(f"Saved provenance metadata to {metadata_path}")


if __name__ == "__main__":
    main()

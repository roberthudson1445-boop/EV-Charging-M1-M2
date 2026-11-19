
"""Extract exact-name settlement anchors for Armenian M1/M2 corridors."""

import csv
from pathlib import Path

from pyrosm import OSM

PBF = Path("data/raw/armenia-latest.osm.pbf")
OUTPUT = Path("data/raw/corridor_place_anchor_candidates.csv")

ROUTES = {
    "M1": [
        ("Yerevan", ["Yerevan", "Երևան"]),
        ("Ashtarak", ["Ashtarak", "Աշտարակ"]),
        ("Talin", ["Talin", "Թալին"]),
        ("Maralik", ["Maralik", "Մարալիկ"]),
        ("Gyumri", ["Gyumri", "Գյումրի"]),
        ("Ashotsk", ["Ashotsk", "Աշոցք"]),
        ("Bavra", ["Bavra", "Բավրա"]),
    ],
    "M2": [
        ("Yerevan", ["Yerevan", "Երևան"]),
        ("Artashat", ["Artashat", "Արտաշատ"]),
        ("Areni", ["Areni", "Արենի"]),
        ("Yeghegnadzor", ["Yeghegnadzor", "Եղեգնաձոր"]),
        ("Vayk", ["Vayk", "Վայք"]),
        ("Sisian", ["Sisian", "Սիսիան"]),
        ("Goris", ["Goris", "Գորիս"]),
        ("Kapan", ["Kapan", "Կապան"]),
        ("Kajaran", ["Kajaran", "Քաջարան"]),
        ("Meghri", ["Meghri", "Մեղրի"]),
    ],
}


def normalize(value):
    if value is None:
        return ""
    return " ".join(str(value).strip().casefold().split())


def main():
    if not PBF.exists():
        raise FileNotFoundError(PBF)

    print("Reading settlement features from local OSM data...")

    osm = OSM(str(PBF))

    places = osm.get_data_by_custom_criteria(
        custom_filter={
            "place": ["city", "town", "village", "hamlet"]
        },
        keep_nodes=True,
        keep_ways=True,
        keep_relations=False,
        extra_attributes=["name:en", "name:hy"],
    )

    output_rows = []
    candidate_number = 0

    for route_id, route_places in ROUTES.items():
        for order, (target, aliases) in enumerate(route_places, start=1):
            alias_set = {normalize(alias) for alias in aliases}

            for _, row in places.iterrows():
                names = [
                    row.get("name"),
                    row.get("name:en"),
                    row.get("name:hy"),
                ]

                matched_names = sorted({
                    str(value).strip()
                    for value in names
                    if normalize(value) in alias_set
                })

                if not matched_names:
                    continue

                geometry = row.geometry

                if geometry is None or geometry.is_empty:
                    continue

                point = (
                    geometry
                    if geometry.geom_type == "Point"
                    else geometry.representative_point()
                )

                candidate_number += 1

                output_rows.append({
                    "route_id": route_id,
                    "sequence_order": order,
                    "anchor_name": target,
                    "osm_type": row.get("osm_type", ""),
                    "osm_id": row.get("id", ""),
                    "place_type": row.get("place", ""),
                    "matched_names": " | ".join(matched_names),
                    "longitude": point.x,
                    "latitude": point.y,
                    "geometry_type": geometry.geom_type,
                })

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    if not output_rows:
        raise RuntimeError("No exact-name settlement anchors were found.")

    with OUTPUT.open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=list(output_rows[0].keys()),
        )
        writer.writeheader()
        writer.writerows(output_rows)

    print("Exact-name candidates saved:", candidate_number)
    print("Output:", OUTPUT)

    for route_id in ("M1", "M2"):
        print(f"\n{route_id} candidates:")

        for row in output_rows:
            if row["route_id"] == route_id:
                print(
                    f"{row['sequence_order']:2}. "
                    f"{row['anchor_name']:15} "
                    f"{row['osm_type']:5} "
                    f"id={row['osm_id']} "
                    f"lon={row['longitude']:.7f} "
                    f"lat={row['latitude']:.7f}"
                )


if __name__ == "__main__":
    main()

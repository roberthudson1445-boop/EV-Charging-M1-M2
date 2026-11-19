
"""Extract settlement candidates from official M1/M2 route sequences."""

import csv
from pathlib import Path

from pyrosm import OSM

PBF = Path("data/raw/armenia-latest.osm.pbf")
OUTPUT = Path("data/raw/official_route_waypoint_candidates.csv")

ROUTES = {
    "M1": [
        ("Yerevan", ["Yerevan", "Երևան"]),
        ("Kasakh", ["Kasakh", "Քասախ"]),
        ("Proshyan", ["Proshyan", "Պռոշյան"]),
        ("Ashtarak", ["Ashtarak", "Աշտարակ"]),
        ("Davtashen", ["Davtashen", "Դավթաշեն"]),
        ("Katnaghbyur", ["Katnaghbyur", "Կաթնաղբյուր"]),
        ("Mastara", ["Mastara", "Մաստարա"]),
        ("Lanjik", ["Lanjik", "Լանջիկ"]),
        ("Maralik", ["Maralik", "Մարալիկ"]),
        ("Lusakert", ["Lusakert", "Լուսակերտ"]),
        ("Azatan", ["Azatan", "Ազատան"]),
        ("Arevik", ["Arevik", "Արևիկ"]),
        ("Mayisyan", ["Mayisyan", "Մայիսյան"]),
        ("Keti", ["Keti", "Քեթի"]),
        ("Pokrashen", ["Pokrashen", "Փոքրաշեն"]),
        ("Vardaghbyur", ["Vardaghbyur", "Վարդաղբյուր"]),
        ("Ashotsk", ["Ashotsk", "Աշոցք"]),
        ("Bavra", ["Bavra", "Բավրա"]),
    ],
    "M2": [
        ("Yerevan", ["Yerevan", "Երևան"]),
        ("Ayntap", ["Ayntap", "Aintap", "Այնթապ"]),
        ("Masis", ["Masis", "Մասիս"]),
        ("Artashat", ["Artashat", "Արտաշատ"]),
        ("Pokr Vedi", ["Pokr Vedi", "Poqr Vedi", "Փոքր Վեդի"]),
        ("Surenavan", ["Surenavan", "Սուրենավան"]),
        ("Armash", ["Armash", "Արմաշ"]),
        ("Yeraskh", ["Yeraskh", "Երասխ"]),
        ("Paruyr Sevak", ["Paruyr Sevak", "Պարույր Սևակ"]),
        ("Chiva", ["Chiva", "Չիվա"]),
        ("Arpi", ["Arpi", "Արփի"]),
        ("Yeghegnadzor", ["Yeghegnadzor", "Եղեգնաձոր"]),
        ("Vayk", ["Vayk", "Վայք"]),
        ("Saravan", ["Saravan", "Սարավան"]),
        ("Saralanj", ["Saralanj", "Սարալանջ"]),
        ("Sarnakunq", ["Sarnakunq", "Սառնակունք"]),
        ("Noravan", ["Noravan", "Նորավան"]),
        ("Ltsen", ["Ltsen", "Լծեն"]),
        ("Tatev", ["Tatev", "Տաթև"]),
        ("Aghvani", ["Aghvani", "Աղվանի"]),
        ("Tandzaver", ["Tandzaver", "Տանձավեր"]),
        ("Syunik", ["Syunik", "Սյունիք"]),
        ("Kapan", ["Kapan", "Կապան"]),
        ("Kajaran", ["Kajaran", "Քաջարան"]),
        ("Vardanidzor", ["Vardanidzor", "Վարդանիձոր"]),
        ("Meghri", ["Meghri", "Մեղրի"]),
    ],
}

# Goris is retained as a demand/access location, not an M2 main-route waypoint.
ACCESS_TARGETS = [
    ("Goris", ["Goris", "Գորիս"]),
]


def normalize(value):
    if value is None:
        return ""
    return " ".join(str(value).strip().casefold().split())


def main():
    if not PBF.exists():
        raise FileNotFoundError(PBF)

    print("Reading settlement features from local OSM PBF...")

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

    rows = []
    missing = []

    for route_id, targets in ROUTES.items():
        for order, (target, aliases) in enumerate(targets, start=1):
            alias_set = {normalize(alias) for alias in aliases}
            matched = []

            for _, place in places.iterrows():
                names = [
                    place.get("name"),
                    place.get("name:en"),
                    place.get("name:hy"),
                ]

                matched_names = sorted({
                    str(name).strip()
                    for name in names
                    if normalize(name) in alias_set
                })

                if not matched_names:
                    continue

                geometry = place.geometry
                if geometry is None or geometry.is_empty:
                    continue

                point = (
                    geometry
                    if geometry.geom_type == "Point"
                    else geometry.representative_point()
                )

                matched.append({
                    "route_id": route_id,
                    "sequence_order": order,
                    "waypoint_name": target,
                    "role": "main_route_waypoint",
                    "osm_type": place.get("osm_type", ""),
                    "osm_id": place.get("id", ""),
                    "place_type": place.get("place", ""),
                    "matched_names": " | ".join(matched_names),
                    "longitude": point.x,
                    "latitude": point.y,
                })

            if not matched:
                missing.append((route_id, order, target))
            rows.extend(matched)

    # Goris is an access/demand anchor associated with the M9 branch.
    for target, aliases in ACCESS_TARGETS:
        alias_set = {normalize(alias) for alias in aliases}

        for _, place in places.iterrows():
            names = [
                place.get("name"),
                place.get("name:en"),
                place.get("name:hy"),
            ]
            matched_names = sorted({
                str(name).strip()
                for name in names
                if normalize(name) in alias_set
            })

            if not matched_names:
                continue

            geometry = place.geometry
            if geometry is None or geometry.is_empty:
                continue

            point = (
                geometry
                if geometry.geom_type == "Point"
                else geometry.representative_point()
            )

            rows.append({
                "route_id": "M9_ACCESS",
                "sequence_order": "",
                "waypoint_name": target,
                "role": "demand_access_anchor",
                "osm_type": place.get("osm_type", ""),
                "osm_id": place.get("id", ""),
                "place_type": place.get("place", ""),
                "matched_names": " | ".join(matched_names),
                "longitude": point.x,
                "latitude": point.y,
            })

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    fields = [
        "route_id", "sequence_order", "waypoint_name", "role",
        "osm_type", "osm_id", "place_type", "matched_names",
        "longitude", "latitude",
    ]

    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print("Saved candidate records:", len(rows))
    print("Output:", OUTPUT)

    print("\nMissing official waypoints:")
    if missing:
        for route_id, order, name in missing:
            print(f"{route_id} {order:2} — {name}")
    else:
        print("None")

    print("\nCandidate counts:")
    for route_id in ("M1", "M2", "M9_ACCESS"):
        count = sum(row["route_id"] == route_id for row in rows)
        print(f"{route_id}: {count}")


if __name__ == "__main__":
    main()

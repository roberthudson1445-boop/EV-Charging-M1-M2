
"""Extract named Armenian corridor towns from the local OSM PBF."""

from pathlib import Path

from pyrosm import OSM

PBF = Path("data/raw/armenia-latest.osm.pbf")

TARGETS = {
    "Yerevan": ["Yerevan", "Երևան"],
    "Ashtarak": ["Ashtarak", "Աշտարակ"],
    "Talin": ["Talin", "Թալին"],
    "Maralik": ["Maralik", "Մարալիկ"],
    "Gyumri": ["Gyumri", "Գյումրի"],
    "Ashotsk": ["Ashotsk", "Աշոցք"],
    "Bavra": ["Bavra", "Բավրա"],
    "Artashat": ["Artashat", "Արտաշատ"],
    "Areni": ["Areni", "Արենի"],
    "Yeghegnadzor": ["Yeghegnadzor", "Եղեգնաձոր"],
    "Vayk": ["Vayk", "Վայք"],
    "Sisian": ["Sisian", "Սիսիան"],
    "Goris": ["Goris", "Գորիս"],
    "Kapan": ["Kapan", "Կապան"],
    "Kajaran": ["Kajaran", "Քաջարան"],
    "Meghri": ["Meghri", "Մեղրի"],
}


def main():
    if not PBF.exists():
        raise FileNotFoundError(PBF)

    print("Reading named settlements from the local OSM PBF...")

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

    print("Settlement features found:", len(places))
    print("\nMatching corridor locations:\n")

    found = set()

    for _, row in places.iterrows():
        names = [
            str(row.get(column, "") or "")
            for column in ("name", "name:en", "name:hy")
        ]

        searchable = " | ".join(names).casefold()

        for target, aliases in TARGETS.items():
            if not any(alias.casefold() in searchable for alias in aliases):
                continue

            geometry = row.geometry

            if geometry is None or geometry.is_empty:
                continue

            point = (
                geometry
                if geometry.geom_type == "Point"
                else geometry.representative_point()
            )

            found.add(target)

            print(
                f"{target:15} "
                f"type={row.get('place')} "
                f"osm_type={row.get('osm_type')} "
                f"id={row.get('id')} "
                f"lon={point.x:.7f} "
                f"lat={point.y:.7f} "
                f"names={names}"
            )

    print("\n" + "=" * 55)
    print("TARGET SUMMARY")
    print("=" * 55)

    for target in TARGETS:
        status = "FOUND" if target in found else "NOT FOUND"
        print(f"{target:15} {status}")


if __name__ == "__main__":
    main()

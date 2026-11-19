from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path.cwd()
REFERENCE_DIR = ROOT / "data" / "reference"

ADB_2008_URL = (
    "https://collaboration.worldbank.org/content/usergenerated/asi/cloud/attachments/"
    "sites/collaboration-for-development/en/groups/eastern-partnership-transport-panel/"
    "documents/jcr%3Acontent/content/primary/blog/2009-2020_-_armenia-0mSW/"
    "2009-2020%20-%20Armenia%2C%20Transport%20Sector%20Development%20Strategy%20%28ADB%29.pdf"
)
ADB_PCR_URL = "https://www.adb.org/sites/default/files/project-documents/42145/42145-023-pcr-en.pdf"
ADB_56317_URL = "https://www.adb.org/projects/56317-001/main"
UNDP_URL = "https://www.undp.org/sites/g/files/zskgke326/files/2024-11/pdna_armenia_eng_final.pdf"

# ADB Armenia Transport Sector Development Strategy (2008), Table 4-2.
# Rows are point traffic counts. The first, second and third blocks correspond
# to 2005, 2006 and 2007, respectively. N/A is intentionally not fabricated.
point_rows = [
    ("M1", "M1_ATC_20_7", 20.700, 2005, 8316, 1351, 71, 9738),
    ("M2", "M2_ATC_9_38", 9.380, 2005, 17032, 4963, 630, 22625),
    ("M2", "M2_ATC_200_32", 200.320, 2005, 560, 185, 15, 760),
    ("M2", "M2_ATC_367_25", 367.250, 2005, 340, 271, 59, 670),
    ("M1", "M1_ATC_20_7", 20.700, 2006, 8813, 1428, 82, 10323),
    ("M2", "M2_ATC_9_38", 9.380, 2006, 17586, 5389, 624, 23599),
    ("M2", "M2_ATC_200_32", 200.320, 2006, 726, 238, 38, 1002),
    ("M2", "M2_ATC_367_25", 367.250, 2006, 400, 325, 79, 804),
    ("M1", "M1_ATC_20_7", 20.700, 2007, 6195, 3441, 317, 9953),
    ("M2", "M2_ATC_9_38", 9.380, 2007, 18352, 5673, 526, 24551),
    ("M2", "M2_ATC_367_25", 367.250, 2007, 495, 221, 124, 840),
]

point_path = REFERENCE_DIR / "adb_traffic_counts_point_reference_2005_2007.csv"
point_fields = [
    "road_id", "count_station", "chainage_km", "year",
    "light_vehicles_per_day", "trucks_per_day", "truck_trailers_per_day",
    "total_vehicles_per_day", "source", "source_url", "notes",
]

# ADB completion report contains detailed vehicle classes for the 2009 count
# at M2 km16 and a 2012 base-year subsection estimate for M2 km13.1-28.9.
detail_rows = [
    {
        "record_id": "ADB_M2_KM16_2009",
        "road_id": "M2",
        "chainage_km": "16.0",
        "year": "2009",
        "cars_per_day": "7651",
        "pickups_per_day": "788",
        "minibuses_per_day": "688",
        "buses_per_day": "137",
        "two_axle_trucks_per_day": "373",
        "three_axle_trucks_per_day": "435",
        "four_plus_axle_trucks_per_day": "225",
        "truck_trailers_per_day": "",
        "total_vehicles_per_day": "10297",
        "source": "ADB North-South Road Corridor Investment Program Tranche 1 Completion Report, Appendix 9 Table 3",
        "source_url": ADB_PCR_URL,
        "notes": "Seasonally adjusted 2009 count; preserve vehicle classes as published; not a 2026 observation.",
    },
    {
        "record_id": "ADB_M1_SECTION3_2012_BASE",
        "road_id": "M1",
        "chainage_km": "",
        "year": "2012",
        "cars_per_day": "12179",
        "pickups_per_day": "830",
        "minibuses_per_day": "854",
        "buses_per_day": "655",
        "two_axle_trucks_per_day": "1353",
        "three_axle_trucks_per_day": "547",
        "four_plus_axle_trucks_per_day": "",
        "truck_trailers_per_day": "360",
        "total_vehicles_per_day": "16778",
        "source": "ADB North-South Road Corridor Investment Program Tranche 1 Completion Report, Appendix 9 Table 4",
        "source_url": ADB_PCR_URL,
        "notes": "M1 Section 3 aggregate; not an exact point chainage. Existing traffic_counts_historic.csv has the related M1 km20.7 ATC record.",
    },
    {
        "record_id": "ADB_M2_KM9_3_13_1_2012_BASE",
        "road_id": "M2",
        "chainage_km": "",
        "year": "2012",
        "cars_per_day": "22252",
        "pickups_per_day": "2293",
        "minibuses_per_day": "2001",
        "buses_per_day": "677",
        "two_axle_trucks_per_day": "1846",
        "three_axle_trucks_per_day": "2151",
        "four_plus_axle_trucks_per_day": "",
        "truck_trailers_per_day": "466",
        "total_vehicles_per_day": "31686",
        "source": "ADB North-South Road Corridor Investment Program Tranche 1 Completion Report, Appendix 9 Table 4",
        "source_url": ADB_PCR_URL,
        "notes": "M2 subsection km9.3-13.1; aggregate section count, not a single counter point. Existing traffic_counts_historic.csv has M2 km9.38 ATC.",
    },
    {
        "record_id": "ADB_M2_KM13_1_28_9_2012_BASE",
        "road_id": "M2",
        "chainage_km": "",
        "year": "2012",
        "cars_per_day": "10960",
        "pickups_per_day": "1129",
        "minibuses_per_day": "986",
        "buses_per_day": "196",
        "two_axle_trucks_per_day": "243",
        "three_axle_trucks_per_day": "283",
        "four_plus_axle_trucks_per_day": "",
        "truck_trailers_per_day": "146",
        "total_vehicles_per_day": "13942",
        "source": "ADB North-South Road Corridor Investment Program Tranche 1 Completion Report, Appendix 9 Table 4",
        "source_url": ADB_PCR_URL,
        "notes": "M2 subsection km13.1-28.9 base-year section estimate; distinct from the km16 2009 point count.",
    },
]

detail_path = REFERENCE_DIR / "adb_traffic_vehicle_class_reference.csv"
detail_fields = list(detail_rows[0].keys())

# Corridor-level / network-level context where exact traffic counter chainage
# is not supplied. These records are NOT spatial demand points for the MILP.
context_rows = [
    {
        "context_id": "ADB_M2_SISIAN_TATEV_KAPAN_2022",
        "road_id": "M2_CONTEXT",
        "route_description": "Road from Sisian via Tatev to Kapan, used for traffic to/from southern Armenia and the Iran border",
        "year": "2022",
        "measure": "average_annual_daily_traffic",
        "value_vehicles_per_day": "2500",
        "exact_chainage_km": "",
        "geographic_scope": "Route-level / exact counter location not specified in public project summary",
        "source": "Asian Development Bank, Resilient and Inclusive Road Sector Improvement Project (56317-001)",
        "source_url": ADB_56317_URL,
        "model_use": "External context and validation only; do not convert to a point demand without an identified counter location and vehicle-class split.",
    },
    {
        "context_id": "UNDP_ARMENIA_INTERSTATE_AADT_CONTEXT",
        "road_id": "NATIONAL_CONTEXT",
        "route_description": "Armenia interstate road network (national context, not a specific M1/M2 segment)",
        "year": "2024_report_using_ADB_2021_draft_strategy",
        "measure": "national_interstate_AADT_summary",
        "value_vehicles_per_day": "3600_average; range_less_than_100_to_23710",
        "exact_chainage_km": "",
        "geographic_scope": "National interstate network; not route-specific",
        "source": "UNDP/EU/Government of Armenia, Armenia Floods May 2024 PDNA, October 2024, transport section",
        "source_url": UNDP_URL,
        "model_use": "National context only; not used as M1/M2 demand or as a substitute for corridor counter data.",
    },
]
context_path = REFERENCE_DIR / "traffic_network_context_not_point_demand.csv"
context_fields = list(context_rows[0].keys())

readme_path = REFERENCE_DIR / "SUPPLEMENTAL_TRAFFIC_EVIDENCE_README.txt"
readme = f"""SUPPLEMENTAL ARMENIA TRAFFIC EVIDENCE\n===================================\n\nFiles created by add_supplemental_traffic_evidence.py\n\n1) {point_path.name}\n   Point counter records on M1/M2 from ADB's 2008 Armenia Transport Sector\n   Development Strategy, Table 4-2 (traffic volumes for 2005-2007). Includes\n   M2 km200.320 and km367.250, which broaden historical geographic coverage.\n   These observations are old and must not be treated as 2026 traffic.\n\n2) {detail_path.name}\n   Vehicle-class detail from the ADB North-South Tranche 1 Completion Report:\n   2009 M2 km16 count and 2012 base-year section traffic for M1 Section 3 and\n   the two M2 subsections. Section totals are not exact point-counter records.\n\n3) {context_path.name}\n   Context-only sources with no exact station chainage. ADB reports about\n   2,500 AADT in 2022 on the Sisian-Tatev-Kapan route used for traffic to/from\n   southern Armenia and the Iran border. UNDP's 2024 assessment summarizes\n   national interstate AADT context. Neither row is added to the MILP demand\n   matrix because a precise count location / compatible vehicle split is not\n   documented in the source summary.\n\nIMPORTANT MODELLING RULES\n-------------------------\n- The new reference files are supplemental evidence only. They do not change\n  traffic_counts_historic.csv, generated demand scenarios, distance matrices,\n  or any existing MILP results.\n- Do not append old 2005-2007 counts to the recent counter series and blindly\n  extrapolate them to 2026. M2's route alignment and operating context changed.\n- Do not map route-level AADT to a fabricated exact chainage.\n- The current demand model still represents three specific locations /\n  subsections, not the full M1/M2 corridor demand.\n\nSOURCES\n------\nADB Armenia Transport Sector Development Strategy (November 2008), Table 4-2:\n{ADB_2008_URL}\n\nADB North-South Road Corridor Investment Program Tranche 1 Completion Report\n(January 2020), Appendix 9 Tables 3-5:\n{ADB_PCR_URL}\n\nADB Resilient and Inclusive Road Sector Improvement Project (56317-001):\n{ADB_56317_URL}\n\nUNDP / Government of Armenia / EU, Armenia Floods May 2024 PDNA (October 2024),\ntransport section:\n{UNDP_URL}\n"""


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    if path.exists():
        # Idempotent: refuse to overwrite an existing file unless its contents match.
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            existing = list(csv.DictReader(f))
        normalised = [{k: str(row.get(k, "")) for k in fields} for row in rows]
        if existing == normalised:
            print(f"Already present (unchanged): {path}")
            return
        raise FileExistsError(
            f"Refusing to overwrite existing file with different contents: {path}. "
            "Back it up or rename it before rerunning."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Created: {path}")


def main() -> None:
    if not (ROOT / "data" / "reference").exists():
        raise FileNotFoundError("Run this script from the EV-Charging-M1-M2 project root.")
    write_csv(
        point_path,
        point_fields,
        [
            {
                "road_id": road,
                "count_station": station,
                "chainage_km": f"{chainage:.3f}",
                "year": year,
                "light_vehicles_per_day": light,
                "trucks_per_day": trucks,
                "truck_trailers_per_day": trailers,
                "total_vehicles_per_day": total,
                "source": "ADB Armenia Transport Sector Development Strategy (2008), Table 4-2",
                "source_url": ADB_2008_URL,
                "notes": "Historical M-route point count; not a current AADT observation. Use for historical context only.",
            }
            for road, station, chainage, year, light, trucks, trailers, total in point_rows
        ],
    )
    write_csv(detail_path, detail_fields, detail_rows)
    write_csv(context_path, context_fields, context_rows)
    if not readme_path.exists():
        readme_path.write_text(readme, encoding="utf-8")
        print(f"Created: {readme_path}")
    else:
        print(f"README already exists; left unchanged: {readme_path}")
    print("\nNo existing project inputs or MILP outputs were modified.")
    print("These records are supplemental references, not new model demand points.")


if __name__ == "__main__":
    main()

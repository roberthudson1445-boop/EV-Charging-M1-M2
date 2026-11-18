"""Convert documented AADT and explicit assumptions into daily kWh scenarios."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from ev_charging.demand_estimation import (
    TrafficDemandScenario,
    estimate_daily_charging_demand,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/raw/traffic_scenarios.csv")
    parser.add_argument("--output", default="data/raw/demand_points.csv")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")
    if output_path.exists() and not args.overwrite:
        raise SystemExit(f"Output already exists: {output_path}. Use --overwrite to replace it.")

    output_rows: list[dict[str, str]] = []
    with input_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {
            "demand_id", "aadt_vehicles_per_day", "ev_share",
            "charging_probability", "energy_per_session_kwh",
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"Input CSV is missing columns: {sorted(missing)}")
        for row in reader:
            scenario = TrafficDemandScenario(
                demand_id=row["demand_id"].strip(),
                aadt_vehicles_per_day=float(row["aadt_vehicles_per_day"]),
                ev_share=float(row["ev_share"]),
                charging_probability=float(row["charging_probability"]),
                energy_per_session_kwh=float(row["energy_per_session_kwh"]),
                aadt_year=int(row["aadt_year"]) if row.get("aadt_year", "").strip() else None,
                source=row.get("source", "").strip(),
            )
            daily_kwh = estimate_daily_charging_demand(scenario)
            output_rows.append(
                {
                    "demand_id": scenario.demand_id,
                    "latitude": row.get("latitude", "").strip(),
                    "longitude": row.get("longitude", "").strip(),
                    "demand_kwh_day": f"{daily_kwh:.6f}",
                    "source": scenario.source,
                    "notes": row.get("notes", "").strip()
                    + " | Scenario estimate: AADT x EV share x charging probability x kWh/session",
                }
            )

    if not output_rows:
        raise SystemExit("Input CSV has no scenario rows.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["demand_id", "latitude", "longitude", "demand_kwh_day", "source", "notes"],
        )
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"Created {len(output_rows)} demand scenarios in {output_path}")
    print("These are scenario estimates, not metered charging demand.")


if __name__ == "__main__":
    main()

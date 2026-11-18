"""CSV/JSON loading for documented EV charging case-study inputs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import numpy as np

from .data import ProblemData


REQUIRED_SITE_COLUMNS = {
    "site_id",
    "fixed_cost",
    "charger_cost",
    "max_chargers",
    "grid_capacity_kw",
    "power_cost_weight",
}
REQUIRED_DEMAND_COLUMNS = {"demand_id", "demand_kwh_day"}
REQUIRED_DISTANCE_COLUMNS = {"site_id", "demand_id", "distance_km"}
REQUIRED_CONFIG_KEYS = {
    "charger_daily_capacity_kwh",
    "max_service_distance_km",
    "charger_peak_power_kw",
    "budget",
    "distance_weight",
}


def _read_csv(path: Path, required_columns: set[str]) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Required data file not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = set(reader.fieldnames or [])
        missing = required_columns - columns
        if missing:
            raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{path.name} contains a header but no data rows.")
    return rows


def _number(row: dict[str, str], column: str, file_name: str) -> float:
    raw = row.get(column, "")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{file_name}: column '{column}' must contain a numeric value; got {raw!r}."
        ) from exc
    if not np.isfinite(value):
        raise ValueError(f"{file_name}: column '{column}' must be finite.")
    return value


def load_problem_from_csv(data_directory: str | Path) -> ProblemData:
    """Load a complete ``ProblemData`` instance from a case-data directory.

    Expected files:
      - sites.csv: site_id, fixed_cost, charger_cost, max_chargers,
        grid_capacity_kw, power_cost_weight
      - demand_points.csv: demand_id, demand_kwh_day
      - distances.csv: site_id, demand_id, distance_km (one row per pair)
      - config.json: charger capacity, service distance, charger power,
        budget, and distance weight

    Optional latitude/longitude/source columns may be kept in the CSV files
    for mapping and provenance; this loader leaves them untouched.
    """
    directory = Path(data_directory)
    site_rows = _read_csv(directory / "sites.csv", REQUIRED_SITE_COLUMNS)
    demand_rows = _read_csv(directory / "demand_points.csv", REQUIRED_DEMAND_COLUMNS)
    distance_rows = _read_csv(directory / "distances.csv", REQUIRED_DISTANCE_COLUMNS)

    config_path = directory / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Required configuration file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as stream:
        config: Any = json.load(stream)
    if not isinstance(config, dict):
        raise ValueError("config.json must contain a JSON object.")
    missing_config = REQUIRED_CONFIG_KEYS - set(config)
    if missing_config:
        raise ValueError(f"config.json is missing keys: {sorted(missing_config)}")

    site_names = tuple(row["site_id"].strip() for row in site_rows)
    demand_names = tuple(row["demand_id"].strip() for row in demand_rows)
    if any(not name for name in site_names) or len(set(site_names)) != len(site_names):
        raise ValueError("sites.csv must contain non-empty, unique site_id values.")
    if any(not name for name in demand_names) or len(set(demand_names)) != len(demand_names):
        raise ValueError("demand_points.csv must contain non-empty, unique demand_id values.")

    site_index = {name: index for index, name in enumerate(site_names)}
    demand_index = {name: index for index, name in enumerate(demand_names)}
    distance_matrix = np.full((len(site_names), len(demand_names)), np.nan, dtype=float)
    seen_pairs: set[tuple[str, str]] = set()
    for row in distance_rows:
        site_id = row["site_id"].strip()
        demand_id = row["demand_id"].strip()
        pair = (site_id, demand_id)
        if site_id not in site_index:
            raise ValueError(f"distances.csv references unknown site_id {site_id!r}.")
        if demand_id not in demand_index:
            raise ValueError(f"distances.csv references unknown demand_id {demand_id!r}.")
        if pair in seen_pairs:
            raise ValueError(f"distances.csv contains duplicate pair {pair!r}.")
        seen_pairs.add(pair)
        distance_matrix[site_index[site_id], demand_index[demand_id]] = _number(
            row, "distance_km", "distances.csv"
        )

    expected_pairs = len(site_names) * len(demand_names)
    if len(seen_pairs) != expected_pairs:
        missing_pairs = [
            (site, demand)
            for site in site_names
            for demand in demand_names
            if (site, demand) not in seen_pairs
        ]
        preview = missing_pairs[:5]
        raise ValueError(
            f"distances.csv must contain all {expected_pairs} site-demand pairs; "
            f"missing {len(missing_pairs)} (examples: {preview})."
        )

    try:
        max_chargers_float = np.array(
            [_number(row, "max_chargers", "sites.csv") for row in site_rows],
            dtype=float,
        )
    except ValueError:
        raise
    if np.any(max_chargers_float != np.floor(max_chargers_float)):
        raise ValueError("sites.csv max_chargers values must be integers.")

    def config_number(key: str) -> float:
        try:
            value = float(config[key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"config.json key '{key}' must be numeric.") from exc
        if not np.isfinite(value):
            raise ValueError(f"config.json key '{key}' must be finite.")
        return value

    problem = ProblemData(
        site_names=site_names,
        demand_names=demand_names,
        demand_kwh_day=np.array(
            [_number(row, "demand_kwh_day", "demand_points.csv") for row in demand_rows],
            dtype=float,
        ),
        distance_km=distance_matrix,
        fixed_cost=np.array(
            [_number(row, "fixed_cost", "sites.csv") for row in site_rows], dtype=float
        ),
        charger_cost=np.array(
            [_number(row, "charger_cost", "sites.csv") for row in site_rows], dtype=float
        ),
        charger_daily_capacity_kwh=config_number("charger_daily_capacity_kwh"),
        max_chargers=max_chargers_float.astype(np.int64),
        grid_capacity_kw=np.array(
            [_number(row, "grid_capacity_kw", "sites.csv") for row in site_rows],
            dtype=float,
        ),
        max_service_distance_km=config_number("max_service_distance_km"),
        charger_peak_power_kw=config_number("charger_peak_power_kw"),
        budget=config_number("budget"),
        distance_weight=config_number("distance_weight"),
        power_cost_weight=np.array(
            [_number(row, "power_cost_weight", "sites.csv") for row in site_rows],
            dtype=float,
        ),
    )
    problem.validate()
    return problem

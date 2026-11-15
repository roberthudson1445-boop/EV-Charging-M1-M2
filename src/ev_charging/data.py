"""Problem data structures and a small synthetic example."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class ProblemData:
    """Numerical inputs for the EV charging-station MILP.

    Arrays use the order of ``site_names`` and ``demand_names``.
    ``distance_km[i, j]`` is the one-way road/detour distance from site i
    to demand point j. ``grid_capacity_kw`` is active power (kW), not kVA.
    """

    site_names: tuple[str, ...]
    demand_names: tuple[str, ...]
    demand_kwh_day: FloatArray
    distance_km: FloatArray
    fixed_cost: FloatArray
    charger_cost: FloatArray
    charger_daily_capacity_kwh: float
    max_chargers: NDArray[np.int64]
    grid_capacity_kw: FloatArray
    max_service_distance_km: float
    charger_peak_power_kw: float
    budget: float
    distance_weight: float
    power_cost_weight: FloatArray

    def validate(self) -> None:
        """Raise ValueError when inputs are inconsistent or physically invalid."""
        n = len(self.site_names)
        m = len(self.demand_names)
        if n == 0 or m == 0:
            raise ValueError("At least one site and one demand point are required.")
        if len(set(self.site_names)) != n:
            raise ValueError("Site names must be unique.")
        if len(set(self.demand_names)) != m:
            raise ValueError("Demand-point names must be unique.")

        expected_shapes = {
            "demand_kwh_day": (m,),
            "distance_km": (n, m),
            "fixed_cost": (n,),
            "charger_cost": (n,),
            "max_chargers": (n,),
            "grid_capacity_kw": (n,),
            "power_cost_weight": (n,),
        }
        for field_name, expected in expected_shapes.items():
            actual = np.asarray(getattr(self, field_name)).shape
            if actual != expected:
                raise ValueError(
                    f"{field_name} must have shape {expected}; got {actual}."
                )

        nonnegative_fields = (
            "demand_kwh_day",
            "distance_km",
            "fixed_cost",
            "charger_cost",
            "grid_capacity_kw",
            "power_cost_weight",
        )
        for field_name in nonnegative_fields:
            values = np.asarray(getattr(self, field_name), dtype=float)
            if not np.all(np.isfinite(values)) or np.any(values < 0):
                raise ValueError(f"{field_name} must contain finite non-negative values.")

        if np.any(np.asarray(self.demand_kwh_day) <= 0):
            raise ValueError("Every demand point must have strictly positive demand.")
        max_chargers = np.asarray(self.max_chargers)
        if np.any(max_chargers < 0) or np.any(max_chargers != np.floor(max_chargers)):
            raise ValueError("max_chargers must contain non-negative integers.")

        positive_scalars = {
            "charger_daily_capacity_kwh": self.charger_daily_capacity_kwh,
            "max_service_distance_km": self.max_service_distance_km,
            "charger_peak_power_kw": self.charger_peak_power_kw,
        }
        for name, value in positive_scalars.items():
            if not np.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and greater than zero.")
        if not np.isfinite(self.budget) or self.budget < 0:
            raise ValueError("budget must be finite and non-negative.")
        if not np.isfinite(self.distance_weight) or self.distance_weight < 0:
            raise ValueError("distance_weight must be finite and non-negative.")


def make_toy_problem() -> ProblemData:
    """Return a two-site/two-demand synthetic case for testing only.

    The data are deliberately illustrative and are not measured Armenian data.
    """
    problem = ProblemData(
        site_names=("A", "B"),
        demand_names=("D1", "D2"),
        demand_kwh_day=np.array([900.0, 800.0]),
        # Rows are sites A/B; columns are demand points D1/D2.
        distance_km=np.array(
            [
                [10.0, 100.0],
                [50.0, 20.0],
            ]
        ),
        fixed_cost=np.array([1_000.0, 10_000.0]),
        charger_cost=np.array([3_000.0, 3_000.0]),
        charger_daily_capacity_kwh=1_000.0,
        max_chargers=np.array([2, 2], dtype=np.int64),
        # Active power in kW. Do not enter kVA here without conversion.
        grid_capacity_kw=np.array([300.0, 300.0]),
        max_service_distance_km=85.0,
        charger_peak_power_kw=150.0,
        budget=18_000.0,
        distance_weight=0.1,
        power_cost_weight=np.array([5.0, 5.0]),
    )
    problem.validate()
    return problem

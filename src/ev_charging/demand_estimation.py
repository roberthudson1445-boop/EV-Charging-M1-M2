"""Scenario-based conversion of traffic counts into charging-energy demand."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class TrafficDemandScenario:
    """Inputs for an explicitly assumed daily charging-demand estimate."""

    demand_id: str
    aadt_vehicles_per_day: float
    ev_share: float
    charging_probability: float
    energy_per_session_kwh: float
    aadt_year: int | None = None
    source: str = ""

    def validate(self) -> None:
        if not self.demand_id.strip():
            raise ValueError("demand_id cannot be empty.")
        if not np.isfinite(self.aadt_vehicles_per_day) or self.aadt_vehicles_per_day < 0:
            raise ValueError("AADT must be a finite non-negative number.")
        for name, value in (
            ("ev_share", self.ev_share),
            ("charging_probability", self.charging_probability),
        ):
            if not np.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be between zero and one.")
        if not np.isfinite(self.energy_per_session_kwh) or self.energy_per_session_kwh < 0:
            raise ValueError("energy_per_session_kwh must be finite and non-negative.")
        if self.aadt_year is not None and self.aadt_year < 1900:
            raise ValueError("aadt_year is not a plausible calendar year.")


def estimate_daily_charging_demand(scenario: TrafficDemandScenario) -> float:
    """Estimate kWh/day from AADT and stated scenario assumptions.

    Formula:
        demand_kwh_day = AADT * EV_share * charging_probability
                         * energy_per_session_kwh

    This is a scenario estimate, not a measured charging load. The AADT
    definition, direction coverage, route segment, EV share, charging
    probability, and energy-per-session assumptions must be documented.
    """
    scenario.validate()
    return float(
        scenario.aadt_vehicles_per_day
        * scenario.ev_share
        * scenario.charging_probability
        * scenario.energy_per_session_kwh
    )

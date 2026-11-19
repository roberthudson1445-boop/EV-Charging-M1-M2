"""Problem data structures and a small synthetic example."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class ProblemData:
    """Numerical inputs for the EV charging-station MILP.

    Arrays use the order of ``site_names`` and ``demand_names``.
    ``distance_km[i, j]`` is the one-way service distance for assigning demand
    point j to charging site i. In the directed Armenia corridor case, this is
    the shortest-path driving distance from demand point j to site i, so it
    respects the direction of travel on the road network. ``grid_capacity_kw``
    is active power (kW), not kVA.
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
    # Optional corridor metadata. When supplied, the model enforces a maximum
    # distance between consecutive open stations, including route endpoints.
    site_route_ids: tuple[str, ...] | None = None
    site_chainage_km: FloatArray | None = None
    route_lengths_km: Mapping[str, float] | None = None
    max_interstation_distance_km: float | None = None

    def interstation_gap_rows(
        self,
    ) -> tuple[tuple[tuple[tuple[int, float], ...], float], ...]:
        """Return linear rows enforcing the maximum open-station route gap.

        Each returned pair is ``(coefficients, rhs)`` for an inequality
        ``sum(coeff * y[site_index]) <= rhs``. For every pair of route
        positions farther apart than the allowed gap, at least one open site
        must lie strictly between them. Route start and end are treated as
        always-present boundary positions.

        The pairwise rows are exact for ordered candidate sites: if two
        selected sites (or a route endpoint and a selected site) are more
        than the allowed distance apart, an intermediate selected site is
        required. The endpoint-to-endpoint row also requires an interior site
        whenever the route itself is longer than the allowed gap.
        """
        if self.max_interstation_distance_km is None:
            return ()

        assert self.site_route_ids is not None
        assert self.site_chainage_km is not None
        assert self.route_lengths_km is not None

        max_gap = float(self.max_interstation_distance_km)
        chainage = np.asarray(self.site_chainage_km, dtype=float)
        rows: list[tuple[tuple[tuple[int, float], ...], float]] = []
        tolerance = 1e-9

        for route_id, route_length_raw in sorted(self.route_lengths_km.items()):
            route_length = float(route_length_raw)
            route_sites = [
                (float(chainage[i]), i)
                for i, candidate_route in enumerate(self.site_route_ids)
                if candidate_route == route_id
            ]
            route_sites.sort(key=lambda item: (item[0], item[1]))

            # Group sites at the same chainage. A co-located site is not an
            # intermediate site and must not artificially split a route gap.
            groups: list[tuple[float, list[int]]] = []
            for position, site_index in route_sites:
                if groups and abs(position - groups[-1][0]) <= tolerance:
                    groups[-1][1].append(site_index)
                else:
                    groups.append((position, [site_index]))

            # Route start (chainage 0) to each candidate position.
            for right_position, right_sites in groups:
                if right_position > max_gap + tolerance:
                    middle = [
                        i
                        for position, indices in groups
                        if tolerance < position < right_position - tolerance
                        for i in indices
                    ]
                    for right in right_sites:
                        coefficients = [(right, 1.0)] + [(i, -1.0) for i in middle]
                        rows.append((tuple(coefficients), 0.0))

            # Every pair of distinct candidate positions.
            for left_group_index, (left_position, left_sites) in enumerate(groups):
                for right_position, right_sites in groups[left_group_index + 1 :]:
                    if right_position - left_position <= max_gap + tolerance:
                        continue
                    middle = [
                        i
                        for position, indices in groups
                        if left_position + tolerance < position < right_position - tolerance
                        for i in indices
                    ]
                    for left in left_sites:
                        for right in right_sites:
                            coefficients = (
                                [(left, 1.0), (right, 1.0)]
                                + [(i, -1.0) for i in middle]
                            )
                            rows.append((tuple(coefficients), 1.0))

            # Each candidate position to the route end (always present).
            for left_position, left_sites in groups:
                if route_length - left_position > max_gap + tolerance:
                    middle = [
                        i
                        for position, indices in groups
                        if left_position + tolerance < position < route_length - tolerance
                        for i in indices
                    ]
                    for left in left_sites:
                        coefficients = [(left, 1.0)] + [(i, -1.0) for i in middle]
                        rows.append((tuple(coefficients), 0.0))

            # The two route endpoints are also a pair. If the corridor is
            # longer than the allowed gap, at least one candidate must be
            # selected strictly inside the endpoints.
            if route_length > max_gap + tolerance:
                interior = [
                    i
                    for position, indices in groups
                    if tolerance < position < route_length - tolerance
                    for i in indices
                ]
                rows.append((tuple((i, -1.0) for i in interior), -1.0))

        return tuple(rows)

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

        route_fields = (
            self.site_route_ids,
            self.site_chainage_km,
            self.route_lengths_km,
            self.max_interstation_distance_km,
        )
        if all(value is None for value in route_fields):
            return
        if any(value is None for value in route_fields):
            raise ValueError(
                "Interstation-gap data must include site_route_ids, "
                "site_chainage_km, route_lengths_km, and "
                "max_interstation_distance_km together."
            )

        assert self.site_route_ids is not None
        assert self.site_chainage_km is not None
        assert self.route_lengths_km is not None
        if len(self.site_route_ids) != n:
            raise ValueError(f"site_route_ids must have length {n}.")
        if any(not isinstance(route_id, str) or not route_id.strip() for route_id in self.site_route_ids):
            raise ValueError("site_route_ids must contain non-empty route identifiers.")

        chainage = np.asarray(self.site_chainage_km, dtype=float)
        if chainage.shape != (n,):
            raise ValueError(f"site_chainage_km must have shape ({n},); got {chainage.shape}.")
        if not np.all(np.isfinite(chainage)) or np.any(chainage < 0):
            raise ValueError("site_chainage_km must contain finite non-negative values.")

        if not isinstance(self.route_lengths_km, Mapping) or not self.route_lengths_km:
            raise ValueError("route_lengths_km must be a non-empty mapping.")
        route_lengths: dict[str, float] = {}
        for route_id, raw_length in self.route_lengths_km.items():
            if not isinstance(route_id, str) or not route_id.strip():
                raise ValueError("route_lengths_km keys must be non-empty route identifiers.")
            try:
                length = float(raw_length)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Route length for {route_id!r} must be numeric.") from exc
            if not np.isfinite(length) or length <= 0:
                raise ValueError(f"Route length for {route_id!r} must be finite and positive.")
            route_lengths[route_id] = length

        unknown_routes = set(self.site_route_ids) - set(route_lengths)
        if unknown_routes:
            raise ValueError(
                "site_route_ids contain routes missing from route_lengths_km: "
                f"{sorted(unknown_routes)}."
            )
        for i, route_id in enumerate(self.site_route_ids):
            if chainage[i] > route_lengths[route_id] + 1e-6:
                raise ValueError(
                    f"Site {self.site_names[i]!r} chainage exceeds the length "
                    f"of route {route_id!r}."
                )

        max_gap = self.max_interstation_distance_km
        if max_gap is None or not np.isfinite(max_gap) or max_gap <= 0:
            raise ValueError("max_interstation_distance_km must be finite and positive.")


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

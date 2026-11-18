"""Run the EV toy LP relaxation through GMI cuts and Dual Simplex."""

from __future__ import annotations

import numpy as np

from ev_charging.data import make_toy_problem
from ev_charging.gomory import solve_with_gomory_cuts
from ev_charging.lp_relaxation import solve_ev_lp_relaxation
from ev_charging.model import solve_milp


def main() -> None:
    problem = make_toy_problem()
    relaxation = solve_ev_lp_relaxation(problem)
    site_count = len(problem.site_names)

    # Variable order in the EV model: y[0:n], z[0:n], P[0:n], x[0:n*m].
    integer_indices = list(range(2 * site_count))
    custom = solve_with_gomory_cuts(
        relaxation.lp_result,
        integer_variable_indices=integer_indices,
        max_cuts=100,
    )
    benchmark = solve_milp(problem)

    print("EV charging synthetic example")
    print(f"Initial LP relaxation objective: {relaxation.lp_result.objective_value:.6f}")
    print(f"Gomory status: {custom.status}")
    print(f"Gomory cuts added: {len(custom.cuts)}")
    print(f"Dual Simplex iterations: {custom.dual_simplex_iterations}")
    print(f"Custom cutting-plane objective: {custom.lp_result.objective_value:.6f}")
    print(f"HiGHS MILP objective: {benchmark.objective_value:.6f}")
    print("Custom integer variables:")
    print(f"  y = {custom.lp_result.x[:site_count]}")
    print(f"  z = {custom.lp_result.x[site_count:2 * site_count]}")
    print("HiGHS integer variables:")
    print(f"  y = {benchmark.opened}")
    print(f"  z = {benchmark.chargers}")

    if custom.status != "integer_optimal":
        raise SystemExit(custom.message)
    if custom.lp_result.x is None:
        raise SystemExit("The custom solver returned no decision vector.")

    vector = custom.lp_result.x
    y = vector[:site_count]
    z = vector[site_count : 2 * site_count]
    power = vector[2 * site_count : 3 * site_count]
    assignment = vector[3 * site_count :].reshape(site_count, len(problem.demand_names))

    # Validate integrality and the original EV constraints independently.
    if not np.allclose(y, np.rint(y), atol=1e-7):
        raise SystemExit("Station-selection variables are not integral.")
    if not np.allclose(z, np.rint(z), atol=1e-7):
        raise SystemExit("Charger-count variables are not integral.")
    np.testing.assert_allclose(assignment.sum(axis=0), 1.0, atol=1e-7)
    if np.any(assignment - y[:, None] > 1e-7):
        raise SystemExit("Station-coupling constraint was violated.")
    if np.any(assignment[problem.distance_km > problem.max_service_distance_km] > 1e-7):
        raise SystemExit("A demand point was assigned to an unreachable station.")
    served = assignment @ problem.demand_kwh_day
    if np.any(served - problem.charger_daily_capacity_kwh * z > 1e-7):
        raise SystemExit("A charger-throughput constraint was violated.")
    if np.any(z - problem.max_chargers * y > 1e-7):
        raise SystemExit("A site-sizing constraint was violated.")
    np.testing.assert_allclose(power, problem.charger_peak_power_kw * z, atol=1e-7)
    if np.any(power - problem.grid_capacity_kw * y > 1e-7):
        raise SystemExit("An electrical-capacity constraint was violated.")
    capital = float(problem.fixed_cost @ y + problem.charger_cost @ z)
    if capital > problem.budget + 1e-7:
        raise SystemExit("The capital budget constraint was violated.")
    if abs(custom.lp_result.objective_value - benchmark.objective_value) > 1e-6:
        raise SystemExit("Custom cutting-plane objective does not match the HiGHS benchmark.")

    print("All original EV constraints passed.")
    print("Validation passed: custom GMI + Dual Simplex matches the HiGHS MILP objective.")


if __name__ == "__main__":
    main()

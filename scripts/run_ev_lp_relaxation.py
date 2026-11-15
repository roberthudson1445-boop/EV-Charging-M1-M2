"""Solve the EV charging LP relaxation with the in-house Revised Simplex."""

from __future__ import annotations

from ev_charging import make_toy_problem
from ev_charging.lp_relaxation import solve_ev_lp_relaxation


def main() -> None:
    problem = make_toy_problem()
    result = solve_ev_lp_relaxation(problem)
    print("=== EV charging LP relaxation (synthetic data) ===")
    print(f"Status: {result.lp_result.status}")
    print(f"Objective value: {result.lp_result.objective_value:.6f}")
    print(f"Iterations: {result.lp_result.iterations}")
    print("Relaxed station-selection variables:")
    for name, value in zip(problem.site_names, result.opened_relaxed):
        print(f"  y_{name} = {value:.6f}")
    print("Relaxed charger-count variables:")
    for name, value in zip(problem.site_names, result.chargers_relaxed):
        print(f"  z_{name} = {value:.6f}")
    print("Assignment matrix (rows=sites, columns=demand points):")
    print(result.assignment)
    print("\nNote: fractional y/z values are permitted only in the LP relaxation.")
    print("They are not final implementable station decisions.")


if __name__ == "__main__":
    main()

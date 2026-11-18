"""Run a non-trivial convex quadratic power-loss allocation example."""

from __future__ import annotations

import numpy as np

from ev_charging.data import ProblemData
from ev_charging.lp_relaxation import solve_ev_lp_relaxation
from ev_charging.quadratic_extension import solve_ev_quadratic_relaxation


def make_quadratic_demo_problem() -> ProblemData:
    """Return an illustrative case where the QP trades distance for lower losses."""
    problem = ProblemData(
        site_names=("A", "B"),
        demand_names=("D1", "D2"),
        demand_kwh_day=np.array([900.0, 900.0]),
        distance_km=np.array([[10.0, 10.0], [20.0, 20.0]]),
        fixed_cost=np.array([5_000.0, 5_000.0]),
        charger_cost=np.array([1_000.0, 1_000.0]),
        charger_daily_capacity_kwh=1_000.0,
        max_chargers=np.array([2, 2], dtype=np.int64),
        grid_capacity_kw=np.array([300.0, 300.0]),
        max_service_distance_km=85.0,
        charger_peak_power_kw=150.0,
        budget=20_000.0,
        distance_weight=0.001,
        power_cost_weight=np.array([0.1, 0.1]),
    )
    problem.validate()
    return problem


def main() -> None:
    problem = make_quadratic_demo_problem()
    lp = solve_ev_lp_relaxation(problem)
    result = solve_ev_quadratic_relaxation(
        problem,
        # Illustrative equivalent feeder parameters only; not ENA measurements.
        line_resistance_ohm=np.array([1.0, 0.01]),
        nominal_voltage_kv=np.array([10.0, 10.0]),
        loss_cost_per_kw=np.array([1_000.0, 1_000.0]),
    )
    if not result.success:
        raise SystemExit(f"Quadratic relaxation failed: {result.message}")

    n = len(problem.site_names)
    m = len(problem.demand_names)
    start_x = 3 * n
    assignment = result.solution[start_x : start_x + n * m].reshape(n, m)

    print("=== Convex quadratic power-loss extension (synthetic data) ===")
    print(f"LP relaxation objective: {lp.lp_result.objective_value:.6f}")
    print(f"QP linear-cost component at QP solution: {result.linear_objective_value:.6f}")
    print(f"Total estimated line loss: {result.total_power_loss_kw:.6f} kW")
    print(f"Loss penalty: {result.loss_cost:.6f} illustrative cost units")
    print(f"Quadratic objective: {result.objective_value:.6f}")
    print("Demand allocation after adding the loss penalty:")
    for i, site in enumerate(problem.site_names):
        print(f"  {site}: {assignment[i].round(4).tolist()}")
    print("Approximate KKT diagnostics")
    print(f"  primal feasibility infinity norm: {result.kkt.primal_feasibility_inf:.3e}")
    print(f"  stationarity infinity norm:       {result.kkt.stationarity_inf:.3e}")
    print(f"  dual-feasibility violation:       {result.kkt.dual_feasibility_violation:.3e}")
    print(f"  complementarity infinity norm:   {result.kkt.complementarity_inf:.3e}")
    print("Note: continuous relaxation only; all resistance, voltage and cost inputs are illustrative.")


if __name__ == "__main__":
    main()

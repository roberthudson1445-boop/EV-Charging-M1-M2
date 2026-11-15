"""Build and solve the continuous LP relaxation of the EV charging model."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .data import ProblemData
from .revised_simplex import LPResult, solve_lp

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class EVLPRelaxationResult:
    """Parsed LP-relaxation solution for the EV charging problem."""

    lp_result: LPResult
    opened_relaxed: FloatArray
    chargers_relaxed: FloatArray
    power_kw: FloatArray
    assignment: FloatArray
    variable_names: tuple[str, ...]


def solve_ev_lp_relaxation(problem: ProblemData) -> EVLPRelaxationResult:
    """Solve the EV model after relaxing integer restrictions on y and z.

    This uses the project's own two-phase Revised Simplex implementation.
    The relaxation permits fractional station-selection and charger-count
    values for analysis; those values are not implementable final decisions.
    """
    problem.validate()
    n = len(problem.site_names)
    m = len(problem.demand_names)

    # Variable order: y[0:n], z[0:n], P[0:n], x[0:n*m].
    y0, z0, p0, x0 = 0, n, 2 * n, 3 * n
    number_of_variables = 3 * n + n * m

    def x_index(i: int, j: int) -> int:
        return x0 + i * m + j

    objective = np.zeros(number_of_variables, dtype=float)
    names: list[str] = []
    for i, name in enumerate(problem.site_names):
        objective[y0 + i] = problem.fixed_cost[i]
        names.append(f"y_{name}")
    for i, name in enumerate(problem.site_names):
        objective[z0 + i] = problem.charger_cost[i]
        names.append(f"z_{name}")
    for i, name in enumerate(problem.site_names):
        objective[p0 + i] = problem.power_cost_weight[i]
        names.append(f"P_{name}")
    for i, site in enumerate(problem.site_names):
        for j, demand in enumerate(problem.demand_names):
            objective[x_index(i, j)] = (
                problem.distance_weight
                * problem.demand_kwh_day[j]
                * problem.distance_km[i, j]
            )
            names.append(f"x_{site}_{demand}")

    ub_rows: list[FloatArray] = []
    ub_rhs: list[float] = []
    eq_rows: list[FloatArray] = []
    eq_rhs: list[float] = []

    # Full demand assignment: sum_i x_ij = 1.
    for j in range(m):
        row = np.zeros(number_of_variables)
        for i in range(n):
            row[x_index(i, j)] = 1.0
        eq_rows.append(row)
        eq_rhs.append(1.0)

    # x_ij <= y_i; unreachable pairs are fixed to zero by equality.
    for i in range(n):
        for j in range(m):
            row = np.zeros(number_of_variables)
            if problem.distance_km[i, j] > problem.max_service_distance_km:
                row[x_index(i, j)] = 1.0
                eq_rows.append(row)
                eq_rhs.append(0.0)
            else:
                row[x_index(i, j)] = 1.0
                row[y0 + i] = -1.0
                ub_rows.append(row)
                ub_rhs.append(0.0)

    # Charger throughput: sum_j d_j*x_ij - Q*z_i <= 0.
    for i in range(n):
        row = np.zeros(number_of_variables)
        for j in range(m):
            row[x_index(i, j)] = problem.demand_kwh_day[j]
        row[z0 + i] = -problem.charger_daily_capacity_kwh
        ub_rows.append(row)
        ub_rhs.append(0.0)

    # Site sizing: z_i - K_i*y_i <= 0.
    for i in range(n):
        row = np.zeros(number_of_variables)
        row[z0 + i] = 1.0
        row[y0 + i] = -float(problem.max_chargers[i])
        ub_rows.append(row)
        ub_rhs.append(0.0)

    # Power relation P_i - gamma*z_i = 0 and grid capacity.
    for i in range(n):
        row = np.zeros(number_of_variables)
        row[p0 + i] = 1.0
        row[z0 + i] = -problem.charger_peak_power_kw
        eq_rows.append(row)
        eq_rhs.append(0.0)

        row = np.zeros(number_of_variables)
        row[p0 + i] = 1.0
        row[y0 + i] = -problem.grid_capacity_kw[i]
        ub_rows.append(row)
        ub_rhs.append(0.0)

    # Capital budget.
    row = np.zeros(number_of_variables)
    for i in range(n):
        row[y0 + i] = problem.fixed_cost[i]
        row[z0 + i] = problem.charger_cost[i]
    ub_rows.append(row)
    ub_rhs.append(problem.budget)

    # Relaxed binary bound 0 <= y_i <= 1.
    for i in range(n):
        row = np.zeros(number_of_variables)
        row[y0 + i] = 1.0
        ub_rows.append(row)
        ub_rhs.append(1.0)

    A_ub = np.vstack(ub_rows) if ub_rows else None
    b_ub = np.asarray(ub_rhs, dtype=float) if ub_rows else None
    A_eq = np.vstack(eq_rows) if eq_rows else None
    b_eq = np.asarray(eq_rhs, dtype=float) if eq_rows else None

    result = solve_lp(objective, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq)
    if result.status != "optimal" or result.x is None:
        raise RuntimeError(f"LP relaxation failed: {result.status}: {result.message}")

    vector = result.x
    return EVLPRelaxationResult(
        lp_result=result,
        opened_relaxed=vector[y0 : y0 + n].copy(),
        chargers_relaxed=vector[z0 : z0 + n].copy(),
        power_kw=vector[p0 : p0 + n].copy(),
        assignment=vector[x0:].reshape(n, m).copy(),
        variable_names=tuple(names),
    )

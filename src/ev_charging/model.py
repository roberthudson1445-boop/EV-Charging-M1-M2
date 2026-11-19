"""MILP formulation solved through SciPy's HiGHS interface."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from .data import ProblemData

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class OptimizationResult:
    """Parsed solution returned by the MILP solver."""

    objective_value: float
    opened: NDArray[np.int64]
    chargers: NDArray[np.int64]
    assignment: FloatArray
    power_kw: FloatArray
    objective_breakdown: dict[str, float]
    solver_status: int
    solver_message: str
    mip_gap: float | None = None
    mip_node_count: int | None = None
    mip_dual_bound: float | None = None


def _indices(n: int, m: int) -> tuple[int, int, int, int]:
    """Return start offsets for y, z, P, and x blocks in the decision vector."""
    y_start = 0
    z_start = n
    p_start = 2 * n
    x_start = 3 * n
    return y_start, z_start, p_start, x_start


def _x_index(x_start: int, m: int, i: int, j: int) -> int:
    return x_start + i * m + j


def solve_milp(
    problem: ProblemData,
    *,
    mip_rel_gap: float = 0.0,
    time_limit_seconds: float | None = None,
) -> OptimizationResult:
    """Solve the MILP using SciPy/HiGHS.

    ``mip_rel_gap`` is the requested relative MIP optimality gap. The default
    0.0 preserves an exact-optimality request. For larger screening cases, a
    small positive gap can reduce solve time; the actual achieved gap is
    returned in ``OptimizationResult.mip_gap``. ``time_limit_seconds`` is an
    optional wall-clock limit. A run that stops without HiGHS status 0 is
    reported as a failure rather than being mislabeled as optimal.

    This is the project baseline/benchmark solver. It is not the planned
    from-scratch Revised Simplex + Gomory + Dual Simplex implementation.
    """
    if not np.isfinite(mip_rel_gap) or mip_rel_gap < 0:
        raise ValueError("mip_rel_gap must be finite and non-negative.")
    if time_limit_seconds is not None and (
        not np.isfinite(time_limit_seconds) or time_limit_seconds <= 0
    ):
        raise ValueError("time_limit_seconds must be finite and greater than zero.")

    problem.validate()
    n = len(problem.site_names)
    m = len(problem.demand_names)
    y_start, z_start, p_start, x_start = _indices(n, m)
    num_vars = 3 * n + n * m

    objective = np.zeros(num_vars, dtype=float)
    lower_bounds = np.zeros(num_vars, dtype=float)
    upper_bounds = np.full(num_vars, np.inf, dtype=float)
    integrality = np.zeros(num_vars, dtype=np.int32)

    # Station-open variables y_i (binary).
    for i in range(n):
        idx = y_start + i
        objective[idx] = problem.fixed_cost[i]
        upper_bounds[idx] = 1.0
        integrality[idx] = 1

    # Charger-count variables z_i (non-negative integer).
    for i in range(n):
        idx = z_start + i
        objective[idx] = problem.charger_cost[i]
        upper_bounds[idx] = float(problem.max_chargers[i])
        integrality[idx] = 1

    # Reserved active-power variables P_i (kW).
    for i in range(n):
        idx = p_start + i
        objective[idx] = problem.power_cost_weight[i]
        upper_bounds[idx] = float(problem.grid_capacity_kw[i])

    # Assignment variables x_ij. Ineligible pairs are fixed to zero.
    for i in range(n):
        for j in range(m):
            idx = _x_index(x_start, m, i, j)
            objective[idx] = (
                problem.distance_weight
                * problem.demand_kwh_day[j]
                * problem.distance_km[i, j]
            )
            if problem.distance_km[i, j] <= problem.max_service_distance_km:
                upper_bounds[idx] = 1.0
            else:
                upper_bounds[idx] = 0.0

    # Constraint matrix in sparse coordinate form.
    row_indices: list[int] = []
    col_indices: list[int] = []
    values: list[float] = []
    row_lower: list[float] = []
    row_upper: list[float] = []
    row = 0

    def add_row(entries: list[tuple[int, float]], lb: float, ub: float) -> None:
        nonlocal row
        for col, value in entries:
            if value != 0.0:
                row_indices.append(row)
                col_indices.append(col)
                values.append(float(value))
        row_lower.append(float(lb))
        row_upper.append(float(ub))
        row += 1

    # 1) Full demand assignment: sum_i x_ij = 1 for each demand point j.
    for j in range(m):
        entries = [(_x_index(x_start, m, i, j), 1.0) for i in range(n)]
        add_row(entries, 1.0, 1.0)

    # 2) Station coupling: x_ij - y_i <= 0.
    # 3) Reachability is enforced by x_ij upper bounds set above.
    for i in range(n):
        for j in range(m):
            entries = [
                (_x_index(x_start, m, i, j), 1.0),
                (y_start + i, -1.0),
            ]
            add_row(entries, -np.inf, 0.0)

    # 4) Charger throughput: sum_j d_j*x_ij - Q*z_i <= 0.
    for i in range(n):
        entries = [
            (_x_index(x_start, m, i, j), problem.demand_kwh_day[j])
            for j in range(m)
        ]
        entries.append((z_start + i, -problem.charger_daily_capacity_kwh))
        add_row(entries, -np.inf, 0.0)

    # 5) Physical site sizing: z_i - K_i*y_i <= 0.
    # An opened station must contain at least one charger: y_i - z_i <= 0.
    # This prevents a zero-charger site from satisfying corridor spacing.
    for i in range(n):
        entries = [
            (z_start + i, 1.0),
            (y_start + i, -float(problem.max_chargers[i])),
        ]
        add_row(entries, -np.inf, 0.0)
        add_row([(y_start + i, 1.0), (z_start + i, -1.0)], -np.inf, 0.0)

    # 6a) Charger count to active power: P_i - gamma*z_i = 0.
    for i in range(n):
        entries = [
            (p_start + i, 1.0),
            (z_start + i, -problem.charger_peak_power_kw),
        ]
        add_row(entries, 0.0, 0.0)

    # 6b) Grid capacity: P_i - Smax_i*y_i <= 0.
    for i in range(n):
        entries = [
            (p_start + i, 1.0),
            (y_start + i, -problem.grid_capacity_kw[i]),
        ]
        add_row(entries, -np.inf, 0.0)

    # 7) Capital budget: sum_i (f_i*y_i + g_i*z_i) <= B.
    budget_entries: list[tuple[int, float]] = []
    for i in range(n):
        budget_entries.extend(
            [
                (y_start + i, problem.fixed_cost[i]),
                (z_start + i, problem.charger_cost[i]),
            ]
        )
    add_row(budget_entries, -np.inf, problem.budget)

    # 8) Maximum distance between consecutive open stations on each corridor.
    # Route endpoints are fixed boundaries; only station-open variables appear.
    for gap_entries, rhs in problem.interstation_gap_rows():
        add_row(
            [(y_start + site_index, coefficient) for site_index, coefficient in gap_entries],
            -np.inf,
            rhs,
        )

    matrix = coo_matrix(
        (values, (row_indices, col_indices)), shape=(row, num_vars)
    ).tocsr()

    solver_options: dict[str, float | bool] = {
        "disp": False,
        "mip_rel_gap": float(mip_rel_gap),
    }
    if time_limit_seconds is not None:
        solver_options["time_limit"] = float(time_limit_seconds)

    result = milp(
        c=objective,
        integrality=integrality,
        bounds=Bounds(lower_bounds, upper_bounds),
        constraints=LinearConstraint(matrix, np.array(row_lower), np.array(row_upper)),
        options=solver_options,
    )

    if result.x is None or result.status != 0:
        raise RuntimeError(
            "The MILP solver did not find an optimal solution. "
            f"Status={result.status}; message={result.message}"
        )

    vector = np.asarray(result.x, dtype=float)
    opened = np.rint(vector[y_start : y_start + n]).astype(np.int64)
    chargers = np.rint(vector[z_start : z_start + n]).astype(np.int64)
    power_kw = vector[p_start : p_start + n].copy()
    assignment = vector[x_start:].reshape(n, m).copy()

    breakdown = {
        "station_establishment": float(np.dot(problem.fixed_cost, opened)),
        "charger_installation": float(np.dot(problem.charger_cost, chargers)),
        "distance_demand_penalty": float(
            problem.distance_weight
            * np.sum(
                problem.demand_kwh_day[np.newaxis, :]
                * problem.distance_km
                * assignment
            )
        ),
        "electrical_capacity_cost": float(
            np.dot(problem.power_cost_weight, power_kw)
        ),
    }

    solution = OptimizationResult(
        objective_value=float(result.fun),
        opened=opened,
        chargers=chargers,
        assignment=assignment,
        power_kw=power_kw,
        objective_breakdown=breakdown,
        solver_status=int(result.status),
        solver_message=str(result.message),
        mip_gap=(float(result.mip_gap) if getattr(result, "mip_gap", None) is not None else None),
        mip_node_count=(int(result.mip_node_count) if getattr(result, "mip_node_count", None) is not None else None),
        mip_dual_bound=(float(result.mip_dual_bound) if getattr(result, "mip_dual_bound", None) is not None else None),
    )
    validate_solution(problem, solution)
    return solution


def validate_solution(
    problem: ProblemData, solution: OptimizationResult, tolerance: float = 1e-6
) -> None:
    """Raise AssertionError if a returned solution violates model constraints."""
    problem.validate()
    n = len(problem.site_names)
    m = len(problem.demand_names)

    assert solution.assignment.shape == (n, m)
    assert np.all(solution.opened >= 0) and np.all(solution.opened <= 1)
    assert np.all(np.isin(solution.opened, [0, 1]))
    assert np.all(solution.chargers >= 0)
    assert np.all(solution.chargers <= problem.max_chargers)
    assert np.all(solution.chargers + tolerance >= solution.opened)
    assert np.all(solution.assignment >= -tolerance)

    # Full demand assignment.
    np.testing.assert_allclose(
        solution.assignment.sum(axis=0), np.ones(m), atol=tolerance
    )

    # No assignment to a station that is not open or is too far away.
    for i in range(n):
        for j in range(m):
            if solution.opened[i] == 0 or (
                problem.distance_km[i, j] > problem.max_service_distance_km
            ):
                assert solution.assignment[i, j] <= tolerance

    # Charger capacity, physical size and power constraints.
    served_kwh = solution.assignment @ problem.demand_kwh_day
    capacity_kwh = problem.charger_daily_capacity_kwh * solution.chargers
    assert np.all(served_kwh <= capacity_kwh + tolerance)
    assert np.all(solution.chargers <= problem.max_chargers * solution.opened)
    np.testing.assert_allclose(
        solution.power_kw,
        problem.charger_peak_power_kw * solution.chargers,
        atol=tolerance,
    )
    assert np.all(solution.power_kw <= problem.grid_capacity_kw * solution.opened + tolerance)

    # Maximum route gap, including the start and end of each corridor.
    for gap_entries, rhs in problem.interstation_gap_rows():
        lhs = sum(coefficient * solution.opened[index] for index, coefficient in gap_entries)
        assert lhs <= rhs + tolerance

    # Capital budget.
    capital_cost = float(
        np.dot(problem.fixed_cost, solution.opened)
        + np.dot(problem.charger_cost, solution.chargers)
    )
    assert capital_cost <= problem.budget + tolerance

    # Objective consistency.
    np.testing.assert_allclose(
        sum(solution.objective_breakdown.values()),
        solution.objective_value,
        atol=1e-5,
    )

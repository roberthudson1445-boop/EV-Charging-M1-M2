"""Convex quadratic power-loss extension for the continuous EV relaxation.

This is a continuous convex QP extension of the LP relaxation. It does not
solve the mixed-integer quadratic problem and it does not claim site-specific
loss estimates without engineering inputs for resistance and voltage.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import Bounds, linprog, minimize

from .data import ProblemData
from .lp_relaxation import solve_ev_lp_relaxation

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class KKTDiagnostics:
    """Approximate KKT residuals for equality constraints and lower bounds."""

    primal_feasibility_inf: float
    stationarity_inf: float
    dual_feasibility_violation: float
    complementarity_inf: float


@dataclass(frozen=True)
class QuadraticRelaxationResult:
    """Solution summary for the continuous convex quadratic relaxation."""

    success: bool
    message: str
    objective_value: float | None
    linear_objective_value: float | None
    total_power_loss_kw: float | None
    loss_cost: float | None
    solution: FloatArray | None
    iterations: int
    kkt: KKTDiagnostics | None


def _site_array(values: float | NDArray[np.float64], n: int, name: str) -> FloatArray:
    array = np.asarray(values, dtype=float)
    if array.ndim == 0:
        array = np.full(n, float(array), dtype=float)
    if array.shape != (n,):
        raise ValueError(f"{name} must be a scalar or an array of length {n}.")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain finite values.")
    return array


def _estimate_kkt(
    A: FloatArray,
    b: FloatArray,
    x: FloatArray,
    gradient: FloatArray,
    *,
    active_tolerance: float,
) -> KKTDiagnostics:
    """Estimate KKT residuals for Ax=b and x>=0.

    Equality multipliers are found from the KKT system with a small LP that
    enforces non-negative multipliers for active lower bounds. This avoids
    reporting a misleading least-squares multiplier that violates dual
    feasibility when equality multipliers are non-unique.
    """
    free = x > active_tolerance
    active_lower = ~free
    A_eq = A[:, free].T if np.any(free) else None
    b_eq = -gradient[free] if np.any(free) else None
    A_ub = -A[:, active_lower].T if np.any(active_lower) else None
    b_ub = gradient[active_lower] if np.any(active_lower) else None

    multiplier_result = linprog(
        c=np.zeros(A.shape[0], dtype=float),
        A_ub=A_ub,
        b_ub=b_ub,
        A_eq=A_eq,
        b_eq=b_eq,
        bounds=[(None, None)] * A.shape[0],
        method="highs",
    )
    if multiplier_result.success:
        multipliers = np.asarray(multiplier_result.x, dtype=float)
        reduced_stationarity = gradient + A.T @ multipliers
        lower_bound_multipliers = np.zeros_like(x)
        lower_bound_multipliers[active_lower] = reduced_stationarity[active_lower]
        stationarity = reduced_stationarity - lower_bound_multipliers
        dual_violation = (
            max(0.0, -float(np.min(lower_bound_multipliers[active_lower])))
            if np.any(active_lower)
            else 0.0
        )
    else:
        # Retain a diagnostic even if the multiplier feasibility problem is
        # numerically ill-conditioned; a non-zero stationarity residual then
        # correctly signals that the KKT check was not established.
        if np.any(free):
            multipliers, *_ = np.linalg.lstsq(A[:, free].T, -gradient[free], rcond=None)
        else:
            multipliers = np.zeros(A.shape[0], dtype=float)
        reduced_stationarity = gradient + A.T @ multipliers
        lower_bound_multipliers = np.zeros_like(x)
        lower_bound_multipliers[active_lower] = np.maximum(
            reduced_stationarity[active_lower], 0.0
        )
        stationarity = reduced_stationarity - lower_bound_multipliers
        dual_violation = (
            max(0.0, -float(np.min(reduced_stationarity[active_lower])))
            if np.any(active_lower)
            else 0.0
        )

    return KKTDiagnostics(
        primal_feasibility_inf=float(np.max(np.abs(A @ x - b))) if b.size else 0.0,
        stationarity_inf=float(np.max(np.abs(stationarity))) if x.size else 0.0,
        dual_feasibility_violation=float(dual_violation),
        complementarity_inf=float(
            np.max(np.abs(lower_bound_multipliers * x)) if x.size else 0.0
        ),
    )


def solve_ev_quadratic_relaxation(
    problem: ProblemData,
    *,
    line_resistance_ohm: float | NDArray[np.float64],
    nominal_voltage_kv: float | NDArray[np.float64],
    loss_cost_per_kw: float | NDArray[np.float64] = 1.0,
    tolerance: float = 1e-8,
    max_iterations: int = 2_000,
) -> QuadraticRelaxationResult:
    """Solve the LP relaxation with an added convex quadratic line-loss penalty.

    The proposal's simplified loss relation is used:

        P_loss_i = R_i * (P_i / V_nominal_i)^2.

    Here ``P_i`` is in kW and ``V_nominal_i`` in kV, so the result of the
    simplified expression is treated as watts and divided by 1000 to report
    kW. This expression is an approximation; actual three-phase losses need
    documented voltage level, power factor, phase configuration, line length,
    conductor resistance, and loading data.

    The objective adds ``loss_cost_per_kw[i] * P_loss_i`` to the LP objective.
    All coefficients must be non-negative, making the quadratic term convex.
    The integer restrictions on station-opening and charger-count variables
    remain relaxed in this QP.
    """
    problem.validate()
    base = solve_ev_lp_relaxation(problem).lp_result
    if (
        base.standard_matrix is None
        or base.standard_rhs is None
        or base.standard_cost is None
        or base.standard_solution is None
    ):
        raise RuntimeError("The LP relaxation did not retain standard-form data.")

    n = len(problem.site_names)
    resistance = _site_array(line_resistance_ohm, n, "line_resistance_ohm")
    voltage = _site_array(nominal_voltage_kv, n, "nominal_voltage_kv")
    loss_weight = _site_array(loss_cost_per_kw, n, "loss_cost_per_kw")
    if np.any(resistance < 0):
        raise ValueError("line_resistance_ohm must be non-negative.")
    if np.any(voltage <= 0):
        raise ValueError("nominal_voltage_kv must be greater than zero.")
    if np.any(loss_weight < 0):
        raise ValueError("loss_cost_per_kw must be non-negative.")

    A = np.asarray(base.standard_matrix, dtype=float)
    b = np.asarray(base.standard_rhs, dtype=float)
    c = np.asarray(base.standard_cost, dtype=float)
    x0 = np.asarray(base.standard_solution, dtype=float)
    power_indices = np.arange(2 * n, 3 * n, dtype=int)
    scale = loss_weight * resistance / (voltage**2 * 1000.0)

    def objective(x: FloatArray) -> float:
        power = x[power_indices]
        return float(c @ x + np.dot(scale, power**2))

    def gradient(x: FloatArray) -> FloatArray:
        grad = c.copy()
        grad[power_indices] += 2.0 * scale * x[power_indices]
        return grad

    result = minimize(
        objective,
        x0,
        method="SLSQP",
        jac=gradient,
        bounds=Bounds(np.zeros_like(x0), np.full_like(x0, np.inf)),
        constraints=[
            {
                "type": "eq",
                "fun": lambda x: A @ x - b,
                "jac": lambda x: A,
            }
        ],
        options={"ftol": tolerance, "maxiter": max_iterations, "disp": False},
    )

    if not result.success:
        return QuadraticRelaxationResult(
            success=False,
            message=str(result.message),
            objective_value=None,
            linear_objective_value=None,
            total_power_loss_kw=None,
            loss_cost=None,
            solution=None,
            iterations=int(getattr(result, "nit", 0)),
            kkt=None,
        )

    solution = np.asarray(result.x, dtype=float)
    powers = solution[power_indices]
    losses_kw = resistance * (powers / voltage) ** 2 / 1000.0
    loss_cost = float(np.dot(loss_weight, losses_kw))
    linear_value = float(c @ solution)
    diagnostics = _estimate_kkt(
        A,
        b,
        solution,
        gradient(solution),
        active_tolerance=max(tolerance * 10.0, 1e-7),
    )

    if np.min(solution) < -1e-6:
        raise RuntimeError("Quadratic solver returned a negative variable.")
    if diagnostics.primal_feasibility_inf > 1e-5:
        raise RuntimeError(
            "Quadratic solver returned a point that violates the standard-form equalities: "
            f"residual={diagnostics.primal_feasibility_inf:.3g}."
        )

    return QuadraticRelaxationResult(
        success=True,
        message=str(result.message),
        objective_value=float(result.fun),
        linear_objective_value=linear_value,
        total_power_loss_kw=float(np.sum(losses_kw)),
        loss_cost=loss_cost,
        solution=solution,
        iterations=int(getattr(result, "nit", 0)),
        kkt=diagnostics,
    )

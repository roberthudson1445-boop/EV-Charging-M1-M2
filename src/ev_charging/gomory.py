"""Mixed-Integer Gomory cutting-plane support for small LP relaxations.

The implementation generates one-row Gomory mixed-integer (GMI) cuts from
an optimal simplex tableau row whose basic variable is integer-constrained.
It then appends the cut and calls the in-house Dual Simplex re-optimizer.

This is a pedagogical cutting-plane implementation for small instances. It
uses floating-point arithmetic, so final results must be checked against a
trusted MILP solver (HiGHS/CBC), especially on larger or poorly scaled models.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

import numpy as np
from numpy.typing import NDArray

from .revised_simplex import LPResult, dual_simplex_reoptimize

FloatArray = NDArray[np.float64]
GomoryStatus = Literal["integer_optimal", "cut_limit_reached", "infeasible", "iteration_limit"]


@dataclass(frozen=True)
class GomoryCut:
    """A generated GMI cut in the current standard-form variable space."""

    basic_variable: int
    tableau_row: int
    fractional_rhs: float
    coefficients: FloatArray
    violation_at_source_lp: float


@dataclass(frozen=True)
class GomoryResult:
    """Result of applying GMI cuts and Dual Simplex re-optimization."""

    status: GomoryStatus
    lp_result: LPResult
    cuts: tuple[GomoryCut, ...]
    integer_variable_indices: tuple[int, ...]
    message: str
    dual_simplex_iterations: int = 0


def _fractional_part(value: float) -> float:
    """Return frac(value) in [0, 1), including for negative values."""
    return float(value - np.floor(value))


def generate_gmi_cut(
    lp_result: LPResult,
    integer_variable_indices: Sequence[int],
    *,
    tolerance: float = 1e-8,
) -> GomoryCut | None:
    """Generate a GMI cut from the most fractional integer basic variable.

    Tableau convention:
        x_B + sum_j(tableau[row, j] * x_j) = rhs[row].

    Integer restrictions are applied only to the listed original variables.
    Slack/surplus variables are treated as continuous, which is valid (though
    sometimes weaker) for a mixed-integer Gomory cut.
    """
    if lp_result.status != "optimal":
        raise ValueError("GMI cuts require an optimal LP relaxation.")
    if (
        lp_result.standard_matrix is None
        or lp_result.standard_rhs is None
        or lp_result.standard_solution is None
        or not lp_result.basis
    ):
        raise ValueError("The LP result does not contain its standard-form basis data.")

    A = np.asarray(lp_result.standard_matrix, dtype=float)
    b = np.asarray(lp_result.standard_rhs, dtype=float)
    basis = list(lp_result.basis)
    m, n = A.shape
    if len(basis) != m or b.shape != (m,):
        raise ValueError("Stored standard-form LP dimensions are inconsistent.")

    integer_mask = np.zeros(n, dtype=bool)
    for index in integer_variable_indices:
        if index < 0 or index >= lp_result.original_variable_count:
            raise ValueError(f"Integer variable index {index} is out of range.")
        integer_mask[index] = True

    try:
        B = A[:, basis]
        basic_values = np.linalg.solve(B, b)
        tableau = np.linalg.solve(B, A)
    except np.linalg.LinAlgError as exc:
        raise ValueError("Cannot form a tableau from a singular basis.") from exc

    nonbasic = [j for j in range(n) if j not in basis]
    candidates: list[tuple[float, int, int, float, FloatArray]] = []

    for row_index, basic_column in enumerate(basis):
        if not integer_mask[basic_column]:
            continue
        rhs_value = float(basic_values[row_index])
        f0 = _fractional_part(rhs_value)
        if f0 <= tolerance or f0 >= 1.0 - tolerance:
            continue

        cut_coefficients = np.zeros(n, dtype=float)
        for column in nonbasic:
            a_bar = float(tableau[row_index, column])
            if integer_mask[column]:
                fj = _fractional_part(a_bar)
                if fj <= f0 + tolerance:
                    coefficient = fj
                else:
                    coefficient = f0 * (1.0 - fj) / (1.0 - f0)
            elif a_bar >= -tolerance:
                coefficient = max(a_bar, 0.0)
            else:
                coefficient = -f0 * a_bar / (1.0 - f0)

            if coefficient > tolerance:
                cut_coefficients[column] = coefficient

        if np.any(cut_coefficients > tolerance):
            # Prefer a strongly fractional RHS; ties use the lower basic index.
            fractionality = min(f0, 1.0 - f0)
            candidates.append(
                (fractionality, -basic_column, row_index, f0, cut_coefficients)
            )

    if not candidates:
        return None

    _, negative_basic, row_index, f0, coefficients = max(
        candidates, key=lambda item: (item[0], item[1])
    )
    basic_column = -negative_basic
    return GomoryCut(
        basic_variable=basic_column,
        tableau_row=row_index,
        fractional_rhs=f0,
        coefficients=coefficients,
        violation_at_source_lp=f0,
    )


def solve_with_gomory_cuts(
    initial_lp: LPResult,
    integer_variable_indices: Sequence[int],
    *,
    max_cuts: int = 100,
    tolerance: float = 1e-8,
    max_dual_iterations: int = 10_000,
) -> GomoryResult:
    """Apply GMI cuts and re-optimize each augmented LP with Dual Simplex.

    ``initial_lp`` must be the optimal result of this project's ``solve_lp``.
    The integer indices refer to the original variable vector, not its
    auxiliary slack/surplus columns.
    """
    if initial_lp.status != "optimal":
        raise ValueError("The initial LP relaxation must be optimal.")
    if (
        initial_lp.standard_matrix is None
        or initial_lp.standard_rhs is None
        or initial_lp.standard_cost is None
        or initial_lp.standard_solution is None
    ):
        raise ValueError("The LP result is missing standard-form data for cutting planes.")
    if max_cuts < 0:
        raise ValueError("max_cuts cannot be negative.")

    A = np.asarray(initial_lp.standard_matrix, dtype=float).copy()
    b = np.asarray(initial_lp.standard_rhs, dtype=float).copy()
    c = np.asarray(initial_lp.standard_cost, dtype=float).copy()
    basis = list(initial_lp.basis)
    original_count = initial_lp.original_variable_count
    integer_indices = tuple(sorted(set(int(i) for i in integer_variable_indices)))
    if any(i < 0 or i >= original_count for i in integer_indices):
        raise ValueError("An integer-variable index is outside the original variable vector.")

    current = initial_lp
    cuts: list[GomoryCut] = []
    total_dual_iterations = 0

    for cut_number in range(max_cuts + 1):
        if current.standard_solution is None:
            raise RuntimeError("The current LP result has no standard-form solution.")
        values = current.standard_solution
        integer_values = values[list(integer_indices)] if integer_indices else np.array([])
        if integer_values.size == 0 or np.all(
            np.abs(integer_values - np.rint(integer_values)) <= tolerance
        ):
            return GomoryResult(
                status="integer_optimal",
                lp_result=current,
                cuts=tuple(cuts),
                integer_variable_indices=integer_indices,
                message="All designated integer variables satisfy integrality; the LP bound is attained by an integer-feasible solution.",
                dual_simplex_iterations=total_dual_iterations,
            )

        if cut_number == max_cuts:
            break

        cut = generate_gmi_cut(current, integer_indices, tolerance=tolerance)
        if cut is None:
            return GomoryResult(
                status="cut_limit_reached",
                lp_result=current,
                cuts=tuple(cuts),
                integer_variable_indices=integer_indices,
                message="Fractional integer variables remain, but no numerically usable GMI row was found.",
                dual_simplex_iterations=total_dual_iterations,
            )

        old_rows, old_columns = A.shape
        # The GMI inequality is g'x >= f0. Convert it to equality form:
        # -g'x + s_cut = -f0, with a new nonnegative slack basic initially.
        augmented = np.zeros((old_rows + 1, old_columns + 1), dtype=float)
        augmented[:old_rows, :old_columns] = A
        augmented[old_rows, :old_columns] = -cut.coefficients
        augmented[old_rows, old_columns] = 1.0
        new_b = np.append(b, -cut.fractional_rhs)
        new_c = np.append(c, 0.0)
        new_basis = basis + [old_columns]

        dual_result = dual_simplex_reoptimize(
            augmented,
            new_b,
            new_c,
            new_basis,
            original_variable_count=original_count,
            tolerance=tolerance,
            max_iterations=max_dual_iterations,
        )
        total_dual_iterations += dual_result.iterations
        if dual_result.status == "infeasible":
            return GomoryResult(
                status="infeasible",
                lp_result=dual_result,
                cuts=tuple(cuts + [cut]),
                integer_variable_indices=integer_indices,
                message="The augmented LP became infeasible after adding a valid GMI cut.",
                dual_simplex_iterations=total_dual_iterations,
            )
        if dual_result.status != "optimal":
            return GomoryResult(
                status="iteration_limit",
                lp_result=dual_result,
                cuts=tuple(cuts + [cut]),
                integer_variable_indices=integer_indices,
                message=dual_result.message,
                dual_simplex_iterations=total_dual_iterations,
            )

        cuts.append(cut)
        current = dual_result
        A = np.asarray(current.standard_matrix, dtype=float).copy()
        b = np.asarray(current.standard_rhs, dtype=float).copy()
        c = np.asarray(current.standard_cost, dtype=float).copy()
        basis = list(current.basis)

    return GomoryResult(
        status="cut_limit_reached",
        lp_result=current,
        cuts=tuple(cuts),
        integer_variable_indices=integer_indices,
        message=f"The maximum number of Gomory cuts ({max_cuts}) was reached before integrality.",
        dual_simplex_iterations=total_dual_iterations,
    )

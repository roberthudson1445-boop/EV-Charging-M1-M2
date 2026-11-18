"""A transparent two-phase Revised Simplex implementation.

The solver handles linear programs in the form

    minimize c @ x
    subject to A_ub @ x <= b_ub
               A_eq @ x == b_eq
               x >= 0.

It is intended for teaching, verification, and small/medium test instances.
For large highway instances, use HiGHS/CBC as the production benchmark.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]
LPStatus = Literal["optimal", "infeasible", "unbounded", "iteration_limit"]


@dataclass(frozen=True)
class LPResult:
    """Result of solving a linear program.

    ``x`` contains the original decision variables. The ``standard_*`` fields
    retain the equality-form LP (including slack/surplus columns) so that
    cutting-plane and dual-simplex routines can safely re-optimize it.
    ``standard_solution`` contains all original and auxiliary variables.
    """

    status: LPStatus
    objective_value: float | None
    x: FloatArray | None
    iterations: int
    message: str
    basis: tuple[int, ...] = ()
    dual_prices: FloatArray | None = None
    reduced_costs: FloatArray | None = None
    standard_matrix: FloatArray | None = None
    standard_rhs: FloatArray | None = None
    standard_cost: FloatArray | None = None
    standard_solution: FloatArray | None = None
    original_variable_count: int = 0


@dataclass(frozen=True)
class _SimplexResult:
    status: Literal["optimal", "unbounded", "iteration_limit"]
    x: FloatArray | None
    objective: float | None
    basis: tuple[int, ...]
    iterations: int
    dual_prices: FloatArray | None
    reduced_costs: FloatArray | None
    message: str


def _as_2d(matrix: NDArray[np.float64] | None, n: int) -> FloatArray:
    if matrix is None:
        return np.zeros((0, n), dtype=float)
    array = np.asarray(matrix, dtype=float)
    if array.ndim != 2 or array.shape[1] != n:
        raise ValueError(f"Constraint matrix must have {n} columns.")
    return array


def _as_1d(vector: NDArray[np.float64] | None, expected: int, name: str) -> FloatArray:
    if vector is None:
        return np.zeros(expected, dtype=float)
    array = np.asarray(vector, dtype=float)
    if array.ndim != 1 or array.size != expected:
        raise ValueError(f"{name} must be a one-dimensional array of length {expected}.")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite numbers.")
    return array


def _revised_simplex_feasible_basis(
    A: FloatArray,
    b: FloatArray,
    c: FloatArray,
    basis: list[int],
    *,
    tolerance: float,
    max_iterations: int,
) -> _SimplexResult:
    """Run primal Revised Simplex from a known primal-feasible basis."""
    m, n = A.shape
    if len(basis) != m:
        raise ValueError("The initial basis must contain one column per constraint row.")
    if len(set(basis)) != len(basis):
        raise ValueError("The initial basis cannot contain duplicate columns.")
    if any(index < 0 or index >= n for index in basis):
        raise ValueError("An initial basis column index is out of range.")

    basis = list(basis)
    for iteration in range(max_iterations + 1):
        B = A[:, basis]
        try:
            x_basic = np.linalg.solve(B, b)
            dual = np.linalg.solve(B.T, c[basis])
        except np.linalg.LinAlgError as exc:
            raise ValueError("The current basis matrix is singular.") from exc

        if np.any(x_basic < -tolerance):
            raise ValueError(
                "The supplied basis is not primal feasible. Use solve_lp(), "
                "which constructs a Phase-I problem automatically."
            )

        reduced = c - A.T @ dual
        nonbasic = [j for j in range(n) if j not in basis]
        improving = [j for j in nonbasic if reduced[j] < -tolerance]

        if not improving:
            x = np.zeros(n, dtype=float)
            x[basis] = np.maximum(x_basic, 0.0)
            return _SimplexResult(
                status="optimal",
                x=x,
                objective=float(c @ x),
                basis=tuple(basis),
                iterations=iteration,
                dual_prices=dual.copy(),
                reduced_costs=reduced.copy(),
                message="Optimal solution found by Revised Simplex.",
            )

        if iteration == max_iterations:
            break

        # Bland's rule: choose the smallest-index improving nonbasic variable.
        entering = min(improving)
        try:
            direction = np.linalg.solve(B, A[:, entering])
        except np.linalg.LinAlgError as exc:
            raise ValueError("Could not solve for the entering-column direction.") from exc

        eligible_rows = [r for r in range(m) if direction[r] > tolerance]
        if not eligible_rows:
            return _SimplexResult(
                status="unbounded",
                x=None,
                objective=None,
                basis=tuple(basis),
                iterations=iteration,
                dual_prices=dual.copy(),
                reduced_costs=reduced.copy(),
                message="The objective is unbounded in an improving direction.",
            )

        ratios = {r: x_basic[r] / direction[r] for r in eligible_rows}
        minimum_ratio = min(ratios.values())
        tied_rows = [r for r in eligible_rows if ratios[r] <= minimum_ratio + tolerance]
        # Bland tie-break on the index of the leaving basic variable.
        leaving_row = min(tied_rows, key=lambda r: basis[r])
        basis[leaving_row] = entering

    return _SimplexResult(
        status="iteration_limit",
        x=None,
        objective=None,
        basis=tuple(basis),
        iterations=max_iterations,
        dual_prices=None,
        reduced_costs=None,
        message=f"Maximum number of iterations ({max_iterations}) reached.",
    )


def solve_standard_form(
    A: NDArray[np.float64],
    b: NDArray[np.float64],
    c: NDArray[np.float64],
    initial_basis: list[int] | tuple[int, ...],
    *,
    tolerance: float = 1e-9,
    max_iterations: int = 10_000,
) -> LPResult:
    """Solve min c'x subject to Ax=b, x>=0 from a feasible basis.

    This lower-level function is useful for inspecting a known simplex basis.
    Most users should call :func:`solve_lp`, which creates a Phase-I basis.
    """
    A_array = np.asarray(A, dtype=float)
    b_array = np.asarray(b, dtype=float)
    c_array = np.asarray(c, dtype=float)
    if A_array.ndim != 2:
        raise ValueError("A must be a two-dimensional matrix.")
    m, n = A_array.shape
    if b_array.shape != (m,) or c_array.shape != (n,):
        raise ValueError("Dimensions of A, b, and c are inconsistent.")
    if not (np.all(np.isfinite(A_array)) and np.all(np.isfinite(b_array)) and np.all(np.isfinite(c_array))):
        raise ValueError("A, b, and c must contain finite values.")
    if m == 0:
        raise ValueError("At least one equality constraint is required.")
    if max_iterations <= 0:
        raise ValueError("max_iterations must be positive.")

    result = _revised_simplex_feasible_basis(
        A_array,
        b_array,
        c_array,
        list(initial_basis),
        tolerance=tolerance,
        max_iterations=max_iterations,
    )
    return LPResult(
        status=result.status,
        objective_value=result.objective,
        x=result.x,
        iterations=result.iterations,
        message=result.message,
        basis=result.basis,
        dual_prices=result.dual_prices,
        reduced_costs=result.reduced_costs,
    )


def solve_lp(
    c: NDArray[np.float64],
    *,
    A_ub: NDArray[np.float64] | None = None,
    b_ub: NDArray[np.float64] | None = None,
    A_eq: NDArray[np.float64] | None = None,
    b_eq: NDArray[np.float64] | None = None,
    A_ge: NDArray[np.float64] | None = None,
    b_ge: NDArray[np.float64] | None = None,
    tolerance: float = 1e-9,
    max_iterations: int = 10_000,
) -> LPResult:
    """Solve a minimization LP with <=, >=, and equality constraints.

    All original variables are non-negative. Upper bounds should be supplied
    as additional <= rows (for example, x_j <= U_j).

    A two-phase method constructs an initial feasible basis using slack,
    surplus, and artificial variables. Artificial variables are removed
    before Phase II.
    """
    c_array = np.asarray(c, dtype=float)
    if c_array.ndim != 1 or c_array.size == 0:
        raise ValueError("c must be a non-empty one-dimensional vector.")
    if not np.all(np.isfinite(c_array)):
        raise ValueError("c must contain finite values.")
    n = c_array.size

    ub = _as_2d(A_ub, n)
    eq = _as_2d(A_eq, n)
    ge = _as_2d(A_ge, n)
    bub = _as_1d(b_ub, ub.shape[0], "b_ub")
    beq = _as_1d(b_eq, eq.shape[0], "b_eq")
    bge = _as_1d(b_ge, ge.shape[0], "b_ge")

    rows: list[tuple[FloatArray, float, str]] = []
    rows.extend((row.copy(), float(rhs), "le") for row, rhs in zip(ub, bub))
    rows.extend((row.copy(), float(rhs), "eq") for row, rhs in zip(eq, beq))
    rows.extend((row.copy(), float(rhs), "ge") for row, rhs in zip(ge, bge))

    if not rows:
        raise ValueError("At least one constraint is required.")

    normalized: list[tuple[FloatArray, float, str]] = []
    for row, rhs, sense in rows:
        if rhs < -tolerance:
            flip = {"le": "ge", "ge": "le", "eq": "eq"}[sense]
            normalized.append((-row, -rhs, flip))
        else:
            normalized.append((row, max(rhs, 0.0), sense))

    total_rows = len(normalized)
    extra_columns: list[FloatArray] = []
    initial_basis: list[int] = [-1] * total_rows
    artificial_indices: set[int] = set()

    # Determine the required slack/surplus/artificial columns row by row.
    for row_index, (_, _, sense) in enumerate(normalized):
        column = np.zeros(total_rows, dtype=float)
        if sense == "le":
            column[row_index] = 1.0
            initial_basis[row_index] = n + len(extra_columns)
            extra_columns.append(column)
        elif sense == "ge":
            column[row_index] = -1.0  # surplus variable
            extra_columns.append(column)
            artificial = np.zeros(total_rows, dtype=float)
            artificial[row_index] = 1.0
            artificial_index = n + len(extra_columns)
            extra_columns.append(artificial)
            initial_basis[row_index] = artificial_index
            artificial_indices.add(artificial_index)
        else:  # equality
            artificial = np.zeros(total_rows, dtype=float)
            artificial[row_index] = 1.0
            artificial_index = n + len(extra_columns)
            extra_columns.append(artificial)
            initial_basis[row_index] = artificial_index
            artificial_indices.add(artificial_index)

    A_original = np.vstack([row for row, _, _ in normalized])
    b_standard = np.array([rhs for _, rhs, _ in normalized], dtype=float)
    if extra_columns:
        A_standard = np.column_stack([A_original, *extra_columns])
    else:
        A_standard = A_original.copy()

    # Phase I: minimize the sum of artificial variables.
    c_phase1 = np.zeros(A_standard.shape[1], dtype=float)
    for index in artificial_indices:
        c_phase1[index] = 1.0
    phase1 = _revised_simplex_feasible_basis(
        A_standard,
        b_standard,
        c_phase1,
        initial_basis,
        tolerance=tolerance,
        max_iterations=max_iterations,
    )
    if phase1.status == "unbounded":
        raise RuntimeError("Phase I unexpectedly became unbounded.")
    if phase1.status == "iteration_limit":
        return LPResult(
            status="iteration_limit", objective_value=None, x=None,
            iterations=phase1.iterations, message="Phase I reached its iteration limit.",
        )
    assert phase1.x is not None and phase1.objective is not None
    if phase1.objective > max(tolerance * 100, 1e-7):
        return LPResult(
            status="infeasible", objective_value=None, x=None,
            iterations=phase1.iterations,
            message=f"The LP is infeasible; Phase-I artificial objective = {phase1.objective:.8g}.",
            basis=phase1.basis,
        )

    basis = list(phase1.basis)
    A_work = A_standard.copy()
    b_work = b_standard.copy()

    # Pivot zero-valued artificial basics out. If no pivot is possible, the
    # corresponding equality is redundant and can be removed.
    row_index = 0
    while row_index < len(basis):
        if basis[row_index] not in artificial_indices:
            row_index += 1
            continue
        B = A_work[:, basis]
        x_basic = np.linalg.solve(B, b_work)
        tableau = np.linalg.solve(B, A_work)
        if abs(x_basic[row_index]) > max(tolerance * 100, 1e-7):
            return LPResult(
                status="infeasible", objective_value=None, x=None,
                iterations=phase1.iterations,
                message="An artificial variable remains positive after Phase I.",
                basis=tuple(basis),
            )
        nonbasic_candidates = [
            j for j in range(A_work.shape[1])
            if j not in basis and j not in artificial_indices
            and abs(tableau[row_index, j]) > tolerance
        ]
        if nonbasic_candidates:
            basis[row_index] = min(nonbasic_candidates)
            row_index += 1
        else:
            A_work = np.delete(A_work, row_index, axis=0)
            b_work = np.delete(b_work, row_index)
            basis.pop(row_index)

    # Remove all artificial columns and remap the remaining basis indices.
    keep_columns = [j for j in range(A_work.shape[1]) if j not in artificial_indices]
    old_to_new = {old: new for new, old in enumerate(keep_columns)}
    A_phase2 = A_work[:, keep_columns]
    basis_phase2 = [old_to_new[index] for index in basis]
    c_phase2 = np.zeros(len(keep_columns), dtype=float)
    for old_index in range(n):
        c_phase2[old_to_new[old_index]] = c_array[old_index]

    phase2 = _revised_simplex_feasible_basis(
        A_phase2,
        b_work,
        c_phase2,
        basis_phase2,
        tolerance=tolerance,
        max_iterations=max_iterations,
    )
    total_iterations = phase1.iterations + phase2.iterations
    if phase2.status != "optimal":
        return LPResult(
            status=phase2.status,
            objective_value=phase2.objective,
            x=None,
            iterations=total_iterations,
            message=phase2.message,
            basis=phase2.basis,
            dual_prices=phase2.dual_prices,
            reduced_costs=phase2.reduced_costs,
        )

    assert phase2.x is not None and phase2.objective is not None
    original_x = phase2.x[:n].copy()
    return LPResult(
        status="optimal",
        objective_value=float(c_array @ original_x),
        x=original_x,
        iterations=total_iterations,
        message="Optimal solution found by the two-phase Revised Simplex method.",
        basis=phase2.basis,
        dual_prices=phase2.dual_prices,
        reduced_costs=phase2.reduced_costs[:n] if phase2.reduced_costs is not None else None,
        standard_matrix=A_phase2.copy(),
        standard_rhs=b_work.copy(),
        standard_cost=c_phase2.copy(),
        standard_solution=phase2.x.copy(),
        original_variable_count=n,
    )


def dual_simplex_reoptimize(
    A: NDArray[np.float64],
    b: NDArray[np.float64],
    c: NDArray[np.float64],
    initial_basis: list[int] | tuple[int, ...],
    *,
    original_variable_count: int | None = None,
    tolerance: float = 1e-9,
    max_iterations: int = 10_000,
) -> LPResult:
    """Re-optimize an equality-form minimization LP using Dual Simplex.

    The supplied basis must be dual feasible (all nonbasic reduced costs are
    nonnegative within tolerance), but its basic solution may be primal
    infeasible. This is the state created when a valid Gomory cut is appended
    to an already optimal LP basis with its new slack variable basic.

    All variables are assumed nonnegative. The returned ``x`` contains the
    first ``original_variable_count`` variables; ``standard_solution``
    contains all columns, including auxiliary slack/surplus variables.
    """
    A_array = np.asarray(A, dtype=float)
    b_array = np.asarray(b, dtype=float)
    c_array = np.asarray(c, dtype=float)
    if A_array.ndim != 2:
        raise ValueError("A must be a two-dimensional matrix.")
    m, n = A_array.shape
    if b_array.shape != (m,) or c_array.shape != (n,):
        raise ValueError("Dimensions of A, b, and c are inconsistent.")
    if m == 0 or len(initial_basis) != m:
        raise ValueError("The basis must contain one column per constraint row.")
    if len(set(initial_basis)) != len(initial_basis):
        raise ValueError("The initial basis cannot contain duplicate columns.")
    if any(index < 0 or index >= n for index in initial_basis):
        raise ValueError("An initial basis column index is out of range.")
    if not (np.all(np.isfinite(A_array)) and np.all(np.isfinite(b_array)) and np.all(np.isfinite(c_array))):
        raise ValueError("A, b, and c must contain finite values.")
    if max_iterations <= 0:
        raise ValueError("max_iterations must be positive.")

    original_count = n if original_variable_count is None else int(original_variable_count)
    if not 0 <= original_count <= n:
        raise ValueError("original_variable_count must be between zero and the column count.")

    basis = list(initial_basis)
    for iteration in range(max_iterations + 1):
        B = A_array[:, basis]
        try:
            x_basic = np.linalg.solve(B, b_array)
            dual = np.linalg.solve(B.T, c_array[basis])
            tableau = np.linalg.solve(B, A_array)
        except np.linalg.LinAlgError as exc:
            raise ValueError("The current basis matrix is singular.") from exc

        reduced = c_array - A_array.T @ dual
        nonbasic = [j for j in range(n) if j not in basis]
        if any(reduced[j] < -tolerance for j in nonbasic):
            raise ValueError(
                "The supplied basis is not dual feasible; Dual Simplex cannot start."
            )

        infeasible_rows = [r for r in range(m) if x_basic[r] < -tolerance]
        if not infeasible_rows:
            full_solution = np.zeros(n, dtype=float)
            full_solution[basis] = np.maximum(x_basic, 0.0)
            return LPResult(
                status="optimal",
                objective_value=float(c_array @ full_solution),
                x=full_solution[:original_count].copy(),
                iterations=iteration,
                message="Optimal solution restored by Dual Simplex.",
                basis=tuple(basis),
                dual_prices=dual.copy(),
                reduced_costs=reduced.copy(),
                standard_matrix=A_array.copy(),
                standard_rhs=b_array.copy(),
                standard_cost=c_array.copy(),
                standard_solution=full_solution,
                original_variable_count=original_count,
            )

        if iteration == max_iterations:
            break

        # Select the most primal-infeasible basic row; Bland tie-breaks ties.
        minimum_value = min(x_basic[r] for r in infeasible_rows)
        tied_rows = [r for r in infeasible_rows if x_basic[r] <= minimum_value + tolerance]
        leaving_row = min(tied_rows, key=lambda r: basis[r])

        candidates = [j for j in nonbasic if tableau[leaving_row, j] < -tolerance]
        if not candidates:
            return LPResult(
                status="infeasible",
                objective_value=None,
                x=None,
                iterations=iteration,
                message=(
                    "The dual-feasible basis has a negative basic value and no "
                    "eligible entering variable; the augmented LP is infeasible."
                ),
                basis=tuple(basis),
                dual_prices=dual.copy(),
                reduced_costs=reduced.copy(),
                standard_matrix=A_array.copy(),
                standard_rhs=b_array.copy(),
                standard_cost=c_array.copy(),
                original_variable_count=original_count,
            )

        ratios = {j: reduced[j] / (-tableau[leaving_row, j]) for j in candidates}
        minimum_ratio = min(ratios.values())
        tied_columns = [j for j in candidates if ratios[j] <= minimum_ratio + tolerance]
        entering = min(tied_columns)
        basis[leaving_row] = entering

    return LPResult(
        status="iteration_limit",
        objective_value=None,
        x=None,
        iterations=max_iterations,
        message=f"Dual Simplex reached the iteration limit ({max_iterations}).",
        basis=tuple(basis),
        standard_matrix=A_array.copy(),
        standard_rhs=b_array.copy(),
        standard_cost=c_array.copy(),
        original_variable_count=original_count,
    )

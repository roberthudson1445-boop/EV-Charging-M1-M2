"""Automated checks for the illustrative MILP baseline."""

import numpy as np

from ev_charging import make_toy_problem, solve_milp, validate_solution


def test_toy_problem_has_an_optimal_feasible_solution() -> None:
    problem = make_toy_problem()
    solution = solve_milp(problem)

    validate_solution(problem, solution)

    assert solution.solver_status == 0
    assert solution.opened.tolist() == [1, 1]
    assert solution.chargers.tolist() == [1, 1]
    np.testing.assert_allclose(solution.assignment, [[1.0, 0.0], [0.0, 1.0]], atol=1e-6)
    np.testing.assert_allclose(solution.power_kw, [150.0, 150.0], atol=1e-6)
    assert np.isclose(solution.objective_value, 21000.0, atol=1e-6)


def test_unreachable_assignment_is_zero() -> None:
    problem = make_toy_problem()
    solution = solve_milp(problem)

    # Site A is 100 km from demand D2, beyond the 85 km service threshold.
    assert solution.assignment[0, 1] <= 1e-8


def test_revised_simplex_solves_classic_two_variable_lp() -> None:
    from ev_charging.revised_simplex import solve_lp

    # max 3*x1 + 2*x2 subject to x1+x2<=4, 2*x1+x2<=5.
    result = solve_lp(
        np.array([-3.0, -2.0]),
        A_ub=np.array([[1.0, 1.0], [2.0, 1.0]]),
        b_ub=np.array([4.0, 5.0]),
    )
    assert result.status == "optimal"
    np.testing.assert_allclose(result.x, [1.0, 3.0], atol=1e-7)
    assert np.isclose(result.objective_value, -9.0, atol=1e-7)


def test_revised_simplex_handles_equality_and_greater_equal_constraints() -> None:
    from ev_charging.revised_simplex import solve_lp

    # min x1 + 2*x2 subject to x1+x2=3, x1>=1, x>=0.
    result = solve_lp(
        np.array([1.0, 2.0]),
        A_eq=np.array([[1.0, 1.0]]),
        b_eq=np.array([3.0]),
        A_ge=np.array([[1.0, 0.0]]),
        b_ge=np.array([1.0]),
    )
    assert result.status == "optimal"
    np.testing.assert_allclose(result.x, [3.0, 0.0], atol=1e-7)
    assert np.isclose(result.objective_value, 3.0, atol=1e-7)


def test_revised_simplex_detects_infeasible_problem() -> None:
    from ev_charging.revised_simplex import solve_lp

    # x <= 1 and x >= 2 cannot both hold.
    result = solve_lp(
        np.array([1.0]),
        A_ub=np.array([[1.0]]),
        b_ub=np.array([1.0]),
        A_ge=np.array([[1.0]]),
        b_ge=np.array([2.0]),
    )
    assert result.status == "infeasible"


def test_ev_lp_relaxation_runs_with_in_house_revised_simplex() -> None:
    from ev_charging.lp_relaxation import solve_ev_lp_relaxation

    problem = make_toy_problem()
    result = solve_ev_lp_relaxation(problem)
    assert result.lp_result.status == "optimal"
    assert result.lp_result.x is not None
    assert np.all(result.opened_relaxed >= -1e-8)
    assert np.all(result.opened_relaxed <= 1.0 + 1e-8)
    np.testing.assert_allclose(result.assignment.sum(axis=0), [1.0, 1.0], atol=1e-7)

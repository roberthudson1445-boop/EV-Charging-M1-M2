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


def test_gomory_cut_and_dual_simplex_round_fractional_integer_up() -> None:
    from ev_charging.gomory import solve_with_gomory_cuts
    from ev_charging.revised_simplex import solve_lp

    # min x subject to x >= 1.5, where x must be integer.
    lp = solve_lp(
        np.array([1.0]),
        A_ge=np.array([[1.0]]),
        b_ge=np.array([1.5]),
    )
    assert lp.status == "optimal"
    np.testing.assert_allclose(lp.x, [1.5], atol=1e-8)

    result = solve_with_gomory_cuts(lp, integer_variable_indices=[0], max_cuts=10)
    assert result.status == "integer_optimal"
    assert len(result.cuts) == 1
    np.testing.assert_allclose(result.lp_result.x, [2.0], atol=1e-8)
    assert np.isclose(result.lp_result.objective_value, 2.0, atol=1e-8)


def test_gomory_cutting_plane_matches_highs_on_ev_toy_case() -> None:
    from ev_charging.gomory import solve_with_gomory_cuts
    from ev_charging.lp_relaxation import solve_ev_lp_relaxation

    problem = make_toy_problem()
    relaxation = solve_ev_lp_relaxation(problem)
    site_count = len(problem.site_names)
    result = solve_with_gomory_cuts(
        relaxation.lp_result,
        integer_variable_indices=list(range(2 * site_count)),
        max_cuts=100,
    )
    benchmark = solve_milp(problem)

    assert result.status == "integer_optimal"
    assert len(result.cuts) > 0
    np.testing.assert_allclose(
        result.lp_result.objective_value, benchmark.objective_value, atol=1e-6
    )
    np.testing.assert_allclose(
        result.lp_result.x[:site_count], benchmark.opened, atol=1e-8
    )
    np.testing.assert_allclose(
        result.lp_result.x[site_count : 2 * site_count], benchmark.chargers, atol=1e-8
    )


def test_gomory_does_not_cut_fractional_continuous_variables() -> None:
    from ev_charging.gomory import solve_with_gomory_cuts
    from ev_charging.revised_simplex import solve_lp

    # x is integer and fixed at 1; y is continuous and optimally 0.5.
    lp = solve_lp(
        np.array([1.0, 1.0]),
        A_ge=np.array([[1.0, 0.0], [0.0, 1.0]]),
        b_ge=np.array([1.0, 0.5]),
    )
    result = solve_with_gomory_cuts(lp, integer_variable_indices=[0])
    assert result.status == "integer_optimal"
    assert len(result.cuts) == 0
    np.testing.assert_allclose(result.lp_result.x, [1.0, 0.5], atol=1e-8)


def test_csv_loader_reads_complete_case_data(tmp_path) -> None:
    import json

    from ev_charging.data_io import load_problem_from_csv

    (tmp_path / "sites.csv").write_text(
        "site_id,fixed_cost,charger_cost,max_chargers,grid_capacity_kw,power_cost_weight\n"
        "A,1000,3000,2,300,5\n"
        "B,10000,3000,2,300,5\n",
        encoding="utf-8",
    )
    (tmp_path / "demand_points.csv").write_text(
        "demand_id,demand_kwh_day\nD1,900\nD2,800\n", encoding="utf-8"
    )
    (tmp_path / "distances.csv").write_text(
        "site_id,demand_id,distance_km\n"
        "A,D1,10\nA,D2,100\nB,D1,50\nB,D2,20\n",
        encoding="utf-8",
    )
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "charger_daily_capacity_kwh": 1000,
                "max_service_distance_km": 85,
                "charger_peak_power_kw": 150,
                "budget": 18000,
                "distance_weight": 0.1,
            }
        ),
        encoding="utf-8",
    )

    problem = load_problem_from_csv(tmp_path)
    assert problem.site_names == ("A", "B")
    assert problem.demand_names == ("D1", "D2")
    np.testing.assert_allclose(problem.distance_km, [[10, 100], [50, 20]])


def test_csv_loader_rejects_missing_distance_pairs(tmp_path) -> None:
    import json

    import pytest
    from ev_charging.data_io import load_problem_from_csv

    (tmp_path / "sites.csv").write_text(
        "site_id,fixed_cost,charger_cost,max_chargers,grid_capacity_kw,power_cost_weight\n"
        "A,1000,3000,2,300,5\n",
        encoding="utf-8",
    )
    (tmp_path / "demand_points.csv").write_text(
        "demand_id,demand_kwh_day\nD1,900\nD2,800\n", encoding="utf-8"
    )
    (tmp_path / "distances.csv").write_text(
        "site_id,demand_id,distance_km\nA,D1,10\n", encoding="utf-8"
    )
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "charger_daily_capacity_kwh": 1000,
                "max_service_distance_km": 85,
                "charger_peak_power_kw": 150,
                "budget": 18000,
                "distance_weight": 0.1,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must contain all"):
        load_problem_from_csv(tmp_path)


def test_traffic_demand_estimation_uses_explicit_scenario_assumptions() -> None:
    from ev_charging.demand_estimation import (
        TrafficDemandScenario,
        estimate_daily_charging_demand,
    )

    scenario = TrafficDemandScenario(
        demand_id="M1_TEST",
        aadt_vehicles_per_day=10_000,
        ev_share=0.05,
        charging_probability=0.20,
        energy_per_session_kwh=30.0,
        aadt_year=2024,
        source="Illustrative scenario only",
    )
    assert estimate_daily_charging_demand(scenario) == 3_000.0


def test_quadratic_power_loss_extension_is_feasible_and_convex() -> None:
    from ev_charging.data import ProblemData
    from ev_charging.lp_relaxation import solve_ev_lp_relaxation
    from ev_charging.quadratic_extension import solve_ev_quadratic_relaxation

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
    lp = solve_ev_lp_relaxation(problem)
    result = solve_ev_quadratic_relaxation(
        problem,
        line_resistance_ohm=np.array([1.0, 0.01]),
        nominal_voltage_kv=np.array([10.0, 10.0]),
        loss_cost_per_kw=np.array([1_000.0, 1_000.0]),
    )
    assert result.success
    assert result.solution is not None
    assert result.objective_value is not None
    assert result.linear_objective_value is not None
    assert result.objective_value >= result.linear_objective_value
    assert result.total_power_loss_kw is not None and result.total_power_loss_kw >= 0
    assert result.loss_cost is not None and result.loss_cost >= 0
    assert result.kkt is not None
    assert result.kkt.primal_feasibility_inf < 1e-6
    assert result.kkt.stationarity_inf < 1e-5
    assert result.kkt.dual_feasibility_violation < 1e-6
    assert result.kkt.complementarity_inf < 1e-5

    # The linear relaxation prefers the closer site A; the added loss penalty
    # moves most assignment to lower-resistance site B in this illustrative case.
    n = len(problem.site_names)
    m = len(problem.demand_names)
    lp_assignment = lp.assignment
    qp_assignment = result.solution[3 * n : 3 * n + n * m].reshape(n, m)
    assert lp_assignment[0].sum() > lp_assignment[1].sum()
    assert qp_assignment[1].sum() > qp_assignment[0].sum()


def test_mm_s_queue_metrics_are_stable_and_wait_falls_with_more_chargers() -> None:
    from ev_charging.queueing import queue_metrics_from_daily_energy

    two = queue_metrics_from_daily_energy(
        daily_charging_energy_kwh=2000,
        average_session_energy_kwh=25,
        operating_hours_per_day=16,
        average_service_minutes=20,
        chargers=2,
    )
    three = queue_metrics_from_daily_energy(
        daily_charging_energy_kwh=2000,
        average_session_energy_kwh=25,
        operating_hours_per_day=16,
        average_service_minutes=20,
        chargers=3,
    )
    assert two.stable and three.stable
    assert 0 <= two.probability_wait <= 1
    assert three.average_wait_minutes < two.average_wait_minutes


def test_mm_s_queue_reports_unstable_when_arrivals_exceed_service_capacity() -> None:
    from math import inf

    from ev_charging.queueing import mm_s_queue_metrics

    result = mm_s_queue_metrics(
        arrival_rate_per_hour=7.0,
        service_rate_per_hour_per_charger=3.0,
        chargers=2,
    )
    assert not result.stable
    assert result.average_wait_minutes == inf


def test_evup_reference_snapshot_contains_twelve_unique_public_locations() -> None:
    import csv
    from pathlib import Path

    snapshot = Path(__file__).parents[1] / "data" / "reference" / "evup_public_stations_snapshot_2026-11-18.csv"
    with snapshot.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 12
    codes = [row["station_code"] for row in rows]
    assert len(set(codes)) == 12
    assert all(row["source_last_verified"] == "2026-10-25" for row in rows)
    assert all(row["source_url"] == "https://evup.app/map" for row in rows)

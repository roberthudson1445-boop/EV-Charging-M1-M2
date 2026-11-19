from __future__ import annotations

import pytest

from ev_charging import make_toy_problem, solve_milp


def test_milp_accepts_gap_and_time_limit_and_returns_diagnostics() -> None:
    solution = solve_milp(
        make_toy_problem(),
        mip_rel_gap=0.01,
        time_limit_seconds=10.0,
    )
    assert solution.solver_status == 0
    assert solution.mip_gap is None or solution.mip_gap >= 0.0
    assert solution.mip_node_count is None or solution.mip_node_count >= 0


def test_milp_rejects_negative_relative_gap() -> None:
    with pytest.raises(ValueError, match="mip_rel_gap"):
        solve_milp(make_toy_problem(), mip_rel_gap=-0.01)


def test_milp_rejects_nonpositive_time_limit() -> None:
    with pytest.raises(ValueError, match="time_limit_seconds"):
        solve_milp(make_toy_problem(), time_limit_seconds=0.0)

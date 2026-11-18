"""Demonstrate a mixed-integer Gomory cut and Dual Simplex re-optimization."""

from __future__ import annotations

import numpy as np

from ev_charging.gomory import solve_with_gomory_cuts
from ev_charging.revised_simplex import solve_lp


def main() -> None:
    # min x, subject to x >= 1.5, x integer.
    lp = solve_lp(
        np.array([1.0]),
        A_ge=np.array([[1.0]]),
        b_ge=np.array([1.5]),
    )
    if lp.status != "optimal":
        raise SystemExit(f"Initial LP failed: {lp.status}: {lp.message}")

    result = solve_with_gomory_cuts(lp, integer_variable_indices=[0], max_cuts=10)
    print("Initial LP relaxation")
    print(f"  x = {lp.x[0]:.6g}; objective = {lp.objective_value:.6g}")
    print("After Gomory cuts + Dual Simplex")
    print(f"  Status: {result.status}")
    print(f"  x = {result.lp_result.x[0]:.6g}")
    print(f"  Objective = {result.lp_result.objective_value:.6g}")
    print(f"  Cuts added = {len(result.cuts)}")
    if result.status != "integer_optimal":
        raise SystemExit(result.message)


if __name__ == "__main__":
    main()

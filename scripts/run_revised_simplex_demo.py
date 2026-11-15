"""Run a small LP example using the project's own Revised Simplex code."""

from __future__ import annotations

import numpy as np

from ev_charging.revised_simplex import solve_lp


def main() -> None:
    # Maximize 3*x1 + 2*x2 subject to:
    # x1 + x2 <= 4
    # 2*x1 + x2 <= 5
    # x1, x2 >= 0
    # The solver minimizes, so we minimize the negative objective.
    c = np.array([-3.0, -2.0])
    A_ub = np.array([[1.0, 1.0], [2.0, 1.0]])
    b_ub = np.array([4.0, 5.0])

    result = solve_lp(c, A_ub=A_ub, b_ub=b_ub)

    print("=== Revised Simplex demonstration ===")
    print(f"Status: {result.status}")
    print(f"Iterations: {result.iterations}")
    if result.status == "optimal" and result.x is not None:
        print(f"x1 = {result.x[0]:.6f}")
        print(f"x2 = {result.x[1]:.6f}")
        print(f"Maximum objective = {-result.objective_value:.6f}")
        print("Expected optimum: x1 = 1, x2 = 3, objective = 9")
    else:
        raise RuntimeError(result.message)


if __name__ == "__main__":
    main()

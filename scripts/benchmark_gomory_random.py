"""Compare the custom GMI + Dual Simplex pipeline with HiGHS on seeded tiny MILPs."""

from __future__ import annotations

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from ev_charging.gomory import solve_with_gomory_cuts
from ev_charging.revised_simplex import solve_lp


def main() -> None:
    rng = np.random.default_rng(20261118)
    checked = 0
    infeasible = 0
    total_cuts = 0
    max_cuts = 0

    for case_number in range(1, 101):
        variable_count = 3  # first two integer, third continuous
        objective = rng.integers(1, 9, size=variable_count).astype(float)
        A_ge = rng.integers(1, 6, size=(2, variable_count)).astype(float)
        b_ge = rng.integers(4, 18, size=2).astype(float)
        upper = np.array([6.0, 6.0, 12.0])
        A_ub = np.eye(variable_count)

        lp = solve_lp(
            objective,
            A_ub=A_ub,
            b_ub=upper,
            A_ge=A_ge,
            b_ge=b_ge,
        )
        highs = milp(
            objective,
            integrality=np.array([1, 1, 0], dtype=np.int32),
            bounds=Bounds(np.zeros(variable_count), upper),
            constraints=LinearConstraint(A_ge, b_ge, np.full(2, np.inf)),
            # Disable presolve for this small cross-check to avoid presolve
            # implied-integrality inference on the continuous variable.
            options={"presolve": False},
        )

        if highs.status == 2:
            infeasible += 1
            if lp.status != "infeasible":
                raise SystemExit(f"Case {case_number}: solvers disagree on infeasibility.")
            continue
        if highs.status != 0:
            raise SystemExit(f"Case {case_number}: HiGHS did not reach optimality: {highs.message}")
        if lp.status != "optimal":
            raise SystemExit(f"Case {case_number}: custom LP relaxation status is {lp.status}.")

        custom = solve_with_gomory_cuts(lp, integer_variable_indices=[0, 1], max_cuts=100)
        if custom.status != "integer_optimal":
            raise SystemExit(f"Case {case_number}: {custom.status}: {custom.message}")
        if abs(float(custom.lp_result.objective_value) - float(highs.fun)) > 1e-6:
            raise SystemExit(
                f"Case {case_number}: objective mismatch: custom={custom.lp_result.objective_value}, "
                f"HiGHS={highs.fun}."
            )

        checked += 1
        total_cuts += len(custom.cuts)
        max_cuts = max(max_cuts, len(custom.cuts))

    print("Seeded tiny mixed-integer benchmark")
    print(f"Instances matched to HiGHS: {checked}")
    print(f"Infeasible instances agreed: {infeasible}")
    print(f"Total GMI cuts: {total_cuts}")
    print(f"Maximum cuts in one instance: {max_cuts}")
    print("All compared optimal objective values matched.")


if __name__ == "__main__":
    main()

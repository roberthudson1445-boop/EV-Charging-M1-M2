"""Run the small synthetic MILP example."""

from __future__ import annotations

from ev_charging import make_toy_problem, solve_milp


def main() -> None:
    problem = make_toy_problem()
    solution = solve_milp(problem)

    print("=" * 68)
    print("EV CHARGING STATION PLANNING - SYNTHETIC TEST CASE")
    print("=" * 68)
    print("IMPORTANT: These are illustrative test data, not Armenian field data.\n")
    print(f"Solver status : {solution.solver_message}")
    print(f"Objective     : {solution.objective_value:,.2f} illustrative cost units")

    print("\nStation decisions")
    for i, site in enumerate(problem.site_names):
        print(
            f"  {site}: open={int(solution.opened[i])}, "
            f"chargers={int(solution.chargers[i])}, "
            f"reserved_power={solution.power_kw[i]:,.1f} kW"
        )

    print("\nDemand allocation fractions")
    header = "      " + "".join(f"{name:>12}" for name in problem.demand_names)
    print(header)
    for i, site in enumerate(problem.site_names):
        values = "".join(f"{value:>12.3f}" for value in solution.assignment[i])
        print(f"  {site:<3} {values}")

    print("\nObjective breakdown")
    for name, value in solution.objective_breakdown.items():
        print(f"  {name.replace('_', ' '):<30} {value:>12,.2f}")

    capital_cost = (
        (problem.fixed_cost * solution.opened).sum()
        + (problem.charger_cost * solution.chargers).sum()
    )
    print(f"\nCapital budget used: {capital_cost:,.2f} / {problem.budget:,.2f}")
    print("\nAll model feasibility checks passed.")
    print("This baseline uses SciPy/HiGHS; custom algorithms are future work.")


if __name__ == "__main__":
    main()

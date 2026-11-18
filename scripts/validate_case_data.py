"""Validate documented M1/M2 CSV inputs and optionally solve the MILP."""

from __future__ import annotations

import argparse

from ev_charging.data_io import load_problem_from_csv
from ev_charging.model import solve_milp


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data/raw", help="Directory containing case CSV files")
    parser.add_argument("--solve", action="store_true", help="Solve the MILP after data validation")
    args = parser.parse_args()

    problem = load_problem_from_csv(args.data_dir)
    print("Case-study data validation passed.")
    print(f"Candidate sites: {len(problem.site_names)}")
    print(f"Demand points: {len(problem.demand_names)}")
    print(f"Distance pairs: {problem.distance_km.size}")

    if args.solve:
        result = solve_milp(problem)
        print(f"MILP objective: {result.objective_value:,.4f}")
        for index, site in enumerate(problem.site_names):
            print(
                f"{site}: open={int(result.opened[index])}, "
                f"chargers={int(result.chargers[index])}, "
                f"power_kw={result.power_kw[index]:.2f}"
            )


if __name__ == "__main__":
    main()

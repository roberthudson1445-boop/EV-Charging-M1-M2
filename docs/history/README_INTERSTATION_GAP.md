# Interstation-gap MILP update

This patch adds an optional maximum-distance constraint between consecutive
open charging stations along each route, including the route start and end.
The threshold is independent from `max_service_distance_km`.

## Files in this update

- `src/ev_charging/data.py`: optional route metadata and exact pairwise gap rows.
- `src/ev_charging/model.py`: gap rows in the HiGHS MILP and validation.
- `src/ev_charging/lp_relaxation.py`: the same gap rows in the in-house LP relaxation.
- `src/ev_charging/data_io.py`: optional CSV/JSON loading of route metadata.
- `tests/test_model.py`: endpoint, MILP, LP, validation, and loader tests.

The QP extension inherits these constraints automatically because it starts
from the LP relaxation's standard-form matrix. Gomory's integer variables
remain the existing y/z variables; corridor rows contain y variables only.

## Required case-data format to enable the feature

Add these columns to `sites.csv`:

```csv
site_id,route_id,chainage_km,...
M1_C001,M1,0.0,...
M1_C002,M1,10.0,...
M2_C001,M2,0.0,...
```

Add these keys to `config.json`:

```json
{
  "max_interstation_distance_km": 80.0,
  "route_lengths_km": {
    "M1": 100.0,
    "M2": 120.0
  }
}
```

All numbers in the JSON snippet are illustrative placeholders, not the
Armenia route lengths or a recommended threshold. Do not assume the
interstation threshold equals the proposal's 85 km demand-service limit.
Choose it separately and justify it with engineering / policy evidence and
sensitivity analysis.

For the exact route lengths matching the generated candidate-site chainages,
run this command after `prepare_corridor_candidate_data.py`:

```cmd
.\.venv\Scripts\python.exe -c "import pandas as pd; d=pd.read_csv('data/derived/corridor_candidate_sites.csv'); print(d.groupby('route_id')['chainage_km'].max().to_dict())"
```

Copy those full-precision values into `route_lengths_km`. Do not use rounded
lengths printed to three decimals by the route-preparation script.

The current generated candidate sites are OSM route-centreline screening
points. Their road access, land availability, grid connection, costs, and
charger capacities still require validation before a real case-study solve.
The generated demand locations have no measured kWh/day values yet, so this
patch does not create those values or claim an Armenia-wide optimized plan.

## Mathematical form

For two route positions `i < j` separated by more than the allowed gap `R`,
the model adds `y_i + y_j - sum(y_k for candidate sites strictly between i and j) <= 1`.
At route boundaries, the endpoint is fixed to 1 and the row is simplified.
These rows ensure that a pair of consecutive selected stations cannot be
farther apart than `R`, including the first/last station and corridor ends.

## Station opening semantics

The update also adds `z_i >= y_i`: an open station must have at least one
charger. Without this, a zero-charger site could satisfy the interstation
spacing rule while not being a usable charging station.

## Applying

Copy the five files in this archive into the matching paths in the project,
overwriting those five project files. Then run:

```cmd
.\.venv\Scripts\python.exe -m pytest
```

If route columns / config keys are absent, corridor spacing stays disabled,
and the existing synthetic toy case remains compatible.

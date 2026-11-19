# Case-study screening MILP update

## Files

- `src/ev_charging/model.py`: adds optional HiGHS `mip_rel_gap` and `time_limit_seconds` controls, and returns MIP gap/node/dual-bound diagnostics. Default `mip_rel_gap=0.0` preserves the previous exact-optimality request.
- `tests/test_milp_solver_options.py`: tests the new solver options and diagnostics.
- `scripts/run_case_study_screening_milp.py`: prepares and solves one base case and writes low/base/high demand and cost sensitivity tables.

## Install

Copy `src/ev_charging/model.py` into the same path in the project, overwriting the existing file. Copy `tests/test_milp_solver_options.py` into `tests/`. Put `scripts/run_case_study_screening_milp.py` in `scripts/`.

Run tests:

```cmd
.\.venv\Scripts\python.exe -m pytest
```

Run the case-study screening model:

```cmd
.\.venv\Scripts\python.exe scripts\run_case_study_screening_milp.py
```

## What the script does

- Solves the **base demand / base charger-cost** case using the 58 candidate sites, the two documented traffic-counter demand points, 85 km service threshold, and 85 km interstation threshold.
- Requests a 1% relative MIP gap and a 60-second per-run limit. The achieved gap is recorded; it is not an exact optimum unless the reported gap is zero.
- Revalues that same selected layout under low/base/high charger-port costs without re-optimizing the layout.
- Creates low/base/high energy-throughput and station-count lower-bound screening tables.
- Estimates annual electricity-purchase-cost bounds for the two ATC scopes using official ENA tariffs; these are kept outside the current MILP objective.

## Important interpretation

This is a deliberately provisional screening case, not a final investment plan for Armenia.

- Demand inputs represent only two historic automatic traffic counter (ATC) locations and their documented scopes, not the full M1/M2 corridors.
- Demand projections use analyst sensitivity assumptions.
- Site-to-demand distances are same-route chainage proxies, not verified driving distances.
- Candidate sites are OSM centreline screening points, not verified buildable parcels.
- DC 150-kW port hardware/installation costs are US NREL benchmarks used only for sensitivity analysis; they are not Armenian vendor bids.
- A site-level fixed cost benchmark is imported from USDOT. It may overlap partly with generic per-port installation components and requires review.
- Six 150-kW ports per site, 900-kW site grid capacity, and 1,000 kWh/day throughput per port are explicit assumptions, not confirmed utility conditions.
- Grid-upgrade CAPEX is excluded because site-specific utility connection quotes are unavailable.
- The USD 20m budget is a nonbinding placeholder, not an approved Armenian project budget.
- The distance coefficient is an analyst-selected penalty and needs sensitivity calibration.
- Electricity purchase tariffs are reported separately; they are not included in the current MILP objective.

## Sources used in the assumption file

- NREL/TP-5400-88513 (2024), Table 2, DC 150-kW hardware and installation cost ranges.
- USDOT, *Climate Strategies that Work*, charging infrastructure cost considerations.
- Electric Networks of Armenia (ENA), official electricity tariff table, including VAT.

Outputs are written to `data/derived/case_study_screening_milp/`.

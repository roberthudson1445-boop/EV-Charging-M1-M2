# Selected station and demand-assignment comparison

Legacy = chainage-based screening distances. Directed = directed OSM shortest-path distances with virtual edge nodes.

The script reads existing result files only; it does not rerun MILP or change either set of outputs.

## low

- Retained selected sites (5): M1_C004, M1_C012, M2_C007, M2_C015, M2_C023
- Legacy-only sites removed (1): M2_C031
- Directed-only sites added (1): M2_C030
- Chargers: 7 legacy → 7 directed

### Selected-site details

| Site | Status | Chainage (km) | Legacy chargers | Directed chargers | Legacy demand (kWh/day) | Directed demand (kWh/day) |
|---|---|---:|---:|---:|---:|---:|
| M1_C004 | retained | 30.00 | 1 | 1 | 450.28 | 450.28 |
| M1_C012 | retained | 110.00 | 1 | 1 | 0.00 | 0.00 |
| M2_C007 | retained | 60.00 | 2 | 2 | 1,430.74 | 1,430.74 |
| M2_C015 | retained | 140.00 | 1 | 1 | 0.00 | 0.00 |
| M2_C023 | retained | 220.00 | 1 | 1 | 0.00 | 0.00 |
| M2_C030 | directed_only | 290.00 | 0 | 1 | 0.00 | 0.00 |
| M2_C031 | legacy_only | 300.00 | 1 | 0 | 0.00 | 0.00 |

## base

- Retained selected sites (7): M1_C004, M1_C012, M2_C002, M2_C007, M2_C015, M2_C023, M2_C031
- Legacy-only sites removed (0): None
- Directed-only sites added (0): None
- Chargers: 16 legacy → 15 directed

### Selected-site details

| Site | Status | Chainage (km) | Legacy chargers | Directed chargers | Legacy demand (kWh/day) | Directed demand (kWh/day) |
|---|---|---:|---:|---:|---:|---:|
| M1_C004 | retained | 30.00 | 3 | 2 | 2,858.24 | 2,000.00 |
| M1_C012 | retained | 110.00 | 1 | 1 | 0.00 | 858.24 |
| M2_C002 | retained | 10.00 | 6 | 6 | 6,000.00 | 6,000.00 |
| M2_C007 | retained | 60.00 | 3 | 3 | 2,030.66 | 2,030.66 |
| M2_C015 | retained | 140.00 | 1 | 1 | 0.00 | 0.00 |
| M2_C023 | retained | 220.00 | 1 | 1 | 0.00 | 0.00 |
| M2_C031 | retained | 300.00 | 1 | 1 | 0.00 | 0.00 |

## high

- Retained selected sites (12): M1_C003, M1_C004, M1_C012, M2_C001, M2_C002, M2_C003, M2_C004, M2_C005, M2_C007, M2_C015, M2_C023, M2_C031
- Legacy-only sites removed (1): M1_C002
- Directed-only sites added (0): None
- Chargers: 50 legacy → 49 directed

### Selected-site details

| Site | Status | Chainage (km) | Legacy chargers | Directed chargers | Legacy demand (kWh/day) | Directed demand (kWh/day) |
|---|---|---:|---:|---:|---:|---:|
| M1_C002 | legacy_only | 10.00 | 1 | 0 | 983.01 | 0.00 |
| M1_C003 | retained | 20.00 | 6 | 6 | 6,000.00 | 6,000.00 |
| M1_C004 | retained | 30.00 | 6 | 6 | 6,000.00 | 6,000.00 |
| M1_C012 | retained | 110.00 | 1 | 1 | 0.00 | 983.01 |
| M2_C001 | retained | 0.00 | 6 | 6 | 6,000.00 | 6,000.00 |
| M2_C002 | retained | 10.00 | 6 | 6 | 6,000.00 | 6,000.00 |
| M2_C003 | retained | 20.00 | 6 | 6 | 6,000.00 | 6,000.00 |
| M2_C004 | retained | 30.00 | 6 | 6 | 6,000.00 | 6,000.00 |
| M2_C005 | retained | 40.00 | 6 | 6 | 6,000.00 | 6,000.00 |
| M2_C007 | retained | 60.00 | 3 | 3 | 2,610.09 | 2,610.09 |
| M2_C015 | retained | 140.00 | 1 | 1 | 0.00 | 0.00 |
| M2_C023 | retained | 220.00 | 1 | 1 | 0.00 | 0.00 |
| M2_C031 | retained | 300.00 | 1 | 1 | 0.00 | 0.00 |

## armstat_ev_share_2_92

- Retained selected sites (7): M1_C004, M1_C012, M2_C002, M2_C007, M2_C015, M2_C023, M2_C031
- Legacy-only sites removed (0): None
- Directed-only sites added (0): None
- Chargers: 18 legacy → 17 directed

### Selected-site details

| Site | Status | Chainage (km) | Legacy chargers | Directed chargers | Legacy demand (kWh/day) | Directed demand (kWh/day) |
|---|---|---:|---:|---:|---:|---:|
| M1_C004 | retained | 30.00 | 4 | 3 | 3,342.66 | 3,000.00 |
| M1_C012 | retained | 110.00 | 1 | 1 | 0.00 | 342.66 |
| M2_C002 | retained | 10.00 | 6 | 6 | 6,000.00 | 6,000.00 |
| M2_C007 | retained | 60.00 | 4 | 4 | 3,391.70 | 3,391.70 |
| M2_C015 | retained | 140.00 | 1 | 1 | 0.00 | 0.00 |
| M2_C023 | retained | 220.00 | 1 | 1 | 0.00 | 0.00 |
| M2_C031 | retained | 300.00 | 1 | 1 | 0.00 | 0.00 |

## Interpretation and limitations

- A retained site is selected in both solutions; a legacy-only site is removed in the directed solution; a directed-only site is newly selected.
- Candidate coordinates are copied from the site template; the coordinate comparison checks that the same site ID still means the same candidate point.
- Assignment differences should be interpreted alongside the demand-point scope and the model's 85-km directed demand-to-site service limit.
- Interstation spacing remains chainage-based, not directed road-distance-based.
- The results remain screening-model outputs: three represented demand scopes, OSM-based access approximations, assumed grid capacity and US benchmark CAPEX. They are not construction-ready recommendations.

## Output files

- `data/derived/case_study_screening_milp_directed_network/scenario_runs/selected_site_location_comparison.csv`
- `data/derived/case_study_screening_milp_directed_network/scenario_runs/selected_site_comparison_summary.csv`
- `data/derived/case_study_screening_milp_directed_network/scenario_runs/demand_assignment_comparison.csv`

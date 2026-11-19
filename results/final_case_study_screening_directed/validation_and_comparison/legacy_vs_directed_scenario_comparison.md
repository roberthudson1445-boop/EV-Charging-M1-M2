# Legacy vs directed-network MILP comparison

The legacy results use the earlier chainage-based distance screening matrix. The directed results use the directed OSM shortest-path matrix with virtual edge nodes.

| Scenario | Legacy stations | Directed stations | Legacy chargers | Directed chargers | Legacy CAPEX proxy (USD) | Directed CAPEX proxy (USD) | CAPEX change (USD) |
|---|---:|---:|---:|---:|---:|---:|---:|
| low | 6 | 6 | 7 | 7 | 1,697,400 | 1,697,400 | 0 |
| base | 7 | 7 | 16 | 15 | 3,188,200 | 3,034,000 | -154,200 |
| high | 13 | 12 | 50 | 49 | 9,049,000 | 8,791,800 | -257,200 |
| armstat_ev_share_2_92 | 7 | 7 | 18 | 17 | 3,496,600 | 3,342,400 | -154,200 |

## Interpretation notes

- This is a comparison of screening-model outputs, not evidence that either layout is construction-ready.
- CAPEX proxy uses the same benchmark cost assumptions only if the legacy and directed scenario input assumptions match; inspect each scenario's assumptions before interpreting cost changes.
- Service assignment now uses directed demand-to-site OSM distances. Interstation spacing remains based on route chainage in the present formulation.
- Demand coverage is limited to the three represented demand subsections; unobserved corridor demand is not modeled.
- OSM edge proximity does not confirm legal driveway access, land availability, or utility connection capacity.
- MIP gaps and solver statuses are recorded in the CSV; compare only runs with accepted solver statuses.

CSV: `data\derived\case_study_screening_milp_directed_network\scenario_runs\legacy_vs_directed_scenario_comparison.csv`

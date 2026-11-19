# Final Directed-Network Case Study Results

## Armenia M1/M2 Electric Vehicle Fast-Charging Infrastructure



**Project:** Optimal Siting and Capacity Allocation of EV Fast-Charging Infrastructure along Armenia's M1 and M2 Corridors

**Method:** Mixed-Integer Linear Programming (MILP) with directed road-network service distances

**Solver:** SciPy / HiGHS

**Status:** Preliminary technical screening and scenario analysis



---



## 1. Purpose



This directory preserves the principal outputs, validation records, input tables, and preliminary financial screening for the directed-network M1/M2 case study.



The results compare four EV-demand scenarios: Low, Base, High, and an Armstat-based EV-share scenario.



These are screening results, not final construction or investment recommendations.



## 2. Main MILP Results



| Scenario | Daily demand (kWh/day) | Stations | Chargers | Installed power (kW) | CAPEX proxy (USD) | Achieved MIP gap |

|---|---:|---:|---:|---:|---:|---:|

| Low | 1,881.02 | 6 | 7 | 1,050 | 1,697,400 | 0.09365% |

| Base | 10,888.90 | 7 | 15 | 2,250 | 3,034,000 | 0.06691% |

| High | 45,593.11 | 12 | 49 | 7,350 | 8,791,800 | 0.08815% |

| Armstat | 12,734.37 | 7 | 17 | 2,550 | 3,342,400 | 0.09773% |



All four runs reached the requested relative MIP gap tolerance of 0.1%. The reported CAPEX values are benchmark-based screening proxies.



The composite model objective contains a distance penalty and is not expressed in USD. The separate CAPEX proxy should be used for capital-cost comparisons.



## 3. Directory Structure



### `scenarios/`



Contains one directory for each demand scenario:



- `low/`

- `base/`

- `high/`

- `armstat_ev_share_2_92/`



Each scenario directory includes:



- `milp_scenario_summary.csv` — solver status, objective, CAPEX proxy, station and charger counts.

- `milp_selected_sites.csv` — selected candidate sites and charger allocation.

- `milp_demand_assignments.csv` — demand assignment results and directed distances.

- `capital_cost_sensitivity_fixed_layout.csv` — alternative charger-cost valuation of the fixed selected layout; not a re-optimized solution.

- `demand_capacity_screening.csv` — capacity and spacing screening bounds.

- `electricity_opex_atc_scope.csv` — electricity purchase cost estimates for represented traffic scopes.

- `global_assumptions.json` and `README.txt` — assumptions and scenario documentation.

- `inputs/` - solver input tables, including demand points, candidate sites, distances, directed distance audit, configuration, and assumptions.



### `validation_and_comparison/`



Contains:



- `DIRECTED_SCENARIO_VALIDATION.csv` — scenario output validation.

- `legacy_vs_directed_scenario_comparison.csv` and `.md` — comparison of legacy and directed-distance results.

- `demand_assignment_comparison.csv` — assignment comparison.

- `selected_site_comparison_summary.csv`

- `selected_site_location_comparison.csv`

- `selected_site_and_assignment_comparison.md`



### `financial/`



Contains:



- `financial_reference_cases.csv` — one reference financial case per demand scenario.

- `financial_screening_sensitivity.csv` — 432 financial sensitivity combinations.

- `financial_break_even_utilization.csv` — 108 break-even demand-realization cases.

- `financial_assumptions.json` — financial assumptions and provenance.

- `README.txt` — financial method and interpretation limitations.



## 4. Validation



The directed scenario validation file records 12 validation conditions for each of the four scenarios, for a total of 48 successful checks.



The checks cover:



- Solver status and achieved MIP gap.

- Agreement between selected-site counts and summary results.

- Agreement between charger counts and summary results.

- Complete demand assignment.

- Assignment fractions summing to one.

- Demand-to-site distance direction.

- Assigned distances not exceeding 85 km.

- Assignments restricted to selected sites.

- Assigned energy matching the demand inputs.

- Summary demand matching the input demand.



The project test suite previously completed with 26 passing tests.



## 5. Modelling Scope and Assumptions



### Demand representation



Demand is represented by three traffic locations or subsections:



1. M1 Section 3 historical ATC reference.

2. M2 km 9.3–13.1 historical ATC reference.

3. M2 km 13.1–28.9 ADB forecast-based subsection reference at km 16.



No full-corridor demand interpolation is performed.



### Road distances



Demand-service distances are directed OSM shortest-path driving distances from demand points to charging sites. Virtual points are inserted on nearby directed road-edge geometries.



Cross-corridor or unreachable pairs are retained in the full matrix using a 99,999 km sentinel and are excluded by the 85 km service-distance limit.



Interstation spacing is still measured using corridor chainage, with an 85 km maximum spacing assumption. It is not calculated using directed driving distances.



### Site and engineering assumptions



- Candidate sites are OSM-derived screening points, not approved construction parcels.

- Six 150 kW chargers per site is the assumed maximum.

- Site grid capacity is assumed to be 900 kW.

- Charger throughput is assumed to be 1,000 kWh/day per port.

- Grid-upgrade CAPEX is excluded.

- The USD 20 million budget is a nonbinding screening assumption.

- The fixed-site and per-port cost benchmarks may have overlapping cost boundaries and require review.



## 6. Preliminary Financial Screening



The financial screening uses the directed-network CAPEX proxies from the four validated scenario runs.



The reference assumptions include:



- Retail electricity price: AMD 205/kWh.

- ENA purchase tariff reference: AMD 50.48/kWh.

- Energy losses: 5% assumption.

- Exchange rate: USD 1 = AMD 360.41, dated 18 November 2026.

- Fixed O&M sensitivities: 2%, 4%, and 6% of CAPEX per year.

- Discount-rate sensitivities: 8%, 10%, and 12%.

- Project-life sensitivities: 10, 15, and 20 years.

- Demand realization sensitivities: 25%, 50%, 75%, and 100%.



Energy contribution is calculated as retail revenue less electricity-purchase cost only.



The financial outputs are preliminary sensitivity indicators. They are not bankable profitability estimates or investment advice.



## 7. Important Limitations



The results must be interpreted within the following limitations:



1. Three demand scopes do not represent total traffic demand along the complete M1 and M2 corridors.

2. Traffic forecasts and EV adoption assumptions introduce uncertainty.

3. OSM road-edge proximity does not establish legal driveway access or parcel buildability.

4. Interstation spacing is chainage-based, while demand-service distance is road-network-based.

5. Cost inputs are external benchmarks rather than verified Armenian contractor quotations.

6. Grid connection capacity and site-specific grid-upgrade costs are unverified.

7. Retail and purchase electricity VAT treatment is not normalized.

8. Taxes, financing, working capital, charger replacement, inflation, demand growth, and residual value are not fully modelled.

9. The composite MILP objective is not a monetary objective because it includes an analyst-set distance penalty.



Consequently, the results should be described as a transparent preliminary planning and optimization study, not as a final infrastructure investment plan.



## 8. Reproducibility



The scenario folders preserve the input tables and assumptions used for the four MILP runs. The full directed road graph and raw OpenStreetMap source data are maintained separately and are not included in this results package.



Relevant project scripts include:



- `scripts/run_case_study_scenario.py`

- `scripts/run_case_study_screening_milp.py`

- `scripts/validate_directed_scenario_outputs.py`

- `scripts/build_preliminary_financial_screen_directed.py`



The preserved input tables support inspection and reproduction of the scenario-level optimization without requiring the raw road-network files to be committed to the repository.



---



**Interpretation:** These results constitute the current validated directed-network screening case study for the Armenia M1/M2 EV fast-charging infrastructure project. Further demand-data expansion, local engineering quotations, grid feasibility checks, and site-access verification are required before implementation-level conclusions can be made.

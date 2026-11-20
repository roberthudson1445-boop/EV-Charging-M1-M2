# EV Fast-Charging Infrastructure Planning on Armenia's M1 and M2 Corridors

**Project:** Optimal Siting and Capacity Allocation of EV Fast-Charging Infrastructure along Armenia's M1 and M2 Corridors
**Methods:** Mixed-Integer Linear Programming (MILP), directed road-network analysis, and optimization-algorithm implementations
**Primary MILP solver for the final case study:** SciPy / HiGHS
**Repository status:** Preliminary directed-network case study and reproducible result package committed on `main`

## 1. Project overview

This repository develops and applies a mathematical optimization framework for the preliminary planning of EV fast-charging stations along Armenia's M1 and M2 road corridors.

The model selects candidate station locations, allocates integer numbers of chargers, assigns represented charging demand to eligible stations, and checks service-distance, interstation-spacing, throughput, electrical-capacity, and investment-budget constraints.

The project combines:

- Official Armenian corridor route references and OpenStreetMap (OSM) road geometry.
- Historical automatic traffic-count (ATC) records and an ADB forecast-based M2 subsection estimate.
- Four EV charging-demand scenarios: Low, Base, High, and Armstat.
- A directed OSM driving graph and demand-to-station shortest-path distances.
- A MILP infrastructure-location and capacity-allocation model.
- Independent scenario validation, sensitivity analysis, and preliminary financial screening.

**Interpretation:** This is a transparent preliminary planning and optimization case study. It is not a final construction plan, a complete corridor-wide demand forecast, or a bankable investment feasibility study.

## 2. Current case-study results

The final directed-network case study uses 58 candidate sites (20 on M1 and 38 on M2) and three documented demand scopes.

| Scenario | Daily demand (kWh/day) | Stations | Chargers | Installed peak power (kW) | CAPEX proxy (USD) | Achieved MIP gap |
|---|---:|---:|---:|---:|---:|---:|
| Low | 1,881.02 | 6 | 7 | 1,050 | 1,697,400 | 0.09365% |
| Base | 10,888.90 | 7 | 15 | 2,250 | 3,034,000 | 0.06691% |
| High | 45,593.11 | 12 | 49 | 7,350 | 8,791,800 | 0.08815% |
| Armstat | 12,734.37 | 7 | 17 | 2,550 | 3,342,400 | 0.09773% |

All four runs reached the requested relative MIP-gap tolerance of 0.1%. A solution within a nonzero MIP gap is not an exact proof of global optimality. The values labelled **CAPEX proxy** are benchmark-based estimates, not Armenian contractor quotations.

The MILP objective includes a distance-demand penalty with an analyst-selected coefficient. Because that coefficient is not dimensionally calibrated to USD, the composite objective value is in model units and must not be interpreted as a dollar cost. Use the separately reported CAPEX proxy for capital-cost comparisons.

### Base-scenario selected sites

| Site | Corridor | Approx. chainage (km) | Chargers | Assigned demand (kWh/day) |
|---|---|---:|---:|---:|
| M1_C004 | M1 | 30 | 2 | 2,000.00 |
| M1_C012 | M1 | 110 | 1 | 858.24 |
| M2_C002 | M2 | 10 | 6 | 6,000.00 |
| M2_C007 | M2 | 60 | 3 | 2,030.66 |
| M2_C015 | M2 | 140 | 1 | 0 |
| M2_C023 | M2 | 220 | 1 | 0 |
| M2_C031 | M2 | 300 | 1 | 0 |

The three M2 sites with zero assigned demand are selected to satisfy the chainage-based interstation-spacing requirement. They should not be described as serving observed demand in the current three-scope demand dataset.

## 3. Demand representation and scope

Demand is represented by three traffic locations or subsections only:

1. **M1 Section 3:** historical ATC reference at approximately M1 km 20.7.
2. **M2 km 9.3–13.1:** historical ATC reference at approximately M2 km 9.38.
3. **M2 km 13.1–28.9:** ADB forecast-based subsection reference at approximately M2 km 16.

The first two scopes use historical ATC observations, with the latest observations used in the demand scenarios from 2017 (M1) and 2018 (M2). Their 2026 traffic values are scenario projections based on historical growth assumptions, not measured 2026 counts.

The additional M2 subsection uses ADB's 2025 and 2032 traffic forecasts, interpolated to 2026, and applies the 2012 light-vehicle composition share. It is also an estimate, not a measured 2026 observation.

The four scenarios use the following EV-share assumptions:

| Scenario | EV share | Charging probability | Energy/session |
|---|---:|---:|---:|
| Low | 1.25% | 10% | 20 kWh |
| Base | 2.50% | 20% | 25 kWh |
| High | 5.00% | 30% | 30 kWh |
| Armstat | 2.9237% | 20% | 25 kWh |

The Armstat share is calculated from 23,759 fully electric passenger cars out of 812,634 registered passenger cars as of 1 November 2025. EV share is applied to light-vehicle traffic; heavy vehicles are excluded from the initial charging-demand estimate.

**No full-corridor demand interpolation is performed.** The 44 official route waypoint anchors are geographical references, not 44 measured demand points. Other locations along M1 and M2 remain unquantified in the current demand model.

## 4. Directed road-network analysis

The road graph was built from a local Geofabrik Armenia OSM PBF extract. The original graph contains approximately 68,642 nodes and 176,406 directed edges. After virtual points were inserted into nearby directed road-edge geometries, the augmented graph contains approximately 68,699 nodes and 176,500 directed edges.

The site-demand distance matrix includes:

- 58 candidate sites and 3 demand points: **174 pairs**.
- **96** same-corridor pairs, all reachable in the constructed graph.
- **78** cross-corridor pairs structurally excluded from assignment.
- **33** same-corridor pairs within the 85 km service limit.
- **63** same-corridor pairs exceeding the 85 km service limit.
- **60** pairs with a difference greater than 1 km between the two travel directions.

Demand-service distance is the directed shortest driving distance **from demand point to charging site** (`demand_to_site`). Cross-corridor or unreachable combinations are represented with a 99,999 km sentinel so that they are ineligible under the 85 km service-distance constraint.

The separate 85 km interstation-spacing requirement is based on corridor chainage, not directed driving distance. The two constraints serve different purposes and should not be conflated.

OSM road-edge proximity does not confirm a legal driveway, parcel access, land availability, or construction approval. Route-leg geometry and access still require local review.

## 5. Mathematical model and optimization methods

The MILP uses the following decision variables:

- `y[i]`: binary variable equal to 1 if candidate site `i` is opened.
- `z[i]`: non-negative integer number of chargers at site `i`.
- `P[i]`: continuous installed active power at site `i` (kW).
- `x[i,j]`: continuous fraction of demand point `j` assigned to site `i`.

The formulation enforces:

- Full assignment of each represented demand point.
- Assignment only to opened, eligible sites.
- Maximum directed demand-to-site service distance.
- Charger daily-throughput capacity.
- Minimum and maximum charger count at each opened station.
- Installed power and assumed site grid-capacity limits.
- An investment-budget limit.
- Maximum interstation spacing along corridor chainage.

The project also includes custom implementations/demonstrations of:

- Two-phase Revised Simplex for LPs.
- Mixed-Integer Gomory (GMI) cutting-plane generation.
- Dual Simplex re-optimization after adding cuts.

**Important solver distinction:** the four full M1/M2 case-study MILP scenarios reported above were solved using `scipy.optimize.milp` with the HiGHS backend. The custom Revised Simplex, GMI, and Dual Simplex routines are separate algorithmic implementations and small-instance demonstrations; the final corridor scenarios should not be described as having been solved by the standalone Gomory implementation.

## 6. Main modeling assumptions

| Parameter | Reference value | Status |
|---|---:|---|
| Charger rated power | 150 kW | Design assumption |
| Maximum chargers per site | 6 | Design assumption |
| Site grid capacity | 900 kW | Assumed; not utility-confirmed |
| Daily throughput per charger | 1,000 kWh/day | Planning assumption |
| Maximum service distance | 85 km | Screening assumption |
| Maximum interstation gap | 85 km | Chainage-based screening assumption |
| Fixed site cost | USD 103,000 | US benchmark |
| Base 150-kW charger cost | USD 154,200/port | US NREL benchmark midpoint |
| Investment budget | USD 20 million | Nonbinding screening placeholder |
| Distance penalty coefficient | 0.1 | Analyst-selected; not dimensionally calibrated |
| Grid-upgrade CAPEX | Excluded | No site-specific utility quotations |

The fixed-site and per-port cost estimates are taken from separate US benchmark sources and may have overlapping cost boundaries. Their application to Armenia requires local validation. Grid capacity is assumed, not confirmed by the electricity utility.

## 7. Sensitivity and preliminary financial screening

The Base-demand service-distance sensitivity produced 7 stations and 16 chargers at 50–70 km, 7 stations and 15 chargers at 80–100 km, and 6 stations and 14 chargers at 120 km.

Across the tested low/base/high charger-cost assumptions, the selected station and charger counts remained unchanged within each demand scenario, while the CAPEX proxy changed with the assumed per-port price.

The preliminary financial screen uses an AMD 205/kWh reference retail price, an ENA daytime 6(10) kV purchase-tariff reference of AMD 50.48/kWh, a 5% energy-loss assumption, fixed O&M at 4% of CAPEX per year in the reference case, a 15-year evaluation period, and a 10% discount rate. Demand realization and other parameters are also tested in sensitivity cases.

| Scenario | Reference NPV (USD) | Simple payback (years) | IRR |
|---|---:|---:|---:|
| Low | -13,418 | 7.67 | 9.86% |
| Base | 8,780,698 | 1.95 | 51.09% |
| High | 41,867,888 | 1.32 | 75.74% |
| Armstat | 10,537,279 | 1.83 | 54.52% |

The financial results are preliminary screening indicators, not bankable profitability estimates. The current model does not fully include taxes, financing, working capital, charger replacement, inflation, demand growth, residual value, confirmed land costs, or site-specific grid-upgrade costs. VAT treatment between retail and purchase prices is not normalized.

## 8. Validation status

The directed scenario validation report records passing checks across all four scenarios, including solver status and achieved MIP gap, station and charger counts, full demand assignment, assignment fractions, demand-to-site direction, service-distance eligibility, assignments to opened sites, and consistency between assigned energy and input demand.

The project test suite's last recorded run completed with **26 passing tests**. Re-run the tests in the local project environment before making a new release.

Validation artifact: [`results/final_case_study_screening_directed/validation_and_comparison/DIRECTED_SCENARIO_VALIDATION.csv`](results/final_case_study_screening_directed/validation_and_comparison/DIRECTED_SCENARIO_VALIDATION.csv)

## 9. Key result files

The complete directed-network results package is stored in [`results/final_case_study_screening_directed/`](results/final_case_study_screening_directed/README.md).

- `scenarios/low/`, `scenarios/base/`, `scenarios/high/`, `scenarios/armstat_ev_share_2_92/`: scenario summaries, selected sites, demand assignments, assumptions, and preserved input snapshots.
- `validation_and_comparison/`: validation report and legacy-versus-directed comparisons.
- `financial/`: reference financial cases, 432 sensitivity combinations, break-even cases, assumptions, and interpretation notes.
- `docs/EV_Charging_M1_M2_Technical_Reference_English.md`: consolidated technical reference and validation log.
- `docs/data_sources.md`: data-source register and known data gaps.

Raw OpenStreetMap PBF files and the full country-scale graph are large local inputs and are not included in the results package. The preserved scenario input snapshots allow inspection of the final case-study inputs without committing those large files.

## Interactive map

[🌐 Open the Live Interactive Map](https://roberthudson1445-boop.github.io/EV-Charging-M1-M2/docs/interactive_map/EV_Charging_M1_M2_Interactive_Map.html)
A browser-based interactive companion map is included in [`docs/interactive_map/`](docs/interactive_map/). It displays the selected candidate charging sites for the Low, Base, High, and Armstat scenarios. Select a scenario and click a station marker to inspect its corridor, chainage, charger count, installed power, and assigned daily demand.

### Run locally on Windows

1. Open the repository folder in File Explorer.
2. Open `docs\interactive_map\`.
3. Double-click `Open_Map.bat`.
4. Keep the minimized local Python server window open while using the map.

Python 3 and an internet connection are required. The internet connection loads the Leaflet library and OpenStreetMap background tiles. Do not open the HTML file directly with a `file://` address; use the batch launcher so the map runs through `http://127.0.0.1:8765`.

**Interpretation:** Map markers represent optimized candidate locations, not approved or operating charging stations. The visualization covers the three documented demand scopes only; site access, land availability, grid connections, and local costs remain unverified. The static corridor figure in the thesis and presentation is retained for printing, while this HTML companion provides interactive scenario selection.


## 10. Setup and tests (Windows)

From Command Prompt in the repository root:

```cmd
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
```

Run the test suite:

```cmd
.\.venv\Scripts\python.exe -m pytest
```

Validate the four directed scenario outputs (requires the generated local `data/derived/` case-study inputs and outputs):

```cmd
.\.venv\Scripts\python.exe scripts\validate_directed_scenario_outputs.py
```

The directed scenario batch runner is:

```cmd
run_all_directed_scenarios.bat
```

It requires the local generated demand scenarios, candidate-site template, route metadata, and directed distance matrix. Do not re-run scenario-generation scripts merely to read the committed results; inspect the preserved CSV/JSON snapshots under `results/final_case_study_screening_directed/` first.

## 11. Repository structure

```text
EV-Charging-M1-M2/
├── data/
│   ├── raw/                 # local/raw data; large source files may be git-ignored
│   ├── reference/           # traffic and reference evidence
│   └── derived/             # generated local inputs and intermediate outputs
├── docs/                    # technical reference and data-source notes
│   ├── history/             # archived notes from earlier development stages
│   └── interactive_map/     # interactive scenario map and local launcher
├── results/
│   └── final_case_study_screening_directed/
│       ├── scenarios/
│       ├── validation_and_comparison/
│       └── financial/
├── scripts/                 # data preparation, optimization, validation, analysis
├── src/ev_charging/         # MILP model and optimization algorithms
├── tests/                   # automated tests
├── run_all_directed_scenarios.bat
├── pyproject.toml
└── requirements.txt
```

## 12. Historical development notes

The files under [`docs/history/`](docs/history/README.md) preserve documentation from earlier development stages. They are retained for traceability, but some paths, commands, assumptions, or data-scope statements in them describe superseded versions of the project.

**For the current case-study status, results, assumptions, validation artifacts, and operating instructions, use this root README and the preserved result package under `results/final_case_study_screening_directed/`. Do not apply old patch instructions from the historical notes to the current checkout without first checking the current code and inputs.**

Historical notes:

- [`README_CASE_STUDY_SCREENING.md`](docs/history/README_CASE_STUDY_SCREENING.md): earlier chainage-proxy screening stage.
- [`README_DIRECTED_DISTANCE_INTEGRATION.txt`](docs/history/README_DIRECTED_DISTANCE_INTEGRATION.txt): development note for integrating directed OSM distances.
- [`README_INTERSTATION_GAP.md`](docs/history/README_INTERSTATION_GAP.md): development note for adding the interstation-spacing constraints.

## 13. Data sources and attribution

- **ADB (2020):** [North-South Road Corridor Investment Program, Tranche 1 Completion Report](https://www.adb.org/sites/default/files/project-documents/42145/42145-023-pcr-en.pdf), Appendix 9. Historical ATC records and subsection forecasts are not current 2026 measurements.
- **SEI (2025):** [National Comprehensive Green Transition Assessment Report for Armenia](https://www.sei.org/wp-content/uploads/2023/07/nationalcomprehensiveassessment-armenia.pdf). Used as the reference for the 2.5% EV-share scenario.
- **Armstat (2025):** Vehicle-registration statistics used to calculate the registered fully electric passenger-car share for the Armstat scenario.
- **OpenStreetMap contributors:** [Copyright and License](https://www.openstreetmap.org/copyright). Road data are subject to ODbL attribution requirements.
- **Geofabrik:** [Armenia OSM extract](https://download.geofabrik.de/asia/armenia.html).
- **NREL (2024):** [Assessment of Alternative Fueling Infrastructure](https://www.nrel.gov/docs/fy24osti/88513.pdf), used as a US benchmark for 150-kW DC charger hardware and installation costs.
- **U.S. Department of Transportation:** [Climate Strategies That Work](https://climateprogramportal.org/wp-content/uploads/2025/02/USDOT-Climate-Strategies-That-Work-JAN-2025.pdf), used as a US fixed-site cost benchmark.
- **Electric Networks of Armenia:** [Technical information](https://www.ena.am/AboutUs.aspx?id=3&lang=2). Public aggregate information does not replace site-specific grid-capacity confirmation.

See [`docs/data_sources.md`](docs/data_sources.md) and the scenario-level `assumptions.json` files for provenance, dates, units, and limitations.

---

**Final interpretation:** The repository contains the completed preliminary directed-network case-study implementation and its preserved scenario results. Corridor-wide traffic-demand coverage, parcel access, local engineering data, utility connection capacity, Armenian contractor quotations, and a complete investment-grade financial model remain outside the validated scope.

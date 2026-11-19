# Technical Reference and Final Validation Log
## Optimal Siting and Capacity Allocation of Fast EV Charging Stations along Armenia's M1 and M2 Corridors

**Reference date:** 19 November 2026  
**Purpose:** Consolidated record of project results, assumptions, sources, limitations, and remaining checks before preparing the final diploma.  
**Status:** Preliminary consolidation and audit of results run and validated in the project environment.

> This document is not the final diploma and is not a bankable feasibility study. It consolidates the user's reported run outputs, validation outputs, and the reviewed data sources and assumptions. The local project directory (`C:\Users\User\EV-Charging-M1-M2`) was not directly accessed during preparation of this reference; a final operational check of the CSV files on the user's machine remains necessary before submission.

---

## 1. Executive Summary

The project has completed the main stages of geographic network construction, directed road-distance calculation, integration of those distances into the MILP model, execution of four demand scenarios, comparison with the earlier chainage-based results, sensitivity analysis of service distance and charger cost/demand, and an updated preliminary financial screen using the new CAPEX proxies.

The following are the principal results reported from the project runs:

| Scenario | Daily demand (kWh/day) | Stations | Chargers | Installed peak power (kW) | CAPEX proxy (USD) | MIP gap |
|---|---:|---:|---:|---:|---:|---:|
| Low | 1,881.02 | 6 | 7 | 1,050 | 1,697,400 | 0.0936% |
| Base | 10,888.90 | 7 | 15 | 2,250 | 3,034,000 | 0.0669% |
| High | 45,593.11 | 12 | 49 | 7,350 | 8,791,800 | 0.0881% |
| Armstat EV share 2.92% | 12,734.37 | 7 | 17 | 2,550 | 3,342,400 | 0.0977% |

**Validation result:** All four scenarios passed the 12 validation checks reported for each scenario, for a total of 48 successful checks according to `validate_directed_scenario_outputs.py`. All recorded MIP gaps are below the requested 0.1% threshold.

**Scope:** Demand data represent only three locations/subsections: M1 Section 3, M2 km 9.3–13.1, and M2 km 13.1–28.9. These results do not represent a final allocation for all demand along the full M1 and M2 corridors.

## 2. Model Definition and Scope

The project concerns the optimal siting and capacity allocation of fast electric-vehicle charging infrastructure along Armenia's M1 and M2 roads, using a mixed-integer linear programming (MILP) model.

In the current implementation:

- The site-opening variable is binary; the number of chargers is integer; the demand-assignment variable is continuous/fractional; and electrical capacity is represented as active power in kilowatts.
- The entire demand at each demand point is assigned among eligible service sites. The implemented formulation is therefore a **facility-location and allocation model with full demand assignment**, not a conventional Maximum Covering Location Problem (MCLP) that permits some demand to remain uncovered.
- The service distance used in the assignment constraint is a directed driving distance from the demand point to the charging station (`demand_to_site`).
- The maximum gap between consecutive charging stations is still based on route chainage, not on directed driving distance over the road network.

### Model operating assumptions

| Assumption | Value | Classification |
|---|---:|---|
| Charger rated power | 150 kW | Design assumption |
| Maximum chargers per site | 6 | Design assumption |
| Assumed grid capacity per site | 900 kW | Assumption; not confirmed by the electricity utility |
| Daily throughput per charger | 1,000 kWh/day | Assumption equivalent to approximately 6.67 full-load hours |
| Maximum service distance | 85 km | Base-case screening value |
| Maximum interstation gap | 85 km | Chainage-based; separate from service distance |
| Fixed site cost | USD 103,000 | US DOT benchmark |
| Base charger cost | USD 154,200/port | Midpoint of US NREL benchmark values |
| Budget | USD 20,000,000 | Nonbinding screening ceiling, not an approved project budget |
| Distance-penalty coefficient | 0.1 | Analyst-selected coefficient; not dimensionally calibrated |
| Grid-upgrade cost | Excluded | No site-specific utility connection quotations available |
| Solver MIP-gap target | 0.1% | Solver setting |
| Time limit | 180 seconds | Solver setting per case |

**Unit-consistency warning:** The objective function combines cost components denominated in USD with a distance penalty using an analyst-selected coefficient. The composite objective value must therefore not be described as a dollar amount until the coefficient and its units have been calibrated. CAPEX proxy is reported separately for cost comparisons.

## 3. Demand Data and Sources

### 3.1 Three represented demand scopes

1. **M1 Section 3:** A traffic counter at M1 km 20.7 is used to represent M1 Section 3 only.
2. **M2 km 9.3–13.1:** An ATC counter at M2 km 9.38. The ADB report indicates that this counter represents the section up to the M15 junction at km 13.1, not the full M2 corridor.
3. **M2 km 13.1–28.9:** An additional demand point referenced at km 16, constructed using ADB data. It is not an actual measured traffic count for 2026.

### 3.2 Conversion of ADB data into a 2026 demand point

The 2020 ADB completion report, Appendix 9, Table 4, reports a 2012 total of 13,942 vehicles/day for the M2 km 13.1–28.9 subsection. Passenger cars, pick-ups, and minibuses were treated as light-vehicle classes: 10,960 + 1,129 + 986 = 13,075 vehicles/day. The resulting light-vehicle share is 13,075 / 13,942 = 93.781%.

Table 5 reports ADB traffic forecasts for the same subsection of 23,200 vehicles/day in 2025 and 28,300 in 2032. The script calculated the compound annual growth rate between those two forecast values and projected one year to 2026:

- Compound annual growth rate: approximately 2.88%.
- Calculated 2026 total traffic: approximately 23,868 vehicles/day.
- Equivalent light-vehicle traffic: approximately 22,383.8 vehicles/day.

This is a **mathematical interpolation/extrapolation between two ADB forecast values**, not traffic measured in 2026. The use of the 2012 vehicle composition is also a projection assumption and must be described as such in the diploma.

### 3.3 Demand scenarios

The Low/Base/High scenarios use the project's assumptions for EV share, charging probability, and energy per charging session. The Armstat scenario uses the registered share of fully electric passenger cars:

- Armstat, 1 November 2025: 23,759 fully electric passenger cars out of 812,634 passenger cars.
- Calculated share = 2.9237%, rounded to 2.92% in the scenario name.

This is a share of the registered passenger-car stock, not a share of all vehicles or all road traffic.

## 4. Road-Network Preparation and Distance Matrix

### 4.1 Road network

- Data source: a local Geofabrik Armenia OSM PBF extract, `data/raw/armenia-latest.osm.pbf`, used instead of relying on Overpass after earlier request failures.
- Pyrosm created a directed driving graph, retaining components and respecting one-way road directionality.
- Original graph: **68,642 nodes and 176,406 directed edges**.
- After inserting virtual nodes into road edges: **68,699 nodes and 176,500 directed edges**.
- Projected metric coordinate reference system: EPSG:32638.

### 4.2 Virtual point insertion

The 58 candidate sites and 3 demand points (61 points in total) were checked. The reported maximum geometric distance from any point to its nearest road-edge geometry was 0.0 m. In addition, 37 coincident reverse directed edges were split at the corresponding locations without creating reverse directions that did not already exist.

**Important interpretation:** A reported distance of zero means that a point lies on the road geometry in the OSM centreline/edge layer. It does not confirm a legal entrance, a drivable access link, or a buildable parcel.

### 4.3 Final distance-matrix statistics

| Indicator | Value |
|---|---:|
| Candidate sites | 58 |
| Demand points | 3 |
| Matrix pairs | 174 |
| Cross-corridor pairs structurally excluded | 78 |
| Same-corridor pairs | 96 |
| Same-corridor pairs with a directed path | 96 |
| Same-corridor pairs with no directed path | 0 |
| Reachable pairs exceeding 85 km | 63 |
| Reachable pairs within 85 km | 33 |
| Pairs with more than 1 km difference between directions | 60 |

Route-level distance summary: M1 has 20 pairs, ranging from 9.24 to 127.73 km, with a mean of 66.12 km. M2 has 76 pairs, ranging from 0.62 to 315.05 km, with a mean of 163.84 km.

The matrix used in the current model run is:

`data/derived/network_distance_validation/corridor_site_demand_distances_virtual_edge.csv`

The `distance_km` field represents travel from demand to charging site. The reverse-direction distance is retained for comparison but is not used for assignment.

### 4.4 Geographic accuracy limits

- Connecting points to their nearest edges is a geometric proximity assumption, not a field-verified station entrance.
- OSM data may omit some access restrictions, recent road changes, or temporary closures.
- Sixty pairs show a directional distance difference exceeding 1 km. This should be documented as a potential effect of network directionality; it should not be claimed that every difference was field-verified.
- Earlier corridor-route validation identified route legs with a detour ratio greater than 1.5: three legs on M1 and six on M2. One M1 leg also had a tagged-road share below 90%. These locations merit visual review before the corridor geometry is treated as final.

## 5. Main MILP Results

| Scenario | Stations | Chargers | Installed peak power | CAPEX proxy | Daily demand | MIP gap |
|---|---:|---:|---:|---:|---:|---:|
| Low | 6 | 7 | 1,050 kW | $1,697,400 | 1,881.02 | 0.0936% |
| Base | 7 | 15 | 2,250 kW | $3,034,000 | 10,888.90 | 0.0669% |
| High | 12 | 49 | 7,350 kW | $8,791,800 | 45,593.11 | 0.0881% |
| Armstat | 7 | 17 | 2,550 kW | $3,342,400 | 12,734.37 | 0.0977% |

All scenarios were solved within the requested 0.1% MIP gap. A limited MIP gap does not prove absolute global optimality independently of solver tolerances; it documents solution quality against the recorded solver criterion.

### Output validation

Each scenario passed 12 checks: solver status, MIP gap, station count, charger count, assignment for every demand point, assignment fractions summing to 1, demand-to-site distance direction, all assigned distances at or below 85 km, assignments only to open sites, assigned energy matching demand, and total demand matching the input. Total: **48/48 successful checks**.

Validation report:

`data/derived/case_study_screening_milp_directed_network/scenario_runs/DIRECTED_SCENARIO_VALIDATION.csv`

### Stations with no assigned demand

In the Base solution, `M2_C015`, `M2_C023`, and `M2_C031` are open with one charger each, but receive no demand from the three currently represented demand points. Their selection results from the chainage-based interstation-gap constraint. They should not be described as stations serving measured demand unless the demand dataset is expanded.

## 6. Comparison with the Earlier Chainage-Based Model

| Scenario | Legacy → directed stations | Legacy → directed chargers | Legacy → directed CAPEX | Change |
|---|---:|---:|---:|---:|
| Low | 6 → 6 | 7 → 7 | $1,697,400 → $1,697,400 | $0 |
| Base | 7 → 7 | 16 → 15 | $3,188,200 → $3,034,000 | -$154,200 (-4.84%) |
| High | 13 → 12 | 50 → 49 | $9,049,000 → $8,791,800 | -$257,200 (-2.84%) |
| Armstat | 7 → 7 | 18 → 17 | $3,496,600 → $3,342,400 | -$154,200 (-4.41%) |

### Spatial changes in selected locations

- **Low:** Five locations were retained; `M2_C031` was removed and `M2_C030` was added. Neither location receives demand from the currently represented demand points, so CAPEX and charger count remained unchanged.
- **Base:** The same seven sites remained selected; charger count decreased from 16 to 15. A daily demand of 858.24 kWh was reassigned from `M1_C004` to `M1_C012`, because the directed distance to `M1_C012` is 79.68 km, within the 85-km limit.
- **High:** Twelve stations were retained; `M1_C002` was removed, and `M1_C012` began serving 983.01 kWh/day of M1 demand rather than zero in the legacy solution.
- **Armstat:** The same seven locations remained selected; approximately 342.66 kWh/day moved from `M1_C004` to `M1_C012`, and charger count decreased from 18 to 17.

The comparison shows that driving distances changed some assignment and capacity decisions, but did not always change station identities. A lower CAPEX proxy does not by itself establish that the new layout is economically superior, since site and charger costs are non-local benchmark assumptions.

## 7. Sensitivity Analyses

### 7.1 Service-distance limit — Base demand

| Service limit (km) | Stations | Chargers | CAPEX proxy (USD) |
|---:|---:|---:|---:|
| 50 | 7 | 16 | $3,188,200 |
| 60 | 7 | 16 | $3,188,200 |
| 70 | 7 | 16 | $3,188,200 |
| 80 | 7 | 15 | $3,034,000 |
| 85 | 7 | 15 | $3,034,000 |
| 90 | 7 | 15 | $3,034,000 |
| 100 | 7 | 15 | $3,034,000 |
| 120 | 6 | 14 | $2,776,800 |

Station counts, charger counts, and CAPEX remained unchanged between 80 and 100 km in the Base case. At 120 km, the number of stations decreased to 6 and chargers to 14, but the longer service limit reduces the service standard and should not be selected solely because it costs less.

### 7.2 Demand and charger-cost sensitivity

All 12 combinations were solved. Within each demand scenario, station and charger counts remained unchanged across the three charger-cost levels.

| Demand | Low charger cost | Base charger cost | High charger cost |
|---|---:|---:|---:|
| Low: stations / chargers | 6 / 7 | 6 / 7 | 6 / 7 |
| Low: CAPEX | $1,403,400 | $1,697,400 | $1,991,400 |
| Base: stations / chargers | 7 / 15 | 7 / 15 | 7 / 15 |
| Base: CAPEX | $2,404,000 | $3,034,000 | $3,664,000 |
| High: stations / chargers | 12 / 49 | 12 / 49 | 12 / 49 |
| High: CAPEX | $6,733,800 | $8,791,800 | $10,849,800 |
| Armstat: stations / chargers | 7 / 17 | 7 / 17 | 7 / 17 |
| Armstat: CAPEX | $2,628,400 | $3,342,400 | $4,056,400 |

These results suggest that network size in the tested cases was more sensitive to demand volume than to charger-port cost changes across the tested cost range. They do not prove that site selection is insensitive to cost under all possible conditions; the selected-site files should be consulted for each case when needed.

## 8. Updated Preliminary Financial Screen

### Reference assumptions

- Reference retail price: AMD 205/kWh, the midpoint of the published EVTEC DC price range of AMD 160–250/kWh. It is not a guaranteed price for every operator or station.
- Electricity purchase: AMD 50.48/kWh, the published ENA daytime reference tariff for 6(10) kV consumers, including VAT.
- Energy losses: 5%, an analyst assumption.
- Exchange rate: USD 1 = AMD 360.41 on 18 November 2026, according to the CBA reference rate.
- Reference case: 100% demand realization, fixed O&M at 4% of CAPEX annually, 15-year project life, and a 10% discount rate.

### Reference financial results

| Scenario | CAPEX | Screening NPV | Screening IRR | Simple payback |
|---|---:|---:|---:|---:|
| Low | $1,697,400 | -$13,418 | 9.86% | 7.67 years |
| Base | $3,034,000 | $8,780,698 | 51.09% | 1.95 years |
| High | $8,791,800 | $41,867,890 | 75.74% | 1.32 years |
| Armstat | $3,342,400 | $10,537,280 | 54.52% | 1.83 years |

### Break-even demand realization

At O&M = 4% of CAPEX per year, a 15-year project life, and a 10% discount rate:

| Scenario | Demand required for break-even |
|---|---:|
| Low | 100.61% |
| Base | 31.07% |
| High | 21.50% |
| Armstat | 29.26% |

The Low scenario does not reach zero NPV at 100% of the screening demand under this assumed framework; it requires approximately 100.61%. This does not establish that a real project would fail, because the model does not include all cash flows and local costs.

**Material limitation:** Energy contribution is retail electricity revenue minus electricity-purchase cost only. Annual cash flow after the assumed O&M remains before tax, financing, replacement, and working capital. NPV, IRR, and payback are therefore hypothetical screening indicators, not verified profitability or a bankable financial assessment.

## 9. Final Audit: Confirmed Results and Open Items

### Confirmed from run outputs

- Directed OSM graph construction with one-way directionality: 68,642 nodes and 176,406 edges.
- Virtual-node insertion on road edges and construction of a 174-pair matrix.
- 96 same-corridor pairs with directed paths and no no-path cases among them.
- Four scenario runs with MIP gaps below 0.1% and 48/48 successful validation checks.
- Completion of the legacy-versus-directed comparison, service-distance sensitivity, demand/charger-cost sensitivity, and updated preliminary financial screen.

### Items to close or document before the final diploma

1. **Correct the distance-direction documentation:** In `src/ev_charging/data.py`, the `distance_km[i,j]` comment currently describes the direction as site-to-demand, while the final run records use `demand_to_site`. Update the docstring to match the actual data meaning. This is a documentation inconsistency; it does not change the reported run results.
2. **Re-run the project test suite:** 26 passing tests were reported earlier; rerun `pytest` on the current final code version and record the output.
3. **Audit the Gomory component:** The current M1/M2 scenario solutions were produced by SciPy/HiGHS. If Gomory Cutting Planes remain a central part of the diploma title or claimed contribution, include a reproducible experiment and a clear evaluation of Gomory's role, or revise the title/objectives to avoid implying that Gomory solved the full corridor cases if it did not.
4. **Check the distance coefficient:** `distance_weight=0.1` was not included in the sensitivity analyses recorded here, and its units are not calibrated against USD. It should be tested or clearly described as an analyst-selected coefficient. The composite objective value must not be presented as USD.
5. **Interstation spacing:** The 85-km interstation limit still uses chainage, not directed road distance. The methodology and limitations should clearly distinguish the demand-service constraint from the interstation-gap constraint.
6. **Site validity:** Candidate locations are OSM-derived points along the route centreline, not verified parcels. Geometric proximity to a road does not prove driveway access rights or land suitability.
7. **Electrical capacity:** The 900-kW allowance per site is an assumption. Feeder/transformer capacity and site-specific grid-upgrade costs have not been verified.
8. **Traffic coverage:** Three demand scopes do not represent the full M1/M2 corridors. The results must not be presented as a complete national network plan.

## Data Sources and Provenance

The project record refers to the following data sources and technical references:

- **ADB (2020),** *Armenia: North-South Road Corridor Investment Program, Tranche 1 Completion Report*, Appendix 9, Tables 4–5. Traffic counts, vehicle composition, and forecast values for the M2 subsection. [ADB report](https://www.adb.org/sites/default/files/project-documents/42145/42145-023-pcr-en.pdf)
- **Armstat,** passenger-car registration statistics used for the 2.92% fully electric passenger-car share calculation (23,759 of 812,634 as of 1 November 2025). [Armstat statistical publication](https://www.armstat.am/file/article/sv_09_25r_6200.pdf)
- **ENA,** published electricity tariffs, including the 6(10)-kV daytime reference rate. [ENA tariffs](https://www.ena.am/Info.aspx?id=11&lang=2)
- **EVTEC Armenia,** published public DC charging-station prices used to define the retail-price sensitivity range. [EVTEC stations](https://www.evtec.am/en/stations.html)
- **NREL (2024),** *Costs Associated with Electric Vehicle Charging Stations*, report NREL/TP-5400-88513, used for US benchmark 150-kW charger hardware and installation costs. [NREL report](https://www.nrel.gov/docs/fy24osti/88513.pdf)
- **US Department of Transportation,** *Climate Strategies that Work*, used for the illustrative fixed station-cost benchmark. [USDOT report](https://www.transportation.gov/sites/dot.gov/files/2024-12/EV%20Charging%20Infrastructure%20-%20Climate%20Strategies%20that%20Work.pdf)
- **Central Bank of Armenia,** USD/AMD reference exchange rate dated 18 November 2026. [CBA](https://www.cba.am/EN/)
- **Geofabrik / OpenStreetMap,** Armenia PBF extract used to construct the local driving graph. [Geofabrik Armenia extract](https://download.geofabrik.de/asia/armenia-latest.osm.pbf)

---

**End of technical reference.** This file is intended to preserve the current technical state and support the final diploma drafting process; it should be updated if the final code, data, or scenario results change.

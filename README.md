# EV Charging Station Planning on Armenia's M1/M2 Corridors

This repository contains the initial computational baseline for a bachelor's thesis on the optimal siting and capacity allocation of electric-vehicle fast-charging stations along Armenia's M1 and M2 highway corridors.

## Current status

- [x] Initial MILP formulation encoded in Python.
- [x] Small illustrative synthetic test case.
- [x] Automated feasibility checks and 16 unit tests.
- [x] CSV/JSON input loader with strict checks for complete site-demand distance matrices.
- [x] Traffic-to-energy scenario estimator with explicit EV-share, charging-probability, and session-energy assumptions.
- [x] Optional OSM feature downloader for M1/M2-tagged road geometry, with provenance metadata.
- [x] Optional OSMnx country road-graph downloader and preliminary site-demand network-distance generator.
- [ ] Current numerical M1/M2 traffic-count time series and site-specific EV demand estimates. A December 2025 Road Department statement reported 14 online counters across eight interstate roads (two on M1 and four on M2), but the article does not publish their station-level counts or chainages.
- [ ] Verified electrical-substation capacity data for candidate sites.
- [x] Two-phase Revised Simplex implementation from scratch for LPs in standard inequality/equality form.
- [x] EV model LP-relaxation builder connected to the in-house Revised Simplex solver.
- [x] Mixed-Integer Gomory (GMI) cutting-plane generator for tableau rows with integer basic variables.
- [x] Dual Simplex re-optimization after each appended GMI cut.
- [x] Seeded benchmark against HiGHS on 100 small generated mixed-integer LP instances.
- [x] Convex quadratic power-loss extension for the continuous relaxation, with approximate KKT diagnostics.
- [x] M/M/s (Erlang-C) waiting-time scenario calculator.
- [x] Snapshot of 12 public EVUP charging locations for existing-infrastructure context (directory snapshot; verify before final case-study use).
- [ ] Broader benchmark on larger instances and complete M1/M2 case-study analysis.

**Important:** The included example is synthetic and is only for software testing. It is not a result for Armenia and must not be reported as a real-world study result.

## Requirements

- Python 3.14 or later
- Git
- Visual Studio Code (recommended)

SciPy 1.16.1 was the first stable SciPy release with Python 3.14 support. The requirements file asks for SciPy 1.18.1 or later.

## Setup on Windows

Open a terminal in the project folder and run:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

If PowerShell blocks environment activation, use Command Prompt instead:

```cmd
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

## Run the from-scratch Revised Simplex demonstrations

Run a classic two-variable LP example:

```powershell
python scripts\run_revised_simplex_demo.py
```

Expected optimum: `x1 = 1`, `x2 = 3`, maximum objective `9`.

Run the EV model's continuous LP relaxation through the in-house Revised Simplex implementation:

```powershell
python scripts\run_ev_lp_relaxation.py
```

The LP relaxation permits fractional values for station-selection and charger-count variables. These are intermediate mathematical values, not implementable final decisions.

## Run the Mixed-Integer Gomory + Dual Simplex demonstrations

Run a small one-integer-variable example to see a fractional LP solution cut off and re-optimized with Dual Simplex:

```powershell
python scripts\run_gomory_demo.py
```

Run the EV synthetic case through the in-house pipeline:

```powershell
python scripts\run_ev_gomory.py
```

The EV demonstration identifies the integer variables (`y` station-selection and `z` charger-count variables), generates valid mixed-integer Gomory cuts from fractional integer-basic tableau rows, and re-optimizes each augmented LP using the in-house Dual Simplex routine. The example is compared with the SciPy/HiGHS MILP baseline. The synthetic case currently reaches the same objective value (21,000) with three cuts; this is a software test only, not an Armenian case-study result.

## Convex quadratic power-loss extension

Run the continuous convex QP extension:

```powershell
python scripts\run_quadratic_extension.py
```

This adds a non-negative quadratic line-loss penalty based on the proposal's simplified relation `P_loss = R * (P / V)^2`, and reports approximate KKT residuals. It solves the **continuous relaxation**, not the integer quadratic program. Resistance, nominal voltage, and loss-cost values in the demo are illustrative and must be replaced by engineering data before any Armenia-specific conclusions. The simplified relation also requires an electrical engineer to confirm the correct phase, power-factor, and unit conversion for the selected feeder model.

## M/M/s queueing scenario

Run the Erlang-C waiting-time example:

```powershell
python scripts\run_queueing_demo.py
```

This estimates queue waiting time from explicitly supplied daily energy demand, average session energy, operating hours, service duration, and charger count. It is a **scenario calculator**, not an empirically calibrated queueing model. Arrival and service assumptions must be measured or justified before use in the case study.

## Run the illustrative MILP baseline

```powershell
python scripts\run_example.py
```

The script solves the MILP with SciPy's `scipy.optimize.milp` interface (HiGHS backend), prints the selected stations, charger counts, demand allocations, power requirements, and objective-cost breakdown. This remains the trusted reference MILP solver for cross-checking the custom cutting-plane pipeline.

## Load case-study data from CSV

The case-data loader expects these files in `data/raw/`:

- `sites.csv`
- `demand_points.csv`
- `distances.csv`
- `config.json`

Column definitions and unit requirements are documented in `data/raw/README.md`.
Empty or incomplete files are rejected; the loader does not silently invent missing distances or grid capacities.

Validate a completed case-data folder:

```powershell
python scripts\validate_case_data.py --data-dir data/raw
```

Solve it after validation:

```powershell
python scripts\validate_case_data.py --data-dir data/raw --solve
```

### Demand scenarios from traffic counts

Copy `data/templates/traffic_scenarios.csv` to `data/raw/traffic_scenarios.csv`, then enter the AADT observation and clearly stated scenario assumptions (`ev_share`, `charging_probability`, and `energy_per_session_kwh`). Generate `demand_points.csv` with:

```powershell
python scripts\build_demand_scenarios.py
```

The formula is AADT × EV share × charging probability × kWh/session. It produces a scenario estimate, not measured charging demand. Record the AADT observation year and source. Historic M1/M2 observations are in `data/reference/traffic_counts_historic.csv`; 2025 public reporting confirms that online counters are deployed on both corridors but does not expose the station-level data. See `docs/data_sources.md` for limitations and citations.

### Optional OpenStreetMap road geometry

Install the optional geospatial dependency:

```powershell
python -m pip install -e ".[geospatial]"
```

Then run:

```powershell
python scripts\download_m1_m2_osm.py
```

The script downloads OSM ways tagged for M1/M2 into a GeoJSON file and writes provenance metadata. Inspect the geometry and route continuity before using it. OSM features are not traffic counts, charging sites, or electrical-substation data.

For a routable road graph (needed to calculate road-network distances), run:

```powershell
python scripts\download_armenia_drive_graph.py
```

This downloads a country-scale driving graph and may be large. Once you have entered verified coordinates in `sites.csv` and `demand_points.csv`, calculate the complete site-demand distance matrix with:

```powershell
python scripts\compute_network_distances.py
```

The current distance script uses shortest paths on an undirected copy of the OSM driving graph. Treat these as preliminary road-distance estimates; inspect snapped nodes, directionality, access roads, and route alignment before using them in final conclusions.

### Benchmark custom GMI + Dual Simplex on generated tiny MILPs

```powershell
python scripts\benchmark_gomory_random.py
```

This uses a fixed random seed and compares the custom cutting-plane objective with HiGHS on small generated mixed-integer linear programs. The recorded development run checked 100 tiny instances: all 100 feasible instances matched the HiGHS optimum, both methods agreed on infeasibility where applicable, 57 cuts were generated in total, and no case needed more than three cuts. It is a numerical regression check, not evidence that the method scales to the full M1/M2 case study.

## Run tests

```powershell
python -m pytest
```

## Model outline

Sets:

- `I`: candidate charging-station sites.
- `J`: aggregated highway demand points.

Decision variables:

- `y[i]`: 1 if a station is opened at site `i`, otherwise 0.
- `z[i]`: integer number of chargers installed at site `i`.
- `x[i,j]`: fraction of demand point `j` assigned to station `i`.
- `P[i]`: active electrical power capacity reserved at site `i` (kW).

The implemented baseline minimizes station fixed costs, charger costs, demand-distance service penalties, and power-capacity costs. It enforces full demand allocation, distance eligibility, station opening, charger throughput, site size, electrical capacity, and investment budget constraints.

## Modeling notes to resolve before the Armenia case study

1. `R_max` in this baseline is interpreted as the maximum distance from a demand point to an eligible station. It is **not** an inter-station spacing constraint and does not by itself guarantee that every point along a highway is within driving range of a station.
2. The electrical capacity input is active power in kW. If source data are provided in kVA, convert using a documented power factor before entering the model; do not compare kW and kVA directly.
3. The coefficients `alpha` and `beta` must be calibrated and their units documented. Until then, the example uses generic illustrative cost units.
4. The demand equality constraint requires 100% of every demand point to be assigned. This is a full-coverage capacitated facility-location formulation. A classical maximum-covering formulation would instead permit some demand to remain uncovered and maximize covered demand (or penalize uncovered demand).
5. The budget constraint currently includes station establishment and charger installation costs, as in the thesis proposal. The power and distance terms are included in the objective but are not currently included in the capital budget constraint.
6. SciPy/HiGHS remains the trusted MILP benchmark. The repository also now contains from-scratch Revised Simplex, GMI cutting-plane, and Dual Simplex routines for small LP/MILP experiments. These custom routines are still research code and require broader validation before being used on the full Armenian case study.

## Revised Simplex implementation notes

- `src/ev_charging/revised_simplex.py` implements a two-phase Revised Simplex algorithm for minimization LPs with non-negative variables, `<=`, `>=`, and equality constraints.
- The solver uses a Phase-I artificial-variable objective to construct a feasible basis, then removes artificial variables and runs Phase II.
- Basis systems are recomputed with NumPy linear solves. This is clear and suitable for a pedagogical implementation, but it is not yet optimized with eta-matrix updates for large instances.
- Bland-style entering/leaving tie-breaking is used to reduce the risk of cycling.
- `src/ev_charging/lp_relaxation.py` constructs the continuous relaxation of the EV charging model and solves it with this in-house implementation.
- Unit tests cover a known two-variable optimum, equality and greater-than constraints, infeasibility, the EV LP relaxation, a GMI cut with Dual Simplex re-optimization, an EV GMI-vs-HiGHS comparison, and the treatment of continuous variables.

**Important mathematical scope:** the EV model is mixed-integer because `y` and `z` are integer while `x` and `P` are continuous. A pure-integer Gomory fractional cut cannot simply be applied to every tableau row. The implemented cutting-plane module uses a mixed-integer Gomory (GMI) cut: only designated original integer variables are treated as integer, while continuous variables and auxiliary slacks/surpluses are treated as continuous. This is valid but can produce weaker cuts than also exploiting integrality of some auxiliary variables. It must still be tested against a trusted MILP solver on a broader collection of instances.

## Data provenance

See [`docs/data_sources.md`](docs/data_sources.md) for the data-source register, traffic-count limitations, existing public charging-infrastructure snapshot, electrical data gaps, and units. The ADB traffic counts included in `data/reference/traffic_counts_historic.csv` are historic observations (M1 2017 and M2 2018 latest observations reported in the cited table), not current counts. ENA public technical information provides nationwide aggregate substation figures but not a complete site-specific available-capacity dataset.

## Repository layout

```text
EV-Charging-M1-M2/
├── data/
│   ├── raw/
│   ├── reference/
│   ├── sample/
│   └── templates/
├── docs/
├── results/
│   ├── figures/
│   └── tables/
├── scripts/
│   ├── run_example.py
│   ├── run_revised_simplex_demo.py
│   ├── run_ev_lp_relaxation.py
│   ├── run_gomory_demo.py
│   ├── run_ev_gomory.py
│   ├── run_quadratic_extension.py
│   ├── run_queueing_demo.py
│   ├── benchmark_gomory_random.py
│   ├── validate_case_data.py
│   ├── build_demand_scenarios.py
│   ├── download_m1_m2_osm.py
│   ├── download_armenia_drive_graph.py
│   └── compute_network_distances.py
├── src/
│   └── ev_charging/
│       ├── __init__.py
│       ├── data.py
│       ├── model.py
│       ├── revised_simplex.py
│       ├── lp_relaxation.py
│       ├── gomory.py
│       ├── data_io.py
│       ├── demand_estimation.py
│       ├── quadratic_extension.py
│       └── queueing.py
├── tests/
│   └── test_model.py
├── .gitignore
├── pyproject.toml
└── requirements.txt
```


## Mixed-integer Gomory and Dual Simplex implementation notes

- `src/ev_charging/gomory.py` generates a GMI cut from an optimal tableau row whose basic variable is designated integer and has a fractional value.
- The GMI formula distinguishes nonbasic integer variables from continuous variables; it does not incorrectly apply a pure-integer Gomory formula to the continuous assignment or power variables.
- Each cut is appended as `-g'x + s_cut = -f0`, with a new nonnegative slack variable initially basic. This makes the new basis primal-infeasible but retains dual feasibility, which is the appropriate starting state for Dual Simplex.
- `dual_simplex_reoptimize` in `revised_simplex.py` performs the re-optimization and checks dual feasibility before pivoting.
- `scripts/run_gomory_demo.py` demonstrates one integer variable with an LP value of 1.5 and an integer result of 2.
- `scripts/run_ev_gomory.py` runs the mixed-integer cutting-plane process on the synthetic EV case and compares its final objective with the HiGHS MILP baseline.
- The method uses floating-point arithmetic and a cut limit. It is a transparent small-instance research implementation, not a replacement for a production branch-and-cut solver.

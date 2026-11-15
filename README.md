# EV Charging Station Planning on Armenia's M1/M2 Corridors

This repository contains the initial computational baseline for a bachelor's thesis on the optimal siting and capacity allocation of electric-vehicle fast-charging stations along Armenia's M1 and M2 highway corridors.

## Current status

- [x] Initial MILP formulation encoded in Python.
- [x] Small illustrative synthetic test case.
- [x] Automated feasibility checks and unit test.
- [ ] Real, documented M1/M2 road and demand data.
- [ ] Verified electrical-substation capacity data.
- [x] Two-phase Revised Simplex implementation from scratch for LPs in standard inequality/equality form.
- [x] EV model LP-relaxation builder connected to the in-house Revised Simplex solver.
- [ ] Gomory cutting-plane implementation for the mixed-integer model (must account for continuous variables).
- [ ] Dual Simplex re-optimization implementation.
- [ ] Benchmark against HiGHS/CBC and full case-study analysis.

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

## Run the illustrative MILP baseline

```powershell
python scripts\run_example.py
```

The script solves the MILP with SciPy's `scipy.optimize.milp` interface (HiGHS backend), prints the selected stations, charger counts, demand allocations, power requirements, and objective-cost breakdown. This remains the trusted MILP benchmark while the custom integer-optimization routines are being developed.

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
6. The present solver call uses SciPy/HiGHS as a trusted baseline. The thesis's planned from-scratch Revised Simplex, Gomory, and Dual Simplex modules are separate tasks and are not yet implemented here.

## Revised Simplex implementation notes

- `src/ev_charging/revised_simplex.py` implements a two-phase Revised Simplex algorithm for minimization LPs with non-negative variables, `<=`, `>=`, and equality constraints.
- The solver uses a Phase-I artificial-variable objective to construct a feasible basis, then removes artificial variables and runs Phase II.
- Basis systems are recomputed with NumPy linear solves. This is clear and suitable for a pedagogical implementation, but it is not yet optimized with eta-matrix updates for large instances.
- Bland-style entering/leaving tie-breaking is used to reduce the risk of cycling.
- `src/ev_charging/lp_relaxation.py` constructs the continuous relaxation of the EV charging model and solves it with this in-house implementation.
- Unit tests cover a known two-variable optimum, equality and greater-than constraints, infeasibility, and the EV LP relaxation.

**Important mathematical scope:** the EV model is mixed-integer because `y` and `z` are integer while `x` and `P` are continuous. A pure-integer Gomory fractional cut cannot simply be applied to every tableau row. The next cutting-plane module must use a valid mixed-integer cut derivation (or clearly restrict the pure-integer demonstration to an all-integer test LP) and must be tested against a trusted MILP solver.

## Repository layout

```text
EV-Charging-M1-M2/
├── data/
│   └── sample/
├── results/
│   ├── figures/
│   └── tables/
├── scripts/
│   ├── run_example.py
│   ├── run_revised_simplex_demo.py
│   └── run_ev_lp_relaxation.py
├── src/
│   └── ev_charging/
│       ├── __init__.py
│       ├── data.py
│       ├── model.py
│       ├── revised_simplex.py
│       └── lp_relaxation.py
├── tests/
│   └── test_model.py
├── .gitignore
├── pyproject.toml
└── requirements.txt
```

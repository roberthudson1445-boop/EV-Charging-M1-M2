# Verified code status

This note records what is implemented in the repository and what is still needed before the code can be described as a completed Armenia M1/M2 case study.

## Implemented and tested

- Baseline EV fast-charging MILP in `src/ev_charging/model.py`, solved with SciPy/HiGHS.
- Two-phase Revised Simplex implementation for small LPs in `src/ev_charging/revised_simplex.py`.
- LP relaxation builder for the EV model.
- Mixed-integer Gomory (GMI) cut generation and Dual Simplex re-optimization.
- Cross-check of the custom GMI + Dual Simplex pipeline against HiGHS on the synthetic EV instance.
- A seeded benchmark over 100 small generated mixed-integer LP instances; custom objective values matched the HiGHS reference in all 100 feasible instances. The run generated 57 cuts in total, with at most three cuts per instance; infeasibility decisions agreed where applicable.
- Convex quadratic power-loss extension of the continuous LP relaxation, including approximate KKT residual diagnostics.
- M/M/s (Erlang-C) queueing scenario calculator.
- CSV/JSON case-data loader, demand scenario estimator, and templates.
- Public EVUP charging-location inventory snapshot for context (not yet integrated as existing capacity into the optimisation model).
- Optional OSM road-feature and road-graph downloaders, plus a script to create a site-demand network-distance matrix from verified coordinates.
- 16 automated tests pass in the development environment.

## Not yet established for the Armenia case study

- The OSM road graph and route feature files have not yet been downloaded and manually inspected in this environment.
- Candidate site and demand-point coordinates have not yet been verified at the roadside/road-access level.
- Current segment-level AADT and classified traffic counts for both M1 and M2 are still required. The ADB observations stored in `data/reference/traffic_counts_historic.csv` are historical (M1 2017 and M2 2018 latest observations at those counters), not current traffic data for all route segments. A Road Department statement reported 2 online counters on M1 and 4 on M2 as of 19 December 2025, but the published report does not provide their chainages or numerical data; see `docs/data_sources.md`.
- The EVUP snapshot is one operator's published network directory. It is not a complete national inventory, does not represent utilisation, and its connector power figures are not site grid capacity.
- Site-specific available substation capacity, transformer loading, connection voltage, and connection costs must be obtained from ENA or another verifiable engineering source. ENA's public page provides nationwide aggregates, not the complete site-level data needed by the model. A 2011 World Bank schematic substation layer exists, but its source explicitly warns that point locations are rough and unsuitable for high-accuracy use; it contains no capacity or loading attributes.
- Fixed installation costs, charger costs, the distance penalty coefficient, power-cost coefficients, and queueing assumptions need documented units, price year, and calibration.
- The current quadratic extension is a continuous QP relaxation, not a mixed-integer quadratic solver. Its example line resistances, voltages, and loss-cost weights are illustrative.
- The M/M/s module is a scenario calculator; it has not been calibrated with measured arrival and service-time distributions at Armenian stations. The included 2/3/4-charger demonstration uses illustrative daily-energy and service-time assumptions only.
- The custom Revised Simplex/GMI/Dual Simplex code is validated on small tests and instances, not yet demonstrated to scale to a full national M1/M2 model. HiGHS/CBC remain the production MILP benchmark.

## Reproduction commands

From the repository root, after installing the project dependencies:

```powershell
python -m pytest -q
python scripts\benchmark_gomory_random.py
python scripts\run_ev_gomory.py
python scripts\run_quadratic_extension.py
python scripts\run_queueing_demo.py
```

The OSM download and network-distance scripts are optional and require `python -m pip install -e ".[geospatial]"` plus internet access.

## Public data references

- EVUP public station map: https://evup.app/map
- Electric Networks of Armenia technical information: https://www.ena.am/AboutUs.aspx?id=3&lang=2
- Asian Development Bank North-South Road Corridor Tranche 1 Completion Report: https://www.adb.org/sites/default/files/project-documents/42145/42145-023-pcr-en.pdf
- UNDP Armenia Post-Disaster Needs Assessment (2024): https://www.undp.org/sites/g/files/zskgke326/files/2024-11/pdna_armenia_eng_final.pdf
- IEA Sustainable Transport Policy for Armenia: https://www.iea.org/reports/sustainable-transport-policy-for-armenia-a-roadmap/sustainable-transport-in-armenia

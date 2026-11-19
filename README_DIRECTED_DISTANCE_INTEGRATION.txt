DIRECTED OSM DISTANCE -> MILP INTEGRATION UPDATE
================================================

PURPOSE
-------
This update connects the directed virtual-edge OSM distance matrix to the
existing Armenia M1/M2 screening MILP. It does not modify the original
chainage-proxy result folders.

FILES IN THIS UPDATE
--------------------
1) scripts/run_case_study_scenario.py
   Directed-network scenario runner. Supports low, base, high, and
   armstat_ev_share_2_92.

2) src/ev_charging/data_io.py
   Existing CSV loader, extended to validate the configured distance direction
   when it is supplied. Existing inputs without that setting remain supported.

3) src/ev_charging/data.py
   Same ProblemData structure and constraints; clarifies that distance_km[i,j]
   for this case is the one-way demand-point -> charging-site driving distance.

4) run_all_directed_scenarios.bat
   Runs all four demand cases sequentially and stops if a case fails.

INPUT MATRIX EXPECTED
--------------------
data/derived/network_distance_validation/
  corridor_site_demand_distances_virtual_edge.csv

The runner checks that the matrix:
- contains all 58 candidate sites and all 3 demand IDs;
- contains 174 unique site-demand pairs;
- uses distance_direction='demand_to_site';
- has route IDs matching the candidate-site and demand-scenario files;
- has no unreachable same-corridor pair incorrectly marked as eligible;
- leaves at least one station within the 85 km service limit for each demand.

For model inputs, reachable pairs keep their measured directed OSM distance.
Cross-corridor or no-path pairs are assigned a finite 99,999 km sentinel so the
model's 85 km service-distance restriction excludes them. Reachable pairs over
85 km keep their actual distance and are excluded by that same restriction.

IMPORTANT: The distance used is demand point -> charging site. The reverse
site -> demand distance is retained only in the audit file and is not averaged
with the selected direction. Interstation spacing remains based on corridor
chainage and is not replaced by this service-distance matrix.

INSTALLATION
------------
1) From the project root, make a backup of these current files:
   scripts/run_case_study_scenario.py
   src/ev_charging/data_io.py
   src/ev_charging/data.py

2) Extract this ZIP into the project root and allow the three files above to
   be replaced. The batch file is added to the project root.

3) Confirm the directed matrix exists at the input path listed above.

4) First run only the BASE case:
   .\.venv\Scripts\python.exe scripts\run_case_study_scenario.py base

5) If BASE completes successfully, run all four scenarios:
   run_all_directed_scenarios.bat

OUTPUT LOCATION
---------------
New results are written below:
data/derived/case_study_screening_milp_directed_network/scenario_runs/
  low/
  base/
  high/
  armstat_ev_share_2_92/

The earlier chainage-proxy results under
case_study_screening_milp/scenario_runs/ are not overwritten.
Each scenario folder contains its own solver outputs and an inputs/ folder.
Each case input folder includes:
- distances.csv: exact distances supplied to the model (sentinel for ineligible pairs)
- directed_distance_matrix_audit.csv: full 174-row source matrix, including
  reverse-direction comparison, status, and service-feasibility flags
- directed_distance_metadata.json: source and pair-count summary
- config.json and assumptions.json

WHAT CHANGES / WHAT DOES NOT
----------------------------
CHANGES:
- Service distance is now the directed OSM shortest driving distance from the
  demand point to the charging site.
- Cross-corridor pairs are explicitly excluded from assignment.
- The run is saved in a new output root, preserving the older results.
- The Armstat EV-share sensitivity is supported alongside Low/Base/High.

UNCHANGED:
- The 85 km service-distance threshold.
- The separate 85 km maximum interstation spacing rule, which continues to use
  route chainage and route endpoints.
- Demand values, charger CAPEX assumptions, 150 kW charger power, six chargers
  maximum per site, 900 kW assumed grid capacity, throughput, budget placeholder,
  distance penalty weight, and solver settings.
- Existing model formulation and solver implementation.

LIMITATIONS TO KEEP IN THE REPORT
---------------------------------
- Only three demand scopes are represented, not all traffic along M1/M2.
- The OSM edge connector is a geometric proximity assumption; it does not
  verify a legal driveway, parcel entrance, or public access to a candidate site.
- OSM can omit restrictions, access rules, closures, or recent road changes.
- Demand counts/projections and station/grid/cost inputs retain their previously
  documented historical, forecast, or screening-assumption limitations.
- The 85 km threshold is a scenario assumption, not a proven universal service
  standard.
- A 0.1% requested MIP gap is a tolerance target, not an exact optimum. Record
  the achieved gap reported by the solver.
- The objective includes an analyst-set distance penalty. Its composite
  objective value is in model units, not USD. Use the separate capital-cost
  proxy for CAPEX comparisons.

VALIDATION PERFORMED ON THIS PATCH
----------------------------------
- Python syntax compilation passed for all three updated modules.
- Synthetic integration test passed for a 58-site x 3-demand (174-pair) matrix,
  including 96 same-corridor eligible pairs and 78 cross-corridor excluded pairs.
- The CSV loader successfully reconstructed a 58 x 3 ProblemData distance
  matrix and retained route metadata/interstation spacing fields.

The actual four MILP runs must still be executed in the user's project virtual
environment using the commands above. This package has not claimed that those
project-specific solves have already run.

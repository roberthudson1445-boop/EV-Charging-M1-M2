ARMENIA M1/M2 — SCREENING MILP CASE (LOW DEMAND)
======================================
This folder contains one MILP run for the low demand scenario at base charger CAPEX. Run separately with low, base, high, and armstat_ev_share_2_92. Each run writes to a separate directed-network scenario folder.
All currency values in the MILP capital-cost inputs are USD benchmark values.

IMPORTANT SCOPE:
- Demand scopes: M1 Section 3 historical ATC; M2 km9.3-13.1 historical ATC; and M2 km13.1-28.9 ADB forecast-based subsection reference at km16.
- No full-corridor demand interpolation is performed.
- Distances are directed OSM shortest-path driving distances from demand points to charging sites, using virtual points inserted on nearest road-edge geometries.
- Cross-corridor / no-directed-path pairs are retained in the complete matrix with a 99,999-km sentinel; the 85-km service-distance constraint excludes them from assignments.
- The nearest road-edge connection is a geometric modelling assumption, not proof of legal/private driveway or parcel access.
- Interstation spacing remains measured using corridor chainage; it is separate from the directed demand-to-site service distance.
- Candidate sites are OSM-derived centreline screening points, not buildable parcel approvals.

COST / ENGINEERING ASSUMPTIONS:
- Fixed site allowance: USD 103,000 per open station (USDOT example for six 150-kW ports; US benchmark).
- DC 150-kW port cost (hardware + installation): NREL 2024 low/base/high values as listed in global_assumptions.json.
- Six ports per site and 900 kW site grid capacity are assumptions, not utility confirmations.
- 1000 kWh/day per port is a throughput assumption.
- Grid-upgrade CAPEX is excluded because site-specific ENA connection quotes are unavailable.
- Budget is a nonbinding USD 20m screening placeholder, not a confirmed project budget.
- Distance coefficient is an analyst-set penalty and requires sensitivity calibration.
- The separate electricity OPEX table uses ENA tariff bounds for the three represented demand scopes (including the Armstat-scaled sensitivity); energy OPEX is not included in the current MILP objective.
- HiGHS is run with a requested 0.1% relative MIP gap and a 180-second case time limit. The achieved gap is recorded; do not call a tolerance solution an exact optimum.
- The composite objective combines USD cost terms with an analyst-set distance penalty. Until the distance coefficient is dimensionally calibrated, objective_value_model_units is not USD; use the separately reported capital-cost proxy for CAPEX comparisons.
- Fixed-site and per-port installation cost boundaries come from separate benchmarks; possible overlap must be reviewed.

OUTPUTS:
- milp_scenario_summary.csv: this scenario's solver status, achieved gap, composite objective (model units), CAPEX proxy (USD), station and charger counts.
- capital_cost_sensitivity_fixed_layout.csv: low/base/high port-cost revaluation of this demand-optimized layout (no re-optimization under alternative costs).
- demand_capacity_screening.csv: low/base/high throughput and spacing lower bounds, not optimal layouts.
- milp_selected_sites.csv: chosen screening sites, charger counts and power.
- milp_demand_assignments.csv: assignments and directed OSM driving distances for the three represented demand scopes (legacy distance_proxy_km column retained for compatibility).
- inputs/<case_id>/directed_distance_matrix_audit.csv: full 174-pair directed matrix and eligibility/status provenance used by this run.
- electricity_opex_atc_scope.csv: annual energy purchase cost bounds for the represented demand scopes and selected scenario set.
- inputs/<case_id>/: full input data and explicit assumptions used by each solver run.

Do not describe these as final Armenia investment results. They are transparent model demonstrations / sensitivity cases until local costs, grid capacity, parcel access and corridor-wide demand are validated.

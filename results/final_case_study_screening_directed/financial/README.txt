PRELIMINARY FINANCIAL SCREEN — DIRECTED NETWORK CAPEX
=====================================================

Outputs
-------
financial_screening_sensitivity.csv : 432 sensitivity combinations.
financial_break_even_utilization.csv : 108 demand-realization break-even cases.
financial_reference_cases.csv       : one comparable reference case per demand scenario.
financial_assumptions.json           : rates, directed CAPEX provenance, assumptions and limitations.

CAPEX basis
-----------
Uses total_capital_cost_proxy_usd from the four validated directed-network scenario runs:
data\derived\case_study_screening_milp_directed_network\scenario_runs\<scenario>\milp_scenario_summary.csv
Legacy chainage-distance CAPEX summaries are NOT used for this directed-network financial update.

Energy contribution basis
-------------------------
Retains the existing selected operating-economics case:
Retail price: AMD 205/kWh (arithmetic midpoint of the published AMD 160-250/kWh DC range; not a guaranteed tariff).
ENA purchase tariff: AMD 50.48/kWh (6(10) kV daytime reference; VAT included, subject to actual connection class).
Energy losses: 5% (analyst assumption, not measured).
Energy contribution: retail revenue less electricity-purchase cost only.
FX conversion: USD 1 = AMD 360.41, dated 2026-11-18, based on the CBA reference-rate display.

Financial assumptions tested
-----------------------------
Demand realization: [0.25, 0.5, 0.75, 1.0]
Fixed O&M: [2.0, 4.0, 6.0]% of CAPEX per year (analyst sensitivities, not sourced local O&M quotes).
Discount rates: [0.08, 0.1, 0.12]
Project lives: [10, 15, 20] years

Critical interpretation limits
-------------------------------
- These are directed-network CAPEX screening proxies, not Armenian contractor or utility bids.
- Demand represents three traffic locations/subsections, not full M1/M2 corridor demand.
- Interstation spacing remains chainage-based at 85 km; demand-service distances use directed OSM paths.
- Retail-vs-purchase VAT treatment is not normalized.
- Fixed O&M percentages are assumptions; no verified local O&M quote is available in these inputs.
- No taxes, financing, working capital, charger replacements, residual values, demand growth, inflation or FX forecasts are included.
- Grid connection CAPEX and site-specific land/buildability remain unverified.
- Road-edge proximity does not confirm legal driveway access.
- NPV/IRR/payback are sensitivity outputs only, not bankable profitability or investment advice.

Do not use these outputs as final project profitability without replacing assumptions
with verified local data and completing a full discounted-cash-flow model.

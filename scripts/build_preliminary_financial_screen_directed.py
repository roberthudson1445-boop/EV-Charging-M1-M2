#!/usr/bin/env python3
"""Build a directed-network, assumption-based financial screening sensitivity.

Run from the repository root:
    .\\.venv\\Scripts\\python.exe scripts\\build_preliminary_financial_screen_directed.py

This is NOT a bankable project-finance model. It converts the existing energy
contribution (retail revenue less electricity purchase only) from AMD to USD,
then tests analyst-defined utilization, fixed-O&M, discount-rate and project-
life sensitivities using CAPEX proxies from the validated directed-network
MILP runs. Legacy financial-screen outputs are not overwritten.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DERIVED = ROOT / "data" / "derived"
SOURCE_DIR = DERIVED / "operating_economics_sensitivity"
DIRECTED_RUN_ROOT = (
    DERIVED
    / "case_study_screening_milp_directed_network"
    / "scenario_runs"
)
OUTPUT_DIR = DERIVED / "preliminary_financial_screen_directed_network"
DETAIL_FILE = SOURCE_DIR / "operating_economics_sensitivity.csv"

# Retain the previously documented dated reference rate for a like-for-like
# update. This is not represented as a live/current FX quote.
FX_AMD_PER_USD = 360.41
FX_DATE = "2026-11-18"
FX_SOURCE = "Central Bank of Armenia official exchange-rate display; USD 1 = AMD 360.41"
FX_SOURCE_URL = "https://www.cba.am/EN/"

# One transparent reference energy case from the existing 72-row sensitivity.
RETAIL_CASE = "DC_midpoint_sensitivity"       # AMD 205/kWh, midpoint of 160-250
PURCHASE_CASE = "ENA_6_10kV_day_reference"   # AMD 50.48/kWh, VAT included
LOSS_CASE = "loss_5pct_assumption"            # analyst sensitivity, not measured

UTILIZATION_FACTORS = [0.25, 0.50, 0.75, 1.00]
FIXED_OM_RATIOS = [0.02, 0.04, 0.06]          # analyst assumptions of CAPEX/year
DISCOUNT_RATES = [0.08, 0.10, 0.12]
PROJECT_LIVES_YEARS = [10, 15, 20]
SCENARIO_ORDER = ["low", "base", "high", "armstat_ev_share_2_92"]
REQUESTED_MIP_GAP_LIMIT = 0.001


def annuity_factor(rate: float, years: int) -> float:
    if rate == 0:
        return float(years)
    return (1.0 - (1.0 + rate) ** (-years)) / rate


def npv_for_rate(capex: float, annual_cash: float, rate: float, years: int) -> float:
    return -capex + annual_cash * annuity_factor(rate, years)


def calculate_irr(capex: float, annual_cash: float, years: int) -> float:
    """Solve IRR for one initial outflow and equal annual cash flows."""
    if annual_cash <= 0:
        return float("nan")

    def f(rate: float) -> float:
        return npv_for_rate(capex, annual_cash, rate, years)

    lo, hi = -0.99, 1.0
    flo, fhi = f(lo), f(hi)
    while fhi > 0 and hi < 1_000_000:
        hi = hi * 2.0 + 1.0
        fhi = f(hi)
    if flo * fhi > 0:
        return float("nan")
    for _ in range(250):
        mid = (lo + hi) / 2.0
        fm = f(mid)
        if abs(fm) < 1e-7:
            return mid
        if flo * fm > 0:
            lo, flo = mid, fm
        else:
            hi, fhi = mid, fm
    return (lo + hi) / 2.0


def load_energy_contributions() -> pd.DataFrame:
    if not DETAIL_FILE.exists():
        raise FileNotFoundError(
            "Required operating-economics detail is missing. Run "
            "scripts/build_operating_economics_sensitivity.py first."
        )
    detail = pd.read_csv(DETAIL_FILE)
    required = {
        "scenario", "retail_price_case", "purchase_tariff_case",
        "energy_loss_case", "annual_retail_revenue_amd",
        "annual_electricity_purchase_cost_amd",
        "indicative_energy_contribution_amd",
    }
    missing = required - set(detail.columns)
    if missing:
        raise ValueError(
            f"{DETAIL_FILE.name} is missing columns: {sorted(missing)}"
        )
    chosen = detail[
        (detail["retail_price_case"] == RETAIL_CASE)
        & (detail["purchase_tariff_case"] == PURCHASE_CASE)
        & (detail["energy_loss_case"] == LOSS_CASE)
    ].copy()
    if chosen.empty:
        raise ValueError("The selected reference energy case has no rows.")
    if chosen["scenario"].duplicated().any():
        raise ValueError("Reference energy case contains duplicate scenario rows.")
    chosen = chosen.set_index("scenario")
    missing_scenarios = set(SCENARIO_ORDER) - set(chosen.index)
    if missing_scenarios:
        raise ValueError(
            f"Reference energy case is missing scenarios: {sorted(missing_scenarios)}"
        )
    return chosen


def load_directed_milp_summary() -> pd.DataFrame:
    """Read and validate CAPEX/counts from the four directed-network MILP runs."""
    records: list[dict[str, Any]] = []
    required = {
        "case_id", "demand_scenario", "status", "achieved_mip_rel_gap",
        "opened_station_count", "charger_count",
        "total_capital_cost_proxy_usd", "total_demand_kwh_day",
    }
    for scenario in SCENARIO_ORDER:
        summary_path = DIRECTED_RUN_ROOT / scenario / "milp_scenario_summary.csv"
        if not summary_path.exists():
            raise FileNotFoundError(
                f"Missing directed MILP summary for {scenario}: {summary_path}"
            )
        frame = pd.read_csv(summary_path)
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(
                f"{summary_path.name} ({scenario}) is missing columns: {sorted(missing)}"
            )
        if len(frame) != 1:
            raise ValueError(
                f"Expected exactly one directed MILP result for {scenario}; found {len(frame)}."
            )
        row = frame.iloc[0].to_dict()
        if str(row["demand_scenario"]) != scenario:
            raise ValueError(
                f"Scenario identity mismatch in {summary_path}: "
                f"expected {scenario!r}, got {row['demand_scenario']!r}."
            )
        if str(row["status"]) != "SOLVED_WITHIN_REQUESTED_MIP_GAP":
            raise ValueError(
                f"Directed MILP result for {scenario} is not accepted: {row['status']}"
            )
        numeric_fields = [
            "achieved_mip_rel_gap", "opened_station_count", "charger_count",
            "total_capital_cost_proxy_usd", "total_demand_kwh_day",
        ]
        for field in numeric_fields:
            row[field] = float(row[field])
            if not math.isfinite(row[field]):
                raise ValueError(f"{scenario}: {field} must be finite.")
        if row["achieved_mip_rel_gap"] > REQUESTED_MIP_GAP_LIMIT + 1e-12:
            raise ValueError(
                f"{scenario}: achieved MIP gap {row['achieved_mip_rel_gap']:.6%} "
                f"exceeds {REQUESTED_MIP_GAP_LIMIT:.3%}."
            )
        if row["opened_station_count"] <= 0 or row["charger_count"] <= 0:
            raise ValueError(f"{scenario}: station and charger counts must be positive.")
        if row["total_capital_cost_proxy_usd"] <= 0:
            raise ValueError(f"{scenario}: directed CAPEX proxy must be positive.")
        row["scenario"] = scenario
        row["directed_milp_summary_file"] = str(summary_path.relative_to(ROOT))
        records.append(row)
    return pd.DataFrame(records).set_index("scenario")


def main() -> int:
    print("[1/5] Loading operating contribution and validated directed-network MILP results...")
    energy = load_energy_contributions()
    directed = load_directed_milp_summary()
    print(f"      Energy reference case: {RETAIL_CASE} / {PURCHASE_CASE} / {LOSS_CASE}")
    print(f"      Directed CAPEX source: {DIRECTED_RUN_ROOT.relative_to(ROOT)}")
    print("      Legacy CAPEX summaries are not used.")

    rows: list[dict[str, Any]] = []
    break_even_rows: list[dict[str, Any]] = []
    reference_rows: list[dict[str, Any]] = []
    capex_provenance: dict[str, dict[str, Any]] = {}

    print("[2/5] Creating 432 financial sensitivity cases from directed CAPEX...")
    for scenario in SCENARIO_ORDER:
        d = energy.loc[scenario]
        c = directed.loc[scenario]
        annual_contribution_amd = float(d["indicative_energy_contribution_amd"])
        annual_revenue_amd = float(d["annual_retail_revenue_amd"])
        annual_purchase_amd = float(d["annual_electricity_purchase_cost_amd"])
        annual_contribution_usd = annual_contribution_amd / FX_AMD_PER_USD
        capex_usd = float(c["total_capital_cost_proxy_usd"])
        stations = int(c["opened_station_count"])
        chargers = int(c["charger_count"])
        mip_gap = float(c["achieved_mip_rel_gap"])
        if capex_usd <= 0 or annual_contribution_amd < 0:
            raise ValueError(f"Invalid CAPEX/contribution for scenario {scenario}.")
        if not math.isclose(
            annual_contribution_amd,
            annual_revenue_amd - annual_purchase_amd,
            rel_tol=1e-8,
            abs_tol=0.05,
        ):
            raise ValueError(
                f"{scenario}: energy contribution does not equal revenue less "
                "electricity purchase cost in the selected source row."
            )

        capex_provenance[scenario] = {
            "directed_capex_proxy_usd": capex_usd,
            "opened_station_count": stations,
            "charger_count": chargers,
            "achieved_mip_rel_gap": mip_gap,
            "directed_milp_summary_file": c["directed_milp_summary_file"],
            "distance_method": "DIRECTED_OSM_SHORTEST_PATH_WITH_VIRTUAL_EDGE_NODES",
            "distance_direction": "demand_to_site",
        }

        for utilization in UTILIZATION_FACTORS:
            for om_ratio in FIXED_OM_RATIOS:
                annual_om_usd = capex_usd * om_ratio
                effective_contribution_usd = annual_contribution_usd * utilization
                annual_net_cash_usd = effective_contribution_usd - annual_om_usd
                simple_payback = (
                    capex_usd / annual_net_cash_usd
                    if annual_net_cash_usd > 0 else np.nan
                )
                for discount in DISCOUNT_RATES:
                    for years in PROJECT_LIVES_YEARS:
                        af = annuity_factor(discount, years)
                        npv = -capex_usd + annual_net_cash_usd * af
                        irr = calculate_irr(capex_usd, annual_net_cash_usd, years)
                        rows.append({
                            "scenario": scenario,
                            "demand_realization_factor": utilization,
                            "annual_energy_contribution_full_scope_amd": annual_contribution_amd,
                            "annual_energy_contribution_full_scope_usd_at_cba_rate": annual_contribution_usd,
                            "annual_retail_revenue_amd": annual_revenue_amd,
                            "annual_electricity_purchase_cost_amd": annual_purchase_amd,
                            "fixed_om_assumption_pct_of_capex_per_year": om_ratio * 100,
                            "annual_fixed_om_assumption_usd": annual_om_usd,
                            "annual_net_cash_before_tax_finance_and_replacements_usd": annual_net_cash_usd,
                            "project_life_years": years,
                            "discount_rate": discount,
                            "capex_proxy_usd": capex_usd,
                            "npv_screening_usd": npv,
                            "simple_payback_years": simple_payback,
                            "irr_screening": irr,
                            "opened_station_count": stations,
                            "charger_count": chargers,
                            "directed_milp_achieved_gap": mip_gap,
                            "capex_source": c["directed_milp_summary_file"],
                            "cba_usd_amd_rate": FX_AMD_PER_USD,
                            "cba_rate_date": FX_DATE,
                            "status": "DIRECTED_CAPEX_ANALYST_ASSUMPTION_SCREEN_ONLY_NOT_BANKABLE_NPV",
                        })

        for om_ratio in FIXED_OM_RATIOS:
            for discount in DISCOUNT_RATES:
                for years in PROJECT_LIVES_YEARS:
                    required_annual_cash = capex_usd / annuity_factor(discount, years)
                    utilization_be = (
                        (required_annual_cash + capex_usd * om_ratio) / annual_contribution_usd
                        if annual_contribution_usd > 0 else np.inf
                    )
                    break_even_rows.append({
                        "scenario": scenario,
                        "fixed_om_assumption_pct_of_capex_per_year": om_ratio * 100,
                        "project_life_years": years,
                        "discount_rate": discount,
                        "break_even_demand_realization_factor": utilization_be,
                        "break_even_percent_of_screening_demand": utilization_be * 100,
                        "capex_proxy_usd": capex_usd,
                        "opened_station_count": stations,
                        "charger_count": chargers,
                        "directed_milp_achieved_gap": mip_gap,
                        "annual_energy_contribution_full_scope_amd": annual_contribution_amd,
                        "cba_usd_amd_rate": FX_AMD_PER_USD,
                        "status": "DIRECTED_CAPEX_ANALYST_ASSUMPTION_SCREEN_ONLY_NOT_BANKABLE_NPV",
                    })

        # Reference: 100% demand realization, 4% O&M, 10% discount, 15 years.
        ref_om = capex_usd * 0.04
        ref_net = annual_contribution_usd - ref_om
        ref_npv = npv_for_rate(capex_usd, ref_net, 0.10, 15)
        reference_rows.append({
            "scenario": scenario,
            "demand_realization_factor": 1.0,
            "fixed_om_assumption_pct_of_capex_per_year": 4.0,
            "project_life_years": 15,
            "discount_rate": 0.10,
            "annual_energy_contribution_amd": annual_contribution_amd,
            "annual_energy_contribution_usd": annual_contribution_usd,
            "annual_retail_revenue_amd": annual_revenue_amd,
            "annual_electricity_purchase_cost_amd": annual_purchase_amd,
            "annual_fixed_om_usd": ref_om,
            "annual_net_cash_before_tax_finance_and_replacements_usd": ref_net,
            "capex_proxy_usd": capex_usd,
            "npv_screening_usd": ref_npv,
            "simple_payback_years": capex_usd / ref_net if ref_net > 0 else np.nan,
            "irr_screening": calculate_irr(capex_usd, ref_net, 15),
            "opened_station_count": stations,
            "charger_count": chargers,
            "directed_milp_achieved_gap": mip_gap,
            "capex_source": c["directed_milp_summary_file"],
            "status": "DIRECTED_CAPEX_REFERENCE_CASE_ASSUMPTIONS_NOT_FORECAST",
        })

    print("[3/5] Writing directed-network financial outputs to a new folder...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUTPUT_DIR / "financial_screening_sensitivity.csv", index=False)
    pd.DataFrame(break_even_rows).to_csv(
        OUTPUT_DIR / "financial_break_even_utilization.csv", index=False
    )
    pd.DataFrame(reference_rows).to_csv(
        OUTPUT_DIR / "financial_reference_cases.csv", index=False
    )

    assumptions = {
        "purpose": "Preliminary financial screening sensitivity using directed-network MILP CAPEX; not a bankable financial model.",
        "capex_basis": {
            "source_root": str(DIRECTED_RUN_ROOT.relative_to(ROOT)),
            "source_field": "total_capital_cost_proxy_usd",
            "distance_method": "DIRECTED_OSM_SHORTEST_PATH_WITH_VIRTUAL_EDGE_NODES",
            "distance_direction": "demand_to_site",
            "service_distance_km": 85.0,
            "interstation_spacing_km": 85.0,
            "interstation_spacing_method": "route_chainage",
            "scenario_capex_and_layouts": capex_provenance,
            "note": "Directed-network CAPEX proxies are used; legacy chainage-distance CAPEX is not used.",
        },
        "selected_energy_case": {
            "retail_price_case": RETAIL_CASE,
            "retail_price_amd_per_kwh": 205.0,
            "purchase_tariff_case": PURCHASE_CASE,
            "purchase_tariff_amd_per_kwh": 50.48,
            "energy_loss_case": LOSS_CASE,
            "energy_loss_fraction": 0.05,
            "source_file": str(DETAIL_FILE.relative_to(ROOT)),
            "interpretation": "Existing scenario energy contribution is retained; only the MILP CAPEX basis has been updated.",
        },
        "fx": {
            "amd_per_usd": FX_AMD_PER_USD,
            "date": FX_DATE,
            "source": FX_SOURCE,
            "source_url": FX_SOURCE_URL,
            "note": "One dated CBA reference rate is held constant for comparability; no FX forecast is made.",
        },
        "financial_sensitivities": {
            "demand_realization_factors": UTILIZATION_FACTORS,
            "fixed_om_percent_of_capex_per_year": [x * 100 for x in FIXED_OM_RATIOS],
            "discount_rates": DISCOUNT_RATES,
            "project_lives_years": PROJECT_LIVES_YEARS,
            "case_count": len(rows),
            "break_even_case_count": len(break_even_rows),
        },
        "excluded_or_unverified": [
            "Full-corridor demand; represented demand remains three traffic locations/subsections only.",
            "VAT normalization between retail revenue and ENA electricity tariff.",
            "Income tax, VAT settlement, financing, working capital and depreciation.",
            "Land, grid connection/upgrades, civil works beyond the current CAPEX proxy.",
            "Maintenance, staffing, insurance, software, payment fees, demand charges and downtime; fixed O&M percentage is a sensitivity assumption only.",
            "Charger replacement, residual value, inflation, demand growth and FX changes.",
            "Site access/buildability and confirmed utility capacity; road-edge proximity does not establish legal driveway access.",
        ],
        "interpretation": "NPV, IRR and payback are screening indicators under explicit analyst assumptions. They must not be described as verified project profitability, bankable returns, or a final investment decision.",
    }
    (OUTPUT_DIR / "financial_assumptions.json").write_text(
        json.dumps(assumptions, indent=2) + "\n", encoding="utf-8"
    )

    readme = f"""PRELIMINARY FINANCIAL SCREEN — DIRECTED NETWORK CAPEX\n=====================================================\n\nOutputs\n-------\nfinancial_screening_sensitivity.csv : {len(rows)} sensitivity combinations.\nfinancial_break_even_utilization.csv : {len(break_even_rows)} demand-realization break-even cases.\nfinancial_reference_cases.csv       : one comparable reference case per demand scenario.\nfinancial_assumptions.json           : rates, directed CAPEX provenance, assumptions and limitations.\n\nCAPEX basis\n-----------\nUses total_capital_cost_proxy_usd from the four validated directed-network scenario runs:\n{DIRECTED_RUN_ROOT.relative_to(ROOT)}\\<scenario>\\milp_scenario_summary.csv\nLegacy chainage-distance CAPEX summaries are NOT used for this directed-network financial update.\n\nEnergy contribution basis\n-------------------------\nRetains the existing selected operating-economics case:\nRetail price: AMD 205/kWh (arithmetic midpoint of the published AMD 160-250/kWh DC range; not a guaranteed tariff).\nENA purchase tariff: AMD 50.48/kWh (6(10) kV daytime reference; VAT included, subject to actual connection class).\nEnergy losses: 5% (analyst assumption, not measured).\nEnergy contribution: retail revenue less electricity-purchase cost only.\nFX conversion: USD 1 = AMD {FX_AMD_PER_USD}, dated {FX_DATE}, based on the CBA reference-rate display.\n\nFinancial assumptions tested\n-----------------------------\nDemand realization: {UTILIZATION_FACTORS}\nFixed O&M: {[x*100 for x in FIXED_OM_RATIOS]}% of CAPEX per year (analyst sensitivities, not sourced local O&M quotes).\nDiscount rates: {DISCOUNT_RATES}\nProject lives: {PROJECT_LIVES_YEARS} years\n\nCritical interpretation limits\n-------------------------------\n- These are directed-network CAPEX screening proxies, not Armenian contractor or utility bids.\n- Demand represents three traffic locations/subsections, not full M1/M2 corridor demand.\n- Interstation spacing remains chainage-based at 85 km; demand-service distances use directed OSM paths.\n- Retail-vs-purchase VAT treatment is not normalized.\n- Fixed O&M percentages are assumptions; no verified local O&M quote is available in these inputs.\n- No taxes, financing, working capital, charger replacements, residual values, demand growth, inflation or FX forecasts are included.\n- Grid connection CAPEX and site-specific land/buildability remain unverified.\n- Road-edge proximity does not confirm legal driveway access.\n- NPV/IRR/payback are sensitivity outputs only, not bankable profitability or investment advice.\n\nDo not use these outputs as final project profitability without replacing assumptions\nwith verified local data and completing a full discounted-cash-flow model.\n"""
    (OUTPUT_DIR / "README.txt").write_text(readme, encoding="utf-8")

    print("[4/5] Writing assumptions and provenance...")
    print("[5/5] Complete")
    print(f"      Sensitivity cases: {len(rows)}")
    print(f"      Break-even cases: {len(break_even_rows)}")
    print(f"      Reference cases: {len(reference_rows)}")
    print(f"      Saved to: {OUTPUT_DIR.relative_to(ROOT)}")
    print("IMPORTANT: NPV/IRR/payback are assumption-based screening indicators, not bankable forecasts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

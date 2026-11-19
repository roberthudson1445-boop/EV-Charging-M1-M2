"""Build an explicitly assumption-based financial screening sensitivity.

Run from the repository root:
    .\\.venv\\Scripts\\python.exe scripts\\build_preliminary_financial_screen.py

This is NOT a bankable project-finance model. It converts the existing
energy contribution (retail revenue less electricity purchase only) from AMD
to USD, then tests analyst-defined utilization, fixed-O&M, discount-rate and
project-life sensitivities against the current CAPEX proxies.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "data" / "derived" / "operating_economics_sensitivity"
OUTPUT_DIR = ROOT / "data" / "derived" / "preliminary_financial_screen"
DETAIL_FILE = SOURCE_DIR / "operating_economics_sensitivity.csv"
SUMMARY_FILE = SOURCE_DIR / "scenario_energy_summary.csv"

# Latest available CBA reference rate found during preparation: 18 Nov 2026.
FX_AMD_PER_USD = 360.41
FX_DATE = "2026-11-18"
FX_SOURCE = "Central Bank of Armenia official exchange-rate display; USD 1 = AMD 360.41"
FX_SOURCE_URL = "https://www.cba.am/EN/"

# Select one transparent reference energy case from the 72-row sensitivity.
RETAIL_CASE = "DC_midpoint_sensitivity"       # AMD 205/kWh, midpoint of 160-250
PURCHASE_CASE = "ENA_6_10kV_day_reference"   # AMD 50.48/kWh, VAT included
LOSS_CASE = "loss_5pct_assumption"            # analyst sensitivity, not measured

UTILIZATION_FACTORS = [0.25, 0.50, 0.75, 1.00]
FIXED_OM_RATIOS = [0.02, 0.04, 0.06]          # analyst assumptions of CAPEX/year
DISCOUNT_RATES = [0.08, 0.10, 0.12]
PROJECT_LIVES_YEARS = [10, 15, 20]

SCENARIO_ORDER = ["low", "base", "high", "armstat_ev_share_2_92"]


def annuity_factor(rate: float, years: int) -> float:
    if rate == 0:
        return float(years)
    return (1.0 - (1.0 + rate) ** (-years)) / rate


def npv_for_rate(capex: float, annual_cash: float, rate: float, years: int) -> float:
    return -capex + annual_cash * annuity_factor(rate, years)


def calculate_irr(capex: float, annual_cash: float, years: int) -> float:
    """Solve IRR for one initial outflow and equal positive annual cash flows."""
    if annual_cash <= 0:
        return float("nan")

    def f(rate: float) -> float:
        return npv_for_rate(capex, annual_cash, rate, years)

    lo = -0.99
    hi = 1.0
    flo = f(lo)
    fhi = f(hi)
    while fhi > 0 and hi < 1_000_000:
        hi = hi * 2.0 + 1.0
        fhi = f(hi)
    if flo * fhi > 0:
        return float("nan")
    # Bisection is sufficient and avoids adding a finance dependency.
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


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not DETAIL_FILE.exists() or not SUMMARY_FILE.exists():
        raise FileNotFoundError(
            "Required operating-economics outputs are missing. Run "
            "scripts/build_operating_economics_sensitivity.py first."
        )
    detail = pd.read_csv(DETAIL_FILE)
    summary = pd.read_csv(SUMMARY_FILE)
    required_detail = {
        "scenario", "retail_price_case", "purchase_tariff_case",
        "energy_loss_case", "annual_retail_revenue_amd",
        "annual_electricity_purchase_cost_amd", "indicative_energy_contribution_amd",
    }
    required_summary = {"scenario", "capital_cost_proxy_usd", "opened_station_count", "charger_count"}
    if missing := required_detail - set(detail.columns):
        raise ValueError(f"Operating economics CSV is missing columns: {sorted(missing)}")
    if missing := required_summary - set(summary.columns):
        raise ValueError(f"Energy summary CSV is missing columns: {sorted(missing)}")
    return detail, summary


def main() -> int:
    print("[1/5] Loading operating contribution and MILP capital-cost proxies...")
    detail, summary = load_inputs()
    chosen = detail[
        (detail["retail_price_case"] == RETAIL_CASE)
        & (detail["purchase_tariff_case"] == PURCHASE_CASE)
        & (detail["energy_loss_case"] == LOSS_CASE)
    ].copy()
    if chosen["scenario"].duplicated().any():
        raise ValueError("Reference energy case contains duplicate scenario rows.")
    chosen = chosen.set_index("scenario")
    capex = summary.set_index("scenario")

    rows: list[dict[str, Any]] = []
    break_even_rows: list[dict[str, Any]] = []
    reference_rows: list[dict[str, Any]] = []

    print("[2/5] Creating 432 financial sensitivity cases...")
    for scenario in SCENARIO_ORDER:
        if scenario not in chosen.index or scenario not in capex.index:
            raise ValueError(f"Missing scenario {scenario!r} in operating/MILP summaries.")
        d = chosen.loc[scenario]
        c = capex.loc[scenario]
        annual_contribution_amd = float(d["indicative_energy_contribution_amd"])
        annual_contribution_usd = annual_contribution_amd / FX_AMD_PER_USD
        capex_usd = float(c["capital_cost_proxy_usd"])
        stations = int(c["opened_station_count"])
        chargers = int(c["charger_count"])
        if capex_usd <= 0 or annual_contribution_amd < 0:
            raise ValueError(f"Invalid CAPEX/contribution for scenario {scenario}.")

        for utilization in UTILIZATION_FACTORS:
            for om_ratio in FIXED_OM_RATIOS:
                annual_om_usd = capex_usd * om_ratio
                effective_contribution_usd = annual_contribution_usd * utilization
                annual_net_cash_usd = effective_contribution_usd - annual_om_usd
                simple_payback = capex_usd / annual_net_cash_usd if annual_net_cash_usd > 0 else np.nan
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
                            "cba_usd_amd_rate": FX_AMD_PER_USD,
                            "cba_rate_date": FX_DATE,
                            "status": "ANALYST_ASSUMPTION_SCREEN_ONLY_NOT_BANKABLE_NPV",
                        })

        # Break-even utilization is independent of the utilization cases above;
        # calculate once for every O&M / discount / life combination.
        for om_ratio in FIXED_OM_RATIOS:
            for discount in DISCOUNT_RATES:
                for years in PROJECT_LIVES_YEARS:
                    required_annual_cash = capex_usd / annuity_factor(discount, years)
                    utilization_be = (required_annual_cash + capex_usd * om_ratio) / annual_contribution_usd if annual_contribution_usd > 0 else np.inf
                    break_even_rows.append({
                        "scenario": scenario,
                        "fixed_om_assumption_pct_of_capex_per_year": om_ratio * 100,
                        "project_life_years": years,
                        "discount_rate": discount,
                        "break_even_demand_realization_factor": utilization_be,
                        "break_even_percent_of_screening_demand": utilization_be * 100,
                        "capex_proxy_usd": capex_usd,
                        "annual_energy_contribution_full_scope_amd": annual_contribution_amd,
                        "cba_usd_amd_rate": FX_AMD_PER_USD,
                        "status": "ANALYST_ASSUMPTION_SCREEN_ONLY_NOT_BANKABLE_NPV",
                    })

        # Reference line: 100% realization, 4% O&M, 10% discount, 15 years.
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
            "annual_fixed_om_usd": ref_om,
            "annual_net_cash_before_tax_finance_and_replacements_usd": ref_net,
            "capex_proxy_usd": capex_usd,
            "npv_screening_usd": ref_npv,
            "simple_payback_years": capex_usd / ref_net if ref_net > 0 else np.nan,
            "irr_screening": calculate_irr(capex_usd, ref_net, 15),
            "opened_station_count": stations,
            "charger_count": chargers,
            "status": "REFERENCE_CASE_ASSUMPTIONS_NOT_FORECAST",
        })

    print("[3/5] Calculating break-even utilization and reference cases...")
    out = OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out / "financial_screening_sensitivity.csv", index=False)
    pd.DataFrame(break_even_rows).to_csv(out / "financial_break_even_utilization.csv", index=False)
    pd.DataFrame(reference_rows).to_csv(out / "financial_reference_cases.csv", index=False)

    assumptions = {
        "purpose": "Preliminary screening sensitivity only; not a bankable financial model.",
        "selected_energy_case": {
            "retail_price_case": RETAIL_CASE,
            "retail_price_amd_per_kwh": 205.0,
            "purchase_tariff_case": PURCHASE_CASE,
            "purchase_tariff_amd_per_kwh": 50.48,
            "energy_loss_case": LOSS_CASE,
            "energy_loss_fraction": 0.05,
        },
        "fx": {
            "amd_per_usd": FX_AMD_PER_USD,
            "date": FX_DATE,
            "source": FX_SOURCE,
            "source_url": FX_SOURCE_URL,
            "note": "One historical CBA reference rate is held constant in the screening; no FX forecast is made.",
        },
        "financial_sensitivities": {
            "demand_realization_factors": UTILIZATION_FACTORS,
            "fixed_om_percent_of_capex_per_year": [x * 100 for x in FIXED_OM_RATIOS],
            "discount_rates": DISCOUNT_RATES,
            "project_lives_years": PROJECT_LIVES_YEARS,
            "case_count": len(rows),
        },
        "excluded_or_unverified": [
            "Full-corridor demand; represented demand remains three traffic locations/subsections only.",
            "VAT normalization between retail revenue and ENA electricity tariff.",
            "Income tax, VAT settlement, financing, working capital and depreciation.",
            "Land, grid connection/upgrades, civil works beyond the current CAPEX proxy.",
            "Maintenance, staffing, insurance, software, payment fees, demand charges and downtime; fixed O&M percentage is a sensitivity assumption only.",
            "Charger replacement, residual value, inflation, demand growth and FX changes.",
            "Site access/buildability and confirmed utility capacity.",
        ],
        "interpretation": "NPV, IRR and payback are screening indicators under explicit analyst assumptions. They must not be described as verified project profitability, bankable returns, or a final investment decision.",
    }
    (out / "financial_assumptions.json").write_text(json.dumps(assumptions, indent=2), encoding="utf-8")

    readme = f"""PRELIMINARY FINANCIAL SCREEN — ARMENIA M1/M2\n============================================\n\nOutputs\n-------\nfinancial_screening_sensitivity.csv : {len(rows)} scenario combinations.\nfinancial_break_even_utilization.csv : demand realization needed for NPV=0.\nfinancial_reference_cases.csv       : one comparable reference case per demand scenario.\nfinancial_assumptions.json           : rates, assumptions and limitations.\n\nReference energy case\n---------------------\nRetail price: AMD 205/kWh (arithmetic midpoint of the published AMD 160-250/kWh DC range; not a guaranteed tariff).\nENA purchase tariff: AMD 50.48/kWh (6(10) kV daytime reference; VAT included, subject to actual connection class).\nEnergy losses: 5% (analyst assumption, not measured).\nFX conversion: USD 1 = AMD {FX_AMD_PER_USD}, dated {FX_DATE}, based on CBA reference-rate display.\n\nFinancial assumptions tested\n-----------------------------\nDemand realization: {UTILIZATION_FACTORS}\nFixed O&M: {[x*100 for x in FIXED_OM_RATIOS]}% of CAPEX per year (analyst sensitivities, not sourced local O&M quotes).\nDiscount rates: {DISCOUNT_RATES}\nProject lives: {PROJECT_LIVES_YEARS} years\n\nCritical interpretation limits\n-------------------------------\n- The energy contribution is retail revenue less electricity-purchase cost only.\n- Demand represents three traffic locations/subsections, not full M1/M2 corridor demand.\n- CAPEX values are screening proxies based partly on international benchmarks, not Armenian bids.\n- Retail-vs-purchase VAT treatment is not normalized.\n- Fixed O&M percentages are assumptions. No verified local O&M quote was available in the inputs.\n- No taxes, financing, working capital, charger replacements, residual values, demand growth, inflation or FX forecasts are included.\n- Grid connection CAPEX and site-specific land/buildability remain unverified.\n- NPV/IRR/payback are sensitivity outputs only, not bankable profitability or investment advice.\n\nDo not use these outputs as final project profitability without replacing assumptions\nwith verified local data and completing a full discounted-cash-flow model.\n"""
    (out / "README.txt").write_text(readme, encoding="utf-8")

    print("[4/5] Writing assumptions and provenance...")
    print("[5/5] Complete")
    print(f"      Sensitivity cases: {len(rows)}")
    print(f"      Reference cases: {len(reference_rows)}")
    print(f"      Saved to: {out}")
    print("IMPORTANT: NPV/IRR/payback values are assumption-based screening indicators, not bankable forecasts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

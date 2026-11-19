"""Build a transparent operating-economics sensitivity for Armenia M1/M2.

This is a separate screening calculation. It does not modify MILP inputs or
claim project profitability. It combines the scenario demand totals with
published Armenian public DC charging-price references and ENA 6(10) kV
energy tariffs, then varies an explicitly illustrative energy-loss factor.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEMAND_ROOT = ROOT / "data" / "derived" / "traffic_ev_demand_scenarios"
MILP_ROOT = ROOT / "data" / "derived" / "case_study_screening_milp" / "scenario_runs"
OUT_DIR = ROOT / "data" / "derived" / "operating_economics_sensitivity"

SCENARIOS = {
    "low": (DEMAND_ROOT / "low" / "demand_points.csv", MILP_ROOT / "low"),
    "base": (DEMAND_ROOT / "base" / "demand_points.csv", MILP_ROOT / "base"),
    "high": (DEMAND_ROOT / "high" / "demand_points.csv", MILP_ROOT / "high"),
    "armstat_ev_share_2_92": (
        DEMAND_ROOT / "armstat_ev_share_2_92" / "demand_points.csv",
        MILP_ROOT / "armstat_ev_share_2_92",
    ),
}

# Public DC charging prices listed by evtec Armenia (50–240 kW): 160–250 AMD/kWh.
# 205 AMD/kWh is the arithmetic midpoint for sensitivity, not a quoted tariff.
RETAIL_PRICE_CASES = [
    ("DC_low_reference", 160.0, "Published lower edge of evtec DC range"),
    ("DC_midpoint_sensitivity", 205.0, "Arithmetic midpoint of published 160–250 range; not an observed tariff"),
    ("DC_high_reference", 250.0, "Published upper edge of evtec DC range"),
]

# ENA end-user tariffs for consumers connected to 6(10) kV, AMD/kWh, including VAT.
# They are reference tariff scenarios; actual customer classification/contract must be confirmed.
PURCHASE_TARIFF_CASES = [
    ("ENA_6_10kV_day_reference", 50.48, "ENA 6(10) kV daytime tariff, VAT included"),
    ("ENA_6_10kV_night_reference", 40.48, "ENA 6(10) kV nighttime tariff, VAT included"),
]

# Illustrative total energy-loss assumptions between grid meter and energy billed to drivers.
# These are sensitivity values, not measured Armenian station-loss data.
LOSS_CASES = [("loss_0pct", 0.00), ("loss_5pct_assumption", 0.05), ("loss_10pct_assumption", 0.10)]
DAYS_PER_YEAR = 365


def read_scenario_demand(path: Path) -> float:
    if not path.exists():
        raise FileNotFoundError(f"Missing scenario demand file: {path}")
    df = pd.read_csv(path)
    required = {"demand_id", "demand_kwh_day", "route_id"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")
    if df.empty:
        raise ValueError(f"{path} contains no demand rows")
    values = pd.to_numeric(df["demand_kwh_day"], errors="raise")
    if values.isna().any() or (values < 0).any():
        raise ValueError(f"{path} has missing or negative demand values")
    return float(values.sum())


def read_milp_summary(path: Path) -> dict[str, float | int | str | None]:
    summary_path = path / "milp_scenario_summary.csv"
    if not summary_path.exists():
        return {
            "milp_status": "NOT_FOUND",
            "opened_station_count": None,
            "charger_count": None,
            "capital_cost_proxy_usd": None,
            "achieved_mip_rel_gap": None,
        }
    df = pd.read_csv(summary_path)
    if df.empty:
        raise ValueError(f"Empty MILP summary: {summary_path}")
    row = df.iloc[0]
    return {
        "milp_status": str(row.get("status", "UNKNOWN")),
        "opened_station_count": int(row["opened_station_count"]),
        "charger_count": int(row["charger_count"]),
        "capital_cost_proxy_usd": float(row["total_capital_cost_proxy_usd"]),
        "achieved_mip_rel_gap": float(row["achieved_mip_rel_gap"]),
    }


def main() -> None:
    print("[1/5] Loading the four demand scenarios and available MILP summaries...")
    demand_by_scenario: dict[str, float] = {}
    milp_by_scenario: dict[str, dict[str, float | int | str | None]] = {}
    for name, (demand_path, milp_path) in SCENARIOS.items():
        demand_by_scenario[name] = read_scenario_demand(demand_path)
        milp_by_scenario[name] = read_milp_summary(milp_path)
        print(f"      {name}: {demand_by_scenario[name]:,.2f} kWh/day")

    print("[2/5] Building retail-price, ENA-tariff and loss sensitivities...")
    rows: list[dict[str, object]] = []
    for scenario, daily_delivered_kwh in demand_by_scenario.items():
        annual_delivered_kwh = daily_delivered_kwh * DAYS_PER_YEAR
        for price_case, retail_price, price_note in RETAIL_PRICE_CASES:
            for tariff_case, purchase_tariff, tariff_note in PURCHASE_TARIFF_CASES:
                for loss_case, loss_rate in LOSS_CASES:
                    annual_grid_kwh = annual_delivered_kwh / (1.0 - loss_rate)
                    revenue = annual_delivered_kwh * retail_price
                    electricity_cost = annual_grid_kwh * purchase_tariff
                    contribution = revenue - electricity_cost
                    m = milp_by_scenario[scenario]
                    rows.append(
                        {
                            "scenario": scenario,
                            "represented_demand_scope": "Three represented traffic locations/subsections only; not full-corridor demand",
                            "daily_delivered_energy_kwh": daily_delivered_kwh,
                            "annual_delivered_energy_kwh": annual_delivered_kwh,
                            "retail_price_case": price_case,
                            "retail_price_amd_per_kwh": retail_price,
                            "retail_price_basis": price_note,
                            "purchase_tariff_case": tariff_case,
                            "purchase_tariff_amd_per_kwh": purchase_tariff,
                            "purchase_tariff_basis": tariff_note,
                            "energy_loss_case": loss_case,
                            "assumed_energy_loss_fraction": loss_rate,
                            "annual_grid_energy_purchased_kwh": annual_grid_kwh,
                            "annual_retail_revenue_amd": revenue,
                            "annual_electricity_purchase_cost_amd": electricity_cost,
                            "indicative_energy_contribution_amd": contribution,
                            "indicative_contribution_amd_per_delivered_kwh": contribution / annual_delivered_kwh if annual_delivered_kwh else 0.0,
                            "milp_status": m["milp_status"],
                            "opened_station_count": m["opened_station_count"],
                            "charger_count": m["charger_count"],
                            "capital_cost_proxy_usd": m["capital_cost_proxy_usd"],
                            "achieved_mip_rel_gap": m["achieved_mip_rel_gap"],
                        }
                    )

    detail = pd.DataFrame(rows)
    print("[3/5] Creating scenario-level energy summaries...")
    summary_rows = []
    for scenario, daily in demand_by_scenario.items():
        m = milp_by_scenario[scenario]
        summary_rows.append(
            {
                "scenario": scenario,
                "daily_delivered_energy_kwh": daily,
                "annual_delivered_energy_kwh": daily * DAYS_PER_YEAR,
                "milp_status": m["milp_status"],
                "opened_station_count": m["opened_station_count"],
                "charger_count": m["charger_count"],
                "capital_cost_proxy_usd": m["capital_cost_proxy_usd"],
                "achieved_mip_rel_gap": m["achieved_mip_rel_gap"],
                "scope_warning": "Only three represented traffic locations/subsections; not full M1/M2 corridor demand",
            }
        )
    summary = pd.DataFrame(summary_rows)

    print("[4/5] Writing outputs and provenance notes...")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    detail_path = OUT_DIR / "operating_economics_sensitivity.csv"
    summary_path = OUT_DIR / "scenario_energy_summary.csv"
    detail.to_csv(detail_path, index=False, float_format="%.6f")
    summary.to_csv(summary_path, index=False, float_format="%.6f")

    assumptions = {
        "purpose": "Screening-only energy revenue and electricity-purchase contribution sensitivity; not a full financial model",
        "days_per_year": DAYS_PER_YEAR,
        "retail_price_source": "evtec Armenia public DC charging price range 160-250 AMD/kWh for DC 50-240 kW; 205 AMD/kWh is the midpoint used only as an analyst sensitivity",
        "retail_price_source_url": "https://www.evtec.am/en/stations.html",
        "ena_tariff_source": "ENA end-user tariff table, consumers connected to 6(10) kV: 50.48 AMD/kWh daytime and 40.48 AMD/kWh nighttime, VAT included",
        "ena_tariff_source_url": "https://www.ena.am/Info.aspx?id=11&lang=2",
        "energy_loss_cases": "0%, 5%, and 10%; analyst-selected sensitivities, not measured values",
        "calculation": "Annual delivered demand = daily model demand * 365. Grid purchases = annual delivered energy / (1-loss fraction). Indicative contribution = retail revenue - electricity purchase cost.",
        "critical_limitations": [
            "Demand covers only three represented traffic locations/subsections, not complete corridor-wide demand.",
            "The public DC retail price range is a market reference, not a signed tariff or guaranteed 150-kW highway-site price.",
            "ENA 6(10) kV tariff applies only if the future station is actually connected and billed in that voltage class.",
            "VAT accounting has not been normalized between retail price and input electricity tariff; both published values may have different tax treatment.",
            "The contribution excludes maintenance, staffing, rent, connectivity/software, insurance, payment fees, taxes, financing, downtime, demand charges and grid-upgrade CAPEX.",
            "No published local Armenian price quotations were found for DC charger hardware and site-specific grid connection; international CAPEX benchmarks remain unverified locally.",
            "This contribution is not net profit, EBITDA, NPV, IRR or payback.",
        ],
        "local_equipment_quote_status": "An Armenia-focused operator information page states that it found no published Armenian AC/DC hardware, installation or grid-connection price quotes; obtain written site-specific supplier/ENA quotations.",
        "local_equipment_quote_source_url": "https://next.ev-armenia.net/en/business/ev-charger-cost-installation-armenia/",
    }
    (OUT_DIR / "assumptions_and_sources.json").write_text(
        json.dumps(assumptions, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    readme = """ARMENIA M1/M2 — OPERATING ECONOMICS SCREENING\n==============================================\n\nThis output estimates a simple energy-revenue less electricity-purchase\ncontribution for the demand represented in the current scenarios. It is not\na full financial feasibility model.\n\nRetail charging-price reference: evtec Armenia lists public DC prices of\n160–250 AMD/kWh for DC charging (50–240 kW). The 205 AMD/kWh case is only\nthe arithmetic midpoint, not a published operator tariff.\nSource: https://www.evtec.am/en/stations.html\n\nElectricity-purchase reference: ENA lists 6(10) kV consumer tariffs of\n50.48 AMD/kWh daytime and 40.48 AMD/kWh nighttime, including VAT. This only\napplies if the eventual station connection is billed in this voltage class.\nSource: https://www.ena.am/Info.aspx?id=11&lang=2\n\nLoss sensitivities of 0%, 5% and 10% are analyst assumptions, not measured\nsite data.\n\nIMPORTANT LIMITATIONS\n---------------------\n- Demand represents three traffic locations/subsections only, not all M1/M2.\n- Retail prices are market references, not guaranteed highway-site tariffs.\n- VAT treatment has not been normalized between retail and input prices.\n- Contribution excludes maintenance, staffing, land/rent, insurance, software,\n  payment fees, taxes, financing, downtime, demand charges, and grid CAPEX.\n- No verified local supplier quotations for DC hardware/site connection are\n  included. International CAPEX assumptions remain provisional.\n- Do not call this value profit, EBITDA, NPV, IRR or payback.\n\nFiles\n-----\noperating_economics_sensitivity.csv : 72 pricing/tariff/loss combinations.\nscenario_energy_summary.csv         : annualized represented energy by case.\nassumptions_and_sources.json        : calculation and provenance details.\n"""
    (OUT_DIR / "README.txt").write_text(readme, encoding="utf-8")

    print(f"      Detail rows: {len(detail)}")
    print(f"      Saved: {detail_path}")
    print(f"      Saved: {summary_path}")
    print(f"      Saved: {OUT_DIR / 'assumptions_and_sources.json'}")
    print(f"      Saved: {OUT_DIR / 'README.txt'}")
    print("[5/5] Complete")
    print("IMPORTANT: energy contribution is not profit or full project profitability.")


if __name__ == "__main__":
    main()

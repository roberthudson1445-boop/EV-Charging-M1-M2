"""Compare M/M/s waiting-time scenarios for an illustrative charger station."""

from __future__ import annotations

from ev_charging.queueing import queue_metrics_from_daily_energy


def main() -> None:
    print("=== M/M/s charging-station queueing scenario ===")
    print("Assumptions: 2,000 kWh/day, 25 kWh/session, 16 operating hours/day,")
    print("and 20 minutes average service time per charger.")
    for chargers in (2, 3, 4):
        metrics = queue_metrics_from_daily_energy(
            daily_charging_energy_kwh=2_000.0,
            average_session_energy_kwh=25.0,
            operating_hours_per_day=16.0,
            average_service_minutes=20.0,
            chargers=chargers,
        )
        print(
            f"chargers={chargers}: stable={metrics.stable}, "
            f"utilization={metrics.utilization:.3f}, "
            f"P(wait)={metrics.probability_wait:.3f}, "
            f"average_wait={metrics.average_wait_minutes:.2f} min"
        )
    print("Note: illustrative M/M/s assumptions, not measured station arrivals or service times.")


if __name__ == "__main__":
    main()

"""M/M/s queueing estimates for charging-station waiting-time scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from math import lgamma, log

import numpy as np


@dataclass(frozen=True)
class QueueMetrics:
    """Steady-state M/M/s queue metrics for one charging station."""

    stable: bool
    arrival_rate_per_hour: float
    service_rate_per_hour_per_charger: float
    chargers: int
    utilization: float
    probability_wait: float
    average_wait_minutes: float
    average_time_in_system_minutes: float


def _logsumexp(values: list[float]) -> float:
    maximum = max(values)
    return maximum + log(sum(np.exp(value - maximum) for value in values))


def mm_s_queue_metrics(
    arrival_rate_per_hour: float,
    service_rate_per_hour_per_charger: float,
    chargers: int,
) -> QueueMetrics:
    """Compute Erlang-C waiting time under an M/M/s model.

    ``arrival_rate_per_hour`` is lambda (vehicles arriving per hour),
    ``service_rate_per_hour_per_charger`` is mu (vehicles served per hour by
    one charger), and ``chargers`` is the number of parallel chargers.

    If lambda >= chargers * mu, the queue is unstable and the steady-state
    waiting time is infinite.
    """
    lam = float(arrival_rate_per_hour)
    mu = float(service_rate_per_hour_per_charger)
    s = int(chargers)
    if not np.isfinite(lam) or lam < 0:
        raise ValueError("Arrival rate must be finite and non-negative.")
    if not np.isfinite(mu) or mu <= 0:
        raise ValueError("Service rate must be finite and positive.")
    if s < 1 or s != chargers:
        raise ValueError("chargers must be a positive integer.")

    capacity = s * mu
    utilization = lam / capacity
    if lam == 0:
        return QueueMetrics(True, lam, mu, s, 0.0, 0.0, 0.0, 60.0 / mu)
    if utilization >= 1.0:
        return QueueMetrics(
            False,
            lam,
            mu,
            s,
            utilization,
            1.0,
            float("inf"),
            float("inf"),
        )

    offered_load = lam / mu
    log_terms = [
        k * log(offered_load) - lgamma(k + 1)
        for k in range(s)
    ]
    log_tail = (
        s * log(offered_load)
        - lgamma(s + 1)
        - log(1.0 - utilization)
    )
    log_denominator = _logsumexp(log_terms + [log_tail])
    probability_wait = float(np.exp(log_tail - log_denominator))
    wait_hours = probability_wait / (capacity - lam)
    service_hours = 1.0 / mu

    return QueueMetrics(
        stable=True,
        arrival_rate_per_hour=lam,
        service_rate_per_hour_per_charger=mu,
        chargers=s,
        utilization=utilization,
        probability_wait=probability_wait,
        average_wait_minutes=60.0 * wait_hours,
        average_time_in_system_minutes=60.0 * (wait_hours + service_hours),
    )


def queue_metrics_from_daily_energy(
    daily_charging_energy_kwh: float,
    average_session_energy_kwh: float,
    operating_hours_per_day: float,
    average_service_minutes: float,
    chargers: int,
) -> QueueMetrics:
    """Convert an energy-demand scenario into M/M/s arrival/service rates.

    This uses explicit scenario assumptions. It is not a calibrated queue
    model unless the arrival and service distributions are empirically
    justified for the charging site.
    """
    inputs = (
        daily_charging_energy_kwh,
        average_session_energy_kwh,
        operating_hours_per_day,
        average_service_minutes,
    )
    if not all(np.isfinite(value) and value > 0 for value in inputs):
        raise ValueError("Energy, session size, operating hours and service time must be positive.")
    if chargers < 1 or chargers != int(chargers):
        raise ValueError("chargers must be a positive integer.")

    arrivals_per_day = daily_charging_energy_kwh / average_session_energy_kwh
    arrival_rate = arrivals_per_day / operating_hours_per_day
    service_rate = 60.0 / average_service_minutes
    return mm_s_queue_metrics(arrival_rate, service_rate, int(chargers))

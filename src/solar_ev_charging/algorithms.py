"""Core decision algorithms for station selection and admission control."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from solar_ev_charging.models import (
    AdmissionDecision,
    ChargeMode,
    ChargingOffer,
    ChargingPolicy,
    QueuedSession,
    StationState,
    VehicleRequest,
)
from solar_ev_charging.security import SecurityCheck, TrustRegistry


def mode_declassification_order(requested_mode: ChargeMode) -> tuple[ChargeMode, ...]:
    """Return candidate modes from requested power down to slower fallbacks."""

    if requested_mode is ChargeMode.RAPID:
        return (ChargeMode.RAPID, ChargeMode.NORMAL, ChargeMode.SLOW)
    if requested_mode is ChargeMode.NORMAL:
        return (ChargeMode.NORMAL, ChargeMode.SLOW)
    return (ChargeMode.SLOW,)


def service_minutes(
    energy_kwh: float,
    mode: ChargeMode,
    request: VehicleRequest,
    policy: ChargingPolicy,
) -> float:
    """Compute service duration for an energy allocation and mode."""

    if energy_kwh <= 0:
        return 0.0
    effective_kw = min(policy.power_kw(mode), request.max_charge_kw)
    delivered_kw = effective_kw * policy.charge_efficiency
    return (energy_kwh / delivered_kw) * 60.0


def adjusted_queue_score(session: QueuedSession, now_minute: float) -> float:
    """EDF-inspired queue score adjusted by priority and waiting age."""

    return session.urgency_score(now_minute)


def estimate_wait_minutes(
    station: StationState,
    incoming: VehicleRequest,
    incoming_service_minutes: float,
    now_minute: float,
    *,
    use_edf: bool = True,
) -> float:
    """Estimate wait under adjusted EDF scheduling.

    The estimator is intentionally conservative and deterministic. It counts
    active socket work plus queued jobs that outrank the incoming request.
    """

    if station.has_free_socket and not station.queue:
        return 0.0

    if not use_edf:
        active_work = sum(station.active_sessions_remaining_minutes)
        queued_work = sum(session.service_minutes for session in station.queue)
        parallelism = max(station.socket_count, 1)
        return (active_work + queued_work) / parallelism

    incoming_session = QueuedSession(
        vehicle_id=incoming.vehicle_id,
        service_minutes=incoming_service_minutes,
        arrival_minute=now_minute,
        deadline_minute=incoming.deadline_minute,
        priority=incoming.priority,
    )
    incoming_score = adjusted_queue_score(incoming_session, now_minute)

    active_work = sum(station.active_sessions_remaining_minutes)
    higher_ranked_work = sum(
        session.service_minutes
        for session in station.queue
        if adjusted_queue_score(session, now_minute) > incoming_score
    )
    parallelism = max(station.socket_count, 1)
    return (active_work + higher_ranked_work) / parallelism


def admit_request(
    request: VehicleRequest,
    station: StationState,
    policy: ChargingPolicy | None = None,
    *,
    now_minute: float | None = None,
    trust_registry: TrustRegistry | None = None,
    allow_partial: bool = True,
    allow_declassification: bool = True,
    use_edf: bool = True,
    deadline_safety_factor: float = 1.0,
) -> ChargingOffer:
    """Evaluate a station-side admission request using S-ACA-PD-EDF."""

    policy = policy or ChargingPolicy()
    now = request.timestamp_minute if now_minute is None else now_minute

    if trust_registry is not None:
        security = trust_registry.check_request(request, now_minute=now)
        if security is not SecurityCheck.PASS:
            return ChargingOffer(
                decision=AdmissionDecision.DECLINE_SECURITY,
                station_id=station.station_id,
                reason=f"security_check_failed:{security.value}",
            )

    if station.queue_full and not station.has_free_socket:
        return ChargingOffer(
            decision=AdmissionDecision.DECLINE_QUEUE_FULL,
            station_id=station.station_id,
            reason="queue_capacity_reached",
        )

    requested_energy = request.requested_energy_kwh()
    best_energy_failure = False
    best_time_failure = False

    modes = (
        mode_declassification_order(request.requested_mode)
        if allow_declassification
        else (request.requested_mode,)
    )
    effective_deadline = request.max_wait_minutes * deadline_safety_factor

    for mode in modes:
        if min(policy.power_kw(mode), request.max_charge_kw) > station.available_power_kw:
            best_time_failure = True
            continue
        duration = service_minutes(requested_energy, mode, request, policy)
        wait = estimate_wait_minutes(station, request, duration, now, use_edf=use_edf)
        enough_time = wait + duration <= effective_deadline
        enough_energy = station.available_energy_kwh() >= requested_energy

        if enough_time and enough_energy:
            immediate = station.has_free_socket and not station.queue
            degraded = mode is not request.requested_mode
            if immediate and not degraded:
                decision = AdmissionDecision.ACCEPT_IMMEDIATE
            elif degraded:
                decision = AdmissionDecision.ACCEPT_DEGRADED_POWER
            else:
                decision = AdmissionDecision.ACCEPT_QUEUE

            return ChargingOffer(
                decision=decision,
                station_id=station.station_id,
                reason="feasible_energy_and_deadline",
                mode=mode,
                allocated_energy_kwh=requested_energy,
                wait_minutes=wait,
                service_minutes=duration,
            )

        best_energy_failure = best_energy_failure or not enough_energy
        best_time_failure = best_time_failure or not enough_time

    if allow_partial:
        partial_energy = request.minimum_useful_energy_kwh()
        if partial_energy > 0:
            for mode in reversed(modes):
                duration = service_minutes(partial_energy, mode, request, policy)
                wait = estimate_wait_minutes(station, request, duration, now, use_edf=use_edf)
                if (
                    wait + duration <= effective_deadline
                    and station.available_energy_kwh() >= partial_energy
                ):
                    return ChargingOffer(
                        decision=AdmissionDecision.ACCEPT_PARTIAL,
                        station_id=station.station_id,
                        reason="partial_charge_feasible",
                        mode=mode,
                        allocated_energy_kwh=partial_energy,
                        wait_minutes=wait,
                        service_minutes=duration,
                    )

    decision = (
        AdmissionDecision.DECLINE_ENERGY if best_energy_failure else AdmissionDecision.DECLINE_TIME
    )
    reason = "insufficient_energy" if best_energy_failure else "deadline_infeasible"
    if best_energy_failure and best_time_failure:
        reason = "insufficient_energy_and_deadline_infeasible"

    return ChargingOffer(decision=decision, station_id=station.station_id, reason=reason)


def station_selection_score(
    request: VehicleRequest,
    station: StationState,
    policy: ChargingPolicy,
    *,
    now_minute: float,
    average_speed_kmh: float = 35.0,
    use_edf: bool = True,
) -> float:
    """Score a station from the vehicle side using V-ASSIST criteria."""

    distance_km = request.position.distance_to(station.position)
    travel_minutes = (distance_km / average_speed_kmh) * 60.0
    duration = service_minutes(
        request.requested_energy_kwh(),
        request.requested_mode,
        request,
        policy,
    )
    wait = estimate_wait_minutes(station, request, duration, now_minute, use_edf=use_edf)
    age_minutes = max(now_minute - station.info_timestamp_minute, 0.0)
    energy_margin = station.available_energy_kwh() - request.requested_energy_kwh()
    urgency = 1.0 / max(request.max_wait_minutes, 1.0)

    return (
        4.0 * urgency
        + 2.0 * request.priority
        + 0.08 * energy_margin
        + 2.0 * station.reliability
        - 0.15 * travel_minutes
        - 0.12 * wait
        - policy.stale_information_penalty_per_minute * age_minutes
        - 0.2 * len(station.queue)
    )


def select_station(
    request: VehicleRequest,
    stations: Iterable[StationState],
    policy: ChargingPolicy | None = None,
    *,
    now_minute: float | None = None,
    average_speed_kmh: float = 35.0,
    allow_partial: bool = True,
    allow_declassification: bool = True,
    use_edf: bool = True,
    use_aoi: bool = True,
    deadline_safety_factor: float = 1.0,
) -> ChargingOffer:
    """Select the best station for a vehicle request using V-ASSIST."""

    policy = policy or ChargingPolicy()
    score_policy = policy if use_aoi else replace(policy, stale_information_penalty_per_minute=0.0)
    now = request.timestamp_minute if now_minute is None else now_minute

    best_offer: ChargingOffer | None = None
    for station in stations:
        admission = admit_request(
            request,
            station,
            policy,
            now_minute=now,
            allow_partial=allow_partial,
            allow_declassification=allow_declassification,
            use_edf=use_edf,
            deadline_safety_factor=deadline_safety_factor,
        )
        if not admission.accepted:
            continue

        score = station_selection_score(
            request,
            station,
            score_policy,
            now_minute=now,
            average_speed_kmh=average_speed_kmh,
            use_edf=use_edf,
        )
        offer = ChargingOffer(
            decision=admission.decision,
            station_id=station.station_id,
            reason=admission.reason,
            mode=admission.mode,
            allocated_energy_kwh=admission.allocated_energy_kwh,
            wait_minutes=admission.wait_minutes,
            service_minutes=admission.service_minutes,
            score=score,
        )
        if best_offer is None or offer.score > best_offer.score:
            best_offer = offer

    if best_offer is None:
        return ChargingOffer(
            decision=AdmissionDecision.REDIRECT,
            station_id="",
            reason="no_feasible_station",
        )
    return best_offer

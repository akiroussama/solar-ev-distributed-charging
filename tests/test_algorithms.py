import pytest

from solar_ev_charging.algorithms import admit_request, select_station
from solar_ev_charging.models import (
    AdmissionDecision,
    ChargeMode,
    Position,
    QueuedSession,
    StationState,
    VehicleRequest,
)
from solar_ev_charging.security import TrustRegistry


def make_request(**overrides: object) -> VehicleRequest:
    values = {
        "vehicle_id": "ev-1",
        "soc": 0.20,
        "soh": 1.0,
        "capacity_kwh": 50.0,
        "desired_soc": 0.80,
        "minimum_soc": 0.40,
        "max_wait_minutes": 120.0,
        "priority": 1,
        "position": Position(0.0, 0.0),
        "requested_mode": ChargeMode.RAPID,
        "timestamp_minute": 0.0,
        "nonce": "n1",
        "signature": "simulated",
    }
    values.update(overrides)
    return VehicleRequest(**values)  # type: ignore[arg-type]


def make_station(**overrides: object) -> StationState:
    values = {
        "station_id": "cs-1",
        "position": Position(1.0, 0.0),
        "socket_count": 2,
        "queue_capacity": 4,
        "stored_energy_kwh": 80.0,
        "storage_reserve_kwh": 10.0,
        "pv_forecast_kwh": 10.0,
        "info_timestamp_minute": 0.0,
    }
    values.update(overrides)
    return StationState(**values)  # type: ignore[arg-type]


def test_admit_request_accepts_feasible_immediate_charge() -> None:
    offer = admit_request(make_request(), make_station())

    assert offer.decision is AdmissionDecision.ACCEPT_IMMEDIATE
    assert offer.mode is ChargeMode.RAPID
    assert offer.allocated_energy_kwh == pytest.approx(30.0)


def test_admit_request_declassifies_when_station_power_cannot_support_rapid() -> None:
    request = make_request(max_wait_minutes=120.0)
    station = make_station(stored_energy_kwh=120.0, available_power_kw=25.0)

    offer = admit_request(request, station)

    assert offer.accepted
    assert offer.mode is ChargeMode.NORMAL
    assert offer.decision is AdmissionDecision.ACCEPT_DEGRADED_POWER


def test_admit_request_returns_partial_when_full_energy_is_infeasible() -> None:
    request = make_request(desired_soc=0.90, minimum_soc=0.35)
    station = make_station(stored_energy_kwh=20.0, pv_forecast_kwh=0.0, storage_reserve_kwh=5.0)

    offer = admit_request(request, station)

    assert offer.decision is AdmissionDecision.ACCEPT_PARTIAL
    assert offer.allocated_energy_kwh == pytest.approx(7.5)


def test_admit_request_declines_when_queue_is_full_and_all_sockets_busy() -> None:
    station = make_station(
        socket_count=1,
        queue_capacity=1,
        active_sessions_remaining_minutes=(20.0,),
        queue=(
            QueuedSession(
                vehicle_id="queued",
                service_minutes=30.0,
                arrival_minute=0.0,
                deadline_minute=60.0,
                priority=0,
            ),
        ),
    )

    offer = admit_request(make_request(), station)

    assert offer.decision is AdmissionDecision.DECLINE_QUEUE_FULL


def test_admit_request_declines_failed_security_check() -> None:
    registry = TrustRegistry(known_vehicle_ids={"ev-1"})
    request = make_request(signature=None)

    offer = admit_request(request, make_station(), trust_registry=registry)

    assert offer.decision is AdmissionDecision.DECLINE_SECURITY
    assert "missing_signature" in offer.reason


def test_admit_request_declines_energy_when_partial_is_disabled() -> None:
    request = make_request(desired_soc=0.90, minimum_soc=0.35)
    station = make_station(stored_energy_kwh=20.0, pv_forecast_kwh=0.0, storage_reserve_kwh=5.0)

    offer = admit_request(request, station, allow_partial=False)

    assert offer.decision is AdmissionDecision.DECLINE_ENERGY


def test_select_station_prefers_feasible_solar_ready_station() -> None:
    request = make_request()
    near_starved = make_station(
        station_id="near-starved",
        position=Position(0.5, 0.0),
        stored_energy_kwh=12.0,
        pv_forecast_kwh=0.0,
        storage_reserve_kwh=10.0,
    )
    farther_ready = make_station(station_id="farther-ready", position=Position(4.0, 0.0))

    offer = select_station(request, [near_starved, farther_ready])

    assert offer.station_id == "farther-ready"
    assert offer.accepted


def test_select_station_returns_redirect_when_no_station_is_feasible() -> None:
    request = make_request()
    station = make_station(stored_energy_kwh=0.0, pv_forecast_kwh=0.0, storage_reserve_kwh=0.0)

    offer = select_station(request, [station])

    assert offer.decision is AdmissionDecision.REDIRECT

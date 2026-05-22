from solar_ev_charging.models import ChargeMode, Position, VehicleRequest
from solar_ev_charging.security import SecurityCheck, TrustRegistry


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


def test_trust_registry_accepts_fresh_known_signed_request() -> None:
    registry = TrustRegistry(known_vehicle_ids={"ev-1"})

    result = registry.check_request(make_request(), now_minute=1.0)

    assert result is SecurityCheck.PASS


def test_trust_registry_rejects_replayed_nonce() -> None:
    registry = TrustRegistry(known_vehicle_ids={"ev-1"})
    request = make_request()

    assert registry.check_request(request, now_minute=1.0) is SecurityCheck.PASS
    assert registry.check_request(request, now_minute=1.0) is SecurityCheck.REPLAY_NONCE


def test_trust_registry_rejects_unknown_vehicle() -> None:
    registry = TrustRegistry(known_vehicle_ids={"ev-2"})

    assert registry.check_request(make_request(), now_minute=1.0) is SecurityCheck.UNKNOWN_VEHICLE


def test_trust_registry_rejects_stale_timestamp() -> None:
    registry = TrustRegistry(known_vehicle_ids={"ev-1"}, max_message_age_minutes=5.0)

    assert registry.check_request(make_request(), now_minute=20.0) is SecurityCheck.STALE_TIMESTAMP


def test_trust_registry_rejects_missing_signature() -> None:
    registry = TrustRegistry(known_vehicle_ids={"ev-1"})

    assert (
        registry.check_request(make_request(signature=None), now_minute=1.0)
        is SecurityCheck.MISSING_SIGNATURE
    )


def test_trust_registry_rejects_low_trust_vehicle() -> None:
    registry = TrustRegistry(known_vehicle_ids={"ev-1"}, vehicle_trust={"ev-1": 0.1})

    assert registry.check_request(make_request(), now_minute=1.0) is SecurityCheck.LOW_TRUST


def test_trust_registry_rejects_implausible_soc_jump() -> None:
    registry = TrustRegistry(known_vehicle_ids={"ev-1"})

    assert (
        registry.check_request(make_request(soc=0.01, desired_soc=0.99), now_minute=1.0)
        is SecurityCheck.IMPLAUSIBLE_SOC
    )

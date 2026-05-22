import pytest

from solar_ev_charging.models import (
    ChargeMode,
    ChargingPolicy,
    Position,
    QueuedSession,
    StationState,
    VehicleRequest,
)
from solar_ev_charging.solar import cloud_adjusted_pv_power_kw, diurnal_irradiance


def test_position_distance_is_euclidean() -> None:
    assert Position(0.0, 0.0).distance_to(Position(3.0, 4.0)) == 5.0


def test_vehicle_energy_request_uses_soh_adjusted_capacity() -> None:
    request = VehicleRequest(
        vehicle_id="ev-1",
        soc=0.25,
        soh=0.9,
        capacity_kwh=80.0,
        desired_soc=0.75,
        minimum_soc=0.40,
        max_wait_minutes=60.0,
        priority=0,
        position=Position(0.0, 0.0),
        requested_mode=ChargeMode.NORMAL,
        timestamp_minute=10.0,
        nonce="abc",
    )

    assert request.requested_energy_kwh() == 36.0
    assert request.minimum_useful_energy_kwh() == pytest.approx(10.8)


def test_vehicle_request_rejects_invalid_soc_ordering() -> None:
    with pytest.raises(ValueError, match="desired_soc"):
        VehicleRequest(
            vehicle_id="ev-1",
            soc=0.80,
            soh=1.0,
            capacity_kwh=60.0,
            desired_soc=0.70,
            minimum_soc=0.70,
            max_wait_minutes=60.0,
            priority=0,
            position=Position(0.0, 0.0),
            requested_mode=ChargeMode.SLOW,
            timestamp_minute=0.0,
            nonce="n",
        )


def test_vehicle_request_rejects_invalid_minimum_soc_ordering() -> None:
    with pytest.raises(ValueError, match="minimum_soc"):
        VehicleRequest(
            vehicle_id="ev-1",
            soc=0.50,
            soh=1.0,
            capacity_kwh=60.0,
            desired_soc=0.80,
            minimum_soc=0.40,
            max_wait_minutes=60.0,
            priority=0,
            position=Position(0.0, 0.0),
            requested_mode=ChargeMode.SLOW,
            timestamp_minute=0.0,
            nonce="n",
        )


def test_vehicle_request_rejects_negative_priority() -> None:
    with pytest.raises(ValueError, match="priority"):
        VehicleRequest(
            vehicle_id="ev-1",
            soc=0.20,
            soh=1.0,
            capacity_kwh=60.0,
            desired_soc=0.80,
            minimum_soc=0.40,
            max_wait_minutes=60.0,
            priority=-1,
            position=Position(0.0, 0.0),
            requested_mode=ChargeMode.SLOW,
            timestamp_minute=0.0,
            nonce="n",
        )


def test_station_state_validates_capacity_and_power() -> None:
    with pytest.raises(ValueError, match="socket_count"):
        StationState(
            station_id="cs",
            position=Position(0.0, 0.0),
            socket_count=0,
            queue_capacity=1,
            stored_energy_kwh=10.0,
            storage_reserve_kwh=1.0,
            pv_forecast_kwh=0.0,
        )

    with pytest.raises(ValueError, match="available_power"):
        StationState(
            station_id="cs",
            position=Position(0.0, 0.0),
            socket_count=1,
            queue_capacity=1,
            stored_energy_kwh=10.0,
            storage_reserve_kwh=1.0,
            pv_forecast_kwh=0.0,
            available_power_kw=0.0,
        )


def test_station_state_energy_and_queue_properties() -> None:
    station = StationState(
        station_id="cs",
        position=Position(0.0, 0.0),
        socket_count=1,
        queue_capacity=1,
        stored_energy_kwh=20.0,
        storage_reserve_kwh=5.0,
        pv_forecast_kwh=10.0,
        reserved_energy_kwh=2.0,
        active_sessions_remaining_minutes=(10.0,),
        queue=(
            QueuedSession(
                vehicle_id="ev",
                service_minutes=5.0,
                arrival_minute=0.0,
                deadline_minute=10.0,
                priority=0,
            ),
        ),
    )

    assert station.free_sockets == 0
    assert station.queue_full
    assert station.available_energy_kwh() == 23.0


def test_policy_power_mapping() -> None:
    policy = ChargingPolicy(slow_kw=3.0, normal_kw=11.0, rapid_kw=100.0)

    assert policy.power_kw(ChargeMode.SLOW) == 3.0
    assert policy.power_kw(ChargeMode.NORMAL) == 11.0
    assert policy.power_kw(ChargeMode.RAPID) == 100.0


def test_solar_model_day_night_and_cloud_factor() -> None:
    assert diurnal_irradiance(0.0) == 0.0
    assert diurnal_irradiance(12.0) == pytest.approx(1.0)
    assert cloud_adjusted_pv_power_kw(
        12.0,
        panel_area_m2=100.0,
        efficiency=0.2,
        cloud_factor=0.5,
    ) == pytest.approx(10.0)


def test_solar_model_rejects_invalid_parameters() -> None:
    with pytest.raises(ValueError, match="panel_area"):
        cloud_adjusted_pv_power_kw(12.0, panel_area_m2=-1.0, efficiency=0.2)
    with pytest.raises(ValueError, match="efficiency"):
        cloud_adjusted_pv_power_kw(12.0, panel_area_m2=1.0, efficiency=1.2)
    with pytest.raises(ValueError, match="orientation"):
        cloud_adjusted_pv_power_kw(
            12.0,
            panel_area_m2=1.0,
            efficiency=0.2,
            orientation_factor=1.2,
        )
    with pytest.raises(ValueError, match="cloud"):
        cloud_adjusted_pv_power_kw(12.0, panel_area_m2=1.0, efficiency=0.2, cloud_factor=1.2)

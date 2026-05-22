"""Run a minimal V-ASSIST + S-ACA-PD-EDF scenario."""

from solar_ev_charging import (
    ChargeMode,
    ChargingPolicy,
    Position,
    StationState,
    VehicleRequest,
    select_station,
)


def main() -> None:
    policy = ChargingPolicy()
    request = VehicleRequest(
        vehicle_id="ev-001",
        soc=0.22,
        soh=0.95,
        capacity_kwh=60.0,
        desired_soc=0.80,
        minimum_soc=0.45,
        max_wait_minutes=90.0,
        priority=1,
        position=Position(0.0, 0.0),
        requested_mode=ChargeMode.RAPID,
        timestamp_minute=0.0,
        nonce="n-001",
        signature="simulated",
    )
    stations = [
        StationState(
            station_id="cs-near-busy",
            position=Position(2.0, 0.0),
            socket_count=2,
            queue_capacity=4,
            stored_energy_kwh=25.0,
            storage_reserve_kwh=5.0,
            pv_forecast_kwh=8.0,
            active_sessions_remaining_minutes=(30.0, 45.0),
            info_timestamp_minute=0.0,
        ),
        StationState(
            station_id="cs-solar-ready",
            position=Position(5.0, 0.0),
            socket_count=4,
            queue_capacity=8,
            stored_energy_kwh=80.0,
            storage_reserve_kwh=10.0,
            pv_forecast_kwh=25.0,
            info_timestamp_minute=0.0,
            reliability=0.98,
        ),
    ]

    offer = select_station(request, stations, policy)
    print(
        {
            "decision": offer.decision.value,
            "station": offer.station_id,
            "mode": offer.mode.value if offer.mode else None,
            "energy_kwh": round(offer.allocated_energy_kwh, 2),
            "wait_min": round(offer.wait_minutes, 2),
            "service_min": round(offer.service_minutes, 2),
            "score": round(offer.score, 2),
        }
    )


if __name__ == "__main__":
    main()

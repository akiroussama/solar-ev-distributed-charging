"""Reusable experimental scenarios for solar EV charging studies."""

from __future__ import annotations

from dataclasses import dataclass

from solar_ev_charging.models import Position


@dataclass(frozen=True)
class StationConfig:
    """Static station parameters used to initialize a simulation run."""

    station_id: str
    position: Position
    socket_count: int
    queue_capacity: int
    initial_energy_kwh: float
    storage_capacity_kwh: float
    storage_reserve_kwh: float
    panel_area_m2: float
    pv_efficiency: float
    available_power_kw: float
    grid_backup_kwh: float = 0.0
    storage_charge_efficiency: float = 0.96
    storage_discharge_efficiency: float = 0.94


@dataclass(frozen=True)
class ScenarioConfig:
    """Scenario-level parameters for reproducible experiments."""

    name: str
    duration_minutes: int
    arrival_rate_per_hour: float
    station_configs: tuple[StationConfig, ...]
    seed: int = 1
    cloud_factor: float = 0.85
    priority_probability: float = 0.08
    communication_loss_probability: float = 0.0
    communication_latency_minutes: float = 0.0
    communication_noise_fraction: float = 0.0
    attack_probability: float = 0.0
    average_speed_kmh: float = 35.0
    demand_scale: float = 1.0


def default_station_configs() -> tuple[StationConfig, ...]:
    """Return a heterogeneous four-station network."""

    return (
        StationConfig(
            station_id="cs-north",
            position=Position(2.0, 9.5),
            socket_count=3,
            queue_capacity=8,
            initial_energy_kwh=110.0,
            storage_capacity_kwh=160.0,
            storage_reserve_kwh=20.0,
            panel_area_m2=160.0,
            pv_efficiency=0.20,
            available_power_kw=55.0,
            grid_backup_kwh=10.0,
        ),
        StationConfig(
            station_id="cs-center",
            position=Position(6.0, 6.0),
            socket_count=4,
            queue_capacity=10,
            initial_energy_kwh=135.0,
            storage_capacity_kwh=190.0,
            storage_reserve_kwh=25.0,
            panel_area_m2=190.0,
            pv_efficiency=0.19,
            available_power_kw=65.0,
            grid_backup_kwh=15.0,
        ),
        StationConfig(
            station_id="cs-east",
            position=Position(10.5, 5.0),
            socket_count=2,
            queue_capacity=6,
            initial_energy_kwh=75.0,
            storage_capacity_kwh=120.0,
            storage_reserve_kwh=18.0,
            panel_area_m2=125.0,
            pv_efficiency=0.18,
            available_power_kw=45.0,
            grid_backup_kwh=8.0,
        ),
        StationConfig(
            station_id="cs-south",
            position=Position(4.5, 1.5),
            socket_count=3,
            queue_capacity=7,
            initial_energy_kwh=90.0,
            storage_capacity_kwh=140.0,
            storage_reserve_kwh=18.0,
            panel_area_m2=145.0,
            pv_efficiency=0.20,
            available_power_kw=50.0,
            grid_backup_kwh=10.0,
        ),
    )


def research_scenarios() -> tuple[ScenarioConfig, ...]:
    """Return the baseline scenario suite used by the CLI and reports."""

    stations = default_station_configs()
    return (
        ScenarioConfig(
            name="nominal",
            duration_minutes=8 * 60,
            arrival_rate_per_hour=22.0,
            station_configs=stations,
            cloud_factor=0.85,
            priority_probability=0.08,
        ),
        ScenarioConfig(
            name="congestion",
            duration_minutes=8 * 60,
            arrival_rate_per_hour=40.0,
            station_configs=stations,
            cloud_factor=0.80,
            priority_probability=0.10,
            demand_scale=1.08,
        ),
        ScenarioConfig(
            name="low_solar",
            duration_minutes=8 * 60,
            arrival_rate_per_hour=25.0,
            station_configs=stations,
            cloud_factor=0.35,
            priority_probability=0.08,
            demand_scale=1.05,
        ),
        ScenarioConfig(
            name="degraded_communication",
            duration_minutes=8 * 60,
            arrival_rate_per_hour=28.0,
            station_configs=stations,
            cloud_factor=0.70,
            priority_probability=0.10,
            communication_loss_probability=0.22,
            communication_latency_minutes=12.0,
            communication_noise_fraction=0.20,
        ),
        ScenarioConfig(
            name="security_stress",
            duration_minutes=8 * 60,
            arrival_rate_per_hour=28.0,
            station_configs=stations,
            cloud_factor=0.75,
            priority_probability=0.12,
            attack_probability=0.15,
        ),
    )


def sensitivity_scenarios() -> tuple[ScenarioConfig, ...]:
    """Return one-factor stress variations for sensitivity analysis."""

    stations = default_station_configs()
    low_bess_stations = tuple(
        StationConfig(
            station_id=station.station_id,
            position=station.position,
            socket_count=station.socket_count,
            queue_capacity=station.queue_capacity,
            initial_energy_kwh=station.initial_energy_kwh * 0.45,
            storage_capacity_kwh=station.storage_capacity_kwh * 0.65,
            storage_reserve_kwh=station.storage_reserve_kwh,
            panel_area_m2=station.panel_area_m2,
            pv_efficiency=station.pv_efficiency,
            available_power_kw=station.available_power_kw,
            grid_backup_kwh=station.grid_backup_kwh,
            storage_charge_efficiency=station.storage_charge_efficiency,
            storage_discharge_efficiency=station.storage_discharge_efficiency,
        )
        for station in stations
    )
    no_grid_stations = tuple(
        StationConfig(
            station_id=station.station_id,
            position=station.position,
            socket_count=station.socket_count,
            queue_capacity=station.queue_capacity,
            initial_energy_kwh=station.initial_energy_kwh,
            storage_capacity_kwh=station.storage_capacity_kwh,
            storage_reserve_kwh=station.storage_reserve_kwh,
            panel_area_m2=station.panel_area_m2,
            pv_efficiency=station.pv_efficiency,
            available_power_kw=station.available_power_kw,
            grid_backup_kwh=0.0,
            storage_charge_efficiency=station.storage_charge_efficiency,
            storage_discharge_efficiency=station.storage_discharge_efficiency,
        )
        for station in stations
    )
    return (
        ScenarioConfig(
            name="sensitivity_high_demand",
            duration_minutes=8 * 60,
            arrival_rate_per_hour=50.0,
            station_configs=stations,
            cloud_factor=0.80,
            priority_probability=0.10,
            demand_scale=1.15,
        ),
        ScenarioConfig(
            name="sensitivity_low_bess",
            duration_minutes=8 * 60,
            arrival_rate_per_hour=28.0,
            station_configs=low_bess_stations,
            cloud_factor=0.65,
            priority_probability=0.10,
        ),
        ScenarioConfig(
            name="sensitivity_high_loss",
            duration_minutes=8 * 60,
            arrival_rate_per_hour=28.0,
            station_configs=stations,
            cloud_factor=0.75,
            priority_probability=0.10,
            communication_loss_probability=0.40,
            communication_latency_minutes=20.0,
            communication_noise_fraction=0.35,
        ),
        ScenarioConfig(
            name="sensitivity_high_attack",
            duration_minutes=8 * 60,
            arrival_rate_per_hour=30.0,
            station_configs=stations,
            cloud_factor=0.75,
            priority_probability=0.12,
            attack_probability=0.30,
        ),
        ScenarioConfig(
            name="sensitivity_no_grid",
            duration_minutes=8 * 60,
            arrival_rate_per_hour=26.0,
            station_configs=no_grid_stations,
            cloud_factor=0.55,
            priority_probability=0.08,
        ),
    )

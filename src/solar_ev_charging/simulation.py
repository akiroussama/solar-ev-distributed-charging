"""Discrete-event simulation for EV charging admission experiments."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from random import Random
from statistics import mean

from solar_ev_charging.algorithms import (
    adjusted_queue_score,
    admit_request,
    select_station,
    service_minutes,
)
from solar_ev_charging.models import (
    AdmissionDecision,
    ChargeMode,
    ChargingOffer,
    ChargingPolicy,
    Position,
    QueuedSession,
    StationState,
    VehicleRequest,
)
from solar_ev_charging.scenarios import ScenarioConfig, StationConfig
from solar_ev_charging.security import SecurityCheck, TrustRegistry
from solar_ev_charging.solar import cloud_adjusted_pv_power_kw


class Baseline(str, Enum):
    """Policies compared in the experimental protocol."""

    NEAREST = "nearest_station"
    MIN_WAIT = "minimum_wait"
    ACA_PD_FIFO = "aca_pd_fifo"
    PROPOSED = "v_assist_s_aca_pd_edf"


@dataclass(frozen=True)
class VehicleArrival:
    """Generated EV arrival with attack metadata."""

    minute: int
    request: VehicleRequest
    is_attack: bool


@dataclass
class ScheduledJob:
    """Accepted EV job waiting or charging at a station."""

    request: VehicleRequest
    offer: ChargingOffer
    station_id: str
    arrival_minute: float
    is_attack: bool
    start_minute: float | None = None

    @property
    def completion_deadline(self) -> float:
        """Latest acceptable completion time."""

        return self.request.timestamp_minute + self.request.max_wait_minutes


@dataclass
class RunningJob:
    """Charging job currently occupying a socket."""

    job: ScheduledJob
    remaining_minutes: float


@dataclass
class SimulationMetrics:
    """Aggregated metrics for one scenario, one baseline and one seed."""

    scenario: str
    baseline: str
    seed: int
    generated: int = 0
    accepted: int = 0
    rejected: int = 0
    completed: int = 0
    deadline_missed: int = 0
    attacks_attempted: int = 0
    attacks_blocked: int = 0
    attacks_accepted: int = 0
    storage_energy_used_kwh: float = 0.0
    grid_energy_used_kwh: float = 0.0
    pv_generated_kwh: float = 0.0
    pv_spilled_kwh: float = 0.0
    wait_minutes: list[float] = field(default_factory=list)
    total_minutes: list[float] = field(default_factory=list)
    extra_distance_km: list[float] = field(default_factory=list)
    completed_by_priority: dict[int, int] = field(default_factory=dict)

    @property
    def rejection_rate(self) -> float:
        """Rejected requests over generated requests."""

        return self.rejected / self.generated if self.generated else 0.0

    @property
    def acceptance_rate(self) -> float:
        """Accepted requests over generated requests."""

        return self.accepted / self.generated if self.generated else 0.0

    @property
    def deadline_miss_rate(self) -> float:
        """Deadline misses over completed sessions."""

        return self.deadline_missed / self.completed if self.completed else 0.0

    @property
    def average_wait_minutes(self) -> float:
        """Average observed queue wait."""

        return mean(self.wait_minutes) if self.wait_minutes else 0.0

    @property
    def average_total_minutes(self) -> float:
        """Average time from request to charge completion."""

        return mean(self.total_minutes) if self.total_minutes else 0.0

    @property
    def average_extra_distance_km(self) -> float:
        """Average selected-station travel distance."""

        return mean(self.extra_distance_km) if self.extra_distance_km else 0.0

    @property
    def solar_utilization(self) -> float:
        """Share of generated PV not spilled."""

        if self.pv_generated_kwh <= 0:
            return 0.0
        return max(0.0, 1.0 - (self.pv_spilled_kwh / self.pv_generated_kwh))

    @property
    def fairness_jain(self) -> float:
        """Jain index over completed-service counts by priority class."""

        if not self.completed_by_priority:
            return 1.0
        values = [float(value) for value in self.completed_by_priority.values()]
        denominator = len(values) * sum(value * value for value in values)
        return (sum(values) ** 2) / denominator if denominator else 1.0

    @property
    def attack_success_rate(self) -> float:
        """Accepted malicious requests over attempted malicious requests."""

        return self.attacks_accepted / self.attacks_attempted if self.attacks_attempted else 0.0

    def as_row(self) -> dict[str, str | int | float]:
        """Return a stable CSV/JSON-friendly row."""

        return {
            "scenario": self.scenario,
            "baseline": self.baseline,
            "seed": self.seed,
            "generated": self.generated,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "completed": self.completed,
            "rejection_rate": self.rejection_rate,
            "acceptance_rate": self.acceptance_rate,
            "deadline_miss_rate": self.deadline_miss_rate,
            "average_wait_minutes": self.average_wait_minutes,
            "average_total_minutes": self.average_total_minutes,
            "average_extra_distance_km": self.average_extra_distance_km,
            "storage_energy_used_kwh": self.storage_energy_used_kwh,
            "grid_energy_used_kwh": self.grid_energy_used_kwh,
            "pv_generated_kwh": self.pv_generated_kwh,
            "pv_spilled_kwh": self.pv_spilled_kwh,
            "solar_utilization": self.solar_utilization,
            "fairness_jain": self.fairness_jain,
            "attacks_attempted": self.attacks_attempted,
            "attacks_blocked": self.attacks_blocked,
            "attacks_accepted": self.attacks_accepted,
            "attack_success_rate": self.attack_success_rate,
        }


@dataclass
class RuntimeStation:
    """Mutable station state used inside a simulation run."""

    config: StationConfig
    stored_energy_kwh: float
    active: list[RunningJob] = field(default_factory=list)
    queue: list[ScheduledJob] = field(default_factory=list)

    @classmethod
    def from_config(cls, config: StationConfig) -> RuntimeStation:
        """Create a runtime station from static configuration."""

        return cls(config=config, stored_energy_kwh=config.initial_energy_kwh)

    def add_pv(self, minute: int, cloud_factor: float) -> tuple[float, float]:
        """Add one minute of PV energy and return generated/spilled energy."""

        hour = 8.0 + (minute / 60.0)
        generated = (
            cloud_adjusted_pv_power_kw(
                hour,
                panel_area_m2=self.config.panel_area_m2,
                efficiency=self.config.pv_efficiency,
                cloud_factor=cloud_factor,
            )
            / 60.0
        )
        room = max(self.config.storage_capacity_kwh - self.stored_energy_kwh, 0.0)
        stored = min(generated, room)
        self.stored_energy_kwh += stored
        return generated, generated - stored

    def forecast_pv_kwh(self, minute: int, cloud_factor: float, horizon_minutes: int = 60) -> float:
        """Estimate near-future PV energy with a rectangular approximation."""

        hour = 8.0 + (minute / 60.0)
        power = cloud_adjusted_pv_power_kw(
            hour,
            panel_area_m2=self.config.panel_area_m2,
            efficiency=self.config.pv_efficiency,
            cloud_factor=cloud_factor,
        )
        return power * (horizon_minutes / 60.0)

    def to_state(
        self,
        *,
        minute: int,
        cloud_factor: float,
        info_timestamp_minute: float | None = None,
        reliability: float = 1.0,
    ) -> StationState:
        """Export a read-only state snapshot for decision algorithms."""

        timestamp = float(minute) if info_timestamp_minute is None else info_timestamp_minute
        return StationState(
            station_id=self.config.station_id,
            position=self.config.position,
            socket_count=self.config.socket_count,
            queue_capacity=self.config.queue_capacity,
            stored_energy_kwh=self.stored_energy_kwh,
            storage_reserve_kwh=self.config.storage_reserve_kwh,
            pv_forecast_kwh=self.forecast_pv_kwh(minute, cloud_factor),
            available_power_kw=self.config.available_power_kw,
            grid_backup_kwh=self.config.grid_backup_kwh,
            active_sessions_remaining_minutes=tuple(job.remaining_minutes for job in self.active),
            queue=tuple(
                QueuedSession(
                    vehicle_id=job.request.vehicle_id,
                    service_minutes=job.offer.service_minutes,
                    arrival_minute=job.arrival_minute,
                    deadline_minute=job.completion_deadline,
                    priority=job.request.priority,
                )
                for job in self.queue
            ),
            info_timestamp_minute=timestamp,
            reliability=reliability,
        )

    def fifo_wait_minutes(self) -> float:
        """Estimate FIFO wait for the next queued job."""

        return (
            sum(job.remaining_minutes for job in self.active)
            + sum(job.offer.service_minutes for job in self.queue)
        ) / self.config.socket_count

    def reserve_energy(self, energy_kwh: float) -> tuple[float, float]:
        """Reserve energy and return storage/grid split."""

        usable_storage = max(self.stored_energy_kwh - self.config.storage_reserve_kwh, 0.0)
        storage_used = min(usable_storage, energy_kwh)
        grid_used = max(energy_kwh - storage_used, 0.0)
        self.stored_energy_kwh -= storage_used
        return storage_used, grid_used

    def enqueue(self, job: ScheduledJob) -> None:
        """Queue an accepted job."""

        self.queue.append(job)

    def advance_one_minute(
        self,
        *,
        minute: int,
        baseline: Baseline,
        metrics: SimulationMetrics,
    ) -> None:
        """Advance active jobs and start queued jobs on free sockets."""

        finished: list[RunningJob] = []
        for running in self.active:
            running.remaining_minutes -= 1.0
            if running.remaining_minutes <= 0:
                finished.append(running)

        for running in finished:
            self.active.remove(running)
            metrics.completed += 1
            job = running.job
            if job.start_minute is None:
                wait = 0.0
            else:
                wait = max(job.start_minute - job.arrival_minute, 0.0)
            total = max(float(minute) - job.arrival_minute, 0.0)
            metrics.wait_minutes.append(wait)
            metrics.total_minutes.append(total)
            metrics.completed_by_priority[job.request.priority] = (
                metrics.completed_by_priority.get(job.request.priority, 0) + 1
            )
            if float(minute) > job.completion_deadline:
                metrics.deadline_missed += 1

        self._start_queued_jobs(minute=minute, baseline=baseline)

    def _start_queued_jobs(self, *, minute: int, baseline: Baseline) -> None:
        while self.queue and len(self.active) < self.config.socket_count:
            if baseline is Baseline.PROPOSED:
                self.queue.sort(
                    key=lambda job: adjusted_queue_score(
                        QueuedSession(
                            vehicle_id=job.request.vehicle_id,
                            service_minutes=job.offer.service_minutes,
                            arrival_minute=job.arrival_minute,
                            deadline_minute=job.completion_deadline,
                            priority=job.request.priority,
                        ),
                        float(minute),
                    ),
                    reverse=True,
                )
            job = self.queue.pop(0)
            job.start_minute = float(minute)
            self.active.append(RunningJob(job=job, remaining_minutes=job.offer.service_minutes))


def run_simulation(
    scenario: ScenarioConfig,
    baseline: Baseline,
    *,
    seed: int,
    policy: ChargingPolicy | None = None,
) -> SimulationMetrics:
    """Run one deterministic simulation replication."""

    rng = Random(seed)
    policy = policy or ChargingPolicy()
    stations = {
        config.station_id: RuntimeStation.from_config(config) for config in scenario.station_configs
    }
    arrivals = _generate_arrivals(scenario, rng=rng, seed=seed)
    arrivals_by_minute: dict[int, list[VehicleArrival]] = {}
    for arrival in arrivals:
        arrivals_by_minute.setdefault(arrival.minute, []).append(arrival)

    metrics = SimulationMetrics(scenario=scenario.name, baseline=baseline.value, seed=seed)
    registry = TrustRegistry(
        known_vehicle_ids={
            arrival.request.vehicle_id for arrival in arrivals if not arrival.is_attack
        }
    )

    for minute in range(scenario.duration_minutes):
        for station in stations.values():
            generated, spilled = station.add_pv(minute, scenario.cloud_factor)
            metrics.pv_generated_kwh += generated
            metrics.pv_spilled_kwh += spilled

        for arrival in arrivals_by_minute.get(minute, []):
            _handle_arrival(
                arrival=arrival,
                stations=stations,
                scenario=scenario,
                baseline=baseline,
                policy=policy,
                registry=registry,
                rng=rng,
                metrics=metrics,
            )

        for station in stations.values():
            station.advance_one_minute(minute=minute, baseline=baseline, metrics=metrics)

    # Flush sessions that are already accepted but not completed within horizon.
    for station in stations.values():
        metrics.rejected += len(station.queue)
        station.queue.clear()
        metrics.rejected += len(station.active)
        station.active.clear()

    return metrics


def _handle_arrival(
    *,
    arrival: VehicleArrival,
    stations: dict[str, RuntimeStation],
    scenario: ScenarioConfig,
    baseline: Baseline,
    policy: ChargingPolicy,
    registry: TrustRegistry,
    rng: Random,
    metrics: SimulationMetrics,
) -> None:
    request = arrival.request
    metrics.generated += 1
    if arrival.is_attack:
        metrics.attacks_attempted += 1

    if baseline is Baseline.PROPOSED:
        security = registry.check_request(request, now_minute=float(arrival.minute))
        if security is not SecurityCheck.PASS:
            metrics.attacks_blocked += 1 if arrival.is_attack else 0
            metrics.rejected += 1
            return

    selected = _choose_station(
        request=request,
        stations=stations,
        scenario=scenario,
        baseline=baseline,
        policy=policy,
        minute=arrival.minute,
        rng=rng,
    )
    if selected is None:
        metrics.rejected += 1
        return

    station, offer = selected
    if not offer.accepted:
        metrics.rejected += 1
        return

    storage_used, grid_used = station.reserve_energy(offer.allocated_energy_kwh)
    metrics.storage_energy_used_kwh += storage_used
    metrics.grid_energy_used_kwh += grid_used
    metrics.accepted += 1
    if arrival.is_attack:
        metrics.attacks_accepted += 1
    metrics.extra_distance_km.append(request.position.distance_to(station.config.position))

    job = ScheduledJob(
        request=request,
        offer=offer,
        station_id=station.config.station_id,
        arrival_minute=float(arrival.minute),
        is_attack=arrival.is_attack,
    )
    if station.config.socket_count > len(station.active) and not station.queue:
        job.start_minute = float(arrival.minute)
        station.active.append(RunningJob(job=job, remaining_minutes=offer.service_minutes))
    else:
        station.enqueue(job)


def _choose_station(
    *,
    request: VehicleRequest,
    stations: dict[str, RuntimeStation],
    scenario: ScenarioConfig,
    baseline: Baseline,
    policy: ChargingPolicy,
    minute: int,
    rng: Random,
) -> tuple[RuntimeStation, ChargingOffer] | None:
    if baseline is Baseline.PROPOSED:
        observed_states = [
            _observed_station_state(station, scenario=scenario, minute=minute, rng=rng)
            for station in stations.values()
        ]
        offer = select_station(
            request,
            observed_states,
            policy,
            now_minute=float(minute),
            average_speed_kmh=scenario.average_speed_kmh,
        )
        if not offer.station_id:
            return None
        station = stations[offer.station_id]
        actual_offer = admit_request(
            request,
            station.to_state(minute=minute, cloud_factor=scenario.cloud_factor),
            policy,
            now_minute=float(minute),
            allow_partial=True,
        )
        return station, actual_offer

    if baseline is Baseline.NEAREST:
        station = min(
            stations.values(),
            key=lambda candidate: request.position.distance_to(candidate.config.position),
        )
        return station, _basic_offer(request, station, policy, minute=minute, allow_degrade=False)

    if baseline is Baseline.MIN_WAIT:
        station = min(stations.values(), key=lambda candidate: candidate.fifo_wait_minutes())
        return station, _basic_offer(request, station, policy, minute=minute, allow_degrade=False)

    if baseline is Baseline.ACA_PD_FIFO:
        station = min(stations.values(), key=lambda candidate: candidate.fifo_wait_minutes())
        offer = admit_request(
            request,
            station.to_state(minute=minute, cloud_factor=scenario.cloud_factor),
            policy,
            now_minute=float(minute),
            allow_partial=False,
        )
        return station, offer


def _basic_offer(
    request: VehicleRequest,
    station: RuntimeStation,
    policy: ChargingPolicy,
    *,
    minute: int,
    allow_degrade: bool,
) -> ChargingOffer:
    modes = (request.requested_mode,) if not allow_degrade else tuple(ChargeMode)
    if (
        station.config.queue_capacity <= len(station.queue)
        and len(station.active) >= station.config.socket_count
    ):
        return ChargingOffer(
            decision=AdmissionDecision.DECLINE_QUEUE_FULL,
            station_id=station.config.station_id,
            reason="queue_full",
        )
    for mode in modes:
        if min(policy.power_kw(mode), request.max_charge_kw) > station.config.available_power_kw:
            continue
        duration = service_minutes(request.requested_energy_kwh(), mode, request, policy)
        wait = station.fifo_wait_minutes()
        available = station.to_state(minute=minute, cloud_factor=1.0).available_energy_kwh()
        if (
            available >= request.requested_energy_kwh()
            and wait + duration <= request.max_wait_minutes
        ):
            decision = (
                AdmissionDecision.ACCEPT_IMMEDIATE
                if len(station.active) < station.config.socket_count and not station.queue
                else AdmissionDecision.ACCEPT_QUEUE
            )
            return ChargingOffer(
                decision=decision,
                station_id=station.config.station_id,
                reason="baseline_feasible",
                mode=mode,
                allocated_energy_kwh=request.requested_energy_kwh(),
                wait_minutes=wait,
                service_minutes=duration,
            )
    return ChargingOffer(
        decision=AdmissionDecision.DECLINE_ENERGY,
        station_id=station.config.station_id,
        reason="baseline_infeasible",
    )


def _observed_station_state(
    station: RuntimeStation,
    *,
    scenario: ScenarioConfig,
    minute: int,
    rng: Random,
) -> StationState:
    if rng.random() < scenario.communication_loss_probability:
        age = max(30.0, scenario.communication_latency_minutes * 2.0)
        reliability = 0.25
    else:
        age = rng.uniform(0.0, scenario.communication_latency_minutes)
        reliability = max(0.0, 1.0 - scenario.communication_loss_probability)
    return station.to_state(
        minute=minute,
        cloud_factor=scenario.cloud_factor,
        info_timestamp_minute=float(minute) - age,
        reliability=reliability,
    )


def _generate_arrivals(
    scenario: ScenarioConfig,
    *,
    rng: Random,
    seed: int,
) -> list[VehicleArrival]:
    arrivals: list[VehicleArrival] = []
    rate_per_minute = scenario.arrival_rate_per_hour / 60.0
    if rate_per_minute <= 0:
        return arrivals
    minute = 0.0
    index = 0
    while minute < scenario.duration_minutes:
        minute += rng.expovariate(rate_per_minute)
        if minute >= scenario.duration_minutes:
            break
        index += 1
        is_attack = rng.random() < scenario.attack_probability
        vehicle_id = f"ev-{seed}-{index}" if not is_attack else f"attacker-{seed}-{index}"
        soc = rng.uniform(0.08, 0.52)
        desired_soc = min(0.92, rng.uniform(0.72, 0.88) * scenario.demand_scale)
        minimum_soc = min(desired_soc, soc + rng.uniform(0.12, 0.24))
        priority = 3 if rng.random() < scenario.priority_probability else rng.choice([0, 1])
        request = VehicleRequest(
            vehicle_id=vehicle_id,
            soc=soc,
            soh=rng.uniform(0.78, 1.0),
            capacity_kwh=rng.uniform(45.0, 85.0),
            desired_soc=desired_soc,
            minimum_soc=minimum_soc,
            max_wait_minutes=rng.uniform(55.0, 150.0) / scenario.demand_scale,
            priority=priority,
            position=Position(rng.uniform(0.0, 12.0), rng.uniform(0.0, 12.0)),
            requested_mode=_random_mode(rng),
            timestamp_minute=float(int(minute)),
            nonce=f"nonce-{seed}-{index}" if not is_attack else "replayed-or-missing",
            signature="simulated" if not is_attack else None,
            max_charge_kw=rng.choice([22.0, 50.0, 100.0, 150.0]),
        )
        arrivals.append(VehicleArrival(minute=int(minute), request=request, is_attack=is_attack))
    return arrivals


def _random_mode(rng: Random) -> ChargeMode:
    draw = rng.random()
    if draw < 0.45:
        return ChargeMode.RAPID
    if draw < 0.85:
        return ChargeMode.NORMAL
    return ChargeMode.SLOW

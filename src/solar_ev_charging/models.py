"""Typed domain models for distributed solar EV charging."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import hypot


@dataclass(frozen=True)
class Position:
    """2D position in kilometers in a projected local coordinate system."""

    x_km: float
    y_km: float

    def distance_to(self, other: Position) -> float:
        """Return Euclidean distance in kilometers."""

        return hypot(self.x_km - other.x_km, self.y_km - other.y_km)


class ChargeMode(str, Enum):
    """Supported charging-rate classes."""

    SLOW = "slow"
    NORMAL = "normal"
    RAPID = "rapid"


class AdmissionDecision(str, Enum):
    """Station response to a charging request."""

    ACCEPT_IMMEDIATE = "accept_immediate"
    ACCEPT_QUEUE = "accept_queue"
    ACCEPT_DEGRADED_POWER = "accept_degraded_power"
    ACCEPT_PARTIAL = "accept_partial"
    REDIRECT = "redirect"
    DECLINE_TIME = "decline_time"
    DECLINE_ENERGY = "decline_energy"
    DECLINE_QUEUE_FULL = "decline_queue_full"
    DECLINE_SECURITY = "decline_security"


@dataclass(frozen=True)
class ChargingPolicy:
    """Decision parameters shared by vehicle and station algorithms."""

    slow_kw: float = 7.0
    normal_kw: float = 22.0
    rapid_kw: float = 50.0
    charge_efficiency: float = 0.92
    grid_energy_penalty: float = 3.0
    stale_information_penalty_per_minute: float = 0.02

    def power_kw(self, mode: ChargeMode) -> float:
        """Return nominal charging power for a mode."""

        match mode:
            case ChargeMode.SLOW:
                return self.slow_kw
            case ChargeMode.NORMAL:
                return self.normal_kw
            case ChargeMode.RAPID:
                return self.rapid_kw


@dataclass(frozen=True)
class VehicleRequest:
    """Charging request emitted by a connected EV."""

    vehicle_id: str
    soc: float
    soh: float
    capacity_kwh: float
    desired_soc: float
    minimum_soc: float
    max_wait_minutes: float
    priority: int
    position: Position
    requested_mode: ChargeMode
    timestamp_minute: float
    nonce: str
    max_charge_kw: float = 150.0
    signature: str | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.soc <= 1:
            msg = "soc must be in [0, 1]"
            raise ValueError(msg)
        if not 0 < self.soh <= 1:
            msg = "soh must be in (0, 1]"
            raise ValueError(msg)
        if not self.soc <= self.desired_soc <= 1:
            msg = "desired_soc must be between soc and 1"
            raise ValueError(msg)
        if not self.soc <= self.minimum_soc <= self.desired_soc:
            msg = "minimum_soc must be between soc and desired_soc"
            raise ValueError(msg)
        if self.capacity_kwh <= 0:
            msg = "capacity_kwh must be positive"
            raise ValueError(msg)
        if self.max_wait_minutes < 0:
            msg = "max_wait_minutes must be non-negative"
            raise ValueError(msg)
        if self.priority < 0:
            msg = "priority must be non-negative"
            raise ValueError(msg)

    @property
    def deadline_minute(self) -> float:
        """Latest acceptable completion time relative to the request clock."""

        return self.timestamp_minute + self.max_wait_minutes

    def requested_energy_kwh(self) -> float:
        """Energy required to reach desired SOC."""

        return self.capacity_kwh * self.soh * (self.desired_soc - self.soc)

    def minimum_useful_energy_kwh(self) -> float:
        """Energy required to reach the minimum acceptable SOC."""

        return self.capacity_kwh * self.soh * (self.minimum_soc - self.soc)


@dataclass(frozen=True)
class QueuedSession:
    """Scheduled or queued charging job."""

    vehicle_id: str
    service_minutes: float
    arrival_minute: float
    deadline_minute: float
    priority: int

    def urgency_score(self, now_minute: float) -> float:
        """Higher score means the session should be served sooner."""

        minutes_to_deadline = max(self.deadline_minute - now_minute, 1.0)
        fairness_age = max(now_minute - self.arrival_minute, 0.0) / minutes_to_deadline
        return (1.0 / minutes_to_deadline) + self.priority + fairness_age


@dataclass(frozen=True)
class StationState:
    """Current state broadcast by a charging station."""

    station_id: str
    position: Position
    socket_count: int
    queue_capacity: int
    stored_energy_kwh: float
    storage_reserve_kwh: float
    pv_forecast_kwh: float
    available_power_kw: float = 150.0
    grid_backup_kwh: float = 0.0
    reserved_energy_kwh: float = 0.0
    active_sessions_remaining_minutes: tuple[float, ...] = ()
    queue: tuple[QueuedSession, ...] = ()
    info_timestamp_minute: float = 0.0
    reliability: float = 1.0

    def __post_init__(self) -> None:
        if self.socket_count <= 0:
            msg = "socket_count must be positive"
            raise ValueError(msg)
        if self.queue_capacity < 0:
            msg = "queue_capacity must be non-negative"
            raise ValueError(msg)
        if not 0 <= self.reliability <= 1:
            msg = "reliability must be in [0, 1]"
            raise ValueError(msg)
        if self.available_power_kw <= 0:
            msg = "available_power_kw must be positive"
            raise ValueError(msg)
        if len(self.active_sessions_remaining_minutes) > self.socket_count:
            msg = "active sessions cannot exceed socket count"
            raise ValueError(msg)

    @property
    def free_sockets(self) -> int:
        """Number of sockets not currently occupied."""

        return self.socket_count - len(self.active_sessions_remaining_minutes)

    @property
    def has_free_socket(self) -> bool:
        """Whether at least one socket can start immediately."""

        return self.free_sockets > 0

    @property
    def queue_full(self) -> bool:
        """Whether the waiting queue has reached its finite capacity."""

        return len(self.queue) >= self.queue_capacity

    def available_energy_kwh(self) -> float:
        """Energy available for new reservations after safety reserve."""

        return max(
            self.stored_energy_kwh
            + self.pv_forecast_kwh
            + self.grid_backup_kwh
            - self.reserved_energy_kwh
            - self.storage_reserve_kwh,
            0.0,
        )


@dataclass(frozen=True)
class ChargingOffer:
    """Admission result returned by a station."""

    decision: AdmissionDecision
    station_id: str
    reason: str
    mode: ChargeMode | None = None
    allocated_energy_kwh: float = 0.0
    wait_minutes: float = 0.0
    service_minutes: float = 0.0
    score: float = 0.0
    redirect_station_id: str | None = None

    @property
    def accepted(self) -> bool:
        """Whether the offer gives the EV a charging slot."""

        return self.decision in {
            AdmissionDecision.ACCEPT_IMMEDIATE,
            AdmissionDecision.ACCEPT_QUEUE,
            AdmissionDecision.ACCEPT_DEGRADED_POWER,
            AdmissionDecision.ACCEPT_PARTIAL,
        }

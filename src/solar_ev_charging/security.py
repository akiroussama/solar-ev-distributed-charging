"""Simulation-ready trust and security checks for EV charging requests."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from solar_ev_charging.models import VehicleRequest


class SecurityCheck(str, Enum):
    """Result of a simulated TRUST-EV request check."""

    PASS = "pass"
    UNKNOWN_VEHICLE = "unknown_vehicle"
    STALE_TIMESTAMP = "stale_timestamp"
    REPLAY_NONCE = "replay_nonce"
    MISSING_SIGNATURE = "missing_signature"
    LOW_TRUST = "low_trust"
    IMPLAUSIBLE_SOC = "implausible_soc"


@dataclass
class TrustRegistry:
    """Small deterministic trust registry for simulation experiments.

    This is not production cryptography. It models identity, replay, freshness,
    and plausibility checks so security-aware algorithms can be evaluated.
    """

    known_vehicle_ids: set[str]
    min_trust: float = 0.2
    max_message_age_minutes: float = 5.0
    require_signature: bool = True
    vehicle_trust: dict[str, float] = field(default_factory=dict)
    seen_nonces: set[tuple[str, str]] = field(default_factory=set)

    def check_request(self, request: VehicleRequest, *, now_minute: float) -> SecurityCheck:
        """Validate identity, freshness, replay, trust, and basic SOC plausibility."""

        if request.vehicle_id not in self.known_vehicle_ids:
            return SecurityCheck.UNKNOWN_VEHICLE
        if self.require_signature and not request.signature:
            return SecurityCheck.MISSING_SIGNATURE
        if abs(now_minute - request.timestamp_minute) > self.max_message_age_minutes:
            return SecurityCheck.STALE_TIMESTAMP

        nonce_key = (request.vehicle_id, request.nonce)
        if nonce_key in self.seen_nonces:
            return SecurityCheck.REPLAY_NONCE

        if self.vehicle_trust.get(request.vehicle_id, 1.0) < self.min_trust:
            return SecurityCheck.LOW_TRUST

        # Plausibility is deliberately conservative: impossible SOC jumps are
        # rejected before the station reserves scarce energy.
        if request.desired_soc - request.soc > 0.95:
            return SecurityCheck.IMPLAUSIBLE_SOC

        self.seen_nonces.add(nonce_key)
        return SecurityCheck.PASS

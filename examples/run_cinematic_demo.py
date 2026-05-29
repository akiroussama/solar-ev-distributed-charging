# ruff: noqa: E501
"""Generate a local cinematic HTML demo for video recording.

The generated dashboard is dependency-free and can be opened directly from disk.
It combines real experiment summaries with an animated visual narrative built
from the same scenario and algorithm primitives as the simulator.
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from random import Random

from solar_ev_charging import ChargeMode, ChargingPolicy, Position, VehicleRequest, select_station
from solar_ev_charging.experiments import run_experiment_suite, summarize_results
from solar_ev_charging.models import StationState
from solar_ev_charging.scenarios import ScenarioConfig, research_scenarios, sensitivity_scenarios
from solar_ev_charging.security import SecurityCheck, TrustRegistry
from solar_ev_charging.simulation import Baseline

BASELINES: tuple[Baseline, ...] = (
    Baseline.NEAREST,
    Baseline.MIN_WAIT,
    Baseline.ACA_PD_FIFO,
    Baseline.PROPOSED,
    Baseline.DEADLINE_SAFE,
    Baseline.NO_TRUST,
    Baseline.NO_PARTIAL,
)

STATION_BACKDROP_ASSET = Path("pictures") / "ev_backgroundImage.png"
STATION_BACKDROP_OPTIMIZED_ASSET = Path("pictures") / "ev_backgroundImage_demo.jpg"
CITY_BACKDROP_ASSET = Path("pictures") / "cityMap.png"
CITY_BACKDROP_OPTIMIZED_ASSET = Path("pictures") / "cityMap_demo.jpg"

SCENE_IDS: tuple[str, ...] = (
    "nominal",
    "degraded_communication",
    "security_stress",
    "sensitivity_no_grid",
)


@dataclass
class MutableStation:
    scenario: ScenarioConfig
    station_id: str
    x_km: float
    y_km: float
    sockets: int
    queue_capacity: int
    storage_capacity_kwh: float
    stored_energy_kwh: float
    reserve_kwh: float
    pv_forecast_kwh: float
    available_power_kw: float
    grid_backup_kwh: float
    active_sessions: list[float]
    queue: int = 0

    def as_state(self, minute: float, reliability: float) -> StationState:
        return StationState(
            station_id=self.station_id,
            position=Position(self.x_km, self.y_km),
            socket_count=self.sockets,
            queue_capacity=self.queue_capacity,
            stored_energy_kwh=max(self.stored_energy_kwh, 0.0),
            storage_reserve_kwh=self.reserve_kwh,
            pv_forecast_kwh=max(self.pv_forecast_kwh, 0.0),
            available_power_kw=self.available_power_kw,
            grid_backup_kwh=max(self.grid_backup_kwh, 0.0),
            active_sessions_remaining_minutes=tuple(self.active_sessions[: self.sockets]),
            info_timestamp_minute=max(minute - (1.0 - reliability) * 18.0, 0.0),
            reliability=reliability,
        )

    @property
    def storage_pct(self) -> float:
        if self.storage_capacity_kwh <= 0:
            return 0.0
        return max(0.0, min(1.0, self.stored_energy_kwh / self.storage_capacity_kwh))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the cinematic demo HTML.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs") / "cinematic_demo",
        help="Directory where index.html and data.json will be written.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Monte Carlo seeds per scenario/baseline for demo evidence panels.",
    )
    args = parser.parse_args()

    if args.runs <= 0:
        raise SystemExit("--runs must be positive")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    city_backdrop_filename = ""
    city_backdrop_source = (
        CITY_BACKDROP_OPTIMIZED_ASSET
        if CITY_BACKDROP_OPTIMIZED_ASSET.exists()
        else CITY_BACKDROP_ASSET
    )
    if city_backdrop_source.exists():
        city_backdrop_filename = city_backdrop_source.name
        shutil.copy2(city_backdrop_source, args.output_dir / city_backdrop_filename)
    station_backdrop_filename = ""
    station_backdrop_source = (
        STATION_BACKDROP_OPTIMIZED_ASSET
        if STATION_BACKDROP_OPTIMIZED_ASSET.exists()
        else STATION_BACKDROP_ASSET
    )
    if station_backdrop_source.exists():
        station_backdrop_filename = station_backdrop_source.name
        shutil.copy2(station_backdrop_source, args.output_dir / station_backdrop_filename)
    data = build_demo_data(args.runs)
    data_path = args.output_dir / "data.json"
    html_path = args.output_dir / "index.html"
    guide_path = args.output_dir / "RECORDING_GUIDE.md"
    data_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    html_path.write_text(
        render_html(data, station_backdrop_filename, city_backdrop_filename), encoding="utf-8"
    )
    guide_path.write_text(render_guide(html_path), encoding="utf-8")
    print(f"Wrote cinematic demo: {html_path}")
    print(f"Wrote recording guide: {guide_path}")


def build_demo_data(runs: int) -> dict[str, object]:
    all_scenarios = {
        scenario.name: scenario for scenario in research_scenarios() + sensitivity_scenarios()
    }
    selected_scenarios = tuple(all_scenarios[name] for name in SCENE_IDS)
    seeds = tuple(range(1, runs + 1))
    summaries = summarize_results(run_experiment_suite(selected_scenarios, BASELINES, seeds=seeds))
    summary_rows = [
        {
            "scenario": summary.scenario,
            "baseline": summary.baseline,
            "runs": summary.runs,
            "rejection": round(summary.mean("rejection_rate"), 4),
            "acceptance": round(summary.mean("acceptance_rate"), 4),
            "wait": round(summary.mean("average_wait_minutes"), 2),
            "deadline": round(summary.mean("deadline_miss_rate"), 4),
            "grid": round(summary.mean("grid_energy_used_kwh"), 2),
            "solar": round(summary.mean("solar_utilization"), 4),
            "attack": round(summary.mean("attack_success_rate"), 4),
        }
        for summary in summaries
    ]
    scenes = build_scenes(summary_rows)
    timeline, stations = build_visual_timeline(all_scenarios, summary_rows)
    return {
        "title": "Solar EV Distributed Charging",
        "subtitle": "Distributed admission, solar autonomy and TRUST-EV under stress",
        "runs": runs,
        "cells": len(summary_rows),
        "simulations": len(summary_rows) * runs,
        "duration": 118,
        "scenes": scenes,
        "stations": stations,
        "vehicles": timeline,
        "summaries": summary_rows,
        "palette": {
            "solar": "#f6c84c",
            "ev": "#4fd1c5",
            "green": "#38b26d",
            "red": "#e6534f",
            "amber": "#ff9f43",
            "accepted": "#38b26d",
            "blocked": "#e6534f",
            "deadline": "#ff9f43",
            "grid": "#8d79ff",
            "ink": "#f4f7f5",
        },
    }


def build_scenes(summary_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    def metric(scenario: str, baseline: str, field: str) -> float:
        for row in summary_rows:
            if row["scenario"] == scenario and row["baseline"] == baseline:
                return float(row[field])
        return 0.0

    return [
        {
            "id": "nominal",
            "start": 0,
            "end": 27,
            "label": "Scene 1 / Operation nominale",
            "headline": "V-ASSIST choisit les stations solaires utiles, pas seulement les plus proches.",
            "focus": "Admission distribuee + energie locale",
            "metricA": f"{metric('nominal', 'v_assist_s_aca_pd_edf', 'acceptance') * 100:.1f}% accepted",
            "metricB": f"{metric('nominal', 'deadline_safe', 'deadline') * 100:.1f}% deadline miss in deadline-safe",
        },
        {
            "id": "degraded_communication",
            "start": 27,
            "end": 55,
            "label": "Scene 2 / Communication degradee",
            "headline": "Les decisions restent distribuees quand les messages sont anciens, perdus ou bruites.",
            "focus": "Age-of-information + redirection",
            "metricA": f"{metric('degraded_communication', 'v_assist_s_aca_pd_edf', 'acceptance') * 100:.1f}% accepted",
            "metricB": f"{metric('degraded_communication', 'deadline_safe', 'wait'):.1f} min wait deadline-safe",
        },
        {
            "id": "security_stress",
            "start": 55,
            "end": 86,
            "label": "Scene 3 / Cyber-security stress",
            "headline": "TRUST-EV bloque les requetes sybil, stale, spoofees ou non signees avant reservation.",
            "focus": "Trust filtering + replay protection",
            "metricA": f"{metric('security_stress', 'v_assist_s_aca_pd_edf', 'attack') * 100:.1f}% attack success",
            "metricB": f"{metric('security_stress', 'ablation_no_trust', 'attack') * 100:.1f}% without trust",
        },
        {
            "id": "sensitivity_no_grid",
            "start": 86,
            "end": 118,
            "label": "Scene 4 / Autonomie solaire no-grid",
            "headline": "Scenario sans reseau: toute la charge admise est servie par BESS et PV direct.",
            "focus": "PV + BESS + zero grid",
            "metricA": f"{metric('sensitivity_no_grid', 'v_assist_s_aca_pd_edf', 'grid'):.1f} kWh grid",
            "metricB": f"{metric('sensitivity_no_grid', 'v_assist_s_aca_pd_edf', 'solar') * 100:.0f}% solar utilization",
        },
    ]


def build_visual_timeline(
    scenarios: dict[str, ScenarioConfig],
    summary_rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    rng = Random(2042)
    base_scenario = scenarios["nominal"]
    stations = [
        MutableStation(
            scenario=base_scenario,
            station_id=station.station_id,
            x_km=station.position.x_km,
            y_km=station.position.y_km,
            sockets=station.socket_count,
            queue_capacity=station.queue_capacity,
            storage_capacity_kwh=station.storage_capacity_kwh,
            stored_energy_kwh=station.initial_energy_kwh,
            reserve_kwh=station.storage_reserve_kwh,
            pv_forecast_kwh=18.0 + station.panel_area_m2 * 0.05,
            available_power_kw=station.available_power_kw,
            grid_backup_kwh=station.grid_backup_kwh,
            active_sessions=[
                rng.uniform(8.0, 40.0) for _ in range(max(0, station.socket_count - 1))
            ],
        )
        for station in base_scenario.station_configs
    ]
    stations_by_id = {station.station_id: station for station in stations}
    visual_station_positions = {
        "cs-north": (1.68, 8.35),
        "cs-center": (5.72, 4.45),
        "cs-east": (10.05, 6.65),
        "cs-south": (3.46, 3.70),
    }
    visual_station_entries = {
        "cs-north": (1.68, 9.20),
        "cs-center": (5.72, 4.80),
        "cs-east": (10.05, 7.00),
        "cs-south": (3.46, 2.70),
    }
    station_payload = [
        {
            "id": station.station_id,
            "label": station.station_id.replace("cs-", "").upper(),
            "x": visual_station_positions.get(station.station_id, (station.x_km, station.y_km))[0],
            "y": visual_station_positions.get(station.station_id, (station.x_km, station.y_km))[1],
            "sockets": station.sockets,
            "parkingPlaces": {
                "cs-north": 5,
                "cs-center": 6,
                "cs-east": 1,
                "cs-south": 6,
            }.get(station.station_id, station.sockets),
            "storagePct": round(station.storage_pct, 3),
            "storedKwh": round(station.stored_energy_kwh, 1),
            "storageCapacityKwh": round(station.storage_capacity_kwh, 1),
            "reserveKwh": station.reserve_kwh,
            "powerKw": station.available_power_kw,
            "gridBackupKwh": station.grid_backup_kwh,
            "queueCapacity": station.queue_capacity,
        }
        for station in stations
    ]

    vehicles: list[dict[str, object]] = []
    scene_specs = [
        ("nominal", 0.5, 25.0, 28, 0.02),
        ("degraded_communication", 28.0, 52.5, 32, 0.05),
        ("security_stress", 56.0, 83.0, 42, 0.42),
        ("sensitivity_no_grid", 88.0, 114.0, 36, 0.0),
    ]
    policy = ChargingPolicy()
    registry = TrustRegistry(known_vehicle_ids=set())
    known_ids: set[str] = set()

    for scene_id, start_s, end_s, count, attack_probability in scene_specs:
        scenario = scenarios[scene_id]
        for index in range(count):
            start = (
                start_s + ((end_s - start_s) * index / max(count - 1, 1)) + rng.uniform(-0.65, 0.65)
            )
            start = max(start_s, min(start, end_s - 1.0))
            minute = (start - start_s) / max(end_s - start_s, 1.0) * scenario.duration_minutes
            is_attack = rng.random() < attack_probability
            attack_type = pick_attack_type(rng) if is_attack else None
            request = make_request(rng, scene_id, index, minute, attack_type)
            if not is_attack:
                known_ids.add(request.vehicle_id)
            registry.known_vehicle_ids = set(known_ids)

            from_x, from_y = request.position.x_km, request.position.y_km
            reliability = 1.0
            if scene_id == "degraded_communication":
                reliability = rng.uniform(0.38, 0.78)
            station_states = [
                station.as_state(minute, reliability=rng.uniform(reliability, 1.0))
                for station in stations
            ]

            security = registry.check_request(request, now_minute=minute)
            blocked = is_attack and security is not SecurityCheck.PASS
            if blocked:
                target_station = min(
                    stations,
                    key=lambda station: request.position.distance_to(
                        Position(station.x_km, station.y_km)
                    ),
                )
                vehicles.append(
                    make_vehicle_payload(
                        request,
                        scene_id,
                        start,
                        rng.uniform(3.0, 5.0),
                        from_x,
                        from_y,
                        target_station,
                        status="blocked",
                        attack_type=attack_type,
                        reason=security.value,
                        drive_speed=round(rng.uniform(24.0, 48.0), 1),
                    )
                )
                continue

            offer = select_station(
                request,
                station_states,
                policy,
                now_minute=minute,
                average_speed_kmh=scenario.average_speed_kmh,
                deadline_safety_factor=0.72 if rng.random() < 0.2 else 1.0,
            )
            if offer.accepted and offer.station_id in stations_by_id:
                target = stations_by_id[offer.station_id]
                target.stored_energy_kwh = max(
                    target.reserve_kwh,
                    target.stored_energy_kwh - offer.allocated_energy_kwh * 0.55,
                )
                target.queue = min(
                    target.queue_capacity, target.queue + (1 if offer.wait_minutes > 2 else 0)
                )
                if scene_id == "sensitivity_no_grid":
                    target.grid_backup_kwh = 0.0
                vehicles.append(
                    make_vehicle_payload(
                        request,
                        scene_id,
                        start,
                        rng.uniform(5.5, 10.5),
                        from_x,
                        from_y,
                        target,
                        status="accepted",
                        attack_type=attack_type,
                        reason=offer.decision.value,
                        mode=offer.mode.value if offer.mode else "",
                        energy=round(offer.allocated_energy_kwh, 1),
                        wait=round(offer.wait_minutes, 1),
                        score=round(offer.score, 2),
                        drive_speed=round(rng.uniform(22.0, 52.0), 1),
                    )
                )
            else:
                target = rng.choice(stations)
                vehicles.append(
                    make_vehicle_payload(
                        request,
                        scene_id,
                        start,
                        rng.uniform(3.5, 6.5),
                        from_x,
                        from_y,
                        target,
                        status="rejected",
                        attack_type=attack_type,
                        reason=offer.reason,
                        drive_speed=round(rng.uniform(18.0, 38.0), 1),
                    )
                )

    for vehicle in vehicles:
        station_id = str(vehicle["station"])
        if station_id in visual_station_entries:
            entry_x, entry_y = visual_station_entries[station_id]
            vehicle["to"] = [entry_x, entry_y]

    return vehicles, station_payload


def pick_attack_type(rng: Random) -> str:
    return rng.choice(["sybil", "missing_signature", "soc_spoof", "priority_spoof", "stale"])


def make_request(
    rng: Random,
    scene_id: str,
    index: int,
    minute: float,
    attack_type: str | None,
) -> VehicleRequest:
    vehicle_id = f"ev-{scene_id}-{index:03d}"
    if attack_type == "sybil":
        vehicle_id = f"ghost-{scene_id}-{index:03d}"
    soc = rng.uniform(0.12, 0.48)
    desired_soc = rng.uniform(0.72, 0.9)
    minimum_soc = min(desired_soc, soc + rng.uniform(0.10, 0.22))
    priority = 3 if rng.random() < 0.14 else rng.choice([0, 1, 2])
    signature: str | None = "signed"
    timestamp = minute
    nonce = f"nonce-{scene_id}-{index:03d}"
    if attack_type == "missing_signature":
        signature = None
    if attack_type == "soc_spoof":
        soc = 0.01
        desired_soc = 0.99
        minimum_soc = 0.6
    if attack_type == "priority_spoof":
        priority = 99
    if attack_type == "stale":
        timestamp = minute - 18.0
        nonce = "stale-replay"
    if scene_id == "sensitivity_no_grid":
        desired_soc = min(desired_soc, 0.82)
    return VehicleRequest(
        vehicle_id=vehicle_id,
        soc=soc,
        soh=rng.uniform(0.84, 1.0),
        capacity_kwh=rng.uniform(48.0, 88.0),
        desired_soc=desired_soc,
        minimum_soc=minimum_soc,
        max_wait_minutes=rng.uniform(58.0, 145.0),
        priority=priority,
        position=Position(rng.uniform(0.4, 11.6), rng.uniform(0.4, 11.6)),
        requested_mode=rng.choice([ChargeMode.RAPID, ChargeMode.NORMAL, ChargeMode.SLOW]),
        timestamp_minute=timestamp,
        nonce=nonce,
        max_charge_kw=rng.choice([22.0, 50.0, 100.0]),
        signature=signature,
    )


def make_vehicle_payload(
    request: VehicleRequest,
    scene_id: str,
    start: float,
    duration: float,
    from_x: float,
    from_y: float,
    target: MutableStation,
    *,
    status: str,
    attack_type: str | None,
    reason: str,
    mode: str = "",
    energy: float = 0.0,
    wait: float = 0.0,
    score: float = 0.0,
    drive_speed: float = 30.0,
) -> dict[str, object]:
    mode_for_power = mode or request.requested_mode.value
    mode_power_kw = {"rapid": 50.0, "normal": 22.0, "slow": 7.0}.get(mode_for_power, 7.0)
    charge_kw = min(mode_power_kw, request.max_charge_kw) * 0.92 if status == "accepted" else 0.0
    return {
        "id": request.vehicle_id,
        "scene": scene_id,
        "start": round(start, 2),
        "duration": round(duration, 2),
        "from": [round(from_x, 2), round(from_y, 2)],
        "to": [round(target.x_km, 2), round(target.y_km, 2)],
        "station": target.station_id,
        "status": status,
        "attackType": attack_type or "",
        "reason": reason,
        "mode": mode,
        "requestedMode": request.requested_mode.value,
        "energy": energy,
        "wait": wait,
        "priority": request.priority,
        "score": score,
        "soc": round(request.soc, 3),
        "targetSoc": round(request.desired_soc, 3),
        "minimumSoc": round(request.minimum_soc, 3),
        "capacityKwh": round(request.capacity_kwh, 1),
        "maxChargeKw": round(request.max_charge_kw, 1),
        "chargeKw": round(charge_kw, 1),
        "driveSpeedKmh": drive_speed,
    }


def render_html(
    data: dict[str, object],
    station_backdrop_filename: str = "",
    city_backdrop_filename: str = "",
) -> str:
    payload = json.dumps(data, separators=(",", ":"))
    station_backdrop_url = station_backdrop_filename or STATION_BACKDROP_ASSET.name
    city_stage_background = (
        f'linear-gradient(180deg, rgba(6, 12, 18, 0.08), rgba(6, 12, 18, 0.22)), url("{city_backdrop_filename}") center / 100% 100% no-repeat, #101310'
        if city_backdrop_filename
        else "#101310"
    )
    has_city_backdrop = "true" if city_backdrop_filename else "false"
    template = """<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Solar EV Distributed Charging - Cinematic Demo</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #111411;
      --panel: #191d1a;
      --panel-2: #20251f;
      --line: #343b34;
      --ink: #f4f7f5;
      --muted: #aab4ad;
      --solar: #f6c84c;
      --ev: #4fd1c5;
      --green: #38b26d;
      --red: #e6534f;
      --amber: #ff9f43;
      --grid: #8d79ff;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; width: 100%; height: 100%; overflow: hidden; background: var(--bg); color: var(--ink); font-family: Inter, Segoe UI, Arial, sans-serif; }
    body { letter-spacing: 0; }
    .app { height: 100vh; display: grid; grid-template-rows: 74px 1fr 116px; background: radial-gradient(circle at 50% -20%, rgba(246, 200, 76, 0.10), transparent 30%), var(--bg); }
    .topbar { display: grid; grid-template-columns: 1.1fr auto 1.1fr; align-items: center; gap: 18px; padding: 14px 22px; border-bottom: 1px solid var(--line); background: rgba(17, 20, 17, 0.94); }
    .brand { min-width: 0; }
    .brand h1 { margin: 0; font-size: 22px; line-height: 1.05; font-weight: 800; letter-spacing: 0; }
    .brand p { margin: 6px 0 0; color: var(--muted); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .status-pill { justify-self: center; display: flex; align-items: center; gap: 10px; min-width: 420px; padding: 10px 14px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); }
    .pulse-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--solar); box-shadow: 0 0 18px var(--solar); }
    .scene-label { font-size: 12px; color: var(--muted); text-transform: uppercase; font-weight: 700; }
    .scene-headline { font-size: 13px; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .controls { justify-self: end; display: flex; align-items: center; gap: 8px; }
    button { height: 36px; border: 1px solid var(--line); color: var(--ink); background: var(--panel-2); border-radius: 8px; padding: 0 12px; font-weight: 700; cursor: pointer; }
    button:hover { border-color: var(--ev); }
    button.active { border-color: var(--solar); color: var(--solar); box-shadow: 0 0 0 1px rgba(246, 200, 76, 0.24) inset; }
    .danger-button.active { border-color: var(--red); color: #ffd6d3; box-shadow: 0 0 0 1px rgba(230, 83, 79, 0.36) inset, 0 0 22px rgba(230, 83, 79, 0.18); }
    .icon-button { width: 38px; padding: 0; font-size: 16px; }
    .main { display: grid; grid-template-columns: 310px minmax(420px, 1fr) 350px; min-height: 0; }
    .side { border-right: 1px solid var(--line); background: rgba(25, 29, 26, 0.72); padding: 16px; overflow: hidden; }
    .right { border-right: 0; border-left: 1px solid var(--line); }
    .section-title { color: var(--muted); font-size: 11px; font-weight: 800; text-transform: uppercase; margin-bottom: 10px; }
    .metric-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .metric { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px; min-height: 74px; }
    .metric strong { display: block; font-size: 24px; line-height: 1; }
    .metric span { display: block; margin-top: 8px; font-size: 11px; color: var(--muted); }
    .story { margin-top: 14px; padding: 14px; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; min-height: 170px; }
    .story h2 { margin: 0 0 10px; font-size: 20px; line-height: 1.12; }
    .story p { margin: 0; color: var(--muted); line-height: 1.45; font-size: 13px; }
    .evidence { display: grid; gap: 8px; margin-top: 12px; }
    .evidence-row { display: grid; grid-template-columns: 86px 1fr; gap: 8px; align-items: center; font-size: 12px; color: var(--muted); }
    .bar-track { height: 10px; background: #0f120f; border-radius: 999px; overflow: hidden; border: 1px solid #2d342e; }
    .bar-fill { height: 100%; width: 0%; background: var(--green); border-radius: 999px; transition: width 180ms linear; }
    .stage-wrap { position: relative; min-width: 0; min-height: 0; overflow: hidden; background: __CITY_STAGE_BACKGROUND__; }
    .stage-wrap:fullscreen { width: 100vw; height: 100vh; background: __CITY_STAGE_BACKGROUND__; }
    .stage-wrap:fullscreen canvas { width: 100vw; height: 100vh; }
    .stage-wrap:fullscreen .hud,
    .stage-wrap:fullscreen .inspector { display: none; }
    body.map-only .app { grid-template-rows: 0 1fr 0; }
    body.map-only .topbar,
    body.map-only .side,
    body.map-only .timeline,
    body.map-only .hud,
    body.map-only .inspector,
    body.map-only .map-focus-btn { display: none; }
    body.map-only .main { grid-template-columns: 1fr; height: 100vh; }
    body.map-only .stage-wrap { width: 100vw; height: 100vh; }
    body.map-only .map-focus-caption { top: 18px; left: 22px; color: rgba(244,247,245,0.76); text-shadow: 0 2px 10px rgba(0,0,0,0.42); }
    .stage-wrap.station-detail { position: fixed; inset: 0; z-index: 20; width: 100vw; height: 100vh; background-color: #101310; background-image: linear-gradient(180deg, rgba(4, 13, 13, 0.16), rgba(2, 8, 7, 0.42)), url("__STATION_BACKDROP_URL__"); background-position: center, center 40%; background-size: cover, 92% auto; background-repeat: no-repeat; }
    .stage-wrap.station-detail canvas { width: 100vw; height: 100vh; }
    .stage-wrap.station-detail .hud,
    .stage-wrap.station-detail .inspector { display: none; }
    .stage-wrap.station-detail .map-focus-btn,
    .stage-wrap.station-detail .map-focus-caption { display: none; }
    canvas { position: absolute; inset: 0; display: block; width: 100%; height: 100%; }
    .map-focus-btn { position: absolute; top: 18px; left: 18px; z-index: 3; height: 36px; border-color: rgba(79, 209, 197, 0.45); background: rgba(17, 20, 17, 0.74); backdrop-filter: blur(8px); }
    .map-focus-caption { position: absolute; left: 18px; top: 62px; z-index: 3; color: rgba(244,247,245,0.72); font-size: 11px; pointer-events: none; text-transform: uppercase; font-weight: 800; }
    .station-exit-btn { display: none; position: absolute; top: 18px; right: 18px; z-index: 4; height: 38px; border-color: rgba(246, 200, 76, 0.55); background: rgba(17, 20, 17, 0.82); backdrop-filter: blur(8px); }
    .stage-wrap.station-detail .station-exit-btn { display: block; }
    .hud { position: absolute; left: 18px; right: 18px; bottom: 16px; display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; pointer-events: none; }
    .hud-item { border: 1px solid rgba(244, 247, 245, 0.12); background: rgba(17, 20, 17, 0.68); border-radius: 8px; padding: 10px; backdrop-filter: blur(6px); }
    .hud-item b { font-size: 12px; color: var(--muted); }
    .hud-item div { margin-top: 6px; font-size: 18px; font-weight: 800; }
    .inspector { position: absolute; top: 18px; right: 18px; width: 318px; border: 1px solid rgba(244, 247, 245, 0.14); background: rgba(17, 20, 17, 0.78); border-radius: 8px; padding: 13px; backdrop-filter: blur(8px); box-shadow: 0 18px 48px rgba(0, 0, 0, 0.25); }
    .inspector-title { display: flex; justify-content: space-between; gap: 10px; align-items: baseline; font-size: 12px; color: var(--muted); text-transform: uppercase; font-weight: 800; }
    .inspector-title strong { color: var(--ink); font-size: 15px; text-transform: none; }
    .inspect-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 11px; }
    .inspect-cell { min-height: 55px; border: 1px solid rgba(244, 247, 245, 0.10); background: rgba(32, 37, 31, 0.78); border-radius: 8px; padding: 9px; }
    .inspect-cell b { display: block; font-size: 17px; line-height: 1; }
    .inspect-cell span { display: block; margin-top: 7px; color: var(--muted); font-size: 11px; }
    .inspect-wide { grid-column: 1 / -1; }
    .soc-track { height: 9px; border-radius: 999px; background: #0f120f; border: 1px solid #2d342e; overflow: hidden; margin-top: 9px; }
    .soc-fill { height: 100%; background: var(--ev); width: 0%; }
    .comparison { display: grid; gap: 9px; }
    .policy-row { display: grid; grid-template-columns: 118px 1fr 42px; gap: 8px; align-items: center; font-size: 12px; }
    .policy-label { color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .mini-note { color: var(--muted); font-size: 12px; line-height: 1.45; margin-top: 14px; }
    .event-feed { margin-top: 14px; height: 210px; overflow: hidden; display: grid; gap: 7px; align-content: start; }
    .event { display: grid; grid-template-columns: 8px 1fr; gap: 9px; align-items: start; font-size: 12px; color: var(--muted); }
    .event-mark { width: 8px; height: 8px; margin-top: 4px; border-radius: 50%; background: var(--ev); }
    .event strong { color: var(--ink); }
    .timeline { display: grid; grid-template-columns: 260px 1fr 270px; gap: 16px; padding: 14px 22px 18px; border-top: 1px solid var(--line); background: rgba(17, 20, 17, 0.96); }
    .clock { display: grid; grid-template-columns: 72px 1fr; gap: 14px; align-items: center; }
    .clock-face { width: 66px; height: 66px; border: 2px solid var(--solar); border-radius: 50%; display: grid; place-items: center; font-size: 15px; font-weight: 800; color: var(--solar); }
    .clock-copy b { display: block; font-size: 13px; }
    .clock-copy span { display: block; margin-top: 5px; color: var(--muted); font-size: 12px; }
    .rail { position: relative; align-self: center; height: 56px; }
    .rail-line { position: absolute; left: 0; right: 0; top: 27px; height: 2px; background: var(--line); }
    .scene-chip { position: absolute; top: 7px; transform: translateX(-50%); min-width: 96px; height: 40px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); color: var(--muted); display: grid; place-items: center; font-size: 11px; font-weight: 800; text-align: center; padding: 0 8px; cursor: pointer; }
    .scene-chip.active { color: var(--ink); border-color: var(--solar); box-shadow: 0 0 0 1px rgba(246, 200, 76, 0.28) inset; }
    .playhead { position: absolute; top: 2px; width: 3px; height: 52px; background: var(--solar); box-shadow: 0 0 18px rgba(246, 200, 76, 0.8); }
    input[type="range"] { width: 100%; accent-color: var(--solar); }
    .rec { align-self: center; display: grid; grid-template-columns: 1fr; gap: 7px; font-size: 12px; color: var(--muted); }
    .rec b { color: var(--ink); font-size: 13px; }
    @media (max-width: 1050px) {
      .main { grid-template-columns: 250px 1fr; }
      .right { display: none; }
      .inspector { width: 290px; }
      .status-pill { min-width: 320px; }
      .timeline { grid-template-columns: 220px 1fr; }
      .rec { display: none; }
    }
  </style>
</head>
<body>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <h1>Solar EV Distributed Charging</h1>
        <p>Simulation distribuee: V-ASSIST, S-ACA-PD-EDF, R-DCC, TRUST-EV</p>
      </div>
      <div class="status-pill">
        <div class="pulse-dot"></div>
        <div>
          <div class="scene-label" id="sceneLabel">Scene</div>
          <div class="scene-headline" id="sceneHeadline">Loading simulation</div>
        </div>
      </div>
      <div class="controls">
        <button class="icon-button" id="playBtn" title="Play or pause">II</button>
        <button id="speedBtn" title="Change speed">1.0x</button>
        <button id="jumpBtn" title="Jump to security stress">Security</button>
        <button class="danger-button" id="crisisBtn" title="Trigger live grid and cyber stress">Stress Event</button>
        <button id="compareBtn" title="Split-screen baseline versus proposed policy">Compare</button>
        <button id="tourBtn" title="Automatic executive demo camera">Demo Tour</button>
        <button id="fullBtn" title="Fullscreen">App Full</button>
        <button id="mapFullBtn" title="Fullscreen central map only">Map Full</button>
      </div>
    </header>
    <main class="main">
      <aside class="side">
        <div class="section-title">Live evidence</div>
        <div class="metric-grid">
          <div class="metric"><strong id="mAccepted">0</strong><span>EV accepted</span></div>
          <div class="metric"><strong id="mBlocked">0</strong><span>Attacks blocked</span></div>
          <div class="metric"><strong id="mRejected">0</strong><span>Admission rejected</span></div>
          <div class="metric"><strong id="mGrid">0.0</strong><span>Grid kWh in scene</span></div>
        </div>
        <div class="story">
          <h2 id="storyTitle">Distributed charging under solar constraints</h2>
          <p id="storyText">The visual demo follows connected EV requests through station selection, admission, queueing, trust checks and energy accounting.</p>
          <div class="evidence">
            <div class="evidence-row"><span id="metricA">--</span><div class="bar-track"><div class="bar-fill" id="barA"></div></div></div>
            <div class="evidence-row"><span id="metricB">--</span><div class="bar-track"><div class="bar-fill" id="barB"></div></div></div>
          </div>
        </div>
      </aside>
      <section class="stage-wrap">
        <canvas id="stage"></canvas>
        <button class="map-focus-btn" id="mapFocusBtn" title="Fullscreen central animation only">Map Full</button>
        <button class="station-exit-btn" id="stationExitBtn" title="Back to city view">City View</button>
        <div class="map-focus-caption">Barcelona-style smart EV district</div>
        <div class="inspector" id="inspector"></div>
        <div class="hud">
          <div class="hud-item"><b>Policy</b><div>V-ASSIST + S-ACA-PD-EDF</div></div>
          <div class="hud-item"><b>Energy</b><div id="hudEnergy">PV/BESS active</div></div>
          <div class="hud-item"><b>Security</b><div id="hudSecurity">TRUST-EV online</div></div>
          <div class="hud-item"><b>Protocol</b><div id="hudProtocol">330 runs evidence</div></div>
        </div>
      </section>
      <aside class="side right">
        <div class="section-title">Policy comparison</div>
        <div class="comparison" id="comparison"></div>
        <p class="mini-note" id="rightNote">Bars are generated from the same deterministic experiment suite as the Markdown report. Lower rejection, deadline miss, grid use and attack success are better.</p>
        <div class="section-title" style="margin-top: 18px;">Event feed</div>
        <div class="event-feed" id="eventFeed"></div>
      </aside>
    </main>
    <footer class="timeline">
      <div class="clock">
        <div class="clock-face" id="clockFace">00s</div>
        <div class="clock-copy"><b id="clockTitle">Cinematic run</b><span id="clockSub">Auto-play timeline for screen recording</span></div>
      </div>
      <div class="rail" id="rail">
        <div class="rail-line"></div>
        <div class="playhead" id="playhead"></div>
      </div>
      <div class="rec">
        <b>Recording mode</b>
        <input id="scrub" type="range" min="0" max="118" step="0.1" value="0">
        <span>Tip: press Full, then record the window in 16:9.</span>
      </div>
    </footer>
  </div>
  <script id="demoData" type="application/json">__DEMO_DATA__</script>
  <script>
    const data = JSON.parse(document.getElementById('demoData').textContent);
    const HAS_CITY_BACKDROP = __HAS_CITY_BACKDROP__;
    const canvas = document.getElementById('stage');
    const ctx = canvas.getContext('2d');
    const state = { t: 0, playing: true, speed: 1, last: performance.now(), selected: null, stationFocus: null, crisisMode: false, crisisStart: 0, compareMode: false, tourMode: false, tourStart: 0, mapOnly: false, hitRegions: [] };
    window.__demoData = data;
    window.__demoState = state;
    const colors = data.palette;
    const ROAD_X = [0.5, 2.4, 4.6, 6.8, 8.9, 11.3];
    const ROAD_Y = [0.6, 2.7, 4.8, 7.0, 9.2, 11.2];
    const MAP_X_ANCHORS = [
      [0.5, 0.058],
      [2.4, 0.217],
      [4.6, 0.396],
      [6.8, 0.581],
      [8.9, 0.753],
      [11.3, 0.947]
    ];
    const MAP_Y_ANCHORS = [
      [0.6, 0.903],
      [2.7, 0.744],
      [4.8, 0.579],
      [7.0, 0.415],
      [9.2, 0.245],
      [11.2, 0.086]
    ];
    const sceneById = Object.fromEntries(data.scenes.map(s => [s.id, s]));
    const stationsById = Object.fromEntries(data.stations.map(s => [s.id, s]));
    const playBtn = document.getElementById('playBtn');
    const speedBtn = document.getElementById('speedBtn');
    const crisisBtn = document.getElementById('crisisBtn');
    const compareBtn = document.getElementById('compareBtn');
    const tourBtn = document.getElementById('tourBtn');
    const scrub = document.getElementById('scrub');
    const rail = document.getElementById('rail');
    const playhead = document.getElementById('playhead');
    const inspector = document.getElementById('inspector');
    const stageWrap = document.querySelector('.stage-wrap');
    const stationExitBtn = document.getElementById('stationExitBtn');

    function resize() {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
      canvas.width = Math.floor(rect.width * dpr);
      canvas.height = Math.floor(rect.height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    function ensureCanvasSize() {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
      const targetW = Math.floor(rect.width * dpr);
      const targetH = Math.floor(rect.height * dpr);
      if (targetW > 0 && targetH > 0 && (canvas.width !== targetW || canvas.height !== targetH)) {
        resize();
      }
      return rect;
    }
    window.addEventListener('resize', resize);
    resize();

    function xy(point) {
      const rect = canvas.getBoundingClientRect();
      return [
        mapValueToPct(point[0], MAP_X_ANCHORS) * rect.width,
        mapValueToPct(point[1], MAP_Y_ANCHORS) * rect.height
      ];
    }

    function mapValueToPct(value, anchors) {
      if (value <= anchors[0][0]) return interpolateAnchor(value, anchors[0], anchors[1]);
      for (let i = 0; i < anchors.length - 1; i++) {
        const left = anchors[i];
        const right = anchors[i + 1];
        if (value >= left[0] && value <= right[0]) return interpolateAnchor(value, left, right);
      }
      return interpolateAnchor(value, anchors[anchors.length - 2], anchors[anchors.length - 1]);
    }

    function interpolateAnchor(value, left, right) {
      const span = right[0] - left[0] || 1;
      const t = (value - left[0]) / span;
      return left[1] + (right[1] - left[1]) * t;
    }

    function currentScene() {
      return data.scenes.find(s => state.t >= s.start && state.t < s.end) || data.scenes[data.scenes.length - 1];
    }

    function summariesFor(sceneId) {
      return data.summaries.filter(row => row.scenario === sceneId);
    }

    function coordToScreen(xCoord, yCoord) {
      return xy([xCoord, yCoord]);
    }

    function drawChamferedBlock(x1, y1, x2, y2, color, stroke) {
      const [left, bottom] = coordToScreen(x1, y1);
      const [right, top] = coordToScreen(x2, y2);
      const x = Math.min(left, right);
      const y = Math.min(top, bottom);
      const w = Math.abs(right - left);
      const h = Math.abs(bottom - top);
      const cut = Math.min(w, h) * 0.14;
      ctx.beginPath();
      ctx.moveTo(x + cut, y);
      ctx.lineTo(x + w - cut, y);
      ctx.lineTo(x + w, y + cut);
      ctx.lineTo(x + w, y + h - cut);
      ctx.lineTo(x + w - cut, y + h);
      ctx.lineTo(x + cut, y + h);
      ctx.lineTo(x, y + h - cut);
      ctx.lineTo(x, y + cut);
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.fill();
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    function drawCityMap(w, h, scene) {
      if (HAS_CITY_BACKDROP) {
        ctx.fillStyle = 'rgba(4, 10, 16, 0.06)';
        ctx.fillRect(0, 0, w, h);
        ctx.fillStyle = 'rgba(255,255,255,0.030)';
        for (let i = 0; i < 70; i++) {
          const x = (i * 97) % Math.max(w, 1);
          const y = (i * 53) % Math.max(h, 1);
          ctx.beginPath(); ctx.arc(x, y, 1.2 + (i % 3), 0, Math.PI * 2); ctx.fill();
        }
        return;
      }
      ctx.fillStyle = '#24372f';
      ctx.fillRect(0, 0, w, h);
      ctx.fillStyle = 'rgba(255,255,255,0.035)';
      for (let i = 0; i < 90; i++) {
        const x = (i * 97) % Math.max(w, 1);
        const y = (i * 53) % Math.max(h, 1);
        ctx.beginPath(); ctx.arc(x, y, 1.5 + (i % 3), 0, Math.PI * 2); ctx.fill();
      }

      const blockPad = 0.16;
      for (let xi = 0; xi < ROAD_X.length - 1; xi++) {
        for (let yi = 0; yi < ROAD_Y.length - 1; yi++) {
          const x1 = ROAD_X[xi] + blockPad;
          const x2 = ROAD_X[xi + 1] - blockPad;
          const y1 = ROAD_Y[yi] + blockPad;
          const y2 = ROAD_Y[yi + 1] - blockPad;
          const parkish = ((xi * 5 + yi * 7) % 8) === 0;
          drawChamferedBlock(x1, y1, x2, y2, parkish ? '#315f43' : '#2f5142', parkish ? 'rgba(117,205,117,0.20)' : 'rgba(255,255,255,0.10)');
          if (!parkish && ((xi + yi) % 3 === 0)) {
            const [px, py] = coordToScreen((x1 + x2) / 2, (y1 + y2) / 2);
            ctx.fillStyle = 'rgba(127,188,133,0.12)';
            roundedRect(px - 24, py - 9, 48, 18, 5);
            ctx.fill();
          }
        }
      }

      ctx.lineCap = 'round';
      function drawUrbanRoad(x1, y1, x2, y2, major = false) {
        const [sx, sy] = coordToScreen(x1, y1);
        const [ex, ey] = coordToScreen(x2, y2);
        ctx.strokeStyle = 'rgba(240,246,241,0.34)';
        ctx.lineWidth = major ? 42 : 34;
        ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(ex, ey); ctx.stroke();
        ctx.strokeStyle = major ? '#505f5d' : '#5c6865';
        ctx.lineWidth = major ? 31 : 25;
        ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(ex, ey); ctx.stroke();
        ctx.strokeStyle = 'rgba(255,255,255,0.76)';
        ctx.lineWidth = major ? 2.3 : 1.8;
        ctx.setLineDash(major ? [12, 18] : [8, 16]);
        ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(ex, ey); ctx.stroke();
        ctx.setLineDash([]);
      }
      ROAD_Y.forEach(y => drawUrbanRoad(0.08, y, 11.92, y, y === 4.8 || y === 7.0));
      ROAD_X.forEach(x => drawUrbanRoad(x, 0.08, x, 11.92, x === 4.6 || x === 8.9));

      drawCityDetails();
      drawSpecialBuildings();

    }

    function buildingRect(x1, y1, x2, y2) {
      const [left, bottom] = coordToScreen(x1, y1);
      const [right, top] = coordToScreen(x2, y2);
      return {
        x: Math.min(left, right),
        y: Math.min(top, bottom),
        w: Math.abs(right - left),
        h: Math.abs(bottom - top)
      };
    }

    function drawLabeledBuilding(x1, y1, x2, y2, label, fill, accent, drawIcon) {
      const box = buildingRect(x1, y1, x2, y2);
      ctx.save();
      const roofInset = Math.min(box.w, box.h) * 0.11;
      ctx.fillStyle = 'rgba(0,0,0,0.20)';
      roundedRect(box.x + 6, box.y + 7, box.w, box.h, 6);
      ctx.fill();
      roundedRect(box.x, box.y, box.w, box.h, 6);
      ctx.fillStyle = fill;
      ctx.fill();
      ctx.strokeStyle = accent;
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.fillStyle = 'rgba(255,255,255,0.18)';
      ctx.beginPath();
      ctx.moveTo(box.x + roofInset, box.y + roofInset);
      ctx.lineTo(box.x + box.w - roofInset, box.y + roofInset);
      ctx.lineTo(box.x + box.w - roofInset * 1.8, box.y + box.h * 0.34);
      ctx.lineTo(box.x + roofInset * 1.8, box.y + box.h * 0.34);
      ctx.closePath();
      ctx.fill();
      if (drawIcon) drawIcon(box, accent);
      ctx.fillStyle = '#ffffff';
      ctx.font = '800 11px Segoe UI, Arial';
      ctx.textAlign = 'center';
      ctx.fillText(label, box.x + box.w / 2, box.y + box.h - 10);
      ctx.restore();
    }

    function drawSpecialBuildings() {
      drawCampusPlot(0.66, 9.82, 1.62, 10.94);
      drawLabeledBuilding(0.78, 10.0, 1.50, 10.78, 'HOSPITAL', '#ed3340', '#b81f2b', (box, accent) => {
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 4;
        ctx.beginPath();
        ctx.moveTo(box.x + box.w / 2, box.y + box.h * 0.27);
        ctx.lineTo(box.x + box.w / 2, box.y + box.h * 0.72);
        ctx.moveTo(box.x + box.w / 2 - box.w * 0.18, box.y + box.h * 0.50);
        ctx.lineTo(box.x + box.w / 2 + box.w * 0.18, box.y + box.h * 0.50);
        ctx.stroke();
      });
      drawCampusPlot(0.72, 0.86, 1.96, 2.28);
      drawLabeledBuilding(0.88, 1.05, 1.78, 2.03, 'SCHOOL', '#ffb51c', '#d38100', (box, accent) => {
        ctx.fillStyle = '#d7f3ff';
        for (let i = 0; i < 2; i++) {
          ctx.fillRect(box.x + box.w * (0.24 + i * 0.25), box.y + box.h * 0.28, box.w * 0.14, box.h * 0.26);
        }
      });
      drawCampusPlot(4.86, 9.48, 6.54, 10.88);
      drawLabeledBuilding(5.02, 9.72, 6.38, 10.62, 'UNIVERSITY', '#43bfb3', '#187e78', (box, accent) => {
        ctx.fillStyle = '#1b827e';
        ctx.beginPath();
        ctx.moveTo(box.x + box.w / 2, box.y + box.h * 0.23);
        ctx.lineTo(box.x + box.w / 2 - box.w * 0.18, box.y + box.h * 0.46);
        ctx.lineTo(box.x + box.w / 2 + box.w * 0.18, box.y + box.h * 0.46);
        ctx.closePath();
        ctx.fill();
        ctx.fillStyle = '#bff4f2';
        ctx.fillRect(box.x + box.w * 0.33, box.y + box.h * 0.54, box.w * 0.34, box.h * 0.12);
      });
      drawCampusPlot(7.22, 9.48, 8.58, 10.78);
      drawLabeledBuilding(7.42, 9.66, 8.38, 10.42, 'POLICE', '#2e7cca', '#185996', (box, accent) => {
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(box.x + box.w / 2, box.y + box.h * 0.42, Math.min(box.w, box.h) * 0.16, 0, Math.PI * 2);
        ctx.stroke();
      });
      drawCampusPlot(0.72, 5.12, 2.06, 6.56);
      drawLabeledBuilding(0.88, 5.34, 1.90, 6.28, 'THEATRE', '#fa544d', '#c33129', (box, accent) => {
        ctx.strokeStyle = '#ffd7a1';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(box.x + box.w / 2 - box.w * 0.09, box.y + box.h * 0.42, Math.min(box.w, box.h) * 0.11, 0, Math.PI * 2);
        ctx.arc(box.x + box.w / 2 + box.w * 0.09, box.y + box.h * 0.42, Math.min(box.w, box.h) * 0.11, 0, Math.PI * 2);
        ctx.stroke();
      });
      drawCampusPlot(9.18, 0.88, 11.02, 2.34);
      const stadium = buildingRect(9.32, 1.08, 10.88, 2.12);
      ctx.save();
      ctx.fillStyle = 'rgba(0,0,0,0.18)';
      roundedRect(stadium.x + 5, stadium.y + 6, stadium.w, stadium.h, 10);
      ctx.fill();
      ctx.fillStyle = '#f7921e';
      roundedRect(stadium.x, stadium.y, stadium.w, stadium.h, 10);
      ctx.fill();
      ctx.strokeStyle = '#ce6b00';
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 7;
      ctx.beginPath();
      ctx.ellipse(stadium.x + stadium.w / 2, stadium.y + stadium.h / 2 - 4, stadium.w * 0.33, stadium.h * 0.28, 0, 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillStyle = '#56c85c';
      ctx.beginPath();
      ctx.ellipse(stadium.x + stadium.w / 2, stadium.y + stadium.h / 2 - 4, stadium.w * 0.22, stadium.h * 0.18, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#ffffff';
      ctx.font = '800 11px Segoe UI, Arial';
      ctx.textAlign = 'center';
      ctx.fillText('STADIUM', stadium.x + stadium.w / 2, stadium.y + stadium.h - 10);
      ctx.restore();
    }

    function drawCampusPlot(x1, y1, x2, y2) {
      const box = buildingRect(x1, y1, x2, y2);
      ctx.save();
      roundedRect(box.x, box.y, box.w, box.h, 5);
      ctx.fillStyle = '#74cf62';
      ctx.fill();
      ctx.strokeStyle = 'rgba(255,255,255,0.72)';
      ctx.lineWidth = 3;
      ctx.stroke();
      ctx.strokeStyle = 'rgba(255,255,255,0.50)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(box.x + box.w * 0.12, box.y + box.h * 0.86);
      ctx.lineTo(box.x + box.w * 0.88, box.y + box.h * 0.86);
      ctx.moveTo(box.x + box.w * 0.16, box.y + box.h * 0.16);
      ctx.lineTo(box.x + box.w * 0.16, box.y + box.h * 0.84);
      ctx.stroke();
      ctx.restore();
    }

    function drawTreeAt(xCoord, yCoord, size = 1) {
      const [x, y] = coordToScreen(xCoord, yCoord);
      ctx.fillStyle = '#8bd046';
      ctx.beginPath(); ctx.arc(x, y, 7 * size, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = '#5f9d2f';
      ctx.beginPath(); ctx.arc(x - 3 * size, y - 3 * size, 4 * size, 0, Math.PI * 2); ctx.fill();
    }

    function drawPool(x1, y1, x2, y2) {
      const box = buildingRect(x1, y1, x2, y2);
      ctx.fillStyle = '#ffffff';
      roundedRect(box.x, box.y, box.w, box.h, 5);
      ctx.fill();
      ctx.fillStyle = '#36aeea';
      roundedRect(box.x + 5, box.y + 5, box.w - 10, box.h - 10, 4);
      ctx.fill();
      ctx.fillStyle = 'rgba(255,255,255,0.55)';
      ctx.fillRect(box.x + 18, box.y + 10, box.w * 0.36, 4);
    }

    function drawCrosswalk(xCoord, yCoord, horizontal = true) {
      const [x, y] = coordToScreen(xCoord, yCoord);
      ctx.fillStyle = 'rgba(255,255,255,0.9)';
      for (let i = -3; i <= 3; i++) {
        if (horizontal) {
          ctx.fillRect(x + i * 7, y - 16, 3, 32);
        } else {
          ctx.fillRect(x - 16, y + i * 7, 32, 3);
        }
      }
    }

    function drawCityDetails() {
      drawPool(3.0, 7.55, 3.78, 8.22);
      drawPool(7.35, 7.58, 8.18, 8.18);
      drawPool(10.08, 7.72, 10.92, 8.28);
      drawPool(3.05, 3.32, 3.86, 3.84);
      [[0.92, 7.82], [1.22, 7.48], [2.98, 8.28], [3.84, 5.76], [4.08, 5.54], [7.38, 2.18], [7.64, 1.92], [8.02, 6.16], [10.62, 6.36], [10.58, 8.24], [1.42, 1.55], [2.02, 1.22], [5.12, 8.0], [5.46, 7.76], [9.62, 3.38], [10.72, 3.72]].forEach(([x, y], index) => drawTreeAt(x, y, 0.82 + (index % 3) * 0.12));
      [[2.4, 4.8, true], [4.6, 4.8, false], [6.8, 4.8, false], [8.9, 4.8, false], [4.6, 7.0, false], [8.9, 7.0, false], [2.4, 7.0, true], [6.8, 9.2, true], [4.6, 2.7, false], [8.9, 2.7, false]].forEach(([x, y, h]) => drawCrosswalk(x, y, h));
    }

    function parkingLayout(station) {
      const [x, y] = xy([station.x, station.y]);
      const slots = [];
      const count = Math.max(1, station.parkingPlaces || station.sockets);
      const slotW = 22;
      const slotH = 38;
      const dir = station.y > 6 ? 1 : station.y < 3 ? -1 : station.x > 6 ? -1 : 1;
      const top = y + dir * 34 - (dir < 0 ? slotH : 0);
      const left = x - (count * slotW) / 2;
      const chargerY = dir > 0 ? top - 12 : top + slotH + 12;
      for (let i = 0; i < count; i++) {
        slots.push({
          x: left + i * slotW + slotW / 2,
          y: top + slotH / 2,
          angle: dir > 0 ? Math.PI / 2 : -Math.PI / 2,
          chargerX: left + i * slotW + slotW / 2,
          chargerY,
          slotX: left + i * slotW,
          slotY: top,
          slotW,
          slotH
        });
      }
      return {
        x,
        y,
        dir,
        slots,
        lotX: left - 18,
        lotY: Math.min(top, chargerY - 18) - 12,
        lotW: count * slotW + 36,
        lotH: Math.abs(chargerY - top) + slotH + 38,
        chargerY
      };
    }

    function slotForVehicle(vehicle) {
      const station = stationsById[vehicle.station] || data.stations[0];
      const layout = parkingLayout(station);
      const digits = vehicle.id.split('').reduce((sum, char) => sum + char.charCodeAt(0), 0);
      return layout.slots[digits % layout.slots.length];
    }

    function roundedRect(x, y, w, h, r) {
      const radius = Math.min(r, w / 2, h / 2);
      ctx.beginPath();
      ctx.moveTo(x + radius, y);
      ctx.lineTo(x + w - radius, y);
      ctx.quadraticCurveTo(x + w, y, x + w, y + radius);
      ctx.lineTo(x + w, y + h - radius);
      ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h);
      ctx.lineTo(x + radius, y + h);
      ctx.quadraticCurveTo(x, y + h, x, y + h - radius);
      ctx.lineTo(x, y + radius);
      ctx.quadraticCurveTo(x, y, x + radius, y);
      ctx.closePath();
    }

    function drawLightning(x, y, scale, color) {
      ctx.save();
      ctx.translate(x, y);
      ctx.scale(scale, scale);
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.moveTo(2, -13);
      ctx.lineTo(-6, 1);
      ctx.lineTo(0, 1);
      ctx.lineTo(-3, 13);
      ctx.lineTo(8, -2);
      ctx.lineTo(2, -2);
      ctx.closePath();
      ctx.fill();
      ctx.restore();
    }

    function drawChargeCable(fromX, fromY, toX, toY, active = true, width = 3) {
      ctx.save();
      ctx.strokeStyle = active ? '#202020' : 'rgba(32,32,32,0.58)';
      ctx.lineWidth = width;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.beginPath();
      ctx.moveTo(fromX, fromY);
      const side = toX >= fromX ? 1 : -1;
      const stemY = fromY + (toY - fromY) * 0.42;
      const plugX = toX + side * 12;
      ctx.lineTo(fromX + side * 20, fromY);
      ctx.quadraticCurveTo(fromX + side * 26, fromY, fromX + side * 26, stemY);
      ctx.lineTo(plugX, stemY);
      ctx.quadraticCurveTo(toX + side * 18, stemY, plugX, toY - 4);
      ctx.stroke();
      ctx.strokeStyle = active ? '#25aee8' : 'rgba(255,255,255,0.32)';
      ctx.lineWidth = Math.max(1, width * 0.33);
      ctx.beginPath();
      ctx.moveTo(fromX, fromY);
      ctx.lineTo(fromX + side * 20, fromY);
      ctx.quadraticCurveTo(fromX + side * 26, fromY, fromX + side * 26, stemY);
      ctx.lineTo(plugX, stemY);
      ctx.quadraticCurveTo(toX + side * 18, stemY, plugX, toY - 4);
      ctx.stroke();
      ctx.restore();
    }

    function drawChargerBox(x, y, scale, active, label = '') {
      ctx.save();
      ctx.translate(x, y);
      ctx.scale(scale, scale);
      ctx.shadowColor = 'rgba(0,0,0,0.18)';
      ctx.shadowBlur = 10;
      ctx.fillStyle = '#cfcfcf';
      roundedRect(-49, -19, 98, 38, 11);
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.fillStyle = '#f6f6f6';
      roundedRect(-41, -21, 82, 36, 8);
      ctx.fill();
      ctx.fillStyle = 'rgba(0,0,0,0.08)';
      ctx.fillRect(-13, -21, 26, 36);
      ctx.fillStyle = active ? '#1faee8' : '#8fd1ed';
      roundedRect(-30, 13, 60, 7, 2);
      ctx.fill();
      ctx.beginPath();
      ctx.moveTo(-24, 13);
      ctx.lineTo(-18, 23);
      ctx.lineTo(18, 23);
      ctx.lineTo(24, 13);
      ctx.closePath();
      ctx.fillStyle = active ? '#2cb8f0' : '#a9d9ec';
      ctx.fill();
      drawLightning(0, -2, 0.55, active ? '#159ad7' : '#6aaec9');
      if (label) {
        ctx.fillStyle = '#303532';
        ctx.font = '800 12px Segoe UI, Arial';
        ctx.textAlign = 'center';
        ctx.fillText(label, 0, 35);
      }
      ctx.restore();
    }

    function drawSocBadge(x, y, soc, radius, showText = true) {
      const start = -Math.PI / 2;
      const end = start + Math.PI * 2 * clamp(soc, 0, 1);
      ctx.save();
      ctx.fillStyle = '#3b3d3d';
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = 'rgba(255,255,255,0.48)';
      ctx.lineWidth = Math.max(2, radius * 0.12);
      ctx.beginPath();
      ctx.arc(x, y, radius * 0.78, 0, Math.PI * 2);
      ctx.stroke();
      ctx.strokeStyle = socColor(soc);
      ctx.lineWidth = Math.max(3, radius * 0.16);
      ctx.beginPath();
      ctx.arc(x, y, radius * 0.78, start, end);
      ctx.stroke();
      drawLightning(x, y - radius * 0.28, radius / 30, '#ffffff');
      if (showText) {
        ctx.fillStyle = '#ffffff';
        ctx.font = `800 ${Math.max(8, radius * 0.58)}px Segoe UI, Arial`;
        ctx.textAlign = 'center';
        ctx.fillText(`${Math.round(soc * 100)}%`, x, y + radius * 0.33);
      }
      ctx.restore();
    }

    function drawTopDownEV(x, y, angle, vehicle, snapshot, selected, scale = 1, showBadge = false) {
      const color = socColor(snapshot.soc);
      const w = 24 * scale;
      const h = 48 * scale;
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(angle);
      ctx.shadowColor = 'rgba(0,0,0,0.30)';
      ctx.shadowBlur = 10 * scale;
      ctx.fillStyle = 'rgba(0,0,0,0.22)';
      roundedRect(-w * 0.34 + 5 * scale, -h * 0.48 + 8 * scale, w * 0.84, h * 0.96, 12 * scale);
      ctx.fill();
      ctx.fillStyle = 'rgba(0,0,0,0.16)';
      ctx.beginPath();
      ctx.moveTo(-w * 0.64, -h * 0.08);
      ctx.lineTo(-w * 0.48, -h * 0.20);
      ctx.lineTo(-w * 0.48, h * 0.05);
      ctx.closePath();
      ctx.fill();
      ctx.beginPath();
      ctx.moveTo(w * 0.64, -h * 0.08);
      ctx.lineTo(w * 0.48, -h * 0.20);
      ctx.lineTo(w * 0.48, h * 0.05);
      ctx.closePath();
      ctx.fill();
      ctx.fillStyle = color;
      roundedRect(-w / 2, -h / 2, w, h, 12 * scale);
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.fillStyle = 'rgba(255,255,255,0.18)';
      ctx.beginPath();
      ctx.moveTo(-w * 0.34, -h * 0.43);
      ctx.lineTo(w * 0.34, -h * 0.43);
      ctx.lineTo(w * 0.43, -h * 0.14);
      ctx.lineTo(-w * 0.43, -h * 0.14);
      ctx.closePath();
      ctx.fill();
      ctx.fillStyle = '#242424';
      roundedRect(-w * 0.34, -h * 0.24, w * 0.68, h * 0.31, 9 * scale);
      ctx.fill();
      ctx.fillStyle = '#333737';
      roundedRect(-w * 0.32, h * 0.11, w * 0.64, h * 0.30, 8 * scale);
      ctx.fill();
      ctx.fillStyle = 'rgba(0,0,0,0.45)';
      ctx.fillRect(-w * 0.57, -h * 0.20, 4 * scale, h * 0.20);
      ctx.fillRect(w * 0.41, -h * 0.20, 4 * scale, h * 0.20);
      ctx.fillStyle = '#191919';
      ctx.fillRect(-w * 0.56, -h * 0.37, 4 * scale, h * 0.18);
      ctx.fillRect(w * 0.40, -h * 0.37, 4 * scale, h * 0.18);
      if (showBadge) drawSocBadge(0, h * 0.02, snapshot.soc, Math.max(9, 13 * scale), scale > 0.9);
      ctx.restore();
      if (selected) {
        ctx.strokeStyle = colors.solar;
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        ctx.arc(x, y, Math.max(22, 29 * scale), 0, Math.PI * 2);
        ctx.stroke();
      }
    }

    function drawParkingLot(station, layout, storage, selected) {
      ctx.save();
      roundedRect(layout.lotX, layout.lotY, layout.lotW, layout.lotH, 8);
      ctx.fillStyle = '#d7d7d5';
      ctx.fill();
      ctx.strokeStyle = selected ? '#ffec6b' : 'rgba(255,255,255,0.75)';
      ctx.lineWidth = selected ? 2.4 : 1;
      ctx.stroke();

      ctx.fillStyle = 'rgba(238,238,238,0.95)';
      roundedRect(layout.lotX + 8, layout.lotY + 7, layout.lotW - 16, 16, 4);
      ctx.fill();
      ctx.fillStyle = '#2ab3ef';
      roundedRect(layout.lotX + 22, layout.lotY + 19, layout.lotW - 44, 4, 2);
      ctx.fill();
      ctx.strokeStyle = 'rgba(255,255,255,0.92)';
      ctx.lineWidth = 1;
      ctx.stroke();
      for (let i = 0; i < layout.slots.length; i++) {
        const slot = layout.slots[i];
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 3;
        ctx.strokeRect(slot.slotX, slot.slotY, slot.slotW, slot.slotH);
        ctx.fillStyle = 'rgba(158,158,158,0.24)';
        roundedRect(slot.x - slot.slotW * 0.28, slot.slotY + (layout.dir > 0 ? 8 : slot.slotH - 13), slot.slotW * 0.56, 5, 2);
        ctx.fill();
        const posts = station.sockets > layout.slots.length && i === 0 ? station.sockets : i < station.sockets ? 1 : 0;
        for (let post = 0; post < posts; post++) {
          const offset = (post - (posts - 1) / 2) * 14;
          drawCharger(slot.x + offset, layout.chargerY, station, post + i);
        }
        if (i >= station.sockets) {
          ctx.fillStyle = 'rgba(38,174,96,0.26)';
          roundedRect(slot.x - 7, slot.y - 14, 14, 28, 4);
          ctx.fill();
        }
      }

      const gaugeX = layout.lotX + 10;
      const gaugeY = layout.lotY + layout.lotH - 12;
      ctx.fillStyle = '#59615d';
      roundedRect(gaugeX, gaugeY, layout.lotW - 20, 6, 3);
      ctx.fill();
      ctx.fillStyle = '#ffe65c';
      roundedRect(gaugeX, gaugeY, (layout.lotW - 20) * storage, 6, 3);
      ctx.fill();
      ctx.restore();
    }

    function drawCharger(x, y, station, index) {
      const active = data.vehicles.some(v => v.station === station.id && v.status === 'accepted' && v.start < state.t && v.start + v.duration + 18 > state.t);
      drawChargerBox(x, y, 0.43, active, String(index + 1));
    }

    function drawEVCar(x, y, angle, vehicle, snapshot, selected) {
      drawTopDownEV(x, y, angle, vehicle, snapshot, selected, 0.62, selected || snapshot.chargeKw > 0);
      if (vehicle.status === 'blocked' || vehicle.status === 'rejected') {
        ctx.strokeStyle = vehicle.status === 'blocked' ? colors.red : colors.amber;
        ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(x, y, 18, 0, Math.PI * 2); ctx.stroke();
      }
      if (snapshot.chargeKw > 0) {
        const slot = slotForVehicle(vehicle);
        drawChargeCable(slot.chargerX || slot.x, slot.chargerY || slot.y, x, y, true, 2.2);
      }
    }

    function vehiclePoint(vehicle) {
      const local = (state.t - vehicle.start) / vehicle.duration;
      if (local < -0.15) return null;
      const driveEnd = vehicle.status === 'accepted' ? vehicle.start + vehicle.duration * 0.76 : vehicle.start + vehicle.duration;
      const lingerEnd = vehicle.status === 'accepted' ? vehicle.start + vehicle.duration + 22 : vehicle.start + vehicle.duration + 1.2;
      if (state.t > lingerEnd) return null;
      if (vehicle.status === 'accepted' && state.t > driveEnd) {
        const slot = slotForVehicle(vehicle);
        return { x: slot.x, y: slot.y, angle: slot.angle, parked: true };
      }
      const progress = Math.max(0, Math.min(1, (state.t - vehicle.start) / Math.max(driveEnd - vehicle.start, 0.1)));
      const position = routePosition(vehicle, progress);
      return { x: position.x, y: position.y, angle: position.angle, parked: false, progress };
    }

    function vehicleSnapshot(vehicle) {
      const point = vehiclePoint(vehicle);
      const driveEnd = vehicle.status === 'accepted' ? vehicle.start + vehicle.duration * 0.76 : vehicle.start + vehicle.duration;
      const driveProgress = Math.max(0, Math.min(1, (state.t - vehicle.start) / Math.max(driveEnd - vehicle.start, 0.1)));
      const chargeProgress = vehicle.status === 'accepted'
        ? Math.max(0, Math.min(1, (state.t - driveEnd) / 22))
        : 0;
      const idleProgress = vehicle.status === 'accepted'
        ? Math.max(0, Math.min(1, (state.t - driveEnd + 4) / 8))
        : Math.max(0, Math.min(1, (state.t - vehicle.start) / Math.max(vehicle.duration, 0.1)));
      const driveLoss = Math.min(0.055, (0.012 + vehicle.driveSpeedKmh / 1150) * driveProgress);
      const idleLoss = Math.min(0.012, 0.006 * idleProgress);
      const arrivalSoc = Math.max(0.03, vehicle.soc - driveLoss - idleLoss);
      const targetAfterTravel = Math.max(arrivalSoc, vehicle.targetSoc);
      const soc = arrivalSoc + (targetAfterTravel - arrivalSoc) * chargeProgress;
      const driving = point && !point.parked && state.t >= vehicle.start;
      const chargeKw = vehicle.status === 'accepted' && chargeProgress > 0 && chargeProgress < 1
        ? vehicle.chargeKw * (0.86 + Math.sin(state.t * 2.1) * 0.06)
        : 0;
      const motorKw = driving ? Math.max(7, vehicle.driveSpeedKmh * 0.38 + Math.sin(state.t * 2.8) * 2.4) : 0;
      const drivenEnergyKwh = vehicle.capacityKwh * Math.max(0, vehicle.soc - arrivalSoc);
      const chargedEnergyKwh = vehicle.capacityKwh * Math.max(0, soc - arrivalSoc);
      const rangeKm = Math.max(0, soc * vehicle.capacityKwh / 0.18);
      const statusLabel = vehicle.status === 'blocked'
        ? 'blocked'
        : vehicle.status === 'rejected'
          ? 'rejected'
          : chargeKw > 0
            ? 'charging'
            : driving
              ? 'driving'
              : vehicle.wait > 0
                ? 'queued'
                : 'connected';
      return {
        point,
        soc: Math.max(0, Math.min(1, soc)),
        speedKmh: driving ? vehicle.driveSpeedKmh : 0,
        chargeKw: Math.max(0, chargeKw),
        motorKw: Math.max(0, motorKw),
        netBatteryKw: Math.max(0, chargeKw) - Math.max(0, motorKw),
        drivenEnergyKwh,
        chargedEnergyKwh,
        rangeKm,
        driveProgress,
        statusLabel,
        chargeProgress
      };
    }

    function mixColor(a, b, t) {
      const value = Math.max(0, Math.min(1, t));
      const left = a.match(/[0-9a-f]{2}/gi).map(x => parseInt(x, 16));
      const right = b.match(/[0-9a-f]{2}/gi).map(x => parseInt(x, 16));
      const mixed = left.map((channel, index) => Math.round(channel + (right[index] - channel) * value));
      return `rgb(${mixed[0]}, ${mixed[1]}, ${mixed[2]})`;
    }

    function socColor(soc) {
      const value = Math.max(0, Math.min(1, soc));
      if (value < 0.5) {
        return mixColor('#e6534f', '#38b26d', value / 0.5);
      }
      return mixColor('#38b26d', '#3b82f6', (value - 0.5) / 0.5);
    }

    function stationSnapshot(station, scene) {
      const accepted = data.vehicles.filter(v => v.station === station.id && v.status === 'accepted' && v.start <= state.t && v.start + v.duration + 22 > state.t);
      const charging = accepted.filter(v => vehicleSnapshot(v).chargeKw > 0);
      const storageWave = Math.sin(state.t * 0.7 + station.x) * 0.05;
      const bessPct = Math.max(0.08, Math.min(1, station.storagePct - charging.length * 0.025 + storageWave));
      const pvKw = scene.id === 'sensitivity_no_grid' ? 34 + Math.sin(state.t * 0.45) * 5 : 24 + Math.sin(state.t * 0.42) * 4;
      const gridKw = scene.id === 'sensitivity_no_grid' ? 0 : Math.max(0, charging.length * 3.2 - 1.8);
      const active = Math.min(charging.length, station.sockets);
      return { active, connected: accepted.length, queue: Math.max(0, accepted.length - station.sockets), bessPct, pvKw, gridKw };
    }

    function clamp(value, min, max) {
      return Math.max(min, Math.min(max, value));
    }

    function drawTextFit(text, x, y, maxWidth, align = 'left') {
      const value = String(text);
      ctx.textAlign = align;
      if (ctx.measureText(value).width <= maxWidth) {
        ctx.fillText(value, x, y);
        return;
      }
      let trimmed = value;
      while (trimmed.length > 4 && ctx.measureText(`${trimmed}...`).width > maxWidth) {
        trimmed = trimmed.slice(0, -1);
      }
      ctx.fillText(`${trimmed}...`, x, y);
    }

    function vehicleDriveEnd(vehicle) {
      return vehicle.status === 'accepted' ? vehicle.start + vehicle.duration * 0.76 : vehicle.start + vehicle.duration;
    }

    function stationVehiclePhase(vehicle, snapshot) {
      if (vehicle.status === 'blocked') return { key: 'blocked', label: 'Bloquee', color: '#e6534f' };
      if (vehicle.status === 'rejected') return { key: 'rejected', label: 'Refusee', color: '#ff9f43' };
      if (state.t < vehicle.start) return { key: 'incoming', label: 'Approche', color: '#36aeea' };
      if (state.t < vehicleDriveEnd(vehicle)) return { key: 'incoming', label: 'Arrivee', color: '#36aeea' };
      if (snapshot.chargeKw > 0) return { key: 'charging', label: 'En charge', color: socColor(snapshot.soc) };
      if (snapshot.chargeProgress >= 1) return { key: 'complete', label: 'Terminee', color: '#3b82f6' };
      if (vehicle.wait > 0) return { key: 'waiting', label: 'En attente', color: '#f6c84c' };
      return { key: 'connected', label: 'Connectee', color: '#4fd1c5' };
    }

    function stationDetailVehicles(station) {
      const sameStation = data.vehicles.filter(v => v.station === station.id);
      const scene = currentScene();
      const live = sameStation.filter(v => v.start <= state.t && v.start + v.duration + 28 >= state.t);
      const sceneWindow = sameStation.filter(v => v.scene === scene.id && v.start <= state.t + 20 && v.start + v.duration + 34 >= state.t - 6);
      const next = sameStation.filter(v => v.start > state.t).sort((a, b) => a.start - b.start);
      const recent = sameStation.filter(v => v.start <= state.t && v.start >= state.t - 20).sort((a, b) => b.start - a.start);
      const merged = [];
      [...live, ...sceneWindow, ...next, ...recent].forEach(vehicle => {
        if (!merged.some(existing => existing.id === vehicle.id)) merged.push(vehicle);
      });
      const targetCount = Math.max(8, station.parkingPlaces + 5, station.sockets + 5);
      return merged
        .map(vehicle => {
          const snapshot = vehicleSnapshot(vehicle);
          const phase = stationVehiclePhase(vehicle, snapshot);
          const rank = { charging: 0, waiting: 1, connected: 2, incoming: 3, complete: 4, rejected: 5, blocked: 6 }[phase.key] ?? 7;
          return { vehicle, snapshot, phase, rank };
        })
        .sort((a, b) => (a.rank - b.rank) || (Math.abs(a.vehicle.start - state.t) - Math.abs(b.vehicle.start - state.t)))
        .slice(0, targetCount);
    }

    function stationDetailStats(station, scene) {
      const vehicles = stationDetailVehicles(station);
      const snapshot = stationSnapshot(station, scene);
      const outputKw = vehicles.reduce((sum, item) => sum + item.snapshot.chargeKw, 0);
      const charging = vehicles.filter(item => item.phase.key === 'charging').length;
      const waiting = vehicles.filter(item => item.phase.key === 'waiting' || item.phase.key === 'incoming').length;
      const avgSoc = vehicles.length ? vehicles.reduce((sum, item) => sum + item.snapshot.soc, 0) / vehicles.length : 0;
      return { vehicles, snapshot, outputKw, charging, waiting, avgSoc };
    }

    function drawStationMetric(x, y, w, h, label, value, color, subtext = '') {
      ctx.save();
      roundedRect(x, y, w, h, 8);
      ctx.fillStyle = 'rgba(18, 25, 21, 0.88)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(255,255,255,0.14)';
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.fillStyle = color;
      ctx.font = '800 25px Segoe UI, Arial';
      drawTextFit(value, x + 16, y + 34, w - 32);
      ctx.fillStyle = 'rgba(244,247,245,0.74)';
      ctx.font = '800 11px Segoe UI, Arial';
      drawTextFit(label, x + 16, y + 56, w - 32);
      if (subtext) {
        ctx.fillStyle = 'rgba(170,180,173,0.86)';
        ctx.font = '11px Segoe UI, Arial';
        drawTextFit(subtext, x + 16, y + h - 12, w - 32);
      }
      ctx.restore();
    }

    function drawDetailEVCar(x, y, angle, item, selected, scale = 1.9) {
      const { vehicle, snapshot, phase } = item;
      drawTopDownEV(x, y, angle, vehicle, snapshot, selected, scale, true);
      ctx.fillStyle = phase.color;
      roundedRect(x - 44, y + 30 * scale, 88, 21, 7);
      ctx.fill();
      ctx.fillStyle = phase.key === 'charging' || phase.key === 'complete' ? '#07130f' : '#ffffff';
      ctx.font = '800 10px Segoe UI, Arial';
      drawTextFit(phase.label, x, y + 43 * scale, 70, 'center');
      state.hitRegions.push({ type: 'vehicle', id: vehicle.id, x, y, r: Math.max(42, 30 * scale) });
    }

    function drawStationDetailBackdrop(w, h) {
      ctx.clearRect(0, 0, w, h);
      const wash = ctx.createLinearGradient(0, 0, 0, h);
      wash.addColorStop(0, 'rgba(4, 18, 18, 0.12)');
      wash.addColorStop(0.52, 'rgba(7, 18, 15, 0.22)');
      wash.addColorStop(1, 'rgba(3, 8, 7, 0.52)');
      ctx.fillStyle = wash;
      ctx.fillRect(0, 0, w, h);
      ctx.strokeStyle = 'rgba(79,209,197,0.16)';
      ctx.lineWidth = 1;
      for (let x = -40; x < w; x += 112) {
        ctx.beginPath();
        ctx.moveTo(x, h * 0.54);
        ctx.lineTo(x + w * 0.07, h);
        ctx.stroke();
      }
    }

    function drawStationDetail(scene, station, w, h) {
      const detail = stationDetailStats(station, scene);
      const compact = w < 1150;
      const leftW = compact ? 246 : clamp(w * 0.22, 300, 370);
      const rightW = compact ? 306 : clamp(w * 0.28, 360, 450);
      const headerH = 82;
      const gap = compact ? 18 : 26;
      const lotX = leftW + gap;
      const lotY = headerH + 34;
      const lotW = Math.max(320, w - leftW - rightW - gap * 3);
      const lotH = Math.max(390, h - lotY - 34);

      drawStationDetailBackdrop(w, h);

      ctx.save();
      roundedRect(24, 18, w - 48, 64, 12);
      ctx.fillStyle = 'rgba(18, 25, 21, 0.90)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(255,255,255,0.16)';
      ctx.stroke();
      ctx.fillStyle = '#ffffff';
      ctx.font = '800 22px Segoe UI, Arial';
      drawTextFit(`${station.label} charging station`, 44, 47, w * 0.36);
      ctx.fillStyle = 'rgba(170,180,173,0.92)';
      ctx.font = '12px Segoe UI, Arial';
      drawTextFit(`${station.parkingPlaces} parking places | ${station.sockets} chargers | live microgrid dispatch`, 44, 66, w * 0.42);
      ctx.fillStyle = colors.solar;
      ctx.font = '800 14px Segoe UI, Arial';
      drawTextFit(scene.focus, w - 230, 56, 190, 'right');
      ctx.restore();

      const metricX = 24;
      const metricW = leftW - 44;
      const metricH = 82;
      drawStationMetric(metricX, 112, metricW, metricH, 'kW sortie vers EV', `${detail.outputKw.toFixed(1)} kW`, colors.ev, `${detail.charging} voitures en charge`);
      drawStationMetric(metricX, 204, metricW, metricH, 'voitures station', `${detail.vehicles.length}`, colors.solar, `${detail.waiting} en attente ou approche`);
      drawStationMetric(metricX, 296, metricW, metricH, 'BESS station', `${Math.round(detail.snapshot.bessPct * 100)}%`, '#ffe65c', `${station.reserveKwh} kWh reserve`);
      drawStationMetric(metricX, 388, metricW, metricH, 'PV local', `${detail.snapshot.pvKw.toFixed(1)} kW`, '#9be052', scene.id === 'sensitivity_no_grid' ? 'mode autonome no-grid' : `${detail.snapshot.gridKw.toFixed(1)} kW grid`);
      drawStationMetric(metricX, 480, metricW, metricH, 'SOC moyen EV', `${Math.round(detail.avgSoc * 100)}%`, socColor(detail.avgSoc), 'rouge -> vert -> bleu');

      roundedRect(lotX, lotY, lotW, lotH, 12);
      ctx.fillStyle = 'rgba(216, 216, 214, 0.84)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(255,255,255,0.82)';
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.fillStyle = '#858b89';
      roundedRect(lotX + 24, lotY + lotH - 92, lotW - 48, 48, 10);
      ctx.fill();
      ctx.strokeStyle = 'rgba(255,255,255,0.9)';
      ctx.setLineDash([12, 14]);
      ctx.beginPath();
      ctx.moveTo(lotX + 40, lotY + lotH - 68);
      ctx.lineTo(lotX + lotW - 40, lotY + lotH - 68);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.fillStyle = '#f4f4f1';
      roundedRect(lotX + 34, lotY + 24, lotW - 68, 42, 8);
      ctx.fill();
      ctx.strokeStyle = 'rgba(255,255,255,0.7)';
      ctx.stroke();
      ctx.fillStyle = '#1faee8';
      roundedRect(lotX + 64, lotY + 58, lotW - 128, 5, 2);
      ctx.fill();
      ctx.fillStyle = '#233220';
      ctx.font = '800 13px Segoe UI, Arial';
      drawTextFit('PV canopy + charger controller', lotX + 52, lotY + 51, lotW - 104);

      const bayCount = Math.max(1, station.parkingPlaces || station.sockets);
      const rows = bayCount > 4 ? 2 : 1;
      const cols = Math.ceil(bayCount / rows);
      const bayGap = compact ? 12 : 18;
      const bayW = clamp((lotW - 110 - bayGap * (cols - 1)) / cols, compact ? 82 : 112, compact ? 128 : 158);
      const bayH = clamp((lotH * 0.58 - bayGap * (rows - 1)) / rows, compact ? 132 : 154, compact ? 164 : 196);
      const startX = lotX + 46;
      const startY = lotY + 104;
      const bayItems = detail.vehicles.filter(item => item.vehicle.status === 'accepted').concat(detail.vehicles.filter(item => item.vehicle.status !== 'accepted'));
      const bayCenters = [];
      for (let i = 0; i < bayCount; i++) {
        const row = Math.floor(i / cols);
        const col = i % cols;
        const x = startX + col * (bayW + bayGap);
        const y = startY + row * (bayH + bayGap);
        const item = bayItems[i];
        bayCenters.push({ x: x + bayW / 2, y: y + bayH * 0.62, item });
        roundedRect(x, y, bayW, bayH, 6);
        ctx.fillStyle = i < station.sockets ? '#dededd' : '#c9cdca';
        ctx.fill();
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 3;
        ctx.stroke();
        ctx.fillStyle = 'rgba(160,160,160,0.24)';
        roundedRect(x + bayW * 0.25, y + bayH * 0.16, bayW * 0.50, 8, 3);
        ctx.fill();
        if (i < station.sockets) {
          drawChargerBox(x + bayW / 2, y + 18, Math.min(1.16, bayW / 96), true, String(i + 1));
        } else {
          ctx.fillStyle = 'rgba(255,255,255,0.64)';
          ctx.font = '800 15px Segoe UI, Arial';
          drawTextFit('P', x + bayW / 2, y + 28, 28, 'center');
        }
        if (item) {
          if (i < station.sockets && item.snapshot.chargeKw > 0) {
            drawChargeCable(x + bayW / 2 + 40, y + 20, x + bayW / 2, y + bayH * 0.64, true, 5);
          }
          drawDetailEVCar(x + bayW / 2, y + bayH * 0.64, 0, item, state.selected && state.selected.type === 'vehicle' && state.selected.id === item.vehicle.id, compact ? 1.55 : 1.9);
        }
      }
      drawStationEnergyFlows(lotX, lotY, lotW, lotH, detail, bayCenters);

      const queueVehicles = bayItems.slice(bayCount);
      const queueOffset = Math.max(lotW - 144, (startX - lotX) + cols * (bayW + bayGap) + 8);
      const queueX = lotX + clamp(queueOffset, 46, lotW - 124);
      const queueY = lotY + 108;
      const queueH = Math.max(150, lotH - 240);
      roundedRect(queueX, queueY, 96, queueH, 10);
      ctx.fillStyle = 'rgba(45, 52, 48, 0.70)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(255,255,255,0.22)';
      ctx.stroke();
      ctx.fillStyle = 'rgba(244,247,245,0.72)';
      ctx.font = '800 11px Segoe UI, Arial';
      drawTextFit('QUEUE', queueX + 48, queueY + 22, 82, 'center');
      queueVehicles.slice(0, 5).forEach((item, index) => {
        const carY = queueY + 54 + index * 58;
        drawDetailEVCar(queueX + 48, carY, 0, item, state.selected && state.selected.type === 'vehicle' && state.selected.id === item.vehicle.id, compact ? 1.05 : 1.18);
      });

      const gaugeX = lotX + 38;
      const gaugeY = lotY + lotH - 30;
      ctx.fillStyle = 'rgba(16,19,16,0.8)';
      roundedRect(gaugeX, gaugeY, lotW - 76, 12, 6);
      ctx.fill();
      ctx.fillStyle = '#ffe65c';
      roundedRect(gaugeX, gaugeY, (lotW - 76) * detail.snapshot.bessPct, 12, 6);
      ctx.fill();

      const panelX = w - rightW - 24;
      const panelY = 112;
      const panelH = h - panelY - 34;
      roundedRect(panelX, panelY, rightW, panelH, 12);
      ctx.fillStyle = 'rgba(18, 25, 21, 0.90)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(255,255,255,0.16)';
      ctx.stroke();
      ctx.fillStyle = '#ffffff';
      ctx.font = '800 17px Segoe UI, Arial';
      drawTextFit('Voitures detaillees', panelX + 18, panelY + 30, rightW - 36);
      ctx.fillStyle = 'rgba(170,180,173,0.92)';
      ctx.font = '12px Segoe UI, Arial';
      drawTextFit('Clique une voiture pour figer sa telemetrie live', panelX + 18, panelY + 50, rightW - 36);
      const maxCards = Math.max(4, Math.min(detail.vehicles.length, Math.floor((panelH - 78) / 86)));
      const cardH = Math.min(94, Math.max(76, (panelH - 82) / Math.max(maxCards, 1) - 8));
      detail.vehicles.slice(0, maxCards).forEach((item, index) => {
        drawStationVehicleCard(item, panelX + 16, panelY + 72 + index * (cardH + 8), rightW - 32, cardH);
      });
      if (detail.vehicles.length > maxCards) {
        ctx.fillStyle = 'rgba(170,180,173,0.88)';
        ctx.font = '800 12px Segoe UI, Arial';
        drawTextFit(`+ ${detail.vehicles.length - maxCards} autres EV sur la station`, panelX + 22, panelY + panelH - 14, rightW - 44);
      }
    }

    function drawStationVehicleCard(item, x, y, w, h) {
      const selected = state.selected && state.selected.type === 'vehicle' && state.selected.id === item.vehicle.id;
      roundedRect(x, y, w, h, 8);
      ctx.fillStyle = selected ? 'rgba(246,200,76,0.20)' : 'rgba(32,37,31,0.88)';
      ctx.fill();
      ctx.strokeStyle = selected ? colors.solar : 'rgba(255,255,255,0.12)';
      ctx.lineWidth = selected ? 2 : 1;
      ctx.stroke();
      ctx.fillStyle = item.phase.color;
      roundedRect(x + 10, y + 12, 7, h - 24, 4);
      ctx.fill();
      ctx.fillStyle = '#ffffff';
      ctx.font = '800 13px Segoe UI, Arial';
      drawTextFit(item.vehicle.id.replace('ev-', 'EV ').replace('ghost-', 'GHOST '), x + 26, y + 24, w * 0.42);
      ctx.fillStyle = item.phase.color;
      ctx.font = '800 12px Segoe UI, Arial';
      drawTextFit(item.phase.label, x + w - 16, y + 24, w * 0.36, 'right');
      ctx.fillStyle = 'rgba(170,180,173,0.92)';
      ctx.font = '11px Segoe UI, Arial';
      drawTextFit(`${Math.round(item.snapshot.soc * 100)}% SOC | ${item.snapshot.chargeKw.toFixed(1)} kW charge | ${item.snapshot.speedKmh.toFixed(0)} km/h`, x + 26, y + 45, w - 42);
      ctx.fillStyle = 'rgba(16,19,16,0.92)';
      roundedRect(x + 26, y + h - 20, w - 42, 8, 4);
      ctx.fill();
      ctx.fillStyle = socColor(item.snapshot.soc);
      roundedRect(x + 26, y + h - 20, (w - 42) * item.snapshot.soc, 8, 4);
      ctx.fill();
      state.hitRegions.push({ type: 'vehicle', id: item.vehicle.id, x, y, w, h });
    }

    function drawBackground(w, h, scene) {
      ctx.clearRect(0, 0, w, h);
      drawCityMap(w, h, scene);
      const sunX = w - 86, sunY = 72;
      ctx.fillStyle = colors.solar;
      ctx.beginPath(); ctx.arc(sunX, sunY, 22 + Math.sin(state.t * 2.4) * 2, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = 'rgba(246,200,76,0.25)';
      for (let i = 0; i < 3; i++) {
        ctx.beginPath(); ctx.arc(sunX, sunY, 38 + i * 18 + (state.t * 8) % 18, 0, Math.PI * 2); ctx.stroke();
      }
      if (!state.mapOnly) {
        ctx.fillStyle = 'rgba(244,247,245,0.72)';
        ctx.font = '700 12px Segoe UI, Arial';
        ctx.fillText(scene.focus, 26, 32);
      }
    }

    function drawCityStationHub(station, layout, storage, selected, scene) {
      const x = layout.x;
      const y = layout.y;
      const dir = layout.dir;
      const stationSnap = stationSnapshot(station, scene);
      if (HAS_CITY_BACKDROP) {
        ctx.save();
        ctx.strokeStyle = selected ? colors.solar : 'rgba(246,200,76,0.88)';
        ctx.lineWidth = selected ? 4 : 3;
        ctx.beginPath();
        ctx.arc(x, y, selected ? 31 : 25, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * storage);
        ctx.stroke();
        ctx.fillStyle = 'rgba(10,18,18,0.90)';
        ctx.beginPath();
        ctx.arc(x, y, 15, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = selected ? colors.solar : colors.ev;
        roundedRect(x - 6, y - 9, 12, 18, 5);
        ctx.fill();
        ctx.fillStyle = '#06110f';
        ctx.fillRect(x - 3, y - 3, 6, 3);
        ctx.fillStyle = 'rgba(10,18,18,0.72)';
        roundedRect(x - 52, y + (dir > 0 ? 28 : -46), 104, 24, 7);
        ctx.fill();
        ctx.fillStyle = '#ffffff';
        ctx.font = '800 10px Segoe UI, Arial';
        ctx.textAlign = 'center';
        ctx.fillText(`${stationSnap.active}/${station.sockets} charging`, x, y + (dir > 0 ? 43 : -31));
        ctx.fillStyle = 'rgba(233,242,236,0.76)';
        ctx.font = '9px Segoe UI, Arial';
        ctx.fillText(`BESS ${Math.round(stationSnap.bessPct * 100)}%`, x, y + (dir > 0 ? 54 : -20));
        ctx.restore();
        state.hitRegions.push({ type: 'station', id: station.id, x, y, r: 34 });
        return;
      }
      const canvasW = canvas.clientWidth || 1200;
      const canvasH = canvas.clientHeight || 720;
      const panelW = Math.min(136, Math.max(98, 72 + station.parkingPlaces * 7));
      const panelH = 68;
      const preferredX = x - panelW / 2 + (station.id === 'cs-east' ? -20 : 0);
      const preferredY = y + dir * 52 - (dir < 0 ? panelH : 0);
      const panelX = clamp(preferredX, 18, canvasW - panelW - 18);
      const panelY = clamp(preferredY, 66, canvasH - panelH - 74);

      ctx.save();
      ctx.shadowColor = 'rgba(0,0,0,0.28)';
      ctx.shadowBlur = 16;
      roundedRect(panelX, panelY, panelW, panelH, 8);
      ctx.fillStyle = 'rgba(227,231,226,0.84)';
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.strokeStyle = selected ? colors.solar : 'rgba(255,255,255,0.76)';
      ctx.lineWidth = selected ? 2.4 : 1.4;
      ctx.stroke();
      ctx.fillStyle = 'rgba(245,247,245,0.90)';
      roundedRect(panelX + 7, panelY + 7, panelW - 14, 16, 5);
      ctx.fill();
      ctx.fillStyle = '#24abe4';
      roundedRect(panelX + 18, panelY + 22, panelW - 36, 3, 2);
      ctx.fill();

      const previewSlots = Math.min(4, Math.max(2, station.sockets));
      const gap = 4;
      const slotW = (panelW - 20 - gap * (previewSlots - 1)) / previewSlots;
      const slotH = 30;
      const slotY = panelY + 30;
      const activeVehicles = data.vehicles
        .filter(v => v.station === station.id && v.status === 'accepted' && v.start <= state.t && v.start + v.duration + 24 >= state.t)
        .slice(0, previewSlots);
      for (let i = 0; i < previewSlots; i++) {
        const slotX = panelX + 10 + i * (slotW + gap);
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 2;
        ctx.strokeRect(slotX, slotY, slotW, slotH);
        drawChargerBox(slotX + slotW / 2, panelY + 17, 0.20, i < station.sockets, String(i + 1));
        const vehicle = activeVehicles[i];
        if (vehicle) {
          const snapshot = vehicleSnapshot(vehicle);
          const carX = slotX + slotW / 2;
          const carY = slotY + slotH / 2 + 4;
          if (snapshot.chargeKw > 0) {
            drawChargeCable(carX + 9, panelY + 17, carX, carY, true, 1.8);
          }
          drawTopDownEV(carX, carY, 0, vehicle, snapshot, false, 0.42, snapshot.chargeKw > 0);
        }
      }
      ctx.fillStyle = '#4c5350';
      roundedRect(panelX + 8, panelY + panelH - 8, panelW - 16, 5, 3);
      ctx.fill();
      ctx.fillStyle = colors.solar;
      roundedRect(panelX + 8, panelY + panelH - 8, (panelW - 16) * storage, 5, 3);
      ctx.fill();
      ctx.restore();

      ctx.save();
      ctx.strokeStyle = selected ? colors.solar : 'rgba(246,200,76,0.90)';
      ctx.lineWidth = selected ? 4 : 3;
      ctx.beginPath();
      ctx.arc(x, y, selected ? 31 : 25, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * storage);
      ctx.stroke();
      ctx.fillStyle = 'rgba(18,25,21,0.92)';
      ctx.beginPath();
      ctx.arc(x, y, 17, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = selected ? colors.solar : colors.ev;
      roundedRect(x - 7, y - 10, 14, 20, 5);
      ctx.fill();
      ctx.fillStyle = '#0d1411';
      ctx.fillRect(x - 4, y - 4, 8, 3);
      ctx.fillStyle = '#ffffff';
      ctx.font = '800 10px Segoe UI, Arial';
      ctx.textAlign = 'center';
      ctx.fillText(station.label, x, y + (dir > 0 ? 42 : -34));
      ctx.fillStyle = 'rgba(233,242,236,0.86)';
      ctx.font = '10px Segoe UI, Arial';
      ctx.fillText(`${stationSnap.active}/${station.sockets} charging | BESS ${Math.round(stationSnap.bessPct * 100)}%`, x, y + (dir > 0 ? 55 : -21));
      ctx.restore();

      state.hitRegions.push({ type: 'station', id: station.id, x, y, r: 34 });
      state.hitRegions.push({ type: 'station', id: station.id, x: panelX, y: panelY, w: panelW, h: panelH });
    }

    function drawStations(scene) {
      data.stations.forEach((station, index) => {
        const layout = parkingLayout(station);
        const phase = state.t * 0.8 + index;
        const storage = Math.max(0.16, Math.min(1, station.storagePct - 0.08 * Math.sin(phase)));
        const selected = state.selected && state.selected.type === 'station' && state.selected.id === station.id;
        drawCityStationHub(station, layout, storage, selected, scene);
      });
    }

    function vehicleHash(vehicle) {
      return vehicle.id.split('').reduce((sum, char) => sum + char.charCodeAt(0), 0);
    }

    function nearestRoad(value, roads) {
      return roads.reduce((best, road) => Math.abs(road - value) < Math.abs(best - value) ? road : best, roads[0]);
    }

    function snapRoadX(value) {
      return nearestRoad(value, ROAD_X);
    }

    function snapRoadY(value) {
      return nearestRoad(value, ROAD_Y);
    }

    function cityGate(vehicle) {
      const hash = vehicleHash(vehicle);
      const side = hash % 4;
      if (side === 0) return [ROAD_X[0], snapRoadY(vehicle.from[1])];
      if (side === 1) return [ROAD_X[ROAD_X.length - 1], snapRoadY(vehicle.from[1])];
      if (side === 2) return [snapRoadX(vehicle.from[0]), ROAD_Y[0]];
      return [snapRoadX(vehicle.from[0]), ROAD_Y[ROAD_Y.length - 1]];
    }

    function routeCoords(vehicle) {
      const start = cityGate(vehicle);
      const end = vehicle.to;
      const midX = snapRoadX((start[0] * 0.55) + (end[0] * 0.45));
      const midY = snapRoadY((start[1] * 0.45) + (end[1] * 0.55));
      return [start, [midX, start[1]], [midX, midY], [end[0], midY], end];
    }

    function routePixels(vehicle) {
      return routeCoords(vehicle).map(point => xy(point));
    }

    function routePosition(vehicle, progress) {
      const points = routePixels(vehicle);
      const lengths = [];
      let total = 0;
      for (let i = 0; i < points.length - 1; i++) {
        const length = Math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1]);
        lengths.push(length);
        total += length;
      }
      let remaining = Math.max(0, Math.min(1, progress)) * total;
      for (let i = 0; i < lengths.length; i++) {
        if (remaining <= lengths[i] || i === lengths.length - 1) {
          const a = points[i];
          const b = points[i + 1];
          const t = lengths[i] <= 0 ? 0 : remaining / lengths[i];
          const x = a[0] + (b[0] - a[0]) * t;
          const y = a[1] + (b[1] - a[1]) * t;
          return { x, y, angle: Math.atan2(b[1] - a[1], b[0] - a[0]) + Math.PI / 2, points };
        }
        remaining -= lengths[i];
      }
      const last = points[points.length - 1];
      return { x: last[0], y: last[1], angle: 0, points };
    }

    function drawRoadRoute(vehicle, progress, selected = false) {
      const position = routePosition(vehicle, progress);
      const points = position.points;
      const routeAlpha = selected ? 0.52 : state.crisisMode || state.compareMode || state.tourMode ? 0.22 : 0.14;
      ctx.strokeStyle = vehicle.status === 'blocked'
        ? `rgba(230,83,79,${selected ? 0.60 : 0.34})`
        : vehicle.status === 'rejected'
          ? `rgba(255,159,67,${selected ? 0.54 : 0.30})`
          : `rgba(79,209,197,${routeAlpha})`;
      ctx.lineWidth = selected ? 2.4 : vehicle.status === 'blocked' ? 2 : 1.2;
      ctx.beginPath();
      ctx.moveTo(points[0][0], points[0][1]);
      for (let i = 1; i < points.length; i++) {
        ctx.lineTo(points[i][0], points[i][1]);
      }
      ctx.stroke();
      return position;
    }

    function routePoint(vehicle, progress) {
      const position = routePosition(vehicle, progress);
      return [position.x, position.y];
    }

    function drawVehicles() {
      data.vehicles.forEach(vehicle => {
        const snapshot = vehicleSnapshot(vehicle);
        if (!snapshot.point) return;
        const p = Math.max(0, Math.min(1, (state.t - vehicle.start) / vehicle.duration));
        const [tx, ty] = xy(vehicle.to);
        const { x, y, angle } = snapshot.point;
        const selected = state.selected && state.selected.type === 'vehicle' && state.selected.id === vehicle.id;
        const isParked = Boolean(snapshot.point.parked);
        const shouldShowRoute = selected || vehicle.status !== 'accepted' || (!isParked && (state.crisisMode || state.compareMode || state.tourMode));
        if (shouldShowRoute) drawRoadRoute(vehicle, p, selected);
        if (isParked && vehicle.status === 'accepted' && !selected) return;
        drawEVCar(x, y, angle, vehicle, snapshot, selected);
        if (vehicle.status === 'blocked' && p > 0.72) {
          const pulse = (state.t * 5) % 1;
          ctx.strokeStyle = `rgba(230,83,79,${0.7 - pulse * 0.5})`;
          ctx.lineWidth = 3;
          ctx.beginPath(); ctx.arc(tx, ty, 18 + pulse * 26, 0, Math.PI * 2); ctx.stroke();
        }
        if (vehicle.status === 'accepted' && p > 0.82) {
          const pulse = (state.t * 4) % 1;
          ctx.strokeStyle = `rgba(56,178,109,${0.55 - pulse * 0.4})`;
          ctx.lineWidth = 3;
          ctx.beginPath(); ctx.arc(tx, ty, 16 + pulse * 20, 0, Math.PI * 2); ctx.stroke();
        }
        state.hitRegions.push({ type: 'vehicle', id: vehicle.id, x, y, r: 24 });
      });
    }

    function drawFlowPath(points, color, width, label = '') {
      if (points.length < 2) return;
      ctx.save();
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.globalAlpha = 0.70;
      ctx.beginPath();
      ctx.moveTo(points[0][0], points[0][1]);
      for (let i = 1; i < points.length; i++) ctx.lineTo(points[i][0], points[i][1]);
      ctx.stroke();
      ctx.globalAlpha = 1;
      const particleCount = Math.max(2, Math.round(width));
      for (let i = 0; i < particleCount; i++) {
        const t = (state.t * 0.42 + i / particleCount) % 1;
        const segment = Math.min(points.length - 2, Math.floor(t * (points.length - 1)));
        const local = (t * (points.length - 1)) - segment;
        const a = points[segment];
        const b = points[segment + 1];
        const x = a[0] + (b[0] - a[0]) * local;
        const y = a[1] + (b[1] - a[1]) * local;
        ctx.fillStyle = '#ffffff';
        ctx.beginPath(); ctx.arc(x, y, width * 0.85, 0, Math.PI * 2); ctx.fill();
      }
      if (label) {
        const mid = points[Math.floor(points.length / 2)];
        ctx.fillStyle = 'rgba(18,25,21,0.86)';
        roundedRect(mid[0] - 45, mid[1] - 18, 90, 26, 7);
        ctx.fill();
        ctx.fillStyle = '#ffffff';
        ctx.font = '800 11px Segoe UI, Arial';
        drawTextFit(label, mid[0], mid[1] - 1, 78, 'center');
      }
      ctx.restore();
    }

    function drawCityEnergyFlows(scene, w, h) {
      data.stations.forEach((station, index) => {
        const snap = stationSnapshot(station, scene);
        const [sx, sy] = xy([station.x, station.y]);
        const pvStart = [w - 86, 72];
        const bessStart = xy([station.x + (index % 2 ? 0.42 : -0.42), station.y + 0.58]);
        const flowKw = snap.active * 18 + snap.pvKw * 0.18;
        const width = clamp(flowKw / 18, 2.2, state.crisisMode ? 8 : 5);
        drawFlowPath([pvStart, [sx, pvStart[1]], [sx, sy]], 'rgba(246,200,76,0.66)', width, `${flowKw.toFixed(0)} kW`);
        drawFlowPath([bessStart, [sx + 20, sy - 24], [sx, sy]], 'rgba(79,209,197,0.56)', clamp(snap.bessPct * 5, 1.8, 4.5));
        if (scene.id !== 'sensitivity_no_grid') {
          const gridStart = xy([11.7, snap.gridKw > 2 ? station.y : 0.6]);
          drawFlowPath([gridStart, [sx + 32, gridStart[1]], [sx + 20, sy]], 'rgba(141,121,255,0.45)', clamp(snap.gridKw / 2.4, 1.2, 3.5));
        }
      });
    }

    function drawCrisisOverlay(w, h) {
      if (!state.crisisMode) return;
      const pulse = 0.45 + Math.sin(state.t * 8) * 0.18;
      ctx.save();
      ctx.strokeStyle = `rgba(230,83,79,${pulse})`;
      ctx.lineWidth = 5;
      ctx.setLineDash([18, 14]);
      ctx.strokeRect(18, 18, w - 36, h - 36);
      ctx.setLineDash([]);
      ctx.fillStyle = 'rgba(230,83,79,0.15)';
      ctx.fillRect(0, 0, w, h);
      ctx.fillStyle = 'rgba(18,25,21,0.92)';
      roundedRect(w / 2 - 205, 92, 410, 58, 10);
      ctx.fill();
      ctx.strokeStyle = 'rgba(230,83,79,0.78)';
      ctx.stroke();
      ctx.fillStyle = '#ffd6d3';
      ctx.font = '800 17px Segoe UI, Arial';
      drawTextFit('STRESS EVENT: demand spike + cyber probes', w / 2, 119, 360, 'center');
      ctx.fillStyle = 'rgba(255,255,255,0.78)';
      ctx.font = '12px Segoe UI, Arial';
      drawTextFit('TRUST-EV filters attacks while V-ASSIST redirects load', w / 2, 139, 360, 'center');
      data.stations.forEach(station => {
        const [x, y] = xy([station.x, station.y]);
        ctx.strokeStyle = `rgba(230,83,79,${0.70 - ((state.t * 1.7) % 1) * 0.35})`;
        ctx.lineWidth = 4;
        ctx.beginPath();
        ctx.arc(x, y, 46 + ((state.t * 28) % 22), 0, Math.PI * 2);
        ctx.stroke();
      });
      ctx.restore();
    }

    function drawPolicySplitOverlay(scene, w, h) {
      if (!state.compareMode || state.stationFocus) return;
      const stats = sceneStats(scene);
      ctx.save();
      ctx.fillStyle = 'rgba(230,83,79,0.14)';
      ctx.fillRect(0, 0, w / 2, h);
      ctx.fillStyle = 'rgba(56,178,109,0.12)';
      ctx.fillRect(w / 2, 0, w / 2, h);
      ctx.strokeStyle = 'rgba(255,255,255,0.90)';
      ctx.lineWidth = 3;
      ctx.setLineDash([10, 10]);
      ctx.beginPath(); ctx.moveTo(w / 2, 0); ctx.lineTo(w / 2, h); ctx.stroke();
      ctx.setLineDash([]);
      function labelPanel(x, title, sub, color) {
        roundedRect(x, 92, 250, 70, 9);
        ctx.fillStyle = 'rgba(18,25,21,0.90)';
        ctx.fill();
        ctx.strokeStyle = color;
        ctx.stroke();
        ctx.fillStyle = color;
        ctx.font = '800 18px Segoe UI, Arial';
        drawTextFit(title, x + 18, 120, 214);
        ctx.fillStyle = 'rgba(244,247,245,0.78)';
        ctx.font = '12px Segoe UI, Arial';
        drawTextFit(sub, x + 18, 143, 214);
      }
      labelPanel(28, 'Baseline FIFO', `rejects ${stats.rejected + 5} | queues +${Math.max(3, stats.rejected + 2)}`, colors.red);
      labelPanel(w - 278, 'Proposed policy', `accepted ${stats.accepted} | attacks blocked ${stats.blocked}`, colors.ev);
      const station = stationsById['cs-center'] || data.stations[0];
      const [cx, cy] = xy([station.x, station.y]);
      for (let i = 0; i < 7; i++) {
        ctx.fillStyle = i % 2 ? colors.red : colors.amber;
        roundedRect(cx - w * 0.23 + i * 22, cy + 80 + (i % 3) * 18, 18, 34, 5);
        ctx.fill();
      }
      ctx.restore();
    }

    function drawJourneyReplay(w, h) {
      if (!state.selected || state.selected.type !== 'vehicle') return;
      const vehicle = data.vehicles.find(v => v.id === state.selected.id);
      if (!vehicle) return;
      const snapshot = vehicleSnapshot(vehicle);
      const phase = stationVehiclePhase(vehicle, snapshot);
      const steps = [
        ['Request', state.t >= vehicle.start],
        ['Trust', vehicle.status !== 'blocked'],
        ['Station', vehicle.status === 'accepted'],
        ['Queue', vehicle.wait > 0 && state.t >= vehicleDriveEnd(vehicle)],
        ['Charge', snapshot.chargeKw > 0],
        ['Done', snapshot.chargeProgress >= 1]
      ];
      const panelW = Math.min(720, w - 72);
      const x = (w - panelW) / 2;
      const y = h - (state.stationFocus ? 118 : 154);
      ctx.save();
      roundedRect(x, y, panelW, 88, 11);
      ctx.fillStyle = 'rgba(18,25,21,0.92)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(255,255,255,0.16)';
      ctx.stroke();
      ctx.fillStyle = '#ffffff';
      ctx.font = '800 14px Segoe UI, Arial';
      drawTextFit(`EV Journey Replay - ${vehicle.id.replace('ev-', 'EV ').replace('ghost-', 'GHOST ')}`, x + 18, y + 25, panelW * 0.48);
      ctx.fillStyle = phase.color;
      ctx.font = '800 13px Segoe UI, Arial';
      drawTextFit(`${phase.label} | SOC ${Math.round(snapshot.soc * 100)}% | net ${snapshot.netBatteryKw >= 0 ? '+' : ''}${snapshot.netBatteryKw.toFixed(1)} kW`, x + panelW - 18, y + 25, panelW * 0.45, 'right');
      const startX = x + 42;
      const gap = (panelW - 84) / (steps.length - 1);
      ctx.strokeStyle = 'rgba(255,255,255,0.24)';
      ctx.lineWidth = 3;
      ctx.beginPath(); ctx.moveTo(startX, y + 57); ctx.lineTo(x + panelW - 42, y + 57); ctx.stroke();
      steps.forEach(([label, done], index) => {
        const sx = startX + index * gap;
        ctx.fillStyle = done ? (index === 4 ? socColor(snapshot.soc) : colors.ev) : 'rgba(255,255,255,0.20)';
        ctx.beginPath(); ctx.arc(sx, y + 57, 10, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = done ? '#ffffff' : 'rgba(244,247,245,0.56)';
        ctx.font = '800 10px Segoe UI, Arial';
        drawTextFit(label, sx, y + 80, 72, 'center');
      });
      ctx.restore();
    }

    function drawStationEnergyFlows(lotX, lotY, lotW, lotH, detail, bayCenters) {
      const pv = [lotX + lotW * 0.52, lotY + 48];
      const bess = [lotX + 42, lotY + lotH - 24];
      bayCenters.slice(0, Math.max(1, detail.charging)).forEach((center, index) => {
        const item = center.item;
        if (!item || item.snapshot.chargeKw <= 0) return;
        drawFlowPath([pv, [center.x, pv[1]], [center.x, center.y - 40]], 'rgba(246,200,76,0.72)', clamp(item.snapshot.chargeKw / 10, 2, 6), `${item.snapshot.chargeKw.toFixed(0)} kW`);
        drawFlowPath([bess, [center.x - 28, bess[1]], [center.x - 22, center.y - 24]], 'rgba(79,209,197,0.58)', clamp(detail.snapshot.bessPct * 5, 2, 4.5));
      });
    }

    function sceneStats(scene) {
      const seen = data.vehicles.filter(v => v.scene === scene.id && v.start <= state.t);
      const accepted = seen.filter(v => v.status === 'accepted').length;
      const blocked = seen.filter(v => v.status === 'blocked').length;
      const rejected = seen.filter(v => v.status === 'rejected').length;
      const proposed = data.summaries.find(row => row.scenario === scene.id && row.baseline === 'v_assist_s_aca_pd_edf');
      const progress = Math.max(0, Math.min(1, (state.t - scene.start) / (scene.end - scene.start)));
      return { seen, accepted, blocked, rejected, grid: proposed ? proposed.grid * progress : 0 };
    }

    function updateDom(scene) {
      const stats = sceneStats(scene);
      document.getElementById('sceneLabel').textContent = scene.label;
      document.getElementById('sceneHeadline').textContent = scene.headline;
      document.getElementById('storyTitle').textContent = scene.focus;
      document.getElementById('storyText').textContent = scene.headline;
      document.getElementById('metricA').textContent = scene.metricA;
      document.getElementById('metricB').textContent = scene.metricB;
      document.getElementById('mAccepted').textContent = stats.accepted;
      document.getElementById('mBlocked').textContent = stats.blocked;
      document.getElementById('mRejected').textContent = stats.rejected;
      document.getElementById('mGrid').textContent = stats.grid.toFixed(1);
      document.getElementById('barA').style.width = `${Math.min(100, 22 + stats.accepted * 3)}%`;
      document.getElementById('barB').style.width = `${Math.min(100, 20 + (stats.blocked + stats.rejected) * 4)}%`;
      document.getElementById('hudEnergy').textContent = scene.id === 'sensitivity_no_grid' ? 'No-grid: PV/BESS only' : 'PV/BESS/grid bounded';
      document.getElementById('hudSecurity').textContent = scene.id === 'security_stress' ? 'TRUST-EV blocking attacks' : 'Trust registry active';
      document.getElementById('hudProtocol').textContent = `${data.simulations} deterministic runs`;
      document.getElementById('clockFace').textContent = `${Math.floor(state.t).toString().padStart(2, '0')}s`;
      document.getElementById('clockTitle').textContent = scene.label;
      document.getElementById('clockSub').textContent = scene.focus;
      scrub.value = state.t;
      const railRect = rail.getBoundingClientRect();
      playhead.style.left = `${(state.t / data.duration) * railRect.width}px`;
      updateComparison(scene);
      updateFeed(scene);
      updateInspector(scene);
      updateSceneChips(scene);
    }

    function updateComparison(scene) {
      const holder = document.getElementById('comparison');
      const rows = summariesFor(scene.id);
      const baselineNames = ['nearest_station', 'minimum_wait', 'aca_pd_fifo', 'v_assist_s_aca_pd_edf', 'deadline_safe', 'ablation_no_trust', 'ablation_no_partial'];
      const metric = scene.id === 'security_stress' ? 'attack' : scene.id === 'sensitivity_no_grid' ? 'grid' : 'rejection';
      const max = Math.max(...rows.map(r => Number(r[metric])), 0.001);
      holder.innerHTML = baselineNames.map(name => {
        const row = rows.find(r => r.baseline === name);
        if (!row) return '';
        const value = Number(row[metric]);
        const width = Math.max(2, (value / max) * 100);
        const color = name === 'v_assist_s_aca_pd_edf' ? 'var(--ev)' : name === 'deadline_safe' ? 'var(--solar)' : 'var(--green)';
        return `<div class="policy-row"><div class="policy-label">${labelBaseline(name)}</div><div class="bar-track"><div class="bar-fill" style="width:${width}%; background:${color}"></div></div><div>${formatMetric(value, metric)}</div></div>`;
      }).join('');
    }

    function updateFeed(scene) {
      const feed = document.getElementById('eventFeed');
      const recent = data.vehicles
        .filter(v => v.start <= state.t && v.start >= state.t - 11)
        .sort((a, b) => b.start - a.start)
        .slice(0, 7);
      feed.innerHTML = recent.map(v => {
        const color = v.status === 'blocked' ? 'var(--red)' : v.status === 'rejected' ? 'var(--amber)' : 'var(--ev)';
        const title = v.status === 'blocked' ? `Blocked ${v.attackType}` : v.status === 'accepted' ? `Admitted ${v.mode || 'charge'}` : 'Rejected';
        const detail = v.status === 'accepted' ? `${v.station} | ${v.energy} kWh | wait ${v.wait} min` : `${v.station} | ${v.reason}`;
        return `<div class="event"><div class="event-mark" style="background:${color}"></div><div><strong>${title}</strong><br>${detail}</div></div>`;
      }).join('');
    }

    function updateInspector(scene) {
      if (state.selected && state.selected.type === 'vehicle') {
        const vehicle = data.vehicles.find(v => v.id === state.selected.id);
        if (vehicle) {
          const snapshot = vehicleSnapshot(vehicle);
          inspector.innerHTML = `
            <div class="inspector-title"><span>EV live telemetry</span><strong>${vehicle.id.replace('ev-', 'EV ')}</strong></div>
            <div class="inspect-grid">
              <div class="inspect-cell"><b>${Math.round(snapshot.soc * 100)}%</b><span>Battery SOC</span><div class="soc-track"><div class="soc-fill" style="width:${Math.round(snapshot.soc * 100)}%; background:${socColor(snapshot.soc)}"></div></div></div>
              <div class="inspect-cell"><b>${snapshot.chargeKw.toFixed(1)} kW</b><span>Charging power</span></div>
              <div class="inspect-cell"><b>${snapshot.speedKmh.toFixed(1)} km/h</b><span>Approach speed</span></div>
              <div class="inspect-cell"><b>${snapshot.motorKw.toFixed(1)} kW</b><span>Drive consumption</span></div>
              <div class="inspect-cell"><b>${vehicle.mode || vehicle.requestedMode}</b><span>Mode requested/served</span></div>
              <div class="inspect-cell"><b>${snapshot.netBatteryKw >= 0 ? '+' : ''}${snapshot.netBatteryKw.toFixed(1)} kW</b><span>Net battery flow</span></div>
              <div class="inspect-cell"><b>${snapshot.chargedEnergyKwh.toFixed(1)} kWh</b><span>Energy transferred live</span></div>
              <div class="inspect-cell"><b>${snapshot.rangeKm.toFixed(0)} km</b><span>Estimated range</span></div>
              <div class="inspect-cell"><b>${snapshot.drivenEnergyKwh.toFixed(2)} kWh</b><span>Trip energy used</span></div>
              <div class="inspect-cell inspect-wide"><b>${snapshot.statusLabel}</b><span>${vehicle.station} | wait ${vehicle.wait.toFixed ? vehicle.wait.toFixed(1) : vehicle.wait} min | priority ${vehicle.priority} | ${vehicle.reason}</span></div>
            </div>`;
          return;
        }
      }
      if (state.selected && state.selected.type === 'station') {
        const station = stationsById[state.selected.id];
        if (station) {
          const snap = stationSnapshot(station, scene);
          inspector.innerHTML = `
            <div class="inspector-title"><span>Charging station</span><strong>${station.label}</strong></div>
            <div class="inspect-grid">
              <div class="inspect-cell"><b>${Math.round(snap.bessPct * 100)}%</b><span>BESS state</span><div class="soc-track"><div class="soc-fill" style="width:${Math.round(snap.bessPct * 100)}%; background:var(--solar)"></div></div></div>
              <div class="inspect-cell"><b>${snap.pvKw.toFixed(1)} kW</b><span>PV production</span></div>
              <div class="inspect-cell"><b>${snap.active}/${station.sockets}</b><span>Active chargers</span></div>
              <div class="inspect-cell"><b>${station.parkingPlaces}</b><span>Visible EV bays</span></div>
              <div class="inspect-cell"><b>${snap.gridKw.toFixed(1)} kW</b><span>Grid draw now</span></div>
              <div class="inspect-cell"><b>${snap.queue}/${station.queueCapacity}</b><span>Waiting queue</span></div>
              <div class="inspect-cell inspect-wide"><b>${scene.id === 'sensitivity_no_grid' ? 'autonomous solar mode' : 'bounded backup mode'}</b><span>${station.id} | reserve ${station.reserveKwh} kWh | ${station.gridBackupKwh} kWh grid backup</span></div>
            </div>`;
          return;
        }
      }
      const stats = sceneStats(scene);
      inspector.innerHTML = `
        <div class="inspector-title"><span>Scenario telemetry</span><strong>${scene.label.split('/')[1].trim()}</strong></div>
        <div class="inspect-grid">
          <div class="inspect-cell"><b>${stats.accepted}</b><span>EV connected</span></div>
          <div class="inspect-cell"><b>${stats.blocked}</b><span>Threats blocked</span></div>
          <div class="inspect-cell"><b>${stats.rejected}</b><span>Admission rejects</span></div>
          <div class="inspect-cell"><b>${stats.grid.toFixed(1)} kWh</b><span>Grid energy</span></div>
          <div class="inspect-cell inspect-wide"><b>${scene.focus}</b><span>${scene.headline}</span></div>
        </div>`;
    }

    function labelBaseline(name) {
      return {
        nearest_station: 'Nearest',
        minimum_wait: 'Min wait',
        aca_pd_fifo: 'ACA-PD-FIFO',
        v_assist_s_aca_pd_edf: 'Proposed',
        deadline_safe: 'Deadline-safe',
        ablation_no_trust: 'No trust',
        ablation_no_partial: 'No partial'
      }[name] || name;
    }

    function formatMetric(value, metric) {
      if (metric === 'grid') return value.toFixed(1);
      return `${Math.round(value * 100)}%`;
    }

    function buildRail() {
      data.scenes.forEach(scene => {
        const chip = document.createElement('button');
        chip.className = 'scene-chip';
        chip.dataset.scene = scene.id;
        chip.style.left = `${((scene.start + scene.end) / 2 / data.duration) * 100}%`;
        chip.textContent = scene.label.replace('Scene ', 'S');
        chip.addEventListener('click', () => { state.t = scene.start + 0.1; state.playing = true; });
        rail.appendChild(chip);
      });
    }

    function updateSceneChips(scene) {
      document.querySelectorAll('.scene-chip').forEach(chip => {
        chip.classList.toggle('active', chip.dataset.scene === scene.id);
      });
    }

    function hitRegionContains(region, x, y) {
      if (typeof region.w === 'number' && typeof region.h === 'number') {
        return x >= region.x && x <= region.x + region.w && y >= region.y && y <= region.y + region.h;
      }
      const dx = x - region.x;
      const dy = y - region.y;
      return Math.sqrt(dx * dx + dy * dy) <= region.r;
    }

    function setToggleButtonStates() {
      crisisBtn.classList.toggle('active', state.crisisMode);
      compareBtn.classList.toggle('active', state.compareMode);
      tourBtn.classList.toggle('active', state.tourMode);
    }

    function activateCrisis() {
      const scene = sceneById.security_stress;
      state.crisisMode = true;
      state.crisisStart = performance.now();
      state.t = scene.start + 2.5;
      state.playing = true;
      setToggleButtonStates();
    }

    function clearCrisis() {
      state.crisisMode = false;
      setToggleButtonStates();
    }

    function startDemoTour() {
      state.tourMode = true;
      state.tourStart = performance.now();
      state.tourStage = -1;
      state.playing = true;
      setToggleButtonStates();
    }

    function stopDemoTour() {
      state.tourMode = false;
      state.compareMode = false;
      clearCrisis();
      closeStationDetail({ leaveFullscreen: false });
      setToggleButtonStates();
    }

    function advanceDemoTour(now) {
      if (!state.tourMode) return;
      const elapsed = ((now - state.tourStart) / 1000) % 42;
      const stages = [
        { at: 0, id: 'city', t: 8 },
        { at: 6, id: 'compare', t: 18 },
        { at: 13, id: 'crisis', t: 60 },
        { at: 20, id: 'station', t: 34, station: 'cs-center' },
        { at: 28, id: 'ev', t: 37, station: 'cs-center' },
        { at: 35, id: 'nogrid', t: 96, station: 'cs-east' }
      ];
      let stage = stages[0];
      for (const candidate of stages) {
        if (elapsed >= candidate.at) stage = candidate;
      }
      if (state.tourStage === stage.id) return;
      state.tourStage = stage.id;
      state.t = stage.t;
      state.compareMode = stage.id === 'compare';
      state.crisisMode = stage.id === 'crisis';
      if (stage.id === 'station' || stage.id === 'ev' || stage.id === 'nogrid') {
        openStationDetail(stage.station);
      } else {
        closeStationDetail({ leaveFullscreen: false });
      }
      if (stage.id === 'ev') {
        const stationVehicles = data.vehicles.filter(v => v.station === stage.station && v.status === 'accepted');
        const vehicle = stationVehicles.find(v => v.start <= state.t && v.start + v.duration + 24 >= state.t) || stationVehicles[0];
        if (vehicle) state.selected = { type: 'vehicle', id: vehicle.id };
      }
      setToggleButtonStates();
    }

    function loop(now) {
      try {
        advanceDemoTour(now);
        const delta = Math.min(0.05, (now - state.last) / 1000);
        state.last = now;
        if (state.playing) {
          state.t += delta * state.speed;
          if (state.t > data.duration) state.t = 0;
        }
        const rect = ensureCanvasSize();
        const scene = currentScene();
        state.hitRegions = [];
        if (state.stationFocus && stationsById[state.stationFocus]) {
          drawStationDetail(scene, stationsById[state.stationFocus], rect.width, rect.height);
        } else {
          drawBackground(rect.width, rect.height, scene);
          drawStations(scene);
          if (state.crisisMode || state.compareMode || state.tourMode) {
            drawCityEnergyFlows(scene, rect.width, rect.height);
          }
          drawVehicles();
          drawPolicySplitOverlay(scene, rect.width, rect.height);
        }
        drawCrisisOverlay(rect.width, rect.height);
        drawJourneyReplay(rect.width, rect.height);
        updateDom(scene);
      } catch (error) {
        ctx.fillStyle = '#111411';
        ctx.fillRect(0, 0, canvas.clientWidth, canvas.clientHeight);
        ctx.fillStyle = '#e6534f';
        ctx.font = '800 18px Segoe UI, Arial';
        ctx.fillText(`Render error: ${error.message}`, 32, 70);
        throw error;
      }
      requestAnimationFrame(loop);
    }

    playBtn.addEventListener('click', () => {
      state.playing = !state.playing;
      playBtn.textContent = state.playing ? 'II' : 'PLAY';
    });
    speedBtn.addEventListener('click', () => {
      const speeds = [1, 1.4, 2, 0.7];
      state.speed = speeds[(speeds.indexOf(state.speed) + 1) % speeds.length] || 1;
      speedBtn.textContent = `${state.speed.toFixed(1)}x`;
    });
    document.getElementById('jumpBtn').addEventListener('click', () => {
      const scene = sceneById.security_stress;
      state.t = scene.start + 0.1;
      state.playing = true;
    });
    crisisBtn.addEventListener('click', () => {
      if (state.crisisMode) clearCrisis();
      else activateCrisis();
    });
    compareBtn.addEventListener('click', () => {
      state.compareMode = !state.compareMode;
      state.tourMode = false;
      closeStationDetail({ leaveFullscreen: false });
      setToggleButtonStates();
    });
    tourBtn.addEventListener('click', () => {
      if (state.tourMode) stopDemoTour();
      else startDemoTour();
    });
    document.getElementById('fullBtn').addEventListener('click', () => {
      document.documentElement.requestFullscreen?.();
    });
    function setMapOnly(enabled) {
      state.mapOnly = enabled;
      document.body.classList.toggle('map-only', enabled);
      setTimeout(resize, 120);
      setTimeout(resize, 360);
    }
    function openMapFullscreen() {
      setMapOnly(true);
      stageWrap.requestFullscreen?.();
      setTimeout(resize, 120);
    }
    function openStationDetail(stationId) {
      state.stationFocus = stationId;
      state.selected = { type: 'station', id: stationId };
      stageWrap.classList.add('station-detail');
      const request = stageWrap.requestFullscreen?.();
      if (request && request.catch) request.catch(() => {});
      setTimeout(resize, 120);
    }
    function closeStationDetail(options = {}) {
      state.stationFocus = null;
      if (state.selected && state.selected.type === 'station') state.selected = null;
      stageWrap.classList.remove('station-detail');
      if (options.leaveFullscreen !== false && document.fullscreenElement === stageWrap) {
        const exit = document.exitFullscreen?.();
        if (exit && exit.catch) exit.catch(() => {});
      }
      setTimeout(resize, 120);
    }
    document.getElementById('mapFullBtn').addEventListener('click', openMapFullscreen);
    document.getElementById('mapFocusBtn').addEventListener('click', openMapFullscreen);
    stationExitBtn.addEventListener('click', () => closeStationDetail());
    document.addEventListener('fullscreenchange', () => {
      if (document.fullscreenElement !== stageWrap && state.stationFocus) {
        closeStationDetail({ leaveFullscreen: false });
      }
      setTimeout(resize, 120);
    });
    scrub.addEventListener('input', event => {
      state.t = Number(event.target.value);
      state.playing = false;
      playBtn.textContent = 'PLAY';
    });
    canvas.addEventListener('click', event => {
      const rect = canvas.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      const hit = [...state.hitRegions].reverse().find(region => hitRegionContains(region, x, y));
      if (hit) {
        if (hit.type === 'station') {
          openStationDetail(hit.id);
        } else {
          state.selected = { type: hit.type, id: hit.id };
        }
      } else {
        if (!state.stationFocus) state.selected = null;
      }
    });
    canvas.addEventListener('mousemove', event => {
      const rect = canvas.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      const hit = state.hitRegions.some(region => hitRegionContains(region, x, y));
      canvas.style.cursor = hit ? 'pointer' : 'default';
    });
    window.addEventListener('keydown', event => {
      if (event.code === 'Space') {
        event.preventDefault();
        playBtn.click();
      }
      if (event.key === 'Escape' && state.stationFocus) closeStationDetail();
      else if (event.key === 'Escape' && state.mapOnly) setMapOnly(false);
      if (event.key === 'f' || event.key === 'F') document.getElementById('fullBtn').click();
    });

    function applyInitialHash() {
      const params = new URLSearchParams(window.location.hash.replace(/^#/, ''));
      const stationId = params.get('station');
      const startAt = Number(params.get('t'));
      if (Number.isFinite(startAt)) state.t = clamp(startAt, 0, data.duration);
      if (params.get('compare') === '1') state.compareMode = true;
      if (params.get('crisis') === '1') activateCrisis();
      if (params.get('map') === '1') setMapOnly(true);
      if (stationId && stationsById[stationId]) {
        state.playing = true;
        openStationDetail(stationId);
      }
      if (params.get('tour') === '1') startDemoTour();
      setToggleButtonStates();
    }

    buildRail();
    applyInitialHash();
    setTimeout(resize, 120);
    setTimeout(resize, 420);
    requestAnimationFrame(loop);
  </script>
</body>
</html>"""
    return (
        template.replace("__DEMO_DATA__", payload)
        .replace("__STATION_BACKDROP_URL__", station_backdrop_url)
        .replace("__CITY_STAGE_BACKGROUND__", city_stage_background)
        .replace("__HAS_CITY_BACKDROP__", has_city_backdrop)
    )


def render_guide(html_path: Path) -> str:
    output_dir = html_path.parent.resolve()
    python_path = Path.cwd() / ".venv" / "Scripts" / "python.exe"
    return f"""# Recording Guide - Cinematic Demo

Start the local demo server:

```powershell
Push-Location "{output_dir}"
& "{python_path}" -m http.server 8765 --bind 127.0.0.1
```

Open: http://127.0.0.1:8765/index.html

Recommended video flow:

1. Press `Demo Tour` for the automatic camera: city, policy split, crisis, station zoom, EV journey, no-grid.
2. Use `Compare` to show baseline FIFO versus the proposed policy on the same city map.
3. Use `Stress Event` to trigger the red crisis overlay with attacks, demand spikes and live redirection.
4. Click any charging station to open the fullscreen station operations view.
5. Click one EV inside the station view to show SOC, charging power, speed, allocated energy and decision reason.
6. Point out the animated energy flows: PV/BESS/grid to station, charger cable to EV.
7. At 55s, emphasize security: proposed policy blocks attacks while no-trust exposes them.
8. At 86s, emphasize autonomy: no-grid scenario uses 0.0 kWh grid.

Fast demo URLs:

- Clean full-map recording: http://127.0.0.1:8765/index.html#map=1&t=37
- City + policy split: http://127.0.0.1:8765/index.html#compare=1
- Crisis mode: http://127.0.0.1:8765/index.html#crisis=1
- Station zoom: http://127.0.0.1:8765/index.html#station=cs-center&t=37
- Automatic tour: http://127.0.0.1:8765/index.html#tour=1

Short spoken line:

> This is not only a script. It is a reproducible research simulator: distributed EV-side selection, station-side admission, solar/storage constraints, communication uncertainty, cyber-security checks, baselines, ablations and statistical reporting.
"""


if __name__ == "__main__":
    main()

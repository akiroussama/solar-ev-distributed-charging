from solar_ev_charging.experiments import run_experiment_suite, summarize_results
from solar_ev_charging.models import Position
from solar_ev_charging.scenarios import ScenarioConfig, StationConfig
from solar_ev_charging.simulation import Baseline, run_simulation


def tiny_scenario(**overrides: object) -> ScenarioConfig:
    station = StationConfig(
        station_id="cs-test",
        position=Position(1.0, 1.0),
        socket_count=2,
        queue_capacity=4,
        initial_energy_kwh=120.0,
        storage_capacity_kwh=150.0,
        storage_reserve_kwh=10.0,
        panel_area_m2=100.0,
        pv_efficiency=0.2,
        available_power_kw=60.0,
        grid_backup_kwh=10.0,
    )
    values = {
        "name": "tiny",
        "duration_minutes": 120,
        "arrival_rate_per_hour": 12.0,
        "station_configs": (station,),
        "seed": 1,
        "cloud_factor": 0.8,
    }
    values.update(overrides)
    return ScenarioConfig(**values)  # type: ignore[arg-type]


def test_run_simulation_is_deterministic_for_same_seed() -> None:
    scenario = tiny_scenario()

    first = run_simulation(scenario, Baseline.PROPOSED, seed=7)
    second = run_simulation(scenario, Baseline.PROPOSED, seed=7)

    assert first.as_row() == second.as_row()
    assert first.generated > 0


def test_security_stress_blocks_attacks_for_proposed_policy() -> None:
    scenario = tiny_scenario(attack_probability=1.0)

    result = run_simulation(scenario, Baseline.PROPOSED, seed=3)

    assert result.attacks_attempted == result.generated
    assert result.attacks_blocked == result.generated
    assert result.attacks_accepted == 0


def test_baseline_without_security_can_accept_attack_requests() -> None:
    scenario = tiny_scenario(attack_probability=1.0)

    result = run_simulation(scenario, Baseline.NEAREST, seed=3)

    assert result.attacks_attempted == result.generated
    assert result.attacks_accepted > 0


def test_experiment_suite_and_summary_group_results() -> None:
    scenario = tiny_scenario()
    results = run_experiment_suite(
        (scenario,),
        (Baseline.NEAREST, Baseline.PROPOSED),
        seeds=(1, 2),
    )
    summaries = summarize_results(results)

    assert len(results) == 4
    assert len(summaries) == 2
    assert all(summary.runs == 2 for summary in summaries)
    assert {"rejection_rate", "average_wait_minutes"} <= set(summaries[0].metrics)

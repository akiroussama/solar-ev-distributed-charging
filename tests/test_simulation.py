from solar_ev_charging.experiments import run_experiment_suite, summarize_results
from solar_ev_charging.models import Position
from solar_ev_charging.scenarios import ScenarioConfig, StationConfig, sensitivity_scenarios
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
    assert first.accepted + first.rejected == first.generated
    assert first.unfinished >= 0


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


def test_no_trust_ablation_exposes_security_contribution() -> None:
    scenario = tiny_scenario(attack_probability=1.0)

    proposed = run_simulation(scenario, Baseline.PROPOSED, seed=4)
    no_trust = run_simulation(scenario, Baseline.NO_TRUST, seed=4)

    assert proposed.attacks_accepted == 0
    assert no_trust.attacks_accepted > proposed.attacks_accepted


def test_deadline_safe_variant_runs_as_explicit_policy() -> None:
    scenario = tiny_scenario(arrival_rate_per_hour=18.0)

    result = run_simulation(scenario, Baseline.DEADLINE_SAFE, seed=5)

    assert result.baseline == Baseline.DEADLINE_SAFE.value
    assert result.generated > 0


def test_sensitivity_scenarios_cover_communication_noise_and_no_grid() -> None:
    scenarios = sensitivity_scenarios()

    assert {scenario.name for scenario in scenarios} >= {
        "sensitivity_high_loss",
        "sensitivity_no_grid",
    }
    assert any(scenario.communication_noise_fraction > 0 for scenario in scenarios)
    assert any(
        all(station.grid_backup_kwh == 0 for station in scenario.station_configs)
        for scenario in scenarios
    )


def test_no_grid_sensitivity_does_not_consume_grid_energy() -> None:
    scenario = next(
        scenario for scenario in sensitivity_scenarios() if scenario.name == "sensitivity_no_grid"
    )

    result = run_simulation(scenario, Baseline.PROPOSED, seed=6)

    assert result.grid_energy_used_kwh == 0.0
    assert result.direct_pv_energy_used_kwh >= 0.0


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

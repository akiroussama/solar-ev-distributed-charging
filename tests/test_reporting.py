from pathlib import Path

from solar_ev_charging.experiments import (
    run_experiment_suite,
    summarize_results,
    write_run_csv,
    write_summary_csv,
)
from solar_ev_charging.models import Position
from solar_ev_charging.reporting import write_report_bundle
from solar_ev_charging.scenarios import ScenarioConfig, StationConfig
from solar_ev_charging.simulation import Baseline


def test_reporting_writes_csv_svg_and_markdown(tmp_path: Path) -> None:
    scenario = ScenarioConfig(
        name="reporting",
        duration_minutes=90,
        arrival_rate_per_hour=8.0,
        station_configs=(
            StationConfig(
                station_id="cs",
                position=Position(0.0, 0.0),
                socket_count=2,
                queue_capacity=4,
                initial_energy_kwh=80.0,
                storage_capacity_kwh=100.0,
                storage_reserve_kwh=10.0,
                panel_area_m2=90.0,
                pv_efficiency=0.2,
                available_power_kw=60.0,
            ),
        ),
    )
    results = run_experiment_suite((scenario,), (Baseline.PROPOSED,), seeds=(1,))
    summaries = summarize_results(results)

    write_run_csv(results, tmp_path / "runs.csv")
    write_summary_csv(summaries, tmp_path / "summary.csv")
    report_path = write_report_bundle(summaries, output_dir=tmp_path)

    assert (tmp_path / "runs.csv").read_text(encoding="utf-8").startswith("scenario,baseline")
    assert "rejection_rate_mean" in (tmp_path / "summary.csv").read_text(encoding="utf-8")
    assert report_path.exists()
    assert "Experimental Report" in report_path.read_text(encoding="utf-8")
    assert (tmp_path / "figures" / "rejection_rate.svg").exists()

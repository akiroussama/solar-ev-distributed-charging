"""Experiment orchestration and statistical summaries."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from math import sqrt
from pathlib import Path
from statistics import mean, stdev

from solar_ev_charging.scenarios import ScenarioConfig
from solar_ev_charging.simulation import Baseline, SimulationMetrics, run_simulation

METRIC_FIELDS: tuple[str, ...] = (
    "rejection_rate",
    "acceptance_rate",
    "deadline_miss_rate",
    "average_wait_minutes",
    "average_total_minutes",
    "average_extra_distance_km",
    "storage_energy_used_kwh",
    "grid_energy_used_kwh",
    "solar_utilization",
    "fairness_jain",
    "attack_success_rate",
)


@dataclass(frozen=True)
class MetricSummary:
    """Mean, sample deviation and 95% normal CI half-width."""

    mean: float
    stdev: float
    ci95: float


@dataclass(frozen=True)
class ExperimentSummary:
    """Aggregated results for one scenario/baseline pair."""

    scenario: str
    baseline: str
    runs: int
    metrics: dict[str, MetricSummary]

    def mean(self, metric: str) -> float:
        """Return a metric mean."""

        return self.metrics[metric].mean


def run_experiment_suite(
    scenarios: tuple[ScenarioConfig, ...],
    baselines: tuple[Baseline, ...],
    *,
    seeds: tuple[int, ...],
) -> list[SimulationMetrics]:
    """Run every scenario/baseline/seed combination."""

    results: list[SimulationMetrics] = []
    for scenario in scenarios:
        for baseline in baselines:
            for seed in seeds:
                scenario_with_seed = ScenarioConfig(
                    name=scenario.name,
                    duration_minutes=scenario.duration_minutes,
                    arrival_rate_per_hour=scenario.arrival_rate_per_hour,
                    station_configs=scenario.station_configs,
                    seed=seed,
                    cloud_factor=scenario.cloud_factor,
                    priority_probability=scenario.priority_probability,
                    communication_loss_probability=scenario.communication_loss_probability,
                    communication_latency_minutes=scenario.communication_latency_minutes,
                    attack_probability=scenario.attack_probability,
                    average_speed_kmh=scenario.average_speed_kmh,
                    demand_scale=scenario.demand_scale,
                )
                results.append(run_simulation(scenario_with_seed, baseline, seed=seed))
    return results


def summarize_results(results: list[SimulationMetrics]) -> list[ExperimentSummary]:
    """Aggregate run-level metrics into scenario/baseline summaries."""

    grouped: dict[tuple[str, str], list[SimulationMetrics]] = {}
    for result in results:
        grouped.setdefault((result.scenario, result.baseline), []).append(result)

    summaries: list[ExperimentSummary] = []
    for (scenario, baseline), group in sorted(grouped.items()):
        metrics: dict[str, MetricSummary] = {}
        for field in METRIC_FIELDS:
            values = [float(result.as_row()[field]) for result in group]
            metrics[field] = _summarize_values(values)
        summaries.append(
            ExperimentSummary(
                scenario=scenario,
                baseline=baseline,
                runs=len(group),
                metrics=metrics,
            )
        )
    return summaries


def write_run_csv(results: list[SimulationMetrics], path: Path) -> None:
    """Write per-run metrics to CSV."""

    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [result.as_row() for result in results]
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_summary_csv(summaries: list[ExperimentSummary], path: Path) -> None:
    """Write summary statistics to CSV."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["scenario", "baseline", "runs"]
    for metric in METRIC_FIELDS:
        fieldnames.extend([f"{metric}_mean", f"{metric}_stdev", f"{metric}_ci95"])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for summary in summaries:
            row: dict[str, str | int | float] = {
                "scenario": summary.scenario,
                "baseline": summary.baseline,
                "runs": summary.runs,
            }
            for metric, values in summary.metrics.items():
                row[f"{metric}_mean"] = values.mean
                row[f"{metric}_stdev"] = values.stdev
                row[f"{metric}_ci95"] = values.ci95
            writer.writerow(row)


def _summarize_values(values: list[float]) -> MetricSummary:
    if not values:
        return MetricSummary(mean=0.0, stdev=0.0, ci95=0.0)
    if len(values) == 1:
        return MetricSummary(mean=values[0], stdev=0.0, ci95=0.0)
    deviation = stdev(values)
    return MetricSummary(
        mean=mean(values),
        stdev=deviation,
        ci95=1.96 * deviation / sqrt(len(values)),
    )

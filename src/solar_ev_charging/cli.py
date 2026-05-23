"""Command-line entrypoints for reproducible experiments."""

from __future__ import annotations

import argparse
from pathlib import Path

from solar_ev_charging.experiments import (
    run_experiment_suite,
    summarize_results,
    write_run_csv,
    write_summary_csv,
)
from solar_ev_charging.reporting import write_report_bundle
from solar_ev_charging.scenarios import ScenarioConfig, research_scenarios, sensitivity_scenarios
from solar_ev_charging.simulation import Baseline

FULL_BASELINES: tuple[Baseline, ...] = (
    Baseline.NEAREST,
    Baseline.MIN_WAIT,
    Baseline.ACA_PD_FIFO,
    Baseline.PROPOSED,
    Baseline.DEADLINE_SAFE,
    Baseline.NO_PD,
    Baseline.NO_EDF,
    Baseline.NO_AOI,
    Baseline.NO_TRUST,
    Baseline.NO_PARTIAL,
    Baseline.NO_REDIRECTION,
)


def main() -> None:
    """Run the research experiment CLI."""

    parser = argparse.ArgumentParser(description="Run solar EV charging experiments.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs") / "research_report",
        help="Directory for CSV, SVG and Markdown report outputs.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=30,
        help="Number of random seeds per scenario/baseline.",
    )
    parser.add_argument(
        "--suite",
        choices=("research", "sensitivity", "full"),
        default="full",
        help="Scenario suite to execute. 'full' combines research and sensitivity stress tests.",
    )
    args = parser.parse_args()

    if args.runs <= 0:
        raise SystemExit("--runs must be positive")

    seeds = tuple(range(1, args.runs + 1))
    scenarios = _scenarios_for_suite(args.suite)
    results = run_experiment_suite(scenarios, FULL_BASELINES, seeds=seeds)
    summaries = summarize_results(results)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_run_csv(results, args.output_dir / "runs.csv")
    write_summary_csv(summaries, args.output_dir / "summary.csv")
    report_path = write_report_bundle(
        summaries,
        output_dir=args.output_dir,
        title=f"Solar EV Distributed Charging - {args.suite.title()} Experimental Report",
    )
    print(f"Wrote report: {report_path}")


def _scenarios_for_suite(suite: str) -> tuple[ScenarioConfig, ...]:
    if suite == "research":
        return research_scenarios()
    if suite == "sensitivity":
        return sensitivity_scenarios()
    return research_scenarios() + sensitivity_scenarios()


if __name__ == "__main__":
    main()

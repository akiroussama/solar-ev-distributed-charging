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
from solar_ev_charging.scenarios import research_scenarios
from solar_ev_charging.simulation import Baseline


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
    args = parser.parse_args()

    if args.runs <= 0:
        raise SystemExit("--runs must be positive")

    seeds = tuple(range(1, args.runs + 1))
    baselines = (
        Baseline.NEAREST,
        Baseline.MIN_WAIT,
        Baseline.ACA_PD_FIFO,
        Baseline.PROPOSED,
    )
    results = run_experiment_suite(research_scenarios(), baselines, seeds=seeds)
    summaries = summarize_results(results)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_run_csv(results, args.output_dir / "runs.csv")
    write_summary_csv(summaries, args.output_dir / "summary.csv")
    report_path = write_report_bundle(summaries, output_dir=args.output_dir)
    print(f"Wrote report: {report_path}")


if __name__ == "__main__":
    main()

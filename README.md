# Solar EV Distributed Charging

[![CI](https://github.com/akiroussama/solar-ev-distributed-charging/actions/workflows/ci.yml/badge.svg)](https://github.com/akiroussama/solar-ev-distributed-charging/actions/workflows/ci.yml)
[![CodeQL](https://github.com/akiroussama/solar-ev-distributed-charging/actions/workflows/codeql.yml/badge.svg)](https://github.com/akiroussama/solar-ev-distributed-charging/actions/workflows/codeql.yml)

Research-grade Python toolkit for distributed admission, assignment, and queue
scheduling in solar-powered electric-vehicle charging networks.

The project implements a clean, testable foundation for:

- `V-ASSIST`: vehicle-side adaptive secure station selection.
- `S-ACA-PD-EDF`: station-side admission control with priority declassification
  and adjusted earliest-deadline-first scheduling.
- `R-DCC`: resilient distributed charging coordination primitives.
- `TRUST-EV`: security and trust checks for simulated charging requests.

This public repository intentionally excludes confidential source attachments
and only contains reusable code, public documentation, tests, and automation.

## Research Direction

The core research question is:

> Can a network of solar-powered autonomous charging stations coordinate EV
> charging under mobility, renewable-energy, queueing, communication, and
> cyber-physical security constraints?

The current implementation includes deterministic domain models, admission
decisions, station scoring, request validation, simulation scenarios, baselines,
statistical summaries, SVG charts and Markdown report generation.

## Quick Start

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -U pip
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
```

Run the minimal scenario:

```bash
.venv\Scripts\python examples\run_minimal_scenario.py
```

Run the reproducible experiment suite:

```bash
.venv\Scripts\solar-ev-experiment --runs 30 --output-dir outputs\research_report
```

The experiment command writes:

- `runs.csv`: per-seed metrics.
- `summary.csv`: mean, standard deviation and 95% confidence intervals.
- `research_report.md`: Markdown report.
- `figures/*.svg`: dependency-free charts.

## Quality Gates

Local checks:

```bash
ruff format --check .
ruff check .
mypy src tests
pytest --cov=solar_ev_charging --cov-report=term-missing --cov-fail-under=85
```

GitHub Actions runs the same gates on every push and pull request.

## Repository Layout

```text
docs/                         # public research plan
examples/                     # runnable examples
src/solar_ev_charging/        # package source
tests/                        # automated tests
.github/workflows/            # CI and release automation
```

## Status

Research implementation under active development. The APIs are intentionally
small and typed so the simulator can grow without mixing confidential project
material into the public codebase.


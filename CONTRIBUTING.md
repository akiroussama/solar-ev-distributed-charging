# Contributing

## Development Setup

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -U pip
.venv\Scripts\python -m pip install -e ".[dev]"
pre-commit install
```

## Required Checks

Before opening a pull request:

```bash
ruff format --check .
ruff check .
mypy src tests
pytest --cov=solar_ev_charging --cov-report=term-missing
```

## Research Standards

- Keep algorithms deterministic unless randomness is explicitly injected.
- Add a baseline or ablation when introducing a new decision module.
- Prefer typed dataclasses and pure functions for decision logic.
- Do not commit confidential attachments, proprietary data, or private notes.


from pathlib import Path

import pytest

from solar_ev_charging.cli import main


def test_cli_generates_research_suite_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "research_cli"
    monkeypatch.setattr(
        "sys.argv",
        [
            "solar-ev-experiment",
            "--suite",
            "research",
            "--runs",
            "1",
            "--output-dir",
            str(output_dir),
        ],
    )

    main()

    assert (output_dir / "research_report.md").exists()
    assert (output_dir / "runs.csv").exists()
    assert (output_dir / "summary.csv").exists()
    assert len((output_dir / "summary.csv").read_text(encoding="utf-8").splitlines()) == 56

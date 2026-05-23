"""Markdown and SVG reporting for simulation experiments."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from solar_ev_charging.experiments import METRIC_FIELDS, ExperimentSummary

METRIC_LABELS: dict[str, str] = {
    "rejection_rate": "Rejection rate",
    "acceptance_rate": "Acceptance rate",
    "deadline_miss_rate": "Deadline miss rate",
    "average_wait_minutes": "Average wait (min)",
    "average_total_minutes": "Average total time (min)",
    "average_extra_distance_km": "Extra distance (km)",
    "storage_energy_used_kwh": "Storage energy used (kWh)",
    "direct_pv_energy_used_kwh": "Direct PV energy used (kWh)",
    "grid_energy_used_kwh": "Grid energy used (kWh)",
    "solar_utilization": "Solar utilization",
    "fairness_jain": "Jain fairness index",
    "attack_success_rate": "Attack success rate",
}

CORE_REPORT_METRICS: tuple[str, ...] = (
    "rejection_rate",
    "average_wait_minutes",
    "deadline_miss_rate",
    "grid_energy_used_kwh",
    "solar_utilization",
    "attack_success_rate",
)

PALETTE: tuple[str, ...] = (
    "#235789",
    "#f18f01",
    "#2e933c",
    "#c73e1d",
    "#6f4e7c",
    "#008f8c",
    "#8f2d56",
    "#33658a",
    "#f26419",
    "#758e4f",
    "#5b5f97",
    "#a63d40",
)

BASELINE_DISPLAY_ORDER: tuple[str, ...] = (
    "nearest_station",
    "minimum_wait",
    "aca_pd_fifo",
    "v_assist_s_aca_pd_edf",
    "deadline_safe",
    "ablation_no_pd",
    "ablation_no_edf",
    "ablation_no_aoi",
    "ablation_no_trust",
    "ablation_no_partial",
    "ablation_no_redirection",
)

BASELINE_DESCRIPTIONS: dict[str, str] = {
    "nearest_station": "greedy allocation to the geographically nearest station.",
    "minimum_wait": "greedy allocation to the station with the shortest FIFO queue.",
    "aca_pd_fifo": "station-side admission with power declassification and FIFO waiting.",
    "v_assist_s_aca_pd_edf": (
        "full proposed policy with vehicle-side selection, secure admission, "
        "power declassification, partial charging, stale-information penalty and EDF queueing."
    ),
    "deadline_safe": "proposed policy with a stricter admission deadline safety margin.",
    "ablation_no_pd": "proposed policy without power declassification.",
    "ablation_no_edf": "proposed policy with FIFO-style waiting instead of EDF scheduling.",
    "ablation_no_aoi": "proposed policy without age-of-information penalty.",
    "ablation_no_trust": "proposed policy without request trust and plausibility filtering.",
    "ablation_no_partial": "proposed policy without partial-charge fallback.",
    "ablation_no_redirection": "proposed policy without station redirection after local rejection.",
}


def write_report_bundle(
    summaries: list[ExperimentSummary],
    *,
    output_dir: Path,
    title: str = "Solar EV Distributed Charging - Experimental Report",
) -> Path:
    """Write SVG charts and a Markdown report."""

    output_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)

    chart_paths: dict[str, Path] = {}
    for metric in CORE_REPORT_METRICS:
        chart_path = figures_dir / f"{metric}.svg"
        write_bar_chart(summaries, metric=metric, path=chart_path)
        chart_paths[metric] = chart_path

    report_path = output_dir / "research_report.md"
    report_path.write_text(
        _render_markdown_report(summaries, chart_paths=chart_paths, title=title),
        encoding="utf-8",
    )
    return report_path


def write_bar_chart(
    summaries: list[ExperimentSummary],
    *,
    metric: str,
    path: Path,
    width: int = 1180,
    height: int = 620,
) -> None:
    """Write a dependency-free grouped bar chart as SVG."""

    path.parent.mkdir(parents=True, exist_ok=True)
    scenarios = sorted({summary.scenario for summary in summaries})
    baselines = _ordered_baselines(summary.baseline for summary in summaries)
    lookup = {(summary.scenario, summary.baseline): summary for summary in summaries}
    max_value = max((summary.mean(metric) for summary in summaries), default=1.0)
    max_value = max(max_value, 1e-9)
    width = max(width, 140 + len(scenarios) * max(95, len(baselines) * 32))
    legend_columns = max(1, min(len(baselines), max(1, width // 255)))
    legend_rows = (len(baselines) + legend_columns - 1) // legend_columns

    margin_left = 90
    margin_right = 30
    margin_top = 70
    margin_bottom = 95 + legend_rows * 26
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    group_width = plot_width / max(len(scenarios), 1)
    bar_width = group_width / (len(baselines) + 1)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{margin_left}" y="35" font-family="Arial" font-size="22" '
        f'font-weight="700">{_escape(METRIC_LABELS.get(metric, metric))}</text>',
        f'<line x1="{margin_left}" y1="{margin_top + plot_height}" '
        f'x2="{width - margin_right}" y2="{margin_top + plot_height}" stroke="#222"/>',
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" '
        f'y2="{margin_top + plot_height}" stroke="#222"/>',
    ]

    for tick in range(6):
        value = max_value * tick / 5
        y = margin_top + plot_height - (value / max_value) * plot_height
        parts.append(
            f'<line x1="{margin_left - 5}" y1="{y:.2f}" x2="{width - margin_right}" '
            f'y2="{y:.2f}" stroke="#e5e5e5"/>'
        )
        parts.append(
            f'<text x="{margin_left - 10}" y="{y + 4:.2f}" text-anchor="end" '
            f'font-family="Arial" font-size="11">{value:.2f}</text>'
        )

    for scenario_index, scenario in enumerate(scenarios):
        group_x = margin_left + scenario_index * group_width
        label_x = group_x + group_width / 2
        parts.append(
            f'<text x="{label_x:.2f}" y="{margin_top + plot_height + 35}" text-anchor="middle" '
            f'font-family="Arial" font-size="12">{_escape(scenario)}</text>'
        )
        for baseline_index, baseline in enumerate(baselines):
            summary = lookup.get((scenario, baseline))
            if summary is None:
                continue
            value = summary.mean(metric)
            bar_height = (value / max_value) * plot_height
            x = group_x + (baseline_index + 0.5) * bar_width
            y = margin_top + plot_height - bar_height
            color = PALETTE[baseline_index % len(PALETTE)]
            parts.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width * 0.82:.2f}" '
                f'height="{bar_height:.2f}" fill="{color}"/>'
            )
            parts.append(
                f'<text x="{x + bar_width * 0.41:.2f}" y="{y - 5:.2f}" '
                f'text-anchor="middle" font-family="Arial" font-size="10">{value:.2f}</text>'
            )

    legend_y = margin_top + plot_height + 62
    legend_x = margin_left
    for index, baseline in enumerate(baselines):
        color = PALETTE[index % len(PALETTE)]
        row = index // legend_columns
        column = index % legend_columns
        x = legend_x + column * 255
        y = legend_y + row * 26
        parts.append(f'<rect x="{x}" y="{y}" width="14" height="14" fill="{color}"/>')
        parts.append(
            f'<text x="{x + 20}" y="{y + 12}" font-family="Arial" '
            f'font-size="12">{_escape(baseline)}</text>'
        )

    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def _render_markdown_report(
    summaries: list[ExperimentSummary],
    *,
    chart_paths: dict[str, Path],
    title: str,
) -> str:
    scenarios = sorted({summary.scenario for summary in summaries})
    baselines = _ordered_baselines(summary.baseline for summary in summaries)
    total_runs = sum(summary.runs for summary in summaries)
    lines = [
        f"# {title}",
        "",
        "## Executive Summary",
        "",
        "This report is generated from deterministic simulation runs. It compares",
        "vehicle-side station selection, station-side admission control, queue",
        "scheduling, solar/storage constraints, degraded communication and",
        "security-aware request handling across explicit baselines.",
        "",
        "## Statistical Protocol",
        "",
        f"- Aggregated simulation cells: `{len(summaries)}`.",
        f"- Total deterministic Monte Carlo runs: `{total_runs}`.",
        "- Each summary row reports the empirical mean; `summary.csv` also reports",
        "  sample standard deviation and normal 95% confidence-interval half-width.",
        "- Ablation baselines isolate the contribution of declassification, EDF,",
        "  age-of-information, trust filtering, partial admission and redirection.",
        "- Sensitivity scenarios stress demand, BESS capacity, communication loss,",
        "  adversarial traffic and strict solar autonomy.",
        "",
        "## Baselines",
        "",
    ]
    for baseline in baselines:
        description = BASELINE_DESCRIPTIONS.get(baseline, "experimental baseline.")
        lines.append(f"- `{baseline}`: {description}")

    lines.extend(["", "## Figures", ""])
    for metric, path in chart_paths.items():
        relative = path.relative_to(path.parent.parent).as_posix()
        lines.append(f"### {METRIC_LABELS.get(metric, metric)}")
        lines.append("")
        lines.append(f"![{METRIC_LABELS.get(metric, metric)}]({relative})")
        lines.append("")

    lines.extend(["## Summary Tables", ""])
    for scenario in scenarios:
        lines.append(f"### Scenario: `{scenario}`")
        lines.append("")
        lines.append(
            "| Baseline | Runs | Rejection | Wait min | Deadline miss | Grid kWh | "
            "Solar util | Attack success |"
        )
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        scenario_summaries = {
            summary.baseline: summary for summary in summaries if summary.scenario == scenario
        }
        for baseline in baselines:
            summary = scenario_summaries.get(baseline)
            if summary is None:
                continue
            lines.append(
                "| {baseline} | {runs} | {rejection:.3f} | {wait:.2f} | {deadline:.3f} | "
                "{grid:.2f} | {solar:.3f} | {attack:.3f} |".format(
                    baseline=summary.baseline,
                    runs=summary.runs,
                    rejection=summary.mean("rejection_rate"),
                    wait=summary.mean("average_wait_minutes"),
                    deadline=summary.mean("deadline_miss_rate"),
                    grid=summary.mean("grid_energy_used_kwh"),
                    solar=summary.mean("solar_utilization"),
                    attack=summary.mean("attack_success_rate"),
                )
            )
        lines.append("")

    lines.extend(_render_interpretation(summaries))

    lines.extend(
        [
            "## Scientific Reading Guide",
            "",
            "- Lower rejection, waiting time, deadline miss, grid energy and attack",
            "  success rates are better.",
            "- Higher solar utilization and fairness are better.",
            "- Conclusions should be based on the summary CSV confidence intervals,",
            "  not only on single-run curves.",
            "",
            "## Metrics Included",
            "",
        ]
    )
    for metric in METRIC_FIELDS:
        lines.append(f"- `{metric}`: {METRIC_LABELS.get(metric, metric)}")

    return "\n".join(lines) + "\n"


def _render_interpretation(summaries: list[ExperimentSummary]) -> list[str]:
    proposed = "v_assist_s_aca_pd_edf"
    deadline_safe = "deadline_safe"
    lines = ["## Interpretation", ""]
    scenarios = sorted({summary.scenario for summary in summaries})
    for scenario in scenarios:
        scenario_summaries = [summary for summary in summaries if summary.scenario == scenario]
        proposed_summary = next(
            (summary for summary in scenario_summaries if summary.baseline == proposed),
            None,
        )
        if proposed_summary is None:
            continue
        best_rejection = min(summary.mean("rejection_rate") for summary in scenario_summaries)
        best_attack = min(summary.mean("attack_success_rate") for summary in scenario_summaries)
        proposed_rejection = proposed_summary.mean("rejection_rate")
        proposed_attack = proposed_summary.mean("attack_success_rate")
        proposed_deadline = proposed_summary.mean("deadline_miss_rate")
        deadline_safe_summary = next(
            (summary for summary in scenario_summaries if summary.baseline == deadline_safe),
            None,
        )
        lines.append(f"### `{scenario}`")
        lines.append("")
        if proposed_rejection <= best_rejection + 1e-12:
            lines.append("- Proposed policy has the best rejection-rate result in this scenario.")
        else:
            lines.append(
                "- Proposed policy does not minimize rejection in this scenario; inspect the "
                "summary CSV before claiming dominance."
            )
        if proposed_attack <= best_attack + 1e-12:
            lines.append("- Proposed policy is among the best policies on attack success rate.")
        if proposed_deadline > 0.05:
            lines.append(
                "- Deadline misses are non-negligible. This is a tuning signal: the current "
                "admission rule favors serving more vehicles and should be compared against a "
                "stricter deadline-safety margin."
            )
        if deadline_safe_summary is not None:
            delta = deadline_safe_summary.mean("deadline_miss_rate") - proposed_deadline
            lines.append(
                "- Deadline-safe variant changes deadline misses by "
                f"{delta:+.3f} relative to the proposed policy, exposing the "
                "acceptance-versus-punctuality trade-off."
            )
        lines.append("")

    lines.extend(
        [
            "## Validity Limits",
            "",
            "- The simulator is a controlled research instrument, not a real deployment.",
            "- Current communication modeling uses probabilistic stale/lost station states.",
            "- Current security modeling is simulation-level trust logic, not production",
            "  cryptography.",
            "- The results are meaningful as comparative evidence between policies, not as",
            "  calibrated real-city forecasts.",
            "",
        ]
    )
    return lines


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _ordered_baselines(baselines: Iterable[str]) -> list[str]:
    order = {baseline: index for index, baseline in enumerate(BASELINE_DISPLAY_ORDER)}
    return sorted(set(baselines), key=lambda baseline: (order.get(baseline, 999), baseline))

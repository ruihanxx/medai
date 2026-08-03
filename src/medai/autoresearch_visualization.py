from __future__ import annotations

from pathlib import Path

from medai.models import IdeaAssessment, RoundSummary


def generate_autoresearch_visualizations(
    assessments: list[IdeaAssessment],
    round_summaries: list[RoundSummary],
    metric_path: Path,
    status_path: Path,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from matplotlib.patches import Rectangle

    metric_path.parent.mkdir(parents=True, exist_ok=True)
    columns = 3
    rows = max(1, (len(assessments) + columns - 1) // columns)
    figure, axes = plt.subplots(rows, columns, figsize=(4.4 * columns, 3.5 * rows))
    flat_axes = list(getattr(axes, "flat", [axes]))
    for axis, assessment in zip(flat_axes, assessments, strict=False):
        metric = assessment.primary_metric
        if metric is None or metric.baseline_value is None or metric.refined_value is None:
            axis.text(0.5, 0.5, "N/A", ha="center", va="center", fontsize=18)
            axis.set_xticks([])
            axis.set_yticks([])
            axis.set_title(f"{assessment.idea_id}\nno comparable metric")
            continue
        values = [metric.baseline_value, metric.refined_value]
        bars = axis.bar(
            ["Baseline", "Refined"],
            values,
            color=["#6c757d", "#2878b5"],
        )
        axis.bar_label(bars, fmt="%.4g", padding=3)
        direction = "+" if metric.improvement_supported else ""
        axis.set_title(
            f"{assessment.idea_id} · {metric.name}\n"
            f"{direction}{metric.absolute_delta:.4g} · {assessment.verdict}"
        )
        axis.grid(axis="y", alpha=0.25)
    for axis in flat_axes[len(assessments) :]:
        axis.axis("off")
    figure.suptitle("Auto Research: baseline vs refined primary metrics", fontsize=15)
    figure.tight_layout()
    figure.savefig(metric_path, dpi=160, bbox_inches="tight")
    plt.close(figure)

    verdict_colors = {
        "valid": "#2ca02c",
        "invalid": "#d62728",
        "inconclusive": "#f2b134",
    }
    figure, axis = plt.subplots(
        figsize=(8, max(2.4, 1.25 * len(round_summaries) + 1.2))
    )
    for row, summary in enumerate(round_summaries):
        for column, idea in enumerate(summary.ideas):
            axis.add_patch(
                Rectangle(
                    (column, row),
                    1,
                    1,
                    facecolor=verdict_colors[idea.verdict],
                    edgecolor="white",
                    linewidth=2,
                )
            )
            axis.text(
                column + 0.5,
                row + 0.5,
                f"{idea.idea_id}\n{idea.verdict}",
                ha="center",
                va="center",
                color="white" if idea.verdict != "inconclusive" else "black",
                fontweight="bold",
            )
    axis.set_xlim(0, 3)
    axis.set_ylim(len(round_summaries), 0)
    axis.set_xticks([0.5, 1.5, 2.5], ["Idea 1", "Idea 2", "Idea 3"])
    axis.set_yticks(
        [index + 0.5 for index in range(len(round_summaries))],
        [f"Round {summary.round}" for summary in round_summaries],
    )
    axis.set_title("Auto Research idea outcomes")
    for spine in axis.spines.values():
        spine.set_visible(False)
    axis.tick_params(length=0)
    figure.tight_layout()
    figure.savefig(status_path, dpi=160, bbox_inches="tight")
    plt.close(figure)

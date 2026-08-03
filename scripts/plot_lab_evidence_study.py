from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import FancyBboxPatch


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "outputs/lab_evidence_benchmark_v2"
OUT = ROOT / "outputs/lab_evidence_figures_v2"
SUMMARY = json.loads((DATA / "lab_evidence_benchmark_summary.json").read_text(encoding="utf-8"))

MODELS = ["qwen2.5-3b", "smollm2-1.7b", "phi3.5-mini"]
MODEL_LABELS = ["Qwen2.5-3B", "SmolLM2-1.7B", "Phi-3.5-mini"]
METHODS = ["mcp_access_only", "confidence_abstention", "mcp_governed"]
METHOD_LABELS = ["Evidence access", "Confidence abstention", "MCP governed"]
COLORS = ["#D9826A", "#6F7F9A", "#287C76"]


def style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.labelsize": 9.5,
            "axes.titlesize": 10.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.linewidth": 0.8,
            "xtick.direction": "out",
            "ytick.direction": "out",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.png", dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(OUT / f"{name}.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def authority_map() -> None:
    fig, ax = plt.subplots(figsize=(9.6, 3.8))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 7)
    ax.axis("off")
    columns = [
        (
            0.1,
            "Evidence state",
            [
                ("Traceable", "value, unit, time, source\nand encounter retained"),
                ("Detectably invalid", "missing, stale, wrong unit,\nconflict, mismatch, or outage"),
                ("Silently substituted", "plausible value with no\nobservable provenance defect"),
            ],
        ),
        (
            4.25,
            "Evidence responsibility",
            [
                ("MCP evidence adapter", "preserves state transitions\nand provenance fields"),
                ("Deterministic contract", "rejects anomalous records\nand owns thresholds"),
                ("Bounded model", "interprets only residual\nvalid-evidence cases"),
            ],
        ),
        (
            8.4,
            "Decision authority",
            [
                ("Approval eligible", "only after validity and\nthreshold checks pass"),
                ("Review required", "model approval cannot\noverride the contract"),
                ("Outside authority", "silent provenance failure\ncannot be detected from current fields"),
            ],
        ),
    ]
    fills = ["#EEF3F2", "#F8ECE8", "#F1F2F4"]
    for x, title, items in columns:
        ax.text(x + 1.55, 6.55, title, ha="center", va="center", weight="bold", fontsize=10.5)
        for index, (head, body) in enumerate(items):
            y = 4.95 - index * 1.75
            box = FancyBboxPatch(
                (x, y),
                3.1,
                1.25,
                boxstyle="round,pad=0.02,rounding_size=0.05",
                facecolor=fills[index],
                edgecolor="#707780",
                linewidth=0.9,
            )
            ax.add_patch(box)
            ax.text(x + 0.16, y + 0.84, head, weight="bold", fontsize=9.1, va="center")
            ax.text(x + 0.16, y + 0.39, body, fontsize=7.7, va="center", color="#33373C", linespacing=1.1)
    for y in [5.58, 3.83, 2.08]:
        ax.annotate("", xy=(4.08, y), xytext=(3.38, y), arrowprops=dict(arrowstyle="->", color="#6B7076", lw=1.2))
        ax.annotate("", xy=(8.23, y), xytext=(7.53, y), arrowprops=dict(arrowstyle="->", color="#6B7076", lw=1.2))
    ax.text(
        6,
        0.16,
        "The contribution constrains approval authority. Connectivity and molecular context do not expand it.",
        ha="center",
        color="#287C76",
        weight="bold",
        fontsize=9.2,
    )
    save(fig, "Fig1_lab_evidence_authority")


def metric_lookup(section: str = "overall") -> dict[tuple[str, str], dict]:
    return {(row["model"], row["method"]): row for row in SUMMARY[section]}


def interval_errors(row: dict, key: str) -> tuple[float, float]:
    value = 100 * row[key]
    low, high = row[f"{key}_domain_bootstrap_95ci"]
    return value - 100 * low, 100 * high - value


def main_outcomes() -> None:
    lookup = metric_lookup()
    x = np.arange(len(MODELS))
    width = 0.23
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.5), sharex=True)
    specs = [
        ("unsafe_approval", "Unsafe approval among required reviews (%)", 12),
        ("unnecessary_escalation", "Unnecessary escalation among approvals (%)", 108),
    ]
    for ax, (metric, ylabel, ymax) in zip(axes, specs):
        for offset, method, label, color in zip([-width, 0, width], METHODS, METHOD_LABELS, COLORS):
            rows = [lookup[(model, method)] for model in MODELS]
            values = np.array([100 * row[metric] for row in rows])
            errors = np.array([interval_errors(row, metric) for row in rows]).T
            bars = ax.bar(x + offset, values, width, color=color, edgecolor="white", yerr=errors, capsize=2.5, label=label)
            for bar, value in zip(bars, values):
                inside = value > 96
                y = value - ymax * 0.055 if inside else value + ymax * 0.025
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    y,
                    f"{value:.1f}",
                    ha="center",
                    va="top" if inside else "baseline",
                    fontsize=7.4,
                    color="white" if inside else "black",
                    weight="bold" if inside else "normal",
                    rotation=90 if inside else 0,
                )
        rule = lookup[(MODELS[0], "deterministic_rules")][metric] * 100
        ax.axhline(rule, color="#6D737A", linestyle="--", linewidth=1.1)
        if rule > 0:
            ax.text(2.36, rule + ymax * 0.018, f"Rule baseline {rule:.1f}%", ha="right", color="#555B62", fontsize=7.6)
        ax.set_xticks(x, MODEL_LABELS)
        ax.set_ylabel(ylabel)
        ax.set_ylim(0, ymax)
        ax.grid(axis="y", linestyle="--", linewidth=0.6, alpha=0.25)
    axes[0].set_title("Safety boundary")
    axes[1].set_title("Workflow cost boundary")
    handles, labels = axes[1].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, fontsize=8, loc="lower center", bbox_to_anchor=(0.5, -0.06), ncol=3)
    fig.suptitle("Equal-model-forward authority replacement on 528 synthetic cases", y=1.03, fontsize=11)
    save(fig, "Fig2_multimodel_authority_ablation")


def detectable_faults() -> None:
    states = ["missing", "stale", "unit_error", "conflict", "wrong_encounter", "service_failure"]
    state_labels = ["Missing", "Stale", "Unit error", "Conflict", "Wrong encounter", "Service failure"]
    rows = {(row["model"], row["method"], row["state"]): row for row in SUMMARY["detectable_faults"]}
    columns = []
    labels = []
    for model, model_label in zip(MODELS, MODEL_LABELS):
        for method, short in [("mcp_access_only", "Access"), ("mcp_governed", "Governed")]:
            columns.append([100 * rows[(model, method, state)]["unsafe_approval"] for state in states])
            labels.append(f"{model_label}\n{short}")
    matrix = np.array(columns).T
    cmap = LinearSegmentedColormap.from_list("risk", ["#EEF3F2", "#F0C2B6", "#A83E3A"])
    fig, ax = plt.subplots(figsize=(7.7, 3.7))
    image = ax.imshow(matrix, cmap=cmap, vmin=0, vmax=max(30, float(matrix.max())), aspect="auto")
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            ax.text(j, i, f"{matrix[i, j]:.1f}", ha="center", va="center", fontsize=8, color="white" if matrix[i, j] > 18 else "#202428")
    ax.set_xticks(range(len(labels)), labels)
    ax.set_yticks(range(len(states)), state_labels)
    ax.set_title("Unsafe approval under six detectable evidence failures (44 cases per state)")
    fig.colorbar(image, ax=ax, fraction=0.025, pad=0.02, label="Unsafe approval (%)")
    save(fig, "Fig3_detectable_faults")


def failure_boundary() -> None:
    main = metric_lookup("overall")
    boundary = metric_lookup("failure_boundary")
    fig, axes = plt.subplots(1, 2, figsize=(9.0, 3.55), sharey=True)
    for ax, lookup, title in [(axes[0], main, "Observable main benchmark"), (axes[1], boundary, "Silent plausible substitution")]:
        matrix = np.array([[100 * lookup[(model, method)]["unsafe_approval"] for method in METHODS] for model in MODELS])
        image = ax.imshow(matrix, cmap="Reds", vmin=0, vmax=100, aspect="auto")
        for i in range(matrix.shape[0]):
            for j in range(matrix.shape[1]):
                ax.text(j, i, f"{matrix[i, j]:.1f}", ha="center", va="center", fontsize=9, color="white" if matrix[i, j] > 55 else "#202428")
        ax.set_xticks(range(len(METHODS)), ["Access", "Abstain", "Governed"])
        ax.set_title(title)
    axes[0].set_yticks(range(len(MODELS)), MODEL_LABELS)
    axes[1].tick_params(axis="y", left=False, labelleft=False)
    fig.colorbar(image, ax=axes, fraction=0.025, pad=0.025, label="Unsafe approval (%)")
    fig.suptitle("The authority boundary depends on observable provenance and model behavior", y=1.01, fontsize=11)
    save(fig, "Fig4_failure_boundary")


def domain_confusion() -> None:
    rows = {(row["model"], row["method"], row["domain"]): row for row in SUMMARY["per_domain_confusion"]}
    domains = sorted({row["domain"] for row in SUMMARY["per_domain_confusion"]})
    short = [name.replace(" carbonate", "").replace(" sodium", "") for name in domains]
    fig, axes = plt.subplots(1, 3, figsize=(9.7, 5.0), sharey=True)
    for ax, model, label in zip(axes, MODELS, MODEL_LABELS):
        matrix = np.array([[rows[(model, "mcp_governed", domain)][key] for key in ["tp", "tn", "fp", "fn"]] for domain in domains])
        image = ax.imshow(matrix, cmap="Blues", vmin=0, vmax=36, aspect="auto")
        for i in range(matrix.shape[0]):
            for j in range(4):
                ax.text(j, i, str(matrix[i, j]), ha="center", va="center", fontsize=7.5, color="white" if matrix[i, j] > 22 else "#202428")
        ax.set_xticks(range(4), ["TP", "TN", "FP", "FN"])
        ax.set_title(label)
    axes[0].set_yticks(range(len(domains)), short)
    fig.colorbar(image, ax=axes, fraction=0.018, pad=0.02, label="Case count")
    fig.suptitle("Domain-level confusion counts for MCP-governed decisions", y=0.99, fontsize=11)
    save(fig, "FigS1_domain_confusion")


def sensitivity_and_stability() -> None:
    curve = SUMMARY["confidence_threshold_curve"]
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.3))
    for model, label, color in zip(MODELS, MODEL_LABELS, ["#287C76", "#6F7F9A", "#D9826A"]):
        rows = sorted((row for row in curve if row["model"] == model), key=lambda row: row["threshold"])
        thresholds = [row["threshold"] for row in rows]
        axes[0].plot(thresholds, [100 * row["unsafe_approval"] for row in rows], marker="o", color=color, label=label)
        axes[1].plot(thresholds, [100 * row["unnecessary_escalation"] for row in rows], marker="o", color=color, label=label)
    axes[0].set(ylabel="Unsafe approval (%)", xlabel="Abstention threshold", ylim=(-1, 12))
    axes[1].set(ylabel="Unnecessary escalation (%)", xlabel="Abstention threshold", ylim=(0, 105))
    stability = SUMMARY["stability"]
    x = np.arange(len(MODELS))
    batch_diff = [100 * stability[model]["batch1_repeat0"]["max_probability_difference"] for model in MODELS]
    repeat_diff = [100 * stability[model]["batch8_repeat2"]["max_probability_difference"] for model in MODELS]
    axes[2].bar(x - 0.17, repeat_diff, 0.34, color="#6F7F9A", label="Repeat, batch 8")
    axes[2].bar(x + 0.17, batch_diff, 0.34, color="#287C76", label="Batch 1 vs 8")
    axes[2].set_xticks(x, ["Qwen", "SmolLM2", "Phi"])
    axes[2].set_ylabel("Maximum probability shift (points)")
    axes[2].set_title("All decision agreements = 100%")
    for ax in axes:
        ax.grid(axis="y", linestyle="--", linewidth=0.6, alpha=0.25)
    axes[0].legend(frameon=False, fontsize=7.2)
    axes[2].legend(frameon=False, fontsize=7.2)
    fig.suptitle("Confidence-abstention sensitivity and deterministic decision stability", y=1.03, fontsize=11)
    save(fig, "FigS2_sensitivity_stability")


def protocol_comparison() -> None:
    latency = SUMMARY["protocol"]["latency_ms"]
    labels = ["Context\ndirect", "Context\nMCP", "Review\ndirect", "Review\nMCP"]
    medians = [latency["direct_context_median"], latency["mcp_context_median"], latency["direct_review_median"], latency["mcp_review_median"]]
    p95 = [latency["direct_context_p95"], latency["mcp_context_p95"], latency["direct_review_p95"], latency["mcp_review_p95"]]
    colors = ["#AAB0B6", "#287C76", "#AAB0B6", "#287C76"]
    fig, ax = plt.subplots(figsize=(5.8, 3.3))
    x = np.arange(4)
    bars = ax.bar(x, medians, color=colors, width=0.65)
    ax.scatter(x, p95, marker="_", s=300, color="#A83E3A", linewidth=1.8, label="95th percentile")
    for bar, value in zip(bars, medians):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.08, f"{value:.3f}", ha="center", fontsize=8)
    ax.set_xticks(x, labels)
    ax.set_ylabel("Latency (ms, model inference excluded)")
    ax.set_ylim(0, 4.3)
    ax.grid(axis="y", linestyle="--", linewidth=0.6, alpha=0.25)
    ax.legend(frameon=False, loc="upper left")
    ax.set_title("Real MCP stdio and direct calls returned identical evidence and decisions\n(660/660 cases)")
    save(fig, "FigS3_protocol_comparison")


def main() -> None:
    style()
    authority_map()
    main_outcomes()
    detectable_faults()
    failure_boundary()
    domain_confusion()
    sensitivity_and_stability()
    protocol_comparison()
    print(f"wrote figures to {OUT}")


if __name__ == "__main__":
    main()

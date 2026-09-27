"""Build the manuscript artifacts from results/peds_abstraction/*.csv:

  results/peds_abstraction/tables/table2_model_by_domain.md   (fills the paper's Table 2)
  results/peds_abstraction/tables/table3_reliability.md
  results/peds_abstraction/tables/table4_error_counts.md
  results/peds_abstraction/figures/fig_ageband_f1.png         (the age-band degradation figure)
  results/peds_abstraction/figures/fig_error_distribution.png

Figures use journal-safe defaults: single panel, grayscale-safe, labeled axes.
"""
from __future__ import annotations
import glob
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def md_table(df, path, floatfmt="{:.3f}"):
    d = df.copy()
    for c in d.columns:
        if d[c].dtype.kind == "f":
            d[c] = d[c].map(lambda v: floatfmt.format(v) if pd.notna(v) else "")
    lines = ["| " + " | ".join(d.columns) + " |",
             "| " + " | ".join(["---"] * len(d.columns)) + " |"]
    for _, r in d.iterrows():
        lines.append("| " + " | ".join(str(v) for v in r.values) + " |")
    open(path, "w").write("\n".join(lines) + "\n")


def main():
    os.makedirs("results/peds_abstraction/tables", exist_ok=True)
    os.makedirs("results/peds_abstraction/figures", exist_ok=True)

    scores = pd.read_csv("results/peds_abstraction/scores.csv")
    summary = pd.read_csv("results/peds_abstraction/summary.csv")
    ageband = pd.read_csv("results/peds_abstraction/ageband.csv")

    # Table 2: model x domain P/R/F1 (run 1)
    d1 = scores[scores.run == 1]
    t2 = (d1.groupby(["model", "domain"])
             .apply(lambda g: pd.Series({
                 "precision": g.tp.sum() / max(g.tp.sum() + g.fp.sum(), 1),
                 "recall": g.tp.sum() / max(g.tp.sum() + g.fn.sum(), 1)}),
                 include_groups=False)
             .reset_index())
    t2["f1"] = 2 * t2.precision * t2.recall / (t2.precision + t2.recall).clip(lower=1e-9)
    md_table(t2, "results/peds_abstraction/tables/table2_model_by_domain.md")

    # Table 3: reliability
    md_table(summary[["model", "field_accuracy", "exact_match",
                      "stability_rate", "parse_failure_rate"]],
             "results/peds_abstraction/tables/table3_reliability.md")

    # Table 4: error counts
    if os.path.exists("results/peds_abstraction/error_rates.csv"):
        md_table(pd.read_csv("results/peds_abstraction/error_rates.csv"),
                 "results/peds_abstraction/tables/table4_error_counts.md", floatfmt="{:.0f}")

    # Figure: macro-F1 by age band per model, with CIs (grouped bars)
    bands = ["neonate", "infant", "child", "adolescent"]
    models = sorted(ageband.model.unique())
    fig, ax = plt.subplots(figsize=(7, 4))
    width = 0.8 / max(len(models), 1)
    hatches = ["", "//", "..", "xx"]
    for mi, model in enumerate(models):
        sub = ageband[ageband.model == model].set_index("band").reindex(bands)
        xs = [i + mi * width for i in range(len(bands))]
        err = [sub.f1 - sub.ci_low, sub.ci_high - sub.f1]
        ax.bar(xs, sub.f1, width=width * 0.95, label=model,
               hatch=hatches[mi % 4], edgecolor="black", linewidth=0.5)
        ax.errorbar(xs, sub.f1, yerr=err, fmt="none", ecolor="black",
                    elinewidth=0.8, capsize=2)
    ax.set_xticks([i + width * (len(models) - 1) / 2 for i in range(len(bands))])
    ax.set_xticklabels([b.capitalize() for b in bands])
    ax.set_ylabel("Macro-F1 (95% CI)")
    ax.set_ylim(0, 1)
    ax.legend(fontsize=7, frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig("results/peds_abstraction/figures/fig_ageband_f1.png", dpi=300)

    # Figure: error class distribution (stacked bars per model)
    if os.path.exists("results/peds_abstraction/error_rates.csv"):
        er = pd.read_csv("results/peds_abstraction/error_rates.csv")
        pivot = er.pivot_table(index="model", columns="error_class",
                               values="count", aggfunc="sum", fill_value=0)
        ax2 = pivot.plot(kind="bar", stacked=True, figsize=(8, 4.5),
                         colormap="tab20", edgecolor="black", linewidth=0.3)
        ax2.set_ylabel("Error count (run 1)")
        ax2.legend(fontsize=6, ncol=2, frameon=False)
        ax2.figure.tight_layout()
        ax2.figure.savefig("results/peds_abstraction/figures/fig_error_distribution.png", dpi=300)

    print("tables and figures written to results/peds_abstraction/")


if __name__ == "__main__":
    main()

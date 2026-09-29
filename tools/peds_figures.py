"""Manuscript figures for the pediatric abstraction benchmark.

Reads results/peds_abstraction/*.csv (primary + secondary) and writes
results/peds_abstraction/figures/fig{N}_*.png at 300 dpi. Journal style:
one hue per model in fixed order, hatch textures for grayscale print,
95% CIs as error bars, no dual axes.

Usage: python tools/peds_figures.py
"""
from __future__ import annotations
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

R = "results/peds_abstraction/"
OUT = R + "figures/"
MODELS = ["openai_gpt-5-5-2026-04-23", "anthropic_claude-sonnet-5",
          "google_gemini-3-1-pro-preview", "deepseek_deepseek-v4-pro"]
LABEL = {"openai_gpt-5-5-2026-04-23": "GPT-5.5", "anthropic_claude-sonnet-5": "Claude Sonnet 5",
         "google_gemini-3-1-pro-preview": "Gemini 3.1 Pro", "deepseek_deepseek-v4-pro": "DeepSeek V4 Pro"}
COLOR = {"openai_gpt-5-5-2026-04-23": "#0072B2", "anthropic_claude-sonnet-5": "#E69F00",
         "google_gemini-3-1-pro-preview": "#009E73", "deepseek_deepseek-v4-pro": "#CC79A7"}
HATCH = {"openai_gpt-5-5-2026-04-23": "", "anthropic_claude-sonnet-5": "//",
         "google_gemini-3-1-pro-preview": "..", "deepseek_deepseek-v4-pro": "xx"}
BANDS = ["neonate", "infant", "child", "adolescent"]
DOMS = ["diagnoses", "medications", "labs", "procedures", "temporal"]

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.linewidth": 0.6, "hatch.linewidth": 0.4})


def grouped_bars(ax, cats, series, ylabel, ylim=(0, 1.02), ci=None, width_total=0.8):
    n = len(series)
    w = width_total / n
    for i, (m, vals) in enumerate(series.items()):
        xs = [c + (i - (n - 1) / 2) * w for c in range(len(cats))]
        ax.bar(xs, vals, width=w * 0.92, color=COLOR[m], hatch=HATCH[m], edgecolor="black",
               linewidth=0.4, label=LABEL[m])
        if ci is not None:
            lo, hi = ci[m]
            ax.errorbar(xs, vals, yerr=[[v - l for v, l in zip(vals, lo)], [h - v for v, h in zip(vals, hi)]],
                        fmt="none", ecolor="black", elinewidth=0.6, capsize=1.5)
    ax.set_xticks(range(len(cats)))
    ax.set_xticklabels([c.capitalize() for c in cats])
    ax.set_ylim(*ylim)
    ax.set_ylabel(ylabel)
    ax.yaxis.grid(True, linewidth=0.3, color="#cccccc")
    ax.set_axisbelow(True)


def fig1_band_by_matching():
    bb = pd.read_csv(R + "secondary_band_breakdown.csv")
    fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.9), sharey=True)
    for ax, (key, title) in zip(axes, [("strict", "(a) Strict (pre-specified)"),
                                       ("lenient", "(b) Lenient"),
                                       ("hard", "(c) Hard clinical facts")]):
        series, ci = {}, {}
        for m in MODELS:
            sub = bb[bb.model == m].set_index("band").reindex(BANDS)
            series[m] = sub[f"{key}_f1"].tolist()
            ci[m] = (sub[f"{key}_ci_low"].tolist(), sub[f"{key}_ci_high"].tolist())
        grouped_bars(ax, BANDS, series, "Per-record F1 (95% CI)" if key == "strict" else "", ci=ci)
        ax.set_title(title, fontsize=8, loc="left")
        ax.set_xticklabels(["Neonate", "Infant", "Child", "Adolesc."], fontsize=7)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, fontsize=7, frameon=False, loc="upper center", ncol=4,
               bbox_to_anchor=(0.5, 1.02))
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(OUT + "fig1_ageband_f1_by_matching.png", dpi=300)
    plt.close(fig)


def fig2_domain_lenient():
    d = pd.read_csv(R + "secondary_lenient_by_domain.csv")
    fig, ax = plt.subplots(figsize=(7.2, 2.6))
    series = {m: [float(d[(d.model == m) & (d.domain == dom)].f1.iloc[0]) for dom in DOMS] for m in MODELS}
    grouped_bars(ax, DOMS, series, "Lenient F1 (run 1)", ylim=(0, 1.12))
    for i, m in enumerate(MODELS):   # direct labels on the temporal group only
        x = 4 + (i - 1.5) * 0.2
        ax.text(x, series[m][4] + 0.02, f"{series[m][4]:.2f}", ha="center", va="bottom", fontsize=6)
    ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.legend(fontsize=6.5, frameon=False, loc="upper left", ncol=4)
    fig.tight_layout()
    fig.savefig(OUT + "fig2_domain_f1_lenient.png", dpi=300)
    plt.close(fig)


def fig3_disagreement_composition():
    """Stacked composition of strict-scoring item outcomes per model (run 1)."""
    sc = pd.read_csv(R + "scores.csv")
    d1 = sc[sc.run == 1].groupby("model")[["tp", "fp", "fn"]].sum()
    lm = pd.read_csv(R + "secondary_lenient_by_domain.csv").groupby("model")[["tp", "fp", "fn"]].sum()
    ls = pd.read_csv(R + "secondary_lenient_summary.csv").set_index("model")
    rows = []
    for m in MODELS:
        strict_fp, strict_fn = int(d1.loc[m, "fp"]), int(d1.loc[m, "fn"])
        len_fp, len_fn = int(lm.loc[m, "fp"]), int(lm.loc[m, "fn"])
        red = int(ls.loc[m, "redundant_encodings"])
        gran = max(strict_fp - red - len_fp, 0)
        rows.append(dict(model=m, granularity=gran, redundant=red, residual_fp=len_fp,
                         fn_recovered=strict_fn - len_fn, residual_fn=len_fn))
    df = pd.DataFrame(rows).set_index("model")
    fig, ax = plt.subplots(figsize=(7.2, 2.6))
    parts = [("granularity", "Same fact, different granularity (event/when split)", "#bbbbbb", ""),
             ("redundant", "Same fact, encoded under another domain", "#888888", "//"),
             ("residual_fp", "Remaining false positives", "#333333", "xx")]
    x = range(len(MODELS))
    bottom = [0] * len(MODELS)
    for col, lab, color, hatch in parts:
        vals = [int(df.loc[m, col]) for m in MODELS]
        ax.bar(x, vals, bottom=bottom, color=color, hatch=hatch, edgecolor="black", linewidth=0.4, label=lab, width=0.6)
        bottom = [b + v for b, v in zip(bottom, vals)]
    for i, m in enumerate(MODELS):
        ax.text(i, bottom[i] + 8, f"n={bottom[i]}", ha="center", fontsize=6.5)
    ax.set_xticks(list(x))
    ax.set_xticklabels([LABEL[m] for m in MODELS])
    ax.set_ylabel("Strict false-positive items (run 1)")
    ax.yaxis.grid(True, linewidth=0.3, color="#cccccc"); ax.set_axisbelow(True)
    ax.legend(fontsize=6.5, frameon=False, loc="upper right")
    fig.tight_layout()
    fig.savefig(OUT + "fig3_false_positive_composition.png", dpi=300)
    plt.close(fig)
    df.to_csv(R + "fig3_false_positive_composition.csv")
    return df


def fig4_stability_by_domain():
    ds = pd.read_csv(R + "secondary_domain_stability.csv")
    fig, ax = plt.subplots(figsize=(7.2, 2.6))
    series = {m: [float(ds[(ds.model == m) & (ds.domain == dom)].keyset_stability.iloc[0]) for dom in DOMS]
              for m in MODELS}
    grouped_bars(ax, DOMS, series, "Run-to-run key-set stability", ylim=(0, 1.15))
    ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.legend(fontsize=6.5, frameon=False, loc="upper left", ncol=4)
    fig.tight_layout()
    fig.savefig(OUT + "fig4_stability_by_domain.png", dpi=300)
    plt.close(fig)


def main():
    os.makedirs(OUT, exist_ok=True)
    fig1_band_by_matching()
    fig2_domain_lenient()
    comp = fig3_disagreement_composition()
    fig4_stability_by_domain()
    print(comp.to_string())
    print("figures written to", OUT)


if __name__ == "__main__":
    main()

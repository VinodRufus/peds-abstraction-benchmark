"""Additional pre-specified analyses for the pediatric abstraction benchmark.

Runs AFTER src/peds_abstraction/score.py and errors.py. Reads runs/ and
results/peds_abstraction/scores.csv. Writes:

  results/peds_abstraction/fairness_band_domain.csv   F1 per model x age band x domain (run 1)
  results/peds_abstraction/fairness_disparity.csv     per model: band macro-F1 spread, min/max ratio, exact-match by band
  results/peds_abstraction/hypothesis_unpaired.csv    adolescent-vs-neonate difference, independent bootstrap (sensitivity)
  results/peds_abstraction/field_accuracy_exact.csv   per model x scalar field accuracy with exact Clopper-Pearson 95% CI
  results/peds_abstraction/ablation.csv               schema prompt vs free-text prompt on the ablation subset, paired bootstrap
  results/peds_abstraction/runs_meta.csv              per model: versions seen, calls, latency, tokens, date span, errors

Usage: python tools/peds_extra_stats.py
"""
from __future__ import annotations
import glob
import json
import math
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "src")
from common.stats import bootstrap_metric, paired_bootstrap  # noqa: E402
from peds_abstraction.score import score_lists, score_scalars, prf, band_of  # noqa: E402

SEED = 20260923
N_BOOT = 10000
BANDS = ["neonate", "infant", "child", "adolescent"]
OUT = "results/peds_abstraction"


# ---------- exact binomial (Clopper-Pearson) ----------
def _binom_cdf(k, n, p):
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(0, k + 1))


def clopper_pearson(k, n, alpha=0.05):
    if n == 0:
        return (float("nan"), float("nan"))
    lo, hi = 0.0, 1.0
    if k > 0:
        a, b = 0.0, 1.0
        for _ in range(80):
            m = (a + b) / 2
            if 1 - _binom_cdf(k - 1, n, m) < alpha / 2:
                a = m
            else:
                b = m
        lo = a
    if k < n:
        a, b = 0.0, 1.0
        for _ in range(80):
            m = (a + b) / 2
            if _binom_cdf(k, n, m) < alpha / 2:
                b = m
            else:
                a = m
        hi = b
    return (lo, hi)


def per_record_f1(df):
    return df.groupby("record").apply(
        lambda g: prf(g.tp.sum(), g.fp.sum(), g.fn.sum())[2], include_groups=False)


def main():
    os.makedirs(OUT, exist_ok=True)
    gold = {os.path.basename(p)[:-5]: json.load(open(p))
            for p in glob.glob("data/peds_abstraction/gold/*.json")}
    scores = pd.read_csv(f"{OUT}/scores.csv")
    d1 = scores[scores.run == 1]
    models = sorted(d1.model.unique())

    # ---------- fairness audit: band x domain F1, disparity ----------
    fb_rows, disp_rows = [], []
    for m in models:
        dm = d1[d1.model == m]
        band_macro = {}
        for band in BANDS:
            db = dm[dm.band == band]
            if db.empty:
                continue
            dom_f1 = []
            for dom, g in db.groupby("domain"):
                p, r, f = prf(g.tp.sum(), g.fp.sum(), g.fn.sum())
                fb_rows.append(dict(model=m, band=band, domain=dom, precision=p, recall=r,
                                    f1=f, n_gold=int(g.n_gold.sum()), n_pred=int(g.n_pred.sum())))
                dom_f1.append(f)
            band_macro[band] = float(np.mean(dom_f1))
        if band_macro:
            vals = list(band_macro.values())
            disp_rows.append(dict(model=m, **{f"macro_f1_{b}": band_macro.get(b) for b in BANDS},
                                  spread_max_minus_min=max(vals) - min(vals),
                                  ratio_min_over_max=(min(vals) / max(vals)) if max(vals) else float("nan"),
                                  worst_band=min(band_macro, key=band_macro.get),
                                  best_band=max(band_macro, key=band_macro.get)))
    pd.DataFrame(fb_rows).to_csv(f"{OUT}/fairness_band_domain.csv", index=False)
    pd.DataFrame(disp_rows).to_csv(f"{OUT}/fairness_disparity.csv", index=False)

    # ---------- unpaired sensitivity for the primary hypothesis ----------
    rng = np.random.default_rng(SEED)
    hu_rows = []
    for m in models:
        dm = d1[d1.model == m]
        neo = per_record_f1(dm[dm.band == "neonate"]).values
        ado = per_record_f1(dm[dm.band == "adolescent"]).values
        if len(neo) and len(ado):
            bi = rng.integers(0, len(neo), size=(N_BOOT, len(neo)))
            bj = rng.integers(0, len(ado), size=(N_BOOT, len(ado)))
            diffs = ado[bj].mean(axis=1) - neo[bi].mean(axis=1)
            hu_rows.append(dict(model=m, mean_ado=float(ado.mean()), mean_neo=float(neo.mean()),
                                diff_ado_minus_neo=float(ado.mean() - neo.mean()),
                                ci_low=float(np.percentile(diffs, 2.5)),
                                ci_high=float(np.percentile(diffs, 97.5)),
                                n_neo=len(neo), n_ado=len(ado)))
    pd.DataFrame(hu_rows).to_csv(f"{OUT}/hypothesis_unpaired.csv", index=False)

    # ---------- per-field accuracy with exact CI (run 1), and ablation ----------
    fa_rows, ab_rows, meta_rows = [], [], []
    for mdir in sorted(glob.glob("runs/peds_abstraction/*/")):
        m = os.path.basename(os.path.dirname(mdir))
        # run 1 field accuracy
        p1 = os.path.join(mdir, "run1.jsonl")
        if os.path.exists(p1):
            flags = {}
            for line in open(p1):
                rec = json.loads(line)
                rid = rec["record_id"]
                if rid not in gold:
                    continue
                for fname, ok in score_scalars(rec.get("parsed") or {}, gold[rid]).items():
                    flags.setdefault(fname, []).append(bool(ok))
            for fname, oks in sorted(flags.items()):
                k, n = sum(oks), len(oks)
                lo, hi = clopper_pearson(k, n)
                fa_rows.append(dict(model=m, field=fname, correct=k, n=n,
                                    accuracy=k / n if n else float("nan"),
                                    exact_ci_low=lo, exact_ci_high=hi))
        # ablation: free prompt (run1_ablation) vs schema prompt (run1) on the same records
        pa = os.path.join(mdir, "run1_ablation.jsonl")
        if os.path.exists(pa) and os.path.exists(p1):
            schema_out = {json.loads(l)["record_id"]: json.loads(l) for l in open(p1)}
            free_f1, schema_f1, free_pf, n_ab = [], [], 0, 0
            for line in open(pa):
                rec = json.loads(line)
                rid = rec["record_id"]
                if rid not in gold or rid not in schema_out:
                    continue
                n_ab += 1
                if rec.get("parsed") is None:
                    free_pf += 1
                sf = score_lists(rec.get("parsed") or {}, gold[rid])
                ss = score_lists(schema_out[rid].get("parsed") or {}, gold[rid])
                free_f1.append(prf(sum(v["tp"] for v in sf.values()), sum(v["fp"] for v in sf.values()),
                                   sum(v["fn"] for v in sf.values()))[2])
                schema_f1.append(prf(sum(v["tp"] for v in ss.values()), sum(v["fp"] for v in ss.values()),
                                     sum(v["fn"] for v in ss.values()))[2])
            if n_ab:
                diff = np.array(schema_f1) - np.array(free_f1)
                md, (lo, hi) = paired_bootstrap(diff)
                ab_rows.append(dict(model=m, n_records=n_ab,
                                    schema_prompt_f1=float(np.mean(schema_f1)),
                                    free_prompt_f1=float(np.mean(free_f1)),
                                    diff_schema_minus_free=md, ci_low=lo, ci_high=hi,
                                    free_prompt_parse_failure_rate=free_pf / n_ab))
        # run metadata
        recs = []
        for path in glob.glob(os.path.join(mdir, "run*.jsonl")):
            for line in open(path):
                recs.append(json.loads(line))
        if recs:
            versions = sorted({str(r.get("model_version")) for r in recs if r.get("model_version")})
            lat = [r["latency_ms"] for r in recs if r.get("latency_ms") is not None]
            tin = [r["tokens_in"] for r in recs if r.get("tokens_in") is not None]
            tout = [r["tokens_out"] for r in recs if r.get("tokens_out") is not None]
            ts = sorted(str(r.get("ts")) for r in recs if r.get("ts"))
            meta_rows.append(dict(
                model=m, model_id=recs[0].get("model_id"), n_calls=len(recs),
                n_api_errors=sum(1 for r in recs if r.get("error")),
                n_parse_failures=sum(1 for r in recs if r.get("parsed") is None and not r.get("error")),
                versions_seen=" || ".join(versions)[:400],
                mean_latency_s=float(np.mean(lat)) / 1000 if lat else None,
                mean_tokens_in=float(np.mean(tin)) if tin else None,
                mean_tokens_out=float(np.mean(tout)) if tout else None,
                first_call=ts[0] if ts else None, last_call=ts[-1] if ts else None,
                calendar_days=len({t[:10] for t in ts}) if ts else None))
    pd.DataFrame(fa_rows).to_csv(f"{OUT}/field_accuracy_exact.csv", index=False)
    pd.DataFrame(ab_rows).to_csv(f"{OUT}/ablation.csv", index=False)
    pd.DataFrame(meta_rows).to_csv(f"{OUT}/runs_meta.csv", index=False)

    pd.set_option("display.width", 200)
    print("\n=== fairness: band macro-F1 spread per model ===")
    print(pd.DataFrame(disp_rows).round(3).to_string(index=False))
    print("\n=== primary hypothesis, unpaired sensitivity (adolescent - neonate) ===")
    print(pd.DataFrame(hu_rows).round(3).to_string(index=False))
    print("\n=== ablation: schema prompt vs free-text prompt ===")
    print(pd.DataFrame(ab_rows).round(3).to_string(index=False))
    print("\n=== runs meta ===")
    print(pd.DataFrame(meta_rows)[["model", "n_calls", "n_api_errors", "n_parse_failures",
                                   "mean_latency_s", "mean_tokens_in", "mean_tokens_out",
                                   "calendar_days"]].round(2).to_string(index=False))
    print("\nwrote fairness_band_domain.csv, fairness_disparity.csv, hypothesis_unpaired.csv, "
          "field_accuracy_exact.csv, ablation.csv, runs_meta.csv")


if __name__ == "__main__":
    main()

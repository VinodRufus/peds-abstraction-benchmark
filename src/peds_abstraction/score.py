"""Score model runs against frozen gold.

Outputs:
  results/peds_abstraction/scores.csv        per record x model x run x domain: TP/FP/FN + PRF
  results/peds_abstraction/summary.csv       per model: macro/micro PRF w/ bootstrap CIs,
                              field accuracy, exact match, stability, parse fail
  results/peds_abstraction/ageband.csv       per model x age band macro-F1 + CI
  results/peds_abstraction/hypothesis.csv    adolescent vs neonate paired test per model
  results/peds_abstraction/pairwise.csv      McNemar + Holm across model pairs (per-field)

Parse failures score as all-FN and are reported as a separate rate.
"""
from __future__ import annotations
import glob
import json
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import normalize as N  # noqa: E402
from common.stats import bootstrap_metric, paired_bootstrap, mcnemar_test, holm  # noqa: E402

LIST_DOMAINS = {
    "diagnoses": (N.dx_key, N.dx_equal),
    "medications": (N.med_key, N.med_equal),
    "labs": (N.lab_key, N.lab_equal),
    "procedures": (N.proc_key, N.proc_equal),
    "temporal": (N.temporal_key, N.temporal_equal),
}
SCALAR_FIELDS = [
    ("demographics", "age_value", N.norm_value),
    ("demographics", "age_unit", N.norm_name),
    ("demographics", "sex", N.norm_name),
    ("demographics", "weight_kg", N.norm_value),
    ("encounter", "setting", N.norm_name),
    ("encounter", "disposition", N.norm_name),
]


def band_of(record_id: str) -> str:
    return {"neo": "neonate", "inf": "infant", "chi": "child", "ado": "adolescent"}[
        record_id.split("-")[1]]


def score_lists(pred: dict, gold: dict):
    """Set-based TP/FP/FN per list domain, plus per-item correctness flags."""
    out = {}
    for dom, (key, equal) in LIST_DOMAINS.items():
        g = gold.get(dom) or []
        p = (pred.get(dom) or []) if isinstance(pred, dict) else []
        if not isinstance(p, list):
            p = []
        gk = {key(x): x for x in g if isinstance(x, dict)}
        pk = {}
        for x in p:
            if isinstance(x, dict) and key(x) is not None:
                pk.setdefault(key(x), x)
        tp = sum(1 for k in pk if k in gk and equal(pk[k], gk[k]))
        fp = len(pk) - sum(1 for k in pk if k in gk and equal(pk[k], gk[k]))
        fn = len(gk) - tp
        out[dom] = dict(tp=tp, fp=fp, fn=fn, n_gold=len(gk), n_pred=len(pk))
    return out


def score_scalars(pred: dict, gold: dict):
    flags = {}
    for dom, field, norm in SCALAR_FIELDS:
        gv = norm((gold.get(dom) or {}).get(field))
        pv = norm(((pred or {}).get(dom) or {}).get(field)) if isinstance(pred, dict) else None
        flags[f"{dom}.{field}"] = (gv == pv)
    return flags


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def main():
    gold = {os.path.basename(p)[:-5]: json.load(open(p))
            for p in glob.glob("data/peds_abstraction/gold/*.json")}
    if not gold:
        sys.exit("No gold found.")
    os.makedirs("results/peds_abstraction", exist_ok=True)

    rows, field_flags, exact_rows = [], defaultdict(dict), []
    outputs = defaultdict(dict)   # (model, rid) -> {run: parsed}
    parse_stats = defaultdict(lambda: [0, 0])

    for path in glob.glob("runs/peds_abstraction/*/run*.jsonl"):
        if "_ablation" in path:
            continue
        model = path.split(os.sep)[-2]
        for line in open(path):
            rec = json.loads(line)
            rid, run, parsed = rec["record_id"], rec["run"], rec.get("parsed")
            if rid not in gold:
                continue
            parse_stats[model][1] += 1
            if parsed is None:
                parse_stats[model][0] += 1
            outputs[(model, rid)][run] = parsed
            dom_scores = score_lists(parsed or {}, gold[rid])
            scal = score_scalars(parsed or {}, gold[rid])
            for dom, s in dom_scores.items():
                p, r, f = prf(s["tp"], s["fp"], s["fn"])
                rows.append(dict(model=model, record=rid, run=run,
                                 band=band_of(rid), domain=dom, **s,
                                 precision=p, recall=r, f1=f))
            all_ok = all(scal.values()) and all(
                s["fp"] == 0 and s["fn"] == 0 for s in dom_scores.values())
            exact_rows.append(dict(model=model, record=rid, run=run, exact=all_ok))
            for fname, ok in scal.items():
                field_flags[(model, run)].setdefault(fname, {})[rid] = ok

    df = pd.DataFrame(rows)
    df.to_csv("results/peds_abstraction/scores.csv", index=False)
    ex = pd.DataFrame(exact_rows)

    # ---- summary per model (primary run = run 1; stability across runs) ----
    summary = []
    for model in sorted(df.model.unique()):
        d1 = df[(df.model == model) & (df.run == 1)]
        # micro
        mp, mr, mf = prf(d1.tp.sum(), d1.fp.sum(), d1.fn.sum())
        # macro across domains
        dom_f1 = d1.groupby("domain").apply(
            lambda g: prf(g.tp.sum(), g.fp.sum(), g.fn.sum())[2], include_groups=False)
        # per-record micro-F1 vector for CI
        per_rec = d1.groupby("record").apply(
            lambda g: prf(g.tp.sum(), g.fp.sum(), g.fn.sum())[2], include_groups=False).values
        mean_f1, (lo, hi) = bootstrap_metric(per_rec)
        # field accuracy (run 1)
        ff = field_flags.get((model, 1), {})
        accs = [ok for fmap in ff.values() for ok in fmap.values()]
        # stability across the 3 runs: fraction of records whose parsed output
        # normalized-JSON is identical in all runs
        stable = 0
        total = 0
        for (m, rid), runs_map in outputs.items():
            if m != model or len(runs_map) < 2:
                continue
            total += 1
            vals = [json.dumps(v, sort_keys=True) for v in runs_map.values()]
            stable += int(len(set(vals)) == 1)
        pf, pt = parse_stats[model]
        summary.append(dict(
            model=model, micro_precision=mp, micro_recall=mr, micro_f1=mf,
            macro_f1=float(dom_f1.mean()), per_record_f1=mean_f1,
            f1_ci_low=lo, f1_ci_high=hi,
            field_accuracy=float(np.mean(accs)) if accs else None,
            exact_match=float(ex[(ex.model == model) & (ex.run == 1)].exact.mean()),
            stability_rate=(stable / total if total else None),
            parse_failure_rate=(pf / pt if pt else None)))
    pd.DataFrame(summary).to_csv("results/peds_abstraction/summary.csv", index=False)

    # ---- age band macro-F1 + primary hypothesis ----
    ab_rows, hyp_rows = [], []
    for model in sorted(df.model.unique()):
        d1 = df[(df.model == model) & (df.run == 1)]
        per_rec = d1.groupby(["band", "record"]).apply(
            lambda g: prf(g.tp.sum(), g.fp.sum(), g.fn.sum())[2], include_groups=False)
        for band in ["neonate", "infant", "child", "adolescent"]:
            if band in per_rec.index.get_level_values(0):
                v = per_rec[band].values
                m_, (lo, hi) = bootstrap_metric(v)
                ab_rows.append(dict(model=model, band=band, f1=m_,
                                    ci_low=lo, ci_high=hi, n=len(v)))
        # paired by template position: sort records within band and pair
        neo = per_rec["neonate"].sort_index().values if "neonate" in per_rec.index.get_level_values(0) else []
        ado = per_rec["adolescent"].sort_index().values if "adolescent" in per_rec.index.get_level_values(0) else []
        n = min(len(neo), len(ado))
        if n:
            diff = np.array(ado[:n]) - np.array(neo[:n])
            m_, (lo, hi) = paired_bootstrap(diff)
            hyp_rows.append(dict(model=model, mean_diff_ado_minus_neo=m_,
                                 ci_low=lo, ci_high=hi, n_pairs=n))
    pd.DataFrame(ab_rows).to_csv("results/peds_abstraction/ageband.csv", index=False)
    pd.DataFrame(hyp_rows).to_csv("results/peds_abstraction/hypothesis.csv", index=False)

    # ---- pairwise McNemar on per-field correctness (run 1), Holm ----
    models = sorted({m for (m, r) in field_flags if r == 1})
    pair_rows, pvals = [], []
    for i in range(len(models)):
        for j in range(i + 1, len(models)):
            a, b = models[i], models[j]
            fa, fb = field_flags[(a, 1)], field_flags[(b, 1)]
            keys = [(f, rid) for f in fa for rid in fa[f]
                    if f in fb and rid in fb[f]]
            va = np.array([fa[f][rid] for f, rid in keys])
            vb = np.array([fb[f][rid] for f, rid in keys])
            res = mcnemar_test(va, vb)
            pair_rows.append(dict(model_a=a, model_b=b, n=len(keys), **res))
            pvals.append(res["p"])
    if pair_rows:
        adj, rej = holm(pvals)
        for row, ap, rj in zip(pair_rows, adj, rej):
            row["p_holm"] = ap
            row["significant"] = rj
    pd.DataFrame(pair_rows).to_csv("results/peds_abstraction/pairwise.csv", index=False)
    print("scored. See results/peds_abstraction/*.csv")


if __name__ == "__main__":
    main()

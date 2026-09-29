"""Secondary (post-hoc, declared before computation) analyses for the
pediatric abstraction benchmark. The pre-specified strict scoring in
src/peds_abstraction/score.py remains the primary analysis; everything
here is reported alongside it and labeled secondary.

Rules applied identically to every model:

LENIENT MATCHING (i2b2/n2c2 lenient-span convention adapted to items).
  A model item matches a gold item in the same domain when the assertion
  (status / qualifier) is equal and the name texts overlap: after
  normalization and stopword removal, the model tokens are a subset of the
  gold tokens, or the gold tokens are a subset of the model tokens, or the
  Jaccard overlap is >= 0.5. For temporal items the model text is
  event + when. Medications and labs additionally require the strict
  value/unit equality of the primary analysis.
  Cross-domain credit: a model item with no within-domain match is not a
  false positive if it lenient-matches a gold item in another list domain
  with a compatible assertion (historical<->historical, planned<->planned,
  completed<->completed, active<->current). Such items are counted
  separately as "redundant encodings". A gold item with no within-domain
  match is not a false negative if any model item lenient-matches it
  cross-domain.

FABRICATION AUDIT. Every strict false-positive item is checked for textual
  support: all its content tokens (4-char prefixes, stopwords removed) must
  occur in the source note. Items failing this are listed as candidate
  unsupported items for manual review.

HARD-FACT F1. Strict scoring restricted to demographics, diagnoses,
  medications, labs, procedures and encounter (temporal excluded).

FIELD-LEVEL STABILITY (the manuscript's definition). Across the available
  runs of a record: fraction of scalar fields with identical normalized
  values, and fraction of list domains with identical normalized key sets.

PAIRWISE PER-RECORD F1. Paired bootstrap CI of the between-model difference
  in per-record micro-F1 (strict and lenient), all model pairs.

Outputs: results/peds_abstraction/secondary_*.csv ; prints a summary.
Usage: python tools/peds_secondary_stats.py
"""
from __future__ import annotations
import glob
import itertools
import json
import os
import re
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, "src")
from common import normalize as N  # noqa: E402
from common.stats import bootstrap_metric, paired_bootstrap  # noqa: E402
from peds_abstraction.score import score_lists, score_scalars, prf, band_of, SCALAR_FIELDS  # noqa: E402

OUT = "results/peds_abstraction"
LIST_DOMS = ["diagnoses", "medications", "labs", "procedures", "temporal"]
HARD_DOMS = ["diagnoses", "medications", "labs", "procedures"]
STOP = {"the", "a", "an", "of", "in", "for", "with", "at", "to", "and", "or", "on", "by",
        "is", "was", "be", "as", "from", "per", "than", "rather", "unit", "status"}
ASSERT_COMPAT = {("historical", "historical"), ("planned", "planned"), ("completed", "completed"),
                 ("active", "current"), ("current", "active"), ("active", "completed"),
                 ("completed", "active"), ("ruled_out", "ruled_out"), ("suspected", "current")}


def toks(s):
    s = N.norm_name(s) or ""
    return {t for t in re.split(r"[^a-z0-9]+", s) if t and t not in STOP}


def item_text(dom, x):
    if dom == "temporal":
        return " ".join(str(v) for v in (x.get("event"), x.get("when")) if v)
    if dom == "labs":
        return str(x.get("test") or "")
    return str(x.get("name") or "")


def assertion(dom, x):
    if dom == "temporal":
        return str(x.get("qualifier") or "").lower()
    if dom in ("diagnoses", "procedures"):
        return str(x.get("status") or "").lower()
    return "current"   # meds, labs: no assertion field


def text_overlap(a, b):
    ta, tb = toks(a), toks(b)
    if not ta or not tb:
        return False
    if ta <= tb or tb <= ta:
        return True
    return len(ta & tb) / len(ta | tb) >= 0.5


def lenient_equal(dom, pred, gold):
    if assertion(dom, pred) != assertion(dom, gold):
        return False
    if dom == "medications":
        return (text_overlap(pred.get("name"), gold.get("name"))
                and N.numbers_match(pred.get("dose"), gold.get("dose"))
                and N.norm_unit(pred.get("dose_unit")) == N.norm_unit(gold.get("dose_unit"))
                and N.norm_name(pred.get("route")) == N.norm_name(gold.get("route"))
                and N.norm_freq(pred.get("frequency")) == N.norm_freq(gold.get("frequency")))
    if dom == "labs":
        return (text_overlap(pred.get("test"), gold.get("test"))
                and N.numbers_match(pred.get("value"), gold.get("value"))
                and N.norm_unit(pred.get("unit")) == N.norm_unit(gold.get("unit")))
    return text_overlap(item_text(dom, pred), item_text(dom, gold))


def cross_compatible(a_dom, a, b_dom, b):
    aa, bb = assertion(a_dom, a), assertion(b_dom, b)
    return (aa, bb) in ASSERT_COMPAT and text_overlap(item_text(a_dom, a), item_text(b_dom, b))


def lenient_score(pred, gold):
    """Returns per-domain tp/fp/fn under lenient rules plus redundant count."""
    pred = pred if isinstance(pred, dict) else {}
    gitems = {d: [x for x in (gold.get(d) or []) if isinstance(x, dict)] for d in LIST_DOMS}
    pitems = {d: [x for x in ((pred.get(d) or []) if isinstance(pred.get(d), list) else [])
                  if isinstance(x, dict)] for d in LIST_DOMS}
    matched_g = {d: [False] * len(gitems[d]) for d in LIST_DOMS}
    matched_p = {d: [False] * len(pitems[d]) for d in LIST_DOMS}
    # within-domain greedy matching
    for d in LIST_DOMS:
        for i, p in enumerate(pitems[d]):
            for j, g in enumerate(gitems[d]):
                if not matched_g[d][j] and lenient_equal(d, p, g):
                    matched_g[d][j] = matched_p[d][i] = True
                    break
    # cross-domain credit
    redundant = 0
    for d in LIST_DOMS:
        for i, p in enumerate(pitems[d]):
            if matched_p[d][i]:
                continue
            for d2 in LIST_DOMS:
                if d2 == d:
                    continue
                hit = False
                for j, g in enumerate(gitems[d2]):
                    if cross_compatible(d, p, d2, g):
                        matched_p[d][i] = True
                        matched_g[d2][j] = True
                        redundant += 1
                        hit = True
                        break
                if hit:
                    break
    out = {}
    for d in LIST_DOMS:
        tp = sum(matched_g[d])
        fn = len(gitems[d]) - tp
        fp = sum(1 for m in matched_p[d] if not m)
        out[d] = dict(tp=tp, fp=fp, fn=fn)
    return out, redundant


def supported_by_note(text, note_toks):
    ts = toks(text)
    if not ts:
        return True
    return all(any(nt.startswith(t[:4]) for nt in note_toks) for t in ts)


def load_runs():
    runs = defaultdict(dict)   # model -> run -> {rid: rec}
    for path in glob.glob("runs/peds_abstraction/*/run[0-9].jsonl"):
        m = path.split(os.sep)[-2]
        k = int(os.path.basename(path)[3])
        for line in open(path):
            r = json.loads(line)
            if not r.get("error"):
                runs[m].setdefault(k, {})[r["record_id"]] = r
    return runs


def main():
    os.makedirs(OUT, exist_ok=True)
    gold = {os.path.basename(p)[:-5]: json.load(open(p))
            for p in glob.glob("data/peds_abstraction/gold/*.json")}
    notes = {rid: open(f"data/peds_abstraction/records/{rid}.txt").read() for rid in gold}
    note_toks = {rid: {t for t in re.split(r"[^a-z0-9]+", notes[rid].lower()) if t} for rid in gold}
    runs = load_runs()
    models = sorted(runs)

    len_rows, dom_rows, fab_rows, hard_rows = [], [], [], []
    per_rec_strict, per_rec_len = {}, {}
    for m in models:
        r1 = runs[m].get(1, {})
        agg_len = defaultdict(lambda: dict(tp=0, fp=0, fn=0))
        agg_hard = dict(tp=0, fp=0, fn=0)
        redundant_total, n_rec = 0, 0
        f1_strict, f1_len, f1_hard, rids = [], [], [], []
        unsupported = []
        for rid in sorted(gold):
            rec = r1.get(rid)
            parsed = (rec or {}).get("parsed")
            n_rec += 1
            # strict per-record micro F1 (primary definition)
            s = score_lists(parsed or {}, gold[rid])
            f1_strict.append(prf(sum(v["tp"] for v in s.values()), sum(v["fp"] for v in s.values()),
                                 sum(v["fn"] for v in s.values()))[2])
            # hard-fact strict (temporal excluded) + scalar fields
            scal = score_scalars(parsed or {}, gold[rid])
            htp = sum(s[d]["tp"] for d in HARD_DOMS) + sum(1 for ok in scal.values() if ok)
            hfp = sum(s[d]["fp"] for d in HARD_DOMS) + sum(1 for ok in scal.values() if not ok)
            hfn = sum(s[d]["fn"] for d in HARD_DOMS) + sum(1 for ok in scal.values() if not ok)
            agg_hard["tp"] += htp; agg_hard["fp"] += hfp; agg_hard["fn"] += hfn
            f1_hard.append(prf(htp, hfp, hfn)[2])
            # lenient
            ls, red = lenient_score(parsed or {}, gold[rid])
            redundant_total += red
            for d, v in ls.items():
                for k in ("tp", "fp", "fn"):
                    agg_len[d][k] += v[k]
            f1_len.append(prf(sum(v["tp"] for v in ls.values()), sum(v["fp"] for v in ls.values()),
                              sum(v["fn"] for v in ls.values()))[2])
            rids.append(rid)
            # fabrication audit on strict FPs
            if isinstance(parsed, dict):
                for d in LIST_DOMS:
                    gk = {(N.dx_key if d == "diagnoses" else N.med_key if d == "medications" else
                           N.lab_key if d == "labs" else N.proc_key if d == "procedures" else
                           N.temporal_key)(x) for x in (gold[rid].get(d) or [])}
                    for x in (parsed.get(d) or []) if isinstance(parsed.get(d), list) else []:
                        if not isinstance(x, dict):
                            continue
                        key = (N.dx_key if d == "diagnoses" else N.med_key if d == "medications" else
                               N.lab_key if d == "labs" else N.proc_key if d == "procedures" else
                               N.temporal_key)(x)
                        if key in gk:
                            continue
                        if not supported_by_note(item_text(d, x), note_toks[rid]):
                            unsupported.append(dict(model=m, record=rid, domain=d,
                                                    item=item_text(d, x)[:80],
                                                    assertion=assertion(d, x)))
        per_rec_strict[m] = dict(zip(rids, f1_strict))
        per_rec_len[m] = dict(zip(rids, f1_len))
        tp = sum(v["tp"] for v in agg_len.values()); fp = sum(v["fp"] for v in agg_len.values())
        fn = sum(v["fn"] for v in agg_len.values())
        p, r, f = prf(tp, fp, fn)
        mean_len, (lo, hi) = bootstrap_metric(np.array(f1_len))
        mean_str, (slo, shi) = bootstrap_metric(np.array(f1_strict))
        mean_hard, (hlo, hhi) = bootstrap_metric(np.array(f1_hard))
        hp, hr, hf = prf(agg_hard["tp"], agg_hard["fp"], agg_hard["fn"])
        len_rows.append(dict(model=m, n_records=n_rec,
                             strict_per_record_f1=mean_str, strict_ci_low=slo, strict_ci_high=shi,
                             lenient_micro_precision=p, lenient_micro_recall=r, lenient_micro_f1=f,
                             lenient_per_record_f1=mean_len, lenient_ci_low=lo, lenient_ci_high=hi,
                             redundant_encodings=redundant_total,
                             hard_fact_micro_f1=hf, hard_fact_per_record_f1=mean_hard,
                             hard_ci_low=hlo, hard_ci_high=hhi,
                             candidate_unsupported_items=len(unsupported)))
        for d, v in agg_len.items():
            p_, r_, f_ = prf(v["tp"], v["fp"], v["fn"])
            dom_rows.append(dict(model=m, domain=d, **v, precision=p_, recall=r_, f1=f_))
        fab_rows.extend(unsupported)

    pd.DataFrame(len_rows).to_csv(f"{OUT}/secondary_lenient_summary.csv", index=False)
    pd.DataFrame(dom_rows).to_csv(f"{OUT}/secondary_lenient_by_domain.csv", index=False)
    pd.DataFrame(fab_rows).to_csv(f"{OUT}/secondary_unsupported_items.csv", index=False)

    # ---- field-level stability (manuscript definition) ----
    stab_rows = []
    for m in models:
        ks = sorted(runs[m])
        common = set.intersection(*(set(runs[m][k]) for k in ks)) if ks else set()
        sc_same = sc_tot = ls_same = ls_tot = 0
        for rid in common:
            outs = [runs[m][k][rid].get("parsed") for k in ks]
            for dom, field, norm in SCALAR_FIELDS:
                vals = {json.dumps(norm(((o or {}).get(dom) or {}).get(field)), default=str) for o in outs}
                sc_tot += 1; sc_same += int(len(vals) == 1)
            for d in LIST_DOMS:
                keyf = (N.dx_key if d == "diagnoses" else N.med_key if d == "medications" else
                        N.lab_key if d == "labs" else N.proc_key if d == "procedures" else N.temporal_key)
                sets = []
                for o in outs:
                    items = (o or {}).get(d) or []
                    sets.append(json.dumps(sorted(str(keyf(x)) for x in items if isinstance(x, dict))))
                ls_tot += 1; ls_same += int(len(set(sets)) == 1)
        stab_rows.append(dict(model=m, runs_available=len(ks), records_with_all_runs=len(common),
                              scalar_field_stability=sc_same / sc_tot if sc_tot else None,
                              list_domain_keyset_stability=ls_same / ls_tot if ls_tot else None))
    pd.DataFrame(stab_rows).to_csv(f"{OUT}/secondary_field_stability.csv", index=False)

    # ---- pairwise per-record F1 differences ----
    pw = []
    for a, b in itertools.combinations(models, 2):
        common = sorted(set(per_rec_strict[a]) & set(per_rec_strict[b]))
        for label, store in (("strict", per_rec_strict), ("lenient", per_rec_len)):
            diff = np.array([store[a][r] - store[b][r] for r in common])
            md, (lo, hi) = paired_bootstrap(diff)
            pw.append(dict(matching=label, model_a=a, model_b=b, n=len(common),
                           mean_diff_a_minus_b=md, ci_low=lo, ci_high=hi,
                           ci_excludes_zero=bool(lo > 0 or hi < 0)))
    pd.DataFrame(pw).to_csv(f"{OUT}/secondary_pairwise_f1.csv", index=False)

    # ---- age-band hypothesis under lenient matching ----
    hyp = []
    for m in models:
        neo = np.array([v for r, v in per_rec_len[m].items() if band_of(r) == "neonate"])
        ado = np.array([v for r, v in per_rec_len[m].items() if band_of(r) == "adolescent"])
        n = min(len(neo), len(ado))
        if n:
            md, (lo, hi) = paired_bootstrap(ado[:n] - neo[:n])
            hyp.append(dict(model=m, lenient_mean_ado=float(ado.mean()), lenient_mean_neo=float(neo.mean()),
                            diff_ado_minus_neo=md, ci_low=lo, ci_high=hi, n_pairs=n))
    pd.DataFrame(hyp).to_csv(f"{OUT}/secondary_hypothesis_lenient.csv", index=False)

    pd.set_option("display.width", 230); pd.set_option("display.max_columns", 40)
    print("\n=== SECONDARY: strict vs lenient vs hard-fact F1 (run 1) ===")
    print(pd.DataFrame(len_rows).round(3).to_string(index=False))
    print("\n=== SECONDARY: lenient P/R/F1 by domain ===")
    print(pd.DataFrame(dom_rows).round(3).to_string(index=False))
    print("\n=== SECONDARY: candidate unsupported (fabricated?) items - for manual review ===")
    fab = pd.DataFrame(fab_rows)
    if len(fab):
        print(fab.groupby("model").size().to_string())
        print(fab.head(40).to_string(index=False))
    else:
        print("none")
    print("\n=== SECONDARY: field-level stability (manuscript definition) ===")
    print(pd.DataFrame(stab_rows).round(3).to_string(index=False))
    print("\n=== SECONDARY: pairwise per-record F1 differences (paired bootstrap) ===")
    print(pd.DataFrame(pw).round(3).to_string(index=False))
    print("\n=== SECONDARY: adolescent minus neonate under lenient matching ===")
    print(pd.DataFrame(hyp).round(3).to_string(index=False))
    print("\nwrote secondary_*.csv")


if __name__ == "__main__":
    main()

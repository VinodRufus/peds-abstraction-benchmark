"""Additional secondary analyses for the pediatric abstraction benchmark
(declared in DEVIATIONS.md 2026-09-29 after a preview of run-1 results and
before the final results tag). Strict scoring in src/peds_abstraction/score.py
stays primary; everything here is descriptive and labeled secondary.

Analyses and outputs (results/peds_abstraction/):
  secondary_band_macro.csv              macro-F1 (domain-averaged) by age band, record-resampling bootstrap CI
  secondary_hypothesis_macro.csv        adolescent - neonate under BOTH estimands (pre-registered macro-F1 and
                                        implemented per-record F1) x BOTH resampling schemes (paired by care
                                        setting and construction position; independent)
  secondary_gold_load.csv               gold item load per age band (the item-load confound)
  secondary_strict_by_domain.csv        strict per-domain P/R/F1, run 1
  secondary_setting.csv                 strict and lenient per-record F1 by care setting, run 1
  secondary_band_setting.csv            strict per-record F1 by band x setting, run 1
  secondary_lenient_sensitivity.csv     lenient per-record F1 under alternative overlap rules
  secondary_maternal_attribution.csv    neonatal records: maternal / perinatal history encoded as the
                                        infant's diagnosis, per model (wrong-patient attribution)
  secondary_maternal_attribution_items.csv   every such item
  secondary_lenient_no_maternal_credit.csv   lenient F1 when cross-domain credit is denied for maternal /
                                        pregnancy history events
  runs_manifest.csv                     per model: requested vs effective decoding settings, versions,
                                        prompt hashes, logged calls, date span

Usage: python tools/peds_v2_analyses.py
"""
from __future__ import annotations
import glob
import json
import os
import re
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, "src")
sys.path.insert(0, "tools")
from common import normalize as N  # noqa: E402
from common.stats import bootstrap_metric, paired_bootstrap  # noqa: E402
from peds_abstraction.score import score_lists, prf, band_of  # noqa: E402
import peds_secondary_stats as S  # noqa: E402

OUT = "results/peds_abstraction"
SEED, NBOOT = 20260923, 10000
BANDS = ["neonate", "infant", "child", "adolescent"]
SETTINGS = {"out": "outpatient", "eme": "emergency", "inp": "inpatient", "icu": "icu"}
LIST_DOMS = S.LIST_DOMS
MATERNAL = re.compile(r"maternal|pregnan|gestational diabetes|group b strep")


def setting_of(rid):
    return SETTINGS[rid.split("-")[2]]


def position_of(rid):
    return rid.split("-")[3]


def load_gold():
    return {os.path.basename(p)[:-5]: json.load(open(p))
            for p in glob.glob("data/peds_abstraction/gold/*.json")}


def run1_outputs():
    """model -> {rid: parsed-or-None}; every logged run-1 record (errors excluded)."""
    out = defaultdict(dict)
    for path in glob.glob("runs/peds_abstraction/*/run1.jsonl"):
        m = path.split(os.sep)[-2]
        for line in open(path):
            r = json.loads(line)
            if not r.get("error"):
                out[m][r["record_id"]] = r.get("parsed")
    return out


def f1_of(tp, fp, fn):
    return prf(tp, fp, fn)[2]


# ------------------------------------------------------------------ estimands
def domain_counts(parsed, gold):
    """dict domain -> (tp, fp, fn) for one record under strict scoring."""
    return {d: (s["tp"], s["fp"], s["fn"]) for d, s in score_lists(parsed or {}, gold).items()}


def macro_f1(records):
    """records: list of domain-count dicts. Pool per domain, F1 per domain, unweighted mean."""
    pooled = defaultdict(lambda: [0, 0, 0])
    for rec in records:
        for d, (tp, fp, fn) in rec.items():
            pooled[d][0] += tp
            pooled[d][1] += fp
            pooled[d][2] += fn
    return float(np.mean([f1_of(*pooled[d]) for d in LIST_DOMS]))


def per_record_f1(rec):
    tp = sum(v[0] for v in rec.values())
    fp = sum(v[1] for v in rec.values())
    fn = sum(v[2] for v in rec.values())
    return f1_of(tp, fp, fn)


def boot_macro(records, rng):
    n = len(records)
    vals = []
    for _ in range(NBOOT):
        idx = rng.integers(0, n, size=n)
        vals.append(macro_f1([records[i] for i in idx]))
    return float(macro_f1(records)), (float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5)))


def estimand_analyses(gold, outputs):
    band_rows, hyp_rows = [], []
    for m in sorted(outputs):
        counts = {rid: domain_counts(outputs[m].get(rid), gold[rid]) for rid in gold}
        by_band = {b: sorted(r for r in gold if band_of(r) == b) for b in BANDS}
        rng = np.random.default_rng(SEED)
        for b in BANDS:
            recs = [counts[r] for r in by_band[b]]
            mval, (lo, hi) = boot_macro(recs, rng)
            pr = [per_record_f1(c) for c in recs]
            prm, (plo, phi) = bootstrap_metric(np.array(pr))
            band_rows.append(dict(model=m, band=b, n=len(recs), macro_f1=mval, macro_ci_low=lo,
                                  macro_ci_high=hi, per_record_f1=prm, per_record_ci_low=plo,
                                  per_record_ci_high=phi))
        # pairing by (setting, position): REC-neo-eme-001 <-> REC-ado-eme-001
        neo = {(setting_of(r), position_of(r)): r for r in by_band["neonate"]}
        ado = {(setting_of(r), position_of(r)): r for r in by_band["adolescent"]}
        keys = sorted(set(neo) & set(ado))
        neo_recs = [counts[neo[k]] for k in keys]
        ado_recs = [counts[ado[k]] for k in keys]
        # macro estimand, paired resampling of (setting, position) pairs
        rng = np.random.default_rng(SEED)
        diffs = []
        for _ in range(NBOOT):
            idx = rng.integers(0, len(keys), size=len(keys))
            diffs.append(macro_f1([ado_recs[i] for i in idx]) - macro_f1([neo_recs[i] for i in idx]))
        hyp_rows.append(dict(model=m, estimand="macro_f1 (pre-registered wording)", resampling="paired by setting and position",
                             n=len(keys), diff_ado_minus_neo=macro_f1(ado_recs) - macro_f1(neo_recs),
                             ci_low=float(np.percentile(diffs, 2.5)), ci_high=float(np.percentile(diffs, 97.5))))
        # macro estimand, independent resampling within band
        rng = np.random.default_rng(SEED)
        diffs = []
        for _ in range(NBOOT):
            ia = rng.integers(0, len(ado_recs), size=len(ado_recs))
            ib = rng.integers(0, len(neo_recs), size=len(neo_recs))
            diffs.append(macro_f1([ado_recs[i] for i in ia]) - macro_f1([neo_recs[i] for i in ib]))
        hyp_rows.append(dict(model=m, estimand="macro_f1 (pre-registered wording)", resampling="independent",
                             n=len(keys), diff_ado_minus_neo=macro_f1(ado_recs) - macro_f1(neo_recs),
                             ci_low=float(np.percentile(diffs, 2.5)), ci_high=float(np.percentile(diffs, 97.5))))
        # per-record estimand (the implemented test), paired and independent
        pa = np.array([per_record_f1(c) for c in ado_recs])
        pn = np.array([per_record_f1(c) for c in neo_recs])
        mdiff, (lo, hi) = paired_bootstrap(pa - pn)
        hyp_rows.append(dict(model=m, estimand="per_record_f1 (implemented test)", resampling="paired by setting and position",
                             n=len(keys), diff_ado_minus_neo=mdiff, ci_low=lo, ci_high=hi))
        rng = np.random.default_rng(SEED)
        diffs = [pa[rng.integers(0, len(pa), len(pa))].mean() - pn[rng.integers(0, len(pn), len(pn))].mean()
                 for _ in range(NBOOT)]
        hyp_rows.append(dict(model=m, estimand="per_record_f1 (implemented test)", resampling="independent",
                             n=len(keys), diff_ado_minus_neo=float(pa.mean() - pn.mean()),
                             ci_low=float(np.percentile(diffs, 2.5)), ci_high=float(np.percentile(diffs, 97.5))))
    pd.DataFrame(band_rows).to_csv(f"{OUT}/secondary_band_macro.csv", index=False)
    pd.DataFrame(hyp_rows).to_csv(f"{OUT}/secondary_hypothesis_macro.csv", index=False)
    return pd.DataFrame(band_rows), pd.DataFrame(hyp_rows)


# ------------------------------------------------------------------ gold load
def gold_load(gold):
    rows = []
    for b in BANDS:
        rids = [r for r in gold if band_of(r) == b]
        row = dict(band=b, records=len(rids))
        for d in LIST_DOMS:
            row[d] = sum(len(gold[r].get(d) or []) for r in rids)
        row["pertinent_negatives"] = sum(1 for r in rids for x in gold[r]["diagnoses"] if x.get("status") == "ruled_out")
        row["historical_events"] = sum(1 for r in rids for x in gold[r]["temporal"] if x.get("qualifier") == "historical")
        row["total_items"] = sum(row[d] for d in LIST_DOMS)
        row["items_per_record"] = row["total_items"] / len(rids)
        rows.append(row)
    df = pd.DataFrame(rows)
    df.to_csv(f"{OUT}/secondary_gold_load.csv", index=False)
    return df


# ------------------------------------------------------------------ strict by domain, settings
def strict_tables(gold, outputs):
    dom_rows, set_rows, bs_rows = [], [], []
    for m in sorted(outputs):
        counts = {rid: domain_counts(outputs[m].get(rid), gold[rid]) for rid in gold}
        pooled = defaultdict(lambda: [0, 0, 0])
        for rec in counts.values():
            for d, (tp, fp, fn) in rec.items():
                pooled[d][0] += tp
                pooled[d][1] += fp
                pooled[d][2] += fn
        for d in LIST_DOMS:
            p, r, f = prf(*pooled[d])
            dom_rows.append(dict(model=m, domain=d, tp=pooled[d][0], fp=pooled[d][1], fn=pooled[d][2],
                                 precision=p, recall=r, f1=f))
        lenient = {}
        for rid in gold:
            out, _ = S.lenient_score(outputs[m].get(rid) or {}, gold[rid])
            lenient[rid] = f1_of(sum(v["tp"] for v in out.values()), sum(v["fp"] for v in out.values()),
                                 sum(v["fn"] for v in out.values()))
        for s in ["outpatient", "emergency", "inpatient", "icu"]:
            rids = [r for r in gold if setting_of(r) == s]
            sv = np.array([per_record_f1(counts[r]) for r in rids])
            lv = np.array([lenient[r] for r in rids])
            sm, (slo, shi) = bootstrap_metric(sv)
            lm, (llo, lhi) = bootstrap_metric(lv)
            set_rows.append(dict(model=m, setting=s, n=len(rids), strict_f1=sm, strict_ci_low=slo, strict_ci_high=shi,
                                 lenient_f1=lm, lenient_ci_low=llo, lenient_ci_high=lhi))
            for b in BANDS:
                rr = [r for r in rids if band_of(r) == b]
                bs_rows.append(dict(model=m, band=b, setting=s, n=len(rr),
                                    strict_f1=float(np.mean([per_record_f1(counts[r]) for r in rr])),
                                    lenient_f1=float(np.mean([lenient[r] for r in rr]))))
    pd.DataFrame(dom_rows).to_csv(f"{OUT}/secondary_strict_by_domain.csv", index=False)
    pd.DataFrame(set_rows).to_csv(f"{OUT}/secondary_setting.csv", index=False)
    pd.DataFrame(bs_rows).to_csv(f"{OUT}/secondary_band_setting.csv", index=False)
    return pd.DataFrame(dom_rows), pd.DataFrame(set_rows)


# ------------------------------------------------------------------ lenient sensitivity
def make_overlap(th, subset):
    def text_overlap(a, b):
        ta, tb = S.toks(a), S.toks(b)
        if not ta or not tb:
            return False
        if subset and (ta <= tb or tb <= ta):
            return True
        return len(ta & tb) / len(ta | tb) >= th
    return text_overlap


VARIANTS = [
    ("jaccard>=0.3 or subset (looser)", 0.3, True, True),
    ("jaccard>=0.5 or subset (declared rule)", 0.5, True, True),
    ("jaccard>=0.7 or subset (stricter)", 0.7, True, True),
    ("jaccard>=0.5, no subset rule", 0.5, False, True),
    ("exact normalized tokens + cross-domain credit", 1.0, False, True),
    ("exact normalized tokens, no cross-domain credit", 1.0, False, False),
]


def lenient_sensitivity(gold, outputs):
    original_overlap, original_cross = S.text_overlap, S.cross_compatible
    rows = []
    try:
        for label, th, subset, cross in VARIANTS:
            S.text_overlap = make_overlap(th, subset)
            S.cross_compatible = original_cross if cross else (lambda *a, **k: False)
            for m in sorted(outputs):
                vals = []
                for rid in sorted(gold):
                    out, _ = S.lenient_score(outputs[m].get(rid) or {}, gold[rid])
                    vals.append(f1_of(sum(v["tp"] for v in out.values()), sum(v["fp"] for v in out.values()),
                                      sum(v["fn"] for v in out.values())))
                mv, (lo, hi) = bootstrap_metric(np.array(vals))
                rows.append(dict(model=m, variant=label, per_record_f1=mv, ci_low=lo, ci_high=hi))
    finally:
        S.text_overlap, S.cross_compatible = original_overlap, original_cross
    df = pd.DataFrame(rows)
    df.to_csv(f"{OUT}/secondary_lenient_sensitivity.csv", index=False)
    return df


# ------------------------------------------------------------------ maternal attribution
def classify_extra_dx(name):
    n = (name or "").lower()
    qualified = bool(re.search(r"maternal|pregnan|mother", n))
    if "gestational diabetes" in n or "diabetes" in n:
        return ("maternal condition, qualified as maternal" if qualified
                else "maternal condition attributed to infant (unqualified)")
    if "strep" in n or "gbs" in n:
        return "maternal GBS status listed as infant diagnosis"
    if re.search(r"prematur|preterm", n):
        return "prematurity inferred from gestational age"
    if re.search(r"term birth|born|delivery|birth", n):
        return "birth history listed as diagnosis"
    return "other"


def maternal_attribution(gold, outputs):
    item_rows, rows = [], []
    neo = sorted(r for r in gold if band_of(r) == "neonate")
    gold_dx = {r: [x["name"].lower() for x in gold[r]["diagnoses"]] for r in neo}
    maternal_line = {r: any(re.search(r"gestational diabetes", t["event"]) for t in gold[r]["temporal"]) for r in neo}
    for m in sorted(outputs):
        cats = defaultdict(int)
        parsed_n = 0
        unq_records = set()
        for rid in neo:
            p = outputs[m].get(rid)
            if not p:
                continue
            parsed_n += 1
            for d in (p.get("diagnoses") or []):
                if not isinstance(d, dict):
                    continue
                nm = str(d.get("name", "")).lower()
                if any(g in nm for g in gold_dx[rid]) or any(nm in g for g in gold_dx[rid] if nm):
                    continue
                cat = classify_extra_dx(nm)
                cats[cat] += 1
                if cat.startswith("maternal condition attributed"):
                    unq_records.add(rid)
                item_rows.append(dict(model=m, record=rid, name=d.get("name"), status=d.get("status"), category=cat))
        n_mat = sum(maternal_line.values())
        rows.append(dict(model=m, neonatal_records_parsed=parsed_n, records_with_maternal_line=n_mat,
                         records_with_unqualified_maternal_dx=len(unq_records),
                         **{k: cats.get(k, 0) for k in [
                             "maternal condition attributed to infant (unqualified)",
                             "maternal condition, qualified as maternal",
                             "maternal GBS status listed as infant diagnosis",
                             "prematurity inferred from gestational age",
                             "birth history listed as diagnosis", "other"]}))
    pd.DataFrame(item_rows).to_csv(f"{OUT}/secondary_maternal_attribution_items.csv", index=False)
    df = pd.DataFrame(rows)
    df.to_csv(f"{OUT}/secondary_maternal_attribution.csv", index=False)
    return df


def lenient_no_maternal_credit(gold, outputs):
    """Lenient scoring with cross-domain credit denied when the gold item is a
    temporal event about maternal / pregnancy history (so a maternal condition
    filed as the infant's diagnosis counts as a false positive)."""
    original = S.cross_compatible

    def guarded(a_dom, a, b_dom, b):
        if b_dom == "temporal" and MATERNAL.search(str(b.get("event", ""))) and a_dom == "diagnoses":
            return False
        if a_dom == "temporal" and MATERNAL.search(str(a.get("event", ""))) and b_dom == "diagnoses":
            return False
        return original(a_dom, a, b_dom, b)

    rows = []
    try:
        for m in sorted(outputs):
            base, guard, denied = [], [], 0
            for rid in sorted(gold):
                S.cross_compatible = original
                o1, r1 = S.lenient_score(outputs[m].get(rid) or {}, gold[rid])
                S.cross_compatible = guarded
                o2, r2 = S.lenient_score(outputs[m].get(rid) or {}, gold[rid])
                denied += r1 - r2
                base.append(f1_of(sum(v["tp"] for v in o1.values()), sum(v["fp"] for v in o1.values()),
                                  sum(v["fn"] for v in o1.values())))
                guard.append(f1_of(sum(v["tp"] for v in o2.values()), sum(v["fp"] for v in o2.values()),
                                   sum(v["fn"] for v in o2.values())))
            bm, (blo, bhi) = bootstrap_metric(np.array(base))
            gm, (glo, ghi) = bootstrap_metric(np.array(guard))
            rows.append(dict(model=m, lenient_f1=bm, lenient_ci_low=blo, lenient_ci_high=bhi,
                             lenient_f1_no_maternal_credit=gm, ci_low=glo, ci_high=ghi,
                             credits_denied=int(denied), delta=gm - bm))
    finally:
        S.cross_compatible = original
    df = pd.DataFrame(rows)
    df.to_csv(f"{OUT}/secondary_lenient_no_maternal_credit.csv", index=False)
    return df


# ------------------------------------------------------------------ run manifest
REQUESTED = dict(temperature=0.0, max_tokens=4000, seed=20260923)
# What each adapter in src/common/runner.py actually transmits (read from the code, not from policy text).
ADAPTER = {
    "openai": "temperature, seed and max_completion_tokens sent; any parameter the model rejects is dropped and the adjustment is appended to model_version",
    "anthropic": "max_tokens sent; SDK 1.x Messages.create exposes no temperature or seed (provider default)",
    "google": "temperature and max_output_tokens sent; API exposes no seed in this adapter",
    "deepseek": "temperature and max_tokens sent; no seed sent by the OpenAI-compatible adapter",
}


def run_manifest():
    rows = []
    for mdir in sorted(glob.glob("runs/peds_abstraction/*/")):
        m = os.path.basename(mdir.rstrip("/"))
        core, abl, versions, hashes, ts, adjust = 0, 0, set(), set(), [], set()
        model_id = None
        for path in glob.glob(mdir + "*.jsonl"):
            is_abl = "_ablation" in path
            for line in open(path):
                r = json.loads(line)
                if r.get("error"):
                    continue
                model_id = model_id or r.get("model_id")
                if is_abl:
                    abl += 1
                else:
                    core += 1
                mv = r.get("model_version") or ""
                versions.add(mv.split(" [")[0])
                if "[" in mv:
                    adjust.add(mv[mv.index("["):])
                hashes.add((r.get("prompt_name"), r.get("prompt_sha256") or ""))
                ts.append(r.get("ts") or "")
        provider = (model_id or m).split(":")[0].split("_")[0]
        eff_temp = ("provider default (temperature rejected)" if any("temperature rejected" in a for a in adjust)
                    else "provider default (parameter not exposed)" if provider == "anthropic"
                    else "0.0 (accepted)")
        eff_seed = ("20260923 sent (accepted)" if provider == "openai" and not any("seed rejected" in a for a in adjust)
                    else "20260923 rejected" if any("seed rejected" in a for a in adjust)
                    else "not sent (not exposed by adapter)")
        rows.append(dict(model=m, model_id=model_id, requested_temperature=REQUESTED["temperature"],
                         effective_temperature=eff_temp, requested_seed=REQUESTED["seed"], effective_seed=eff_seed,
                         requested_max_tokens=REQUESTED["max_tokens"], adapter_behavior=ADAPTER.get(provider, ""),
                         recorded_adjustments="; ".join(sorted(adjust)) or "none", versions_seen="; ".join(sorted(versions)),
                         prompt_hashes="; ".join(f"{n}:{h}" for n, h in sorted(hashes)),
                         core_calls_logged=core, ablation_calls_logged=abl,
                         first_call=min(ts) if ts else None, last_call=max(ts) if ts else None,
                         calendar_days=len({t[:10] for t in ts if t})))
    df = pd.DataFrame(rows)
    df.to_csv(f"{OUT}/runs_manifest.csv", index=False)
    return df


def main():
    os.makedirs(OUT, exist_ok=True)
    gold = load_gold()
    outputs = run1_outputs()
    pd.set_option("display.width", 220)
    band, hyp = estimand_analyses(gold, outputs)
    print("=== macro-F1 vs per-record F1 by band ===")
    print(band.round(3).to_string(index=False))
    print("\n=== adolescent - neonate under both estimands ===")
    print(hyp.round(3).to_string(index=False))
    print("\n=== gold item load ===")
    print(gold_load(gold).round(2).to_string(index=False))
    dom, sett = strict_tables(gold, outputs)
    print("\n=== strict per-domain F1 ===")
    print(dom.round(3).to_string(index=False))
    print("\n=== per-setting F1 ===")
    print(sett.round(3).to_string(index=False))
    print("\n=== lenient sensitivity ===")
    print(lenient_sensitivity(gold, outputs).round(3).to_string(index=False))
    print("\n=== maternal / perinatal attribution (neonatal records) ===")
    print(maternal_attribution(gold, outputs).to_string(index=False))
    print("\n=== lenient F1 without maternal cross-domain credit ===")
    print(lenient_no_maternal_credit(gold, outputs).round(3).to_string(index=False))
    print("\n=== run manifest ===")
    print(run_manifest()[["model", "effective_temperature", "effective_seed", "core_calls_logged",
                          "ablation_calls_logged", "calendar_days"]].to_string(index=False))
    print("\nwrote secondary_band_macro, secondary_hypothesis_macro, secondary_gold_load, secondary_strict_by_domain, "
          "secondary_setting, secondary_band_setting, secondary_lenient_sensitivity, secondary_maternal_attribution(_items), "
          "secondary_lenient_no_maternal_credit, runs_manifest")


if __name__ == "__main__":
    main()

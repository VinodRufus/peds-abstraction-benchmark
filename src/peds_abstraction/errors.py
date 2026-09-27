"""Rule-based error stratification into the paper's taxonomy.

Every FP/FN is labeled with exactly one class:
omission; hallucinated_field; wrong_patient_attribute; negation_reversal;
temporality_error; medication_name_error; dose_error; dose_unit_error;
route_frequency_error; age_interpretation_error; weight_interpretation_error;
lab_value_unit_error; reference_range_error; schema_format_failure.

Output: results/peds_abstraction/errors.csv (one row per error) and
        results/peds_abstraction/error_rates.csv (counts per model x band x class).
"""
from __future__ import annotations
import glob
import json
import os
import sys
from collections import Counter

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import normalize as N  # noqa: E402


def band_of(record_id: str) -> str:
    return {"neo": "neonate", "inf": "infant", "chi": "child", "ado": "adolescent"}[
        record_id.split("-")[1]]


def classify_med(pred, gold):
    if N.norm_name(pred.get("name")) != N.norm_name(gold.get("name")):
        return "medication_name_error"
    if N.norm_unit(pred.get("dose_unit")) != N.norm_unit(gold.get("dose_unit")):
        return "dose_unit_error"
    if not N.numbers_match(pred.get("dose"), gold.get("dose")):
        return "dose_error"
    return "route_frequency_error"


def classify_record(pred, gold, model, rid):
    errs = []
    band = band_of(rid)

    def add(cls, dom, detail):
        errs.append(dict(model=model, record=rid, band=band,
                         error_class=cls, domain=dom, detail=str(detail)[:120]))

    if pred is None or not isinstance(pred, dict):
        add("schema_format_failure", "record", "unparseable output")
        return errs

    # scalars
    g, p = gold["demographics"], pred.get("demographics") or {}
    if N.norm_value(p.get("age_value")) != N.norm_value(g.get("age_value")) or \
       N.norm_name(p.get("age_unit")) != N.norm_name(g.get("age_unit")):
        add("age_interpretation_error", "demographics",
            f"gold {g.get('age_value')} {g.get('age_unit')} vs pred {p.get('age_value')} {p.get('age_unit')}")
    if not N.numbers_match(p.get("weight_kg"), g.get("weight_kg")):
        add("weight_interpretation_error", "demographics",
            f"gold {g.get('weight_kg')} vs pred {p.get('weight_kg')}")
    if N.norm_name(p.get("sex")) != N.norm_name(g.get("sex")):
        add("wrong_patient_attribute", "demographics", "sex mismatch")

    # list domains
    for dom, (key, equal), name_cls in [
        ("diagnoses", (N.dx_key, N.dx_equal), None),
        ("medications", (N.med_key, N.med_equal), None),
        ("labs", (N.lab_key, N.lab_equal), None),
        ("procedures", (N.proc_key, N.proc_equal), None),
        ("temporal", (N.temporal_key, N.temporal_equal), None),
    ]:
        gk = {key(x): x for x in gold.get(dom) or []}
        pk = {}
        for xitem in (pred.get(dom) or []) if isinstance(pred.get(dom), list) else []:
            if isinstance(xitem, dict) and key(xitem) is not None:
                pk.setdefault(key(xitem), xitem)
        for k, gv in gk.items():
            if k not in pk:
                add("omission", dom, k)
            elif not equal(pk[k], gv):
                pv = pk[k]
                if dom == "diagnoses":
                    gs, ps = gv.get("status"), pv.get("status")
                    if {gs, ps} & {"ruled_out"} or (gs == "suspected" and ps == "active"):
                        add("negation_reversal", dom, f"{k}: {gs} -> {ps}")
                    else:
                        add("temporality_error", dom, f"{k}: {gs} -> {ps}")
                elif dom == "medications":
                    add(classify_med(pv, gv), dom, k)
                elif dom == "labs":
                    if gv.get("flag") != pv.get("flag") and \
                       N.numbers_match(pv.get("value"), gv.get("value")) and \
                       N.norm_unit(pv.get("unit")) == N.norm_unit(gv.get("unit")):
                        add("reference_range_error", dom, k)
                    else:
                        add("lab_value_unit_error", dom, k)
                elif dom in ("procedures", "temporal"):
                    add("temporality_error", dom, f"{k}: {gv.get('status', gv.get('qualifier'))} -> "
                                                  f"{pv.get('status', pv.get('qualifier'))}")
        for k in pk:
            if k not in gk:
                add("hallucinated_field", dom, k)
    return errs


def main():
    gold = {os.path.basename(p)[:-5]: json.load(open(p))
            for p in glob.glob("data/peds_abstraction/gold/*.json")}
    all_errs = []
    for path in glob.glob("runs/peds_abstraction/*/run1.jsonl"):
        model = path.split(os.sep)[-2]
        for line in open(path):
            rec = json.loads(line)
            if rec["record_id"] in gold:
                all_errs.extend(classify_record(rec.get("parsed"), gold[rec["record_id"]],
                                                model, rec["record_id"]))
    os.makedirs("results/peds_abstraction", exist_ok=True)
    df = pd.DataFrame(all_errs)
    df.to_csv("results/peds_abstraction/errors.csv", index=False)
    if len(df):
        rates = df.groupby(["model", "band", "error_class"]).size().reset_index(name="count")
        rates.to_csv("results/peds_abstraction/error_rates.csv", index=False)
        print(df.groupby("error_class").size().sort_values(ascending=False))
    print("error stratification written to results/peds_abstraction/")


if __name__ == "__main__":
    main()

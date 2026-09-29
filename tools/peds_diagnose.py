"""Read-only diagnostics on the scored benchmark: where do FP/FN come from?

Prints (nothing written):
  1. omission / hallucination counts per model x domain (run 1)
  2. top mismatched keys per domain (what gold had vs what models produced)
  3. two worked examples (gold vs model output) for the temporal + diagnoses domains
  4. parse-error reasons per model
  5. one free-text-prompt (ablation) raw output excerpt per model

Usage: python tools/peds_diagnose.py
"""
from __future__ import annotations
import glob
import json
import os
import sys
from collections import Counter, defaultdict

import pandas as pd

sys.path.insert(0, "src")
from common import normalize as N  # noqa: E402

KEYS = {"diagnoses": N.dx_key, "medications": N.med_key, "labs": N.lab_key,
        "procedures": N.proc_key, "temporal": N.temporal_key}


def main():
    gold = {os.path.basename(p)[:-5]: json.load(open(p))
            for p in glob.glob("data/peds_abstraction/gold/*.json")}
    err = pd.read_csv("results/peds_abstraction/errors.csv")

    print("=== 1. omission / hallucination by model x domain (run 1) ===")
    sub = err[err.error_class.isin(["omission", "hallucinated_field"])]
    print(sub.pivot_table(index="domain", columns=["error_class", "model"], values="record",
                          aggfunc="count", fill_value=0).to_string())

    print("\n=== 2. top mismatched keys per domain (all models, run 1) ===")
    for dom in ["temporal", "diagnoses", "procedures", "medications", "labs"]:
        om = Counter(sub[(sub.domain == dom) & (sub.error_class == "omission")].detail)
        ha = Counter(sub[(sub.domain == dom) & (sub.error_class == "hallucinated_field")].detail)
        print(f"\n--- {dom}: gold keys most often OMITTED ---")
        for k, n in om.most_common(8):
            print(f"  x{n}: {k}")
        print(f"--- {dom}: model keys most often counted as HALLUCINATED ---")
        for k, n in ha.most_common(12):
            print(f"  x{n}: {k}")

    print("\n=== 3. worked examples: gold vs model (run 1), temporal + diagnoses ===")
    for rid in ["REC-neo-inp-001", "REC-ado-eme-002"]:
        g = gold.get(rid)
        if not g:
            continue
        print(f"\n##### {rid}")
        print("NOTE:", open(f"data/peds_abstraction/records/{rid}.txt").read()[:600])
        print("GOLD diagnoses:", [(d["name"], d["status"]) for d in g["diagnoses"]])
        print("GOLD temporal :", [(t["event"], t["qualifier"]) for t in g["temporal"]])
        print("GOLD procs    :", [(p["name"], p["status"]) for p in g["procedures"]])
        for mdir in sorted(glob.glob("runs/peds_abstraction/*/")):
            m = os.path.basename(os.path.dirname(mdir))
            for line in open(os.path.join(mdir, "run1.jsonl")):
                r = json.loads(line)
                if r["record_id"] != rid:
                    continue
                p = r.get("parsed") or {}
                print(f"  [{m}] diagnoses:", [(d.get("name"), d.get("status")) for d in p.get("diagnoses") or []])
                print(f"  [{m}] temporal :", [(t.get("event"), t.get("when"), t.get("qualifier")) for t in p.get("temporal") or []])
                print(f"  [{m}] procs    :", [(q.get("name"), q.get("status")) for q in p.get("procedures") or []])
                break

    print("\n=== 4. parse-error reasons per model (core runs) ===")
    for mdir in sorted(glob.glob("runs/peds_abstraction/*/")):
        m = os.path.basename(os.path.dirname(mdir))
        reasons, n, sample = Counter(), 0, None
        for k in (1, 2, 3):
            path = os.path.join(mdir, f"run{k}.jsonl")
            if not os.path.exists(path):
                continue
            for line in open(path):
                r = json.loads(line)
                n += 1
                if r.get("parsed") is None and not r.get("error"):
                    reasons[str(r.get("parse_error"))[:70]] += 1
                    if sample is None:
                        sample = (r.get("text") or "")[:300].replace("\n", " ")
                        tok = r.get("tokens_out")
        print(f"\n[{m}] parse failures {sum(reasons.values())}/{n}")
        for k_, v in reasons.most_common(3):
            print(f"  x{v}: {k_}")
        if sample is not None:
            print(f"  sample raw text (tokens_out={tok}): {sample!r}")

    print("\n=== 5. free-text prompt (ablation) raw output excerpt ===")
    for mdir in sorted(glob.glob("runs/peds_abstraction/*/")):
        m = os.path.basename(os.path.dirname(mdir))
        pa = os.path.join(mdir, "run1_ablation.jsonl")
        if os.path.exists(pa):
            for line in open(pa):
                r = json.loads(line)
                if r.get("text"):
                    print(f"\n[{m}] {r['record_id']}: {r['text'][:350]!r}")
                    break
    print("\n================ DIAGNOSE DONE ================")


if __name__ == "__main__":
    main()

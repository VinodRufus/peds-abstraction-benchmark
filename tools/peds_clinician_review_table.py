"""Build the clinician-review table for the 155 lexical-support candidates.

Reads results/peds_abstraction/secondary_unsupported_adjudication.csv (rule-based
classification, frozen) and adds, for every candidate item: the raw model output
(JSON), the best-matching source sentence, the full source note, and empty columns
for clinician decision, reason, reviewer id, second-reviewer decision and
disagreement resolution. Derived table only; no result is changed.

Writes results/peds_abstraction/secondary_unsupported_adjudication_for_clinician_review.csv
Usage: python tools/peds_clinician_review_table.py
"""
import json
import re

import pandas as pd

R = "results/peds_abstraction/"


def toks(s):
    return {t for t in re.split(r"[^a-z0-9]+", str(s).lower()) if t}


def main():
    adj = pd.read_csv(R + "secondary_unsupported_adjudication.csv")
    runs = {}
    for m in adj.model.unique():
        for line in open(f"runs/peds_abstraction/{m}/run1.jsonl"):
            rec = json.loads(line)
            runs[(m, rec["record_id"])] = rec.get("parsed")
    rows = []
    for _, r in adj.iterrows():
        item, rid, dom, m = str(r["item"]), r["record"], r["domain"], r["model"]
        note = open(f"data/peds_abstraction/records/{rid}.txt").read().strip()
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", note) if s.strip()]
        it = toks(item)
        best = max(sents, key=lambda s: len(it & toks(s)) / max(1, len(it)))
        overlap = len(it & toks(best)) / max(1, len(it))
        raw = ""
        for x in ((runs.get((m, rid)) or {}).get(dom) or []):
            if isinstance(x, dict):
                txt = " ".join(str(v) for v in (x.get("event"), x.get("when"), x.get("name"), x.get("test")) if v)
                if toks(txt) == it or item in txt or txt in item:
                    raw = json.dumps(x)
                    break
        rows.append(dict(model=m, record=rid, domain=dom, model_item=item, model_item_json=raw,
                         assertion=r["assertion"], best_matching_source_sentence=best,
                         item_token_overlap_with_sentence=round(overlap, 2), full_source_note=note,
                         rule_category=r["category"], rule_rationale=r["rationale"],
                         clinician_decision="", clinician_reason="", reviewer_id="",
                         second_reviewer_decision="", disagreement_resolution=""))
    out = pd.DataFrame(rows)
    out.to_csv(R + "secondary_unsupported_adjudication_for_clinician_review.csv", index=False)
    print(f"clinician-review table: {len(out)} rows; {(out.model_item_json == '').sum()} without raw JSON match")


if __name__ == "__main__":
    main()

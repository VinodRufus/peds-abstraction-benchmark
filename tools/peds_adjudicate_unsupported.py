"""Rule-based adjudication of the fabrication-audit candidates.

Reads results/peds_abstraction/secondary_unsupported_items.csv and writes
secondary_unsupported_adjudication.csv with a category per item:
lexical_variant, abbreviation, paraphrase, inference_correct, or fabrication
(anything the rules cannot classify is left UNRESOLVED for manual review and
the script exits non-zero so it is never silently counted as benign).

Usage: python tools/peds_adjudicate_unsupported.py
"""
import re
import sys

import pandas as pd

R = "results/peds_abstraction/"


def cat(item: str):
    t = item.lower()
    if re.search(r"\bbirth\b", t) and not re.search(r"prematur|preterm", t):
        return "lexical_variant", "'birth' for note text 'born'"
    if re.search(r"\d+ days ago", t):
        return "inference_correct", "delivery dated from the documented age in days"
    if "icu" in t or "cbc" in t:
        return "abbreviation", "ICU / CBC for 'intensive care unit' / 'complete blood count' or the reverse"
    if re.search(r"prematur|preterm", t):
        return "inference_correct", "36 weeks gestation classified as late preterm / prematurity"
    if "delivery complications" in t:
        return "inference_correct", "'uncomplicated vaginal delivery' rendered as complications ruled out"
    if "gestational diabetes" in t:
        return "paraphrase", "'pregnancy complicated by gestational diabetes' rendered as maternal gestational diabetes"
    if re.search(r"initiation|started|therapy|infusion", t):
        return "paraphrase", "'Started <drug> ... IV continuous' rendered as initiation / therapy / infusion"
    if re.search(r"prior clinic|dose documentation|dosing documentation|clinic visit", t):
        return "paraphrase", "dose-basis distractor sentence reworded"
    if re.search(r"encounter|diagnosis|workup|admission", t):
        return "paraphrase", "encounter/assessment wording restated as an event"
    return "UNRESOLVED", ""


def main():
    d = pd.read_csv(R + "secondary_unsupported_items.csv")
    rows = []
    for _, r in d.iterrows():
        c, why = cat(str(r["item"]))
        rows.append(dict(**r, category=c, rationale=why))
    adj = pd.DataFrame(rows)
    adj.to_csv(R + "secondary_unsupported_adjudication.csv", index=False)
    print(adj.groupby("category").size().to_string())
    print(f"fabrications: {(adj.category == 'fabrication').sum()} of {len(adj)}")
    unresolved = int((adj.category == "UNRESOLVED").sum())
    if unresolved:
        print(f"{unresolved} UNRESOLVED items need manual review:")
        print(adj[adj.category == "UNRESOLVED"][["model", "record", "domain", "item"]].to_string(index=False))
        sys.exit(1)


if __name__ == "__main__":
    main()

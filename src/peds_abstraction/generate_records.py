"""Render clinical narratives and gold JSON from scenario specs.

Ordering guarantee (this is what keeps gold independent):
  scenario spec -> narrative (template render, optional LLM paraphrase)
  scenario spec -> gold JSON (deterministic derivation)
The paraphrasing model NEVER sees the gold JSON, and any factual drift it
introduces is caught by the clinician review, which checks narrative
against gold field by field.

Usage:
    python src/peds_abstraction/generate_records.py --config config/prereg_peds_abstraction.yaml
    python src/peds_abstraction/generate_records.py --paraphrase openai:gpt-4o   # optional
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import sys
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.runner import make_runner  # noqa: E402

AGE_PHRASE = {"days": "day-old", "weeks": "week-old", "months": "month-old", "years": "year-old"}
SETTING_PHRASE = {"outpatient": "seen in the outpatient clinic",
                  "emergency": "evaluated in the emergency department",
                  "inpatient": "admitted to the inpatient ward",
                  "icu": "admitted to the intensive care unit"}


def render_narrative(sc: dict) -> str:
    d = sc
    age = d["age_value"]
    lines = []
    lines.append(f"Patient is a {age['value']}-{AGE_PHRASE[age['unit']]} "
                 f"{d['sex']} weighing {d['weight_kg']} kg, "
                 f"{SETTING_PHRASE[d['encounter']]}.")
    for dx in d["diagnoses"]:
        if dx["status"] == "active":
            lines.append(f"Assessment: {dx['name']}.")
        elif dx["status"] == "suspected":
            lines.append(f"Assessment: suspected {dx['name']}; workup in progress.")
        elif dx["status"] == "historical":
            lines.append(f"Past medical history is notable for {dx['name']}.")
        elif dx["status"] == "ruled_out":
            lines.append(f"{dx['name']} was considered and ruled out.")
    for m in d["medications"]:
        wb = " (weight-based)" if m.get("weight_based") else ""
        lines.append(f"Started {m['name']} {m['dose']} {m['dose_unit']} "
                     f"{m['route']} {m['frequency']}{wb}.")
    for l in d["labs"]:
        flag = f", flagged {l['flag']}" if l.get("flag") else ""
        lines.append(f"Laboratory results: {l['test']} {l['value']} {l['unit']}{flag}.")
    for p in d["procedures"]:
        if p["status"] == "completed":
            lines.append(f"{p['name'].capitalize()} was performed.")
        else:
            lines.append(f"{p['name'].capitalize()} is planned.")
    for dis in d.get("distractors", []):
        lines.append(dis["text"].capitalize() + ".")
    lines.append(f"Disposition: {d['disposition']}.")
    return " ".join(lines)


def derive_gold(sc: dict) -> dict:
    """Gold comes from the spec, deterministically. Every distractor kind is
    keyed (2026-09-28, pre-gold, zero model runs; see DEVIATIONS.md): a
    schema-following model that preserves negation and temporality must
    never be penalized for doing so. Negations key as ruled_out diagnoses,
    planned/historical lines as temporal events, and the dose_trap line as
    a historical documentation event."""
    gold = {
        "demographics": {"age_value": sc["age_value"]["value"],
                         "age_unit": sc["age_value"]["unit"],
                         "sex": sc["sex"], "weight_kg": sc["weight_kg"]},
        "diagnoses": [dict(name=d["name"], status=d["status"]) for d in sc["diagnoses"]],
        "medications": [dict(m) for m in sc["medications"]],
        "labs": [dict(l) for l in sc["labs"]],
        "procedures": [dict(p) for p in sc["procedures"]],
        "encounter": {"setting": sc["encounter"], "disposition": sc["disposition"]},
        "temporal": [],
    }
    for dis in sc.get("distractors", []):
        if dis["kind"] == "planned":
            gold["temporal"].append({"event": dis["text"], "when": None, "qualifier": "planned"})
        elif dis["kind"] in ("historical", "dose_trap"):
            gold["temporal"].append({"event": dis["text"], "when": None, "qualifier": "historical"})
        elif dis["kind"] == "negation":
            txt = dis["text"].lower()
            if "allergy" in txt:
                gold["diagnoses"].append({"name": "penicillin allergy", "status": "ruled_out"})
            elif "fever" in txt:
                gold["diagnoses"].append({"name": "fever", "status": "ruled_out"})
    return gold


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/prereg_peds_abstraction.yaml")
    ap.add_argument("--scenarios", default="data/peds_abstraction/scenarios")
    ap.add_argument("--paraphrase", default=None,
                    help="optional model id to vary narrative wording; never sees gold")
    a = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(a.scenarios, "*.yaml")))
    if not paths:
        sys.exit("No scenarios found. Run src/peds_abstraction/make_scenarios.py first.")
    runner = make_runner(a.paraphrase) if a.paraphrase else None
    os.makedirs("data/peds_abstraction/records", exist_ok=True)
    os.makedirs("data/peds_abstraction/gold", exist_ok=True)
    for p in paths:
        sc = yaml.safe_load(open(p))
        narrative = render_narrative(sc)
        if runner:
            c = runner.complete(
                "You reword clinical notes. Preserve every clinical fact, number, "
                "unit, negation, and planned-versus-completed status EXACTLY. "
                "Change only sentence structure and connective wording. "
                "Return the reworded note only.",
                narrative, temperature=0.0, max_tokens=800)
            if not c.error and c.text.strip():
                narrative = c.text.strip()
        open(f"data/peds_abstraction/records/{sc['id']}.txt", "w").write(narrative)
        json.dump(derive_gold(sc), open(f"data/peds_abstraction/gold/{sc['id']}.json", "w"), indent=1)
    print(f"rendered {len(paths)} records + gold.")
    print("NEXT: clinician review (all records; 25% double), kappa to data/peds_abstraction/review/, "
          "adjudication log, then: git tag gold-peds_abstraction-v1")


if __name__ == "__main__":
    main()

"""Generate the 160-scenario skeleton corpus (4 age bands x 4 encounters x 10).

Clinical truth is fixed HERE, first. The narrative is rendered FROM the
scenario, and the gold JSON is derived FROM the scenario, never from the
narrative. Every generated scenario is marked review_required: true and the
corpus is not usable until two clinically qualified reviewers have reviewed
it (see config gold policy) and the gold is frozen with `git tag gold-peds_abstraction-v1`.

Usage:
    python src/peds_abstraction/make_scenarios.py --config config/prereg_peds_abstraction.yaml
"""
from __future__ import annotations
import argparse
import os
import random
import yaml

# Seed clinical templates per age band. Values are chosen to be plausible
# pediatric documentation; the CLINICIAN REVIEW is the authority that
# corrects them. Extend freely BEFORE the gold freeze.
TEMPLATES = {
    "neonate": [
        dict(dx="early-onset sepsis, suspected", med=("ampicillin", 100, "mg/kg/dose", "IV", "q8h", True),
             lab=("WBC", 4.1, "10^3/uL", "low"), proc=("lumbar puncture", "completed"),
             wt=(2.8, 4.2), age=("days", 2, 25)),
        dict(dx="neonatal jaundice", med=(None, None, None, None, None, None),
             lab=("total bilirubin", 14.2, "mg/dL", "high"), proc=("phototherapy", "completed"),
             wt=(2.6, 4.0), age=("days", 3, 20)),
        dict(dx="hypoglycemia of the newborn", med=("dextrose 10%", 2, "mL/kg", "IV", "prn", True),
             lab=("glucose", 38, "mg/dL", "low"), proc=("heel-stick glucose check", "completed"),
             wt=(2.5, 4.1), age=("days", 1, 14)),
    ],
    "infant": [
        dict(dx="bronchiolitis", med=("albuterol", 2.5, "mg", "nebulized", "q6h", False),
             lab=("WBC", 11.8, "10^3/uL", "normal"), proc=("nasal suctioning", "completed"),
             wt=(4.5, 10.0), age=("months", 2, 11)),
        dict(dx="acute otitis media", med=("amoxicillin", 45, "mg/kg/day", "PO", "q12h", True),
             lab=(None, None, None, None), proc=("tympanic membrane exam", "completed"),
             wt=(6.0, 10.5), age=("months", 6, 12)),
        dict(dx="febrile urinary tract infection", med=("ceftriaxone", 50, "mg/kg/dose", "IV", "q24h", True),
             lab=("CRP", 6.4, "mg/dL", "high"), proc=("urine culture", "completed"),
             wt=(5.0, 10.0), age=("months", 3, 11)),
    ],
    "child": [
        dict(dx="asthma exacerbation", med=("prednisolone", 2, "mg/kg/day", "PO", "q24h", True),
             lab=(None, None, None, None), proc=("peak flow measurement", "completed"),
             wt=(14, 30), age=("years", 3, 11)),
        dict(dx="community-acquired pneumonia", med=("amoxicillin", 90, "mg/kg/day", "PO", "q12h", True),
             lab=("WBC", 16.2, "10^3/uL", "high"), proc=("chest radiograph", "completed"),
             wt=(15, 35), age=("years", 4, 11)),
        dict(dx="appendicitis, suspected", med=("morphine", 0.05, "mg/kg/dose", "IV", "prn", True),
             lab=("WBC", 14.9, "10^3/uL", "high"), proc=("abdominal ultrasound", "planned"),
             wt=(18, 40), age=("years", 5, 11)),
    ],
    "adolescent": [
        dict(dx="diabetic ketoacidosis", med=("insulin", 0.1, "units/kg/hour", "IV", "continuous", True),
             lab=("glucose", 486, "mg/dL", "high"), proc=("venous blood gas", "completed"),
             wt=(40, 80), age=("years", 12, 17)),
        dict(dx="major depressive disorder, historical", med=("sertraline", 50, "mg", "PO", "q24h", False),
             lab=(None, None, None, None), proc=("safety screening", "completed"),
             wt=(45, 85), age=("years", 13, 17)),
        dict(dx="sports-related concussion", med=("acetaminophen", 650, "mg", "PO", "prn", False),
             lab=(None, None, None, None), proc=("head CT", "planned"),
             wt=(45, 90), age=("years", 12, 17)),
    ],
}

DISTRACTORS = [
    ("negation", "no history of penicillin allergy"),
    ("negation", "denies fever at home"),
    ("planned", "repeat CBC planned for tomorrow morning"),
    ("planned", "follow-up echocardiogram to be scheduled"),
    ("historical", "history of RSV bronchiolitis last winter, resolved"),
    ("dose_trap", "prior clinic note listed the dose per day rather than per dose"),
]

DISPO = {"outpatient": "discharged home", "emergency": "admitted to inpatient unit",
         "inpatient": "discharged home", "icu": "transferred to inpatient unit"}


def build(cfg, outdir):
    rng = random.Random(cfg["decoding"]["seed"])
    bands = cfg["corpus"]["age_bands"]
    encounters = cfg["corpus"]["encounters"]
    per_band = cfg["corpus"]["per_age_band"]
    n_per_cell = per_band // len(encounters)
    count = 0
    for band in bands:
        for enc in encounters:
            for i in range(n_per_cell):
                t = TEMPLATES[band][i % len(TEMPLATES[band])]
                unit, lo, hi = t["age"]
                age_val = rng.randint(lo, hi)
                wt = round(rng.uniform(*t["wt"]), 1)
                sex = rng.choice(["male", "female"])
                n_dis = rng.randint(1, 3)
                distractors = rng.sample(DISTRACTORS, n_dis)
                sc = {
                    "id": f"REC-{band[:3]}-{enc[:3]}-{i+1:03d}",
                    "review_required": True,
                    "age_band": band,
                    "age_value": {"unit": unit, "value": age_val},
                    "weight_kg": wt,
                    "sex": sex,
                    "encounter": enc,
                    "disposition": DISPO[enc],
                    "diagnoses": [{"name": t["dx"].split(",")[0].strip(),
                                   "status": ("suspected" if "suspected" in t["dx"]
                                              else "historical" if "historical" in t["dx"]
                                              else "active")}],
                    "medications": ([] if t["med"][0] is None else [{
                        "name": t["med"][0], "dose": t["med"][1],
                        "dose_unit": t["med"][2], "route": t["med"][3],
                        "frequency": t["med"][4], "weight_based": t["med"][5]}]),
                    "labs": ([] if t["lab"][0] is None else [{
                        "test": t["lab"][0], "value": t["lab"][1],
                        "unit": t["lab"][2], "flag": t["lab"][3]}]),
                    "procedures": [{"name": t["proc"][0], "status": t["proc"][1]}],
                    "distractors": [{"kind": k, "text": txt} for k, txt in distractors],
                }
                path = os.path.join(outdir, sc["id"] + ".yaml")
                with open(path, "w") as f:
                    yaml.safe_dump(sc, f, sort_keys=False)
                count += 1
    print(f"wrote {count} scenario skeletons to {outdir}")
    print("NEXT: clinician review of every scenario, adjudication log, then git tag gold-peds_abstraction-v1")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/prereg_peds_abstraction.yaml")
    ap.add_argument("--out", default="data/peds_abstraction/scenarios")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config))
    os.makedirs(a.out, exist_ok=True)
    build(cfg, a.out)

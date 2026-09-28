"""Generate the 160-scenario skeleton corpus (4 age bands x 4 encounters x 10).

Clinical truth is fixed HERE, first. The narrative is rendered FROM the
scenario, and the gold JSON is derived FROM the scenario, never from the
narrative. Every generated scenario is marked review_required: true and the
corpus is not usable until the gold policy in config (clinical review or
documented construction validity) is satisfied and the gold is frozen with
`git tag gold-peds_abstraction-v1`.

2026-09-28 revision (pre-gold, zero model runs; see DEVIATIONS.md):
applied the AI plausibility screen's corrections. Diagnosis templates are
now restricted to clinically plausible care settings, distractor pools are
age-band aware, guideline-misaligned template values were corrected
(bronchiolitis albuterol removed per AAP; AOM amoxicillin raised to
90 mg/kg/day; early-onset sepsis restricted to the first 72 hours;
pediatric MDD switched to active status with fluoxetine, the labeled
pediatric agent), and fixed history lines give jaundice/hypoglycemia
records the gestational and risk context plausibility requires.

Usage:
    python src/peds_abstraction/make_scenarios.py --config config/prereg_peds_abstraction.yaml
"""
from __future__ import annotations
import argparse
import os
import random
import yaml

# Seed clinical templates per age band. Values are chosen to be plausible
# pediatric documentation; the gold policy in the config is the authority
# that validates them. Extend freely BEFORE the gold freeze.
# Each template: settings = encounters where this presentation is
# clinically plausible; history = fixed context lines (rendered in the note
# AND keyed into gold temporal, so context is never an unkeyed trap);
# overrides = per-setting replacements applied on top of the template.
TEMPLATES = {
    "neonate": [
        dict(dx="early-onset sepsis, suspected",
             med=("ampicillin", 100, "mg/kg/dose", "IV", "q8h", True),
             lab=("WBC", 4.1, "10^3/uL", "low"), proc=("lumbar puncture", "completed"),
             wt=(2.8, 4.2), age=("days", 1, 2),
             settings={"emergency", "inpatient", "icu"},
             history=[("historical", "born at term with unknown maternal group B streptococcus status")]),
        dict(dx="neonatal jaundice",
             med=(None, None, None, None, None, None),
             lab=("total bilirubin", 14.2, "mg/dL", "high"), proc=("phototherapy", "completed"),
             wt=(2.6, 4.0), age=("days", 3, 6),
             settings={"outpatient", "emergency", "inpatient"},
             history=[("historical", "born at 36 weeks gestation, exclusively breastfed")]),
        dict(dx="hypoglycemia of the newborn",
             med=("dextrose 10%", 2, "mL/kg", "IV", "once", True),
             lab=("glucose", 38, "mg/dL", "low"), proc=("heel-stick glucose check", "completed"),
             wt=(2.5, 4.1), age=("days", 1, 2),
             settings={"emergency", "inpatient", "icu"},
             history=[("historical", "pregnancy complicated by gestational diabetes")]),
    ],
    "infant": [
        dict(dx="bronchiolitis",
             med=(None, None, None, None, None, None),   # supportive care per AAP
             lab=(None, None, None, None), proc=("nasal suctioning", "completed"),   # no routine testing per AAP
             wt=(4.5, 10.0), age=("months", 2, 11),
             settings={"outpatient", "emergency", "inpatient", "icu"}),
        dict(dx="acute otitis media",
             med=("amoxicillin", 90, "mg/kg/day", "PO", "q12h", True),   # AAP high dose
             lab=(None, None, None, None), proc=("tympanic membrane exam", "completed"),
             wt=(6.0, 10.5), age=("months", 6, 12),
             settings={"outpatient", "emergency"},
             dispo={"emergency": "discharged home from the emergency department"}),
        dict(dx="febrile urinary tract infection",
             med=("ceftriaxone", 50, "mg/kg/dose", "IV", "q24h", True),
             lab=("CRP", 6.4, "mg/dL", "high"), proc=("urine culture", "completed"),
             wt=(5.0, 10.0), age=("months", 3, 11),
             settings={"emergency", "inpatient", "icu"}, no_fever_negation=True),
    ],
    "child": [
        dict(dx="asthma exacerbation",
             med=("prednisolone", 2, "mg/kg/day", "PO", "q24h", True),
             lab=(None, None, None, None), proc=("peak flow measurement", "completed"),
             wt=(14, 30), age=("years", 6, 11),
             settings={"outpatient", "emergency", "inpatient", "icu"},
             overrides={"icu": dict(dx="status asthmaticus",
                                    med=("albuterol", 0.5, "mg/kg/hour", "nebulized", "continuous", True),
                                    proc=("continuous pulse oximetry", "completed"))}),
        dict(dx="community-acquired pneumonia",
             med=("amoxicillin", 90, "mg/kg/day", "PO", "q12h", True),
             lab=("WBC", 16.2, "10^3/uL", "high"), proc=("chest radiograph", "completed"),
             wt=(15, 35), age=("years", 4, 11),
             settings={"outpatient", "emergency", "inpatient"}),
        dict(dx="appendicitis, suspected",
             med=("morphine", 0.05, "mg/kg/dose", "IV", "prn", True),
             lab=("WBC", 14.9, "10^3/uL", "high"), proc=("abdominal ultrasound", "planned"),
             wt=(18, 40), age=("years", 5, 11),
             settings={"emergency", "inpatient", "icu"},
             overrides={"icu": dict(dx="perforated appendicitis",
                                    proc=("appendectomy", "completed"))}),
    ],
    "adolescent": [
        dict(dx="diabetic ketoacidosis",
             med=("insulin", 0.1, "units/kg/hour", "IV", "continuous", True),
             lab=("glucose", 486, "mg/dL", "high"), proc=("venous blood gas", "completed"),
             wt=(40, 80), age=("years", 12, 17),
             settings={"emergency", "inpatient", "icu"}),
        dict(dx="major depressive disorder",
             med=("fluoxetine", 10, "mg", "PO", "q24h", False),   # labeled pediatric agent
             lab=(None, None, None, None), proc=("safety screening", "completed"),
             wt=(45, 85), age=("years", 13, 17),
             settings={"outpatient", "emergency", "inpatient"}),
        dict(dx="sports-related concussion",
             med=("acetaminophen", 650, "mg", "PO", "prn", False),
             lab=(None, None, None, None), proc=("concussion symptom assessment", "completed"),   # no routine imaging per CDC
             wt=(45, 90), age=("years", 12, 17),
             settings={"outpatient", "emergency", "inpatient"}),
    ],
}

# Band-aware distractor pools. A neonate has no "last winter", cannot
# "deny" symptoms, and RSV bronchiolitis is an infancy illness, so the
# historical and fever lines vary by band. dose_trap is only sampled for
# records whose medication uses a per-weight mg/kg dose unit, where the
# per-day / per-dose confusion it describes can actually occur.
FEVER_NEG = {"neonate": "no fever reported at home", "infant": "no fever reported at home",
             "child": "denies fever at home", "adolescent": "denies fever at home"}
HISTORICAL = {"neonate": "born by uncomplicated vaginal delivery",
              "infant": "history of mild eczema, well controlled",
              "child": "history of RSV bronchiolitis in infancy, resolved",
              "adolescent": "history of RSV bronchiolitis in infancy, resolved"}


def distractor_pool(band, t):
    pool = [
        ("negation", "no history of penicillin allergy"),
        ("planned", "repeat CBC planned for tomorrow morning"),
        ("planned", "follow-up with the primary care clinic in one week"),
        ("historical", HISTORICAL[band]),
    ]
    if not t.get("no_fever_negation"):
        pool.append(("negation", FEVER_NEG[band]))
    med = t["med"]
    if med[0] is not None and med[2] and "mg/kg" in str(med[2]):
        pool.append(("dose_trap",
                     "prior clinic note listed the dose per day rather than per dose"))
    return pool


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
            allowed = [t for t in TEMPLATES[band] if enc in t["settings"]]
            if not allowed:
                raise SystemExit(f"no template allowed for {band}/{enc}")
            for i in range(n_per_cell):
                t = dict(allowed[i % len(allowed)])
                ov = (t.get("overrides") or {}).get(enc, {})
                for k, v in ov.items():
                    t[k] = v
                unit, lo, hi = t["age"]
                age_val = rng.randint(lo, hi)
                wt = round(rng.uniform(*t["wt"]), 1)
                sex = rng.choice(["male", "female"])
                pool = distractor_pool(band, t)
                n_dis = rng.randint(1, 3)
                distractors = rng.sample(pool, n_dis)
                fixed = [{"kind": k, "text": txt} for k, txt in t.get("history", [])]
                dispo = (t.get("dispo") or {}).get(enc, DISPO[enc])
                sc = {
                    "id": f"REC-{band[:3]}-{enc[:3]}-{i+1:03d}",
                    "review_required": True,
                    "age_band": band,
                    "age_value": {"unit": unit, "value": age_val},
                    "weight_kg": wt,
                    "sex": sex,
                    "encounter": enc,
                    "disposition": dispo,
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
                    "distractors": fixed + [{"kind": k, "text": txt}
                                            for k, txt in distractors],
                }
                path = os.path.join(outdir, sc["id"] + ".yaml")
                with open(path, "w") as f:
                    yaml.safe_dump(sc, f, sort_keys=False)
                count += 1
    print(f"wrote {count} scenario skeletons to {outdir}")
    print("NEXT: satisfy the gold policy (review/validation + adjudication log), "
          "then git tag gold-peds_abstraction-v1")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/prereg_peds_abstraction.yaml")
    ap.add_argument("--out", default="data/peds_abstraction/scenarios")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config))
    os.makedirs(a.out, exist_ok=True)
    build(cfg, a.out)

"""Construction-validity check: every frozen gold value must appear in its record's narrative.

List items (diagnoses.name, medications.name, labs.test, procedures.name, temporal.event)
must occur verbatim (case-insensitive). Scalar fields must occur in the narrative's
controlled-vocabulary form: age as "<value>-<unit singular>-old", setting "icu" as
"intensive care unit", sex, weight, and disposition verbatim. Exits non-zero on any miss.

Usage: python tools/peds_gold_narrative_check.py
"""
import glob, json, os, sys

SETTING_TEXT = {"icu": "intensive care unit", "inpatient": "inpatient", "emergency": "emergency",
                "outpatient": "outpatient"}
gold = {os.path.basename(p)[:-5]: json.load(open(p)) for p in glob.glob("data/peds_abstraction/gold/*.json")}
n_items = n_scalars = 0
misses = []
for rid, g in sorted(gold.items()):
    note = open(f"data/peds_abstraction/records/{rid}.txt").read().lower()
    for dom, key in (("diagnoses", "name"), ("medications", "name"), ("labs", "test"),
                     ("procedures", "name"), ("temporal", "event")):
        for x in g[dom]:
            n_items += 1
            if str(x[key]).lower() not in note:
                misses.append((rid, dom, x[key]))
    d, e = g["demographics"], g["encounter"]
    unit = str(d["age_unit"]).lower()
    checks = {
        "age": f"{d['age_value']}-{unit[:-1] if unit.endswith('s') else unit}-old" in note,
        "sex": str(d["sex"]).lower() in note,
        "weight_kg": f"{d['weight_kg']} kg" in note,
        "setting": SETTING_TEXT.get(str(e["setting"]).lower(), str(e["setting"]).lower()) in note,
        "disposition": str(e["disposition"]).lower() in note,
    }
    for f, ok in checks.items():
        n_scalars += 1
        if not ok:
            misses.append((rid, f, g["demographics"].get(f, g["encounter"].get(f))))
print(f"gold list items checked: {n_items}; scalar values checked: {n_scalars}; misses: {len(misses)}")
for m in misses[:20]:
    print("MISS", m)
sys.exit(1 if misses else 0)

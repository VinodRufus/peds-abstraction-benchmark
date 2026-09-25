"""Normalization and matching rules, written down BEFORE scoring.

Policies:
- names: lowercase, strip punctuation, synonym map lookup
- numeric values: value AND unit must both match after explicit unit
  conversion; mg/kg/dose vs mg/kg/day are handled explicitly, never silently
- categorical: exact match after normalization
- lists (diagnoses, meds, labs, procedures, temporal): set-based matching
  keyed on the normalized name/test/event -> TP / FP / FN
"""
from __future__ import annotations
import re

SYNONYMS = {
    # medication names (starter map; extend in repo, freeze before scoring)
    "acetaminophen": ["paracetamol", "tylenol"],
    "albuterol": ["salbutamol"],
    "ampicillin": [],
    "ceftriaxone": ["rocephin"],
    "ibuprofen": ["motrin", "advil"],
    # lab tests
    "wbc": ["white blood cell count", "white blood cells", "leukocytes"],
    "hgb": ["hemoglobin", "hb"],
    "plt": ["platelets", "platelet count"],
    "crp": ["c-reactive protein"],
    "glucose": ["blood glucose", "serum glucose"],
    # routes
    "iv": ["intravenous", "intravenously"],
    "po": ["oral", "orally", "by mouth"],
    "im": ["intramuscular"],
}
_CANON = {}
for canon, alts in SYNONYMS.items():
    _CANON[canon] = canon
    for a in alts:
        _CANON[a] = canon

UNIT_EQUIV = {
    "mg/kg/dose": "mg/kg/dose",
    "mg/kg/day": "mg/kg/day",
    "mg/kg": "mg/kg/dose",     # bare mg/kg documented per-dose by convention;
                               # the scenario spec must always state which.
    "10^3/ul": "10^3/ul",
    "x10^3/ul": "10^3/ul",
    "k/ul": "10^3/ul",
    "10*3/ul": "10^3/ul",
    "mg/dl": "mg/dl",
    "mmol/l": "mmol/l",
    "g/dl": "g/dl",
}

AGE_TO_DAYS = {"days": 1.0, "weeks": 7.0, "months": 30.44, "years": 365.25}

FREQ_MAP = {
    "q6h": "q6h", "every 6 hours": "q6h", "four times daily": "q6h",
    "q8h": "q8h", "every 8 hours": "q8h", "three times daily": "q8h", "tid": "q8h",
    "q12h": "q12h", "every 12 hours": "q12h", "twice daily": "q12h", "bid": "q12h",
    "q24h": "q24h", "daily": "q24h", "once daily": "q24h", "qd": "q24h",
    "prn": "prn", "as needed": "prn",
}


def norm_name(s):
    if s is None:
        return None
    s = re.sub(r"[^a-z0-9 /^*.+-]", "", str(s).lower().strip())
    s = re.sub(r"\s+", " ", s)
    return _CANON.get(s, s)


def norm_unit(s):
    if s is None:
        return None
    s = str(s).lower().replace(" ", "")
    s = s.replace("µ", "u").replace("μ", "u")
    return UNIT_EQUIV.get(s, s)


def norm_freq(s):
    if s is None:
        return None
    return FREQ_MAP.get(str(s).lower().strip(), str(s).lower().strip())


def norm_value(v):
    if v is None:
        return None
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return str(v).lower().strip()


def age_in_days(value, unit):
    if value is None or unit not in AGE_TO_DAYS:
        return None
    return float(value) * AGE_TO_DAYS[unit]


def numbers_match(a, b, rel_tol=0.0):
    a, b = norm_value(a), norm_value(b)
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) and isinstance(b, float):
        if rel_tol == 0.0:
            return a == b
        return abs(a - b) <= rel_tol * max(abs(a), abs(b), 1e-9)
    return a == b


def med_key(m):
    return norm_name(m.get("name"))


def med_equal(pred, gold):
    """Full-field medication match. Dose unit must match after explicit
    conversion; mg/kg/dose vs mg/kg/day mismatches are counted as errors,
    never silently reconciled."""
    return (norm_name(pred.get("name")) == norm_name(gold.get("name"))
            and numbers_match(pred.get("dose"), gold.get("dose"))
            and norm_unit(pred.get("dose_unit")) == norm_unit(gold.get("dose_unit"))
            and norm_name(pred.get("route")) == norm_name(gold.get("route"))
            and norm_freq(pred.get("frequency")) == norm_freq(gold.get("frequency")))


def lab_key(l):
    return norm_name(l.get("test"))


def lab_equal(pred, gold):
    return (norm_name(pred.get("test")) == norm_name(gold.get("test"))
            and numbers_match(pred.get("value"), gold.get("value"))
            and norm_unit(pred.get("unit")) == norm_unit(gold.get("unit")))


def dx_key(d):
    return norm_name(d.get("name"))


def dx_equal(pred, gold):
    return (norm_name(pred.get("name")) == norm_name(gold.get("name"))
            and str(pred.get("status")).lower() == str(gold.get("status")).lower())


def proc_key(p):
    return norm_name(p.get("name"))


def proc_equal(pred, gold):
    return (norm_name(pred.get("name")) == norm_name(gold.get("name"))
            and str(pred.get("status")).lower() == str(gold.get("status")).lower())


def temporal_key(t):
    return norm_name(t.get("event"))


def temporal_equal(pred, gold):
    return (norm_name(pred.get("event")) == norm_name(gold.get("event"))
            and str(pred.get("qualifier")).lower() == str(gold.get("qualifier")).lower())

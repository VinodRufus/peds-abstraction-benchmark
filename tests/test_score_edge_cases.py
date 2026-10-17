"""Edge cases named in the manuscript's scoring validation description."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from common.runner import parse_json_strict
from peds_abstraction.score import score_lists, score_scalars


def _med(dose=45, dose_unit="mg/kg/day"):
    return {"name": "amoxicillin", "dose": dose, "dose_unit": dose_unit,
            "route": "PO", "frequency": "q12h", "weight_based": True}


def _scalars(weight=20.0):
    return {"demographics": {"age_value": 6, "age_unit": "years",
                             "sex": "female", "weight_kg": weight},
            "encounter": {"setting": "outpatient", "disposition": "home"}}


def test_empty_prediction_counts_all_gold_items_as_missing():
    gold = {**_scalars(),
            "diagnoses": [{"name": "asthma", "status": "active"}],
            "medications": [_med()],
            "labs": [{"test": "glucose", "value": 100, "unit": "mg/dL"}],
            "procedures": [{"name": "chest radiograph", "status": "planned"}],
            "temporal": [{"event": "symptoms began yesterday", "qualifier": "historical"}]}
    scores = score_lists({}, gold)
    assert all(s["tp"] == 0 and s["fp"] == 0 and s["fn"] == 1
               for s in scores.values())
    assert not any(score_scalars({}, gold).values())


def test_malformed_json_is_not_given_partial_credit():
    parsed, error = parse_json_strict('{"diagnoses": [')
    assert parsed is None and error
    gold = {"diagnoses": [{"name": "sepsis", "status": "suspected"}]}
    assert score_lists(parsed, gold)["diagnoses"] == {
        "tp": 0, "fp": 0, "fn": 1, "n_gold": 1, "n_pred": 0}


def test_duplicate_prediction_items_count_once():
    diagnosis = {"name": "asthma", "status": "active"}
    scored = score_lists({"diagnoses": [diagnosis, dict(diagnosis)]},
                         {"diagnoses": [diagnosis]})["diagnoses"]
    assert scored == {"tp": 1, "fp": 0, "fn": 0, "n_gold": 1, "n_pred": 1}


def test_null_value_does_not_match_documented_value():
    med = score_lists({"medications": [_med(dose=None)]},
                      {"medications": [_med()]})["medications"]
    assert (med["tp"], med["fp"], med["fn"]) == (0, 1, 1)
    assert score_scalars(_scalars(weight=None), _scalars())["demographics.weight_kg"] is False


def test_equivalent_numeric_representations_match():
    gold = {**_scalars(), "medications": [_med()],
            "labs": [{"test": "glucose", "value": 100, "unit": "mg/dL"}]}
    pred = {**_scalars(weight="20.0000"), "medications": [_med(dose="45.0")],
            "labs": [{"test": "glucose", "value": "100.0", "unit": "mg/dl"}]}
    scored = score_lists(pred, gold)
    assert scored["medications"]["tp"] == scored["labs"]["tp"] == 1
    assert score_scalars(pred, gold)["demographics.weight_kg"] is True


def test_lab_unit_mismatch_counts_both_fp_and_fn():
    gold = {"labs": [{"test": "glucose", "value": 100, "unit": "mg/dL"}]}
    pred = {"labs": [{"test": "glucose", "value": 100, "unit": "mmol/L"}]}
    scored = score_lists(pred, gold)["labs"]
    assert (scored["tp"], scored["fp"], scored["fn"]) == (0, 1, 1)


def test_invalid_list_shape_does_not_crash_or_receive_credit():
    gold = {"diagnoses": [{"name": "asthma", "status": "active"}],
            "medications": [_med()]}
    pred = {"diagnoses": {"name": "asthma", "status": "active"},
            "medications": None}
    scored = score_lists(pred, gold)
    assert scored["diagnoses"]["fn"] == scored["medications"]["fn"] == 1
    assert scored["diagnoses"]["tp"] == scored["medications"]["tp"] == 0

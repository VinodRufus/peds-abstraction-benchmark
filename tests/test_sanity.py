import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from common import normalize as N
from common.stats import paired_bootstrap, holm


def test_dose_unit_never_silently_reconciled():
    a = {"name": "amoxicillin", "dose": 45, "dose_unit": "mg/kg/day",
         "route": "PO", "frequency": "q12h", "weight_based": True}
    b = dict(a, dose_unit="mg/kg/dose")
    assert not N.med_equal(a, b)


def test_synonyms_and_units():
    assert N.norm_name("Paracetamol") == "acetaminophen"
    assert N.norm_unit("K/uL") == N.norm_unit("10^3/uL")
    assert N.norm_freq("twice daily") == N.norm_freq("q12h")


def test_negation_status_matters():
    g = {"name": "sepsis", "status": "ruled_out"}
    p = {"name": "sepsis", "status": "active"}
    assert not N.dx_equal(p, g)


def test_bootstrap_and_holm():
    import numpy as np
    m, (lo, hi) = paired_bootstrap(np.array([0.1] * 50))
    assert abs(m - 0.1) < 1e-9 and lo <= m <= hi
    adj, rej = holm([0.001, 0.04, 0.2])
    assert rej[0] and not rej[2]


def test_audit_catches_blocklist(tmp_path):
    from common.audit import scan
    p = tmp_path / "x.txt"
    p.write_text("data exported from Epic yesterday")
    assert scan(str(tmp_path))

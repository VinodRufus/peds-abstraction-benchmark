"""Pre-registered statistics: paired bootstrap CIs, McNemar, Holm correction."""
from __future__ import annotations
import numpy as np


def paired_bootstrap(diff: np.ndarray, n: int = 10_000, seed: int = 20260923,
                     ci: float = 0.95):
    """Mean difference with a percentile bootstrap CI over paired units."""
    diff = np.asarray(diff, dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(diff), size=(n, len(diff)))
    boots = diff[idx].mean(axis=1)
    lo, hi = np.percentile(boots, [(1 - ci) / 2 * 100, (1 + ci) / 2 * 100])
    return float(diff.mean()), (float(lo), float(hi))


def bootstrap_metric(values: np.ndarray, n: int = 10_000, seed: int = 20260923,
                     ci: float = 0.95):
    """CI for the mean of per-record metric values."""
    return paired_bootstrap(np.asarray(values, dtype=float), n=n, seed=seed, ci=ci)


def mcnemar_test(correct_a: np.ndarray, correct_b: np.ndarray):
    """Exact McNemar on paired binary correctness vectors."""
    from statsmodels.stats.contingency_tables import mcnemar
    a = np.asarray(correct_a, dtype=bool)
    b = np.asarray(correct_b, dtype=bool)
    n01 = int(np.sum(~a & b))
    n10 = int(np.sum(a & ~b))
    table = [[int(np.sum(a & b)), n01], [n10, int(np.sum(~a & ~b))]]
    exact = (n01 + n10) < 25
    res = mcnemar(table, exact=exact, correction=not exact)
    # effect size: difference in accuracy
    eff = float(a.mean() - b.mean())
    return {"p": float(res.pvalue), "n01": n01, "n10": n10, "effect": eff}


def holm(pvals: list[float], alpha: float = 0.05):
    """Holm step-down correction. Returns adjusted p-values and rejections."""
    m = len(pvals)
    order = np.argsort(pvals)
    adj = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (m - rank) * pvals[i])
        adj[i] = min(1.0, running)
    return adj.tolist(), [bool(p <= alpha) for p in adj]


def cohen_kappa(a, b):
    from sklearn.metrics import cohen_kappa_score
    return float(cohen_kappa_score(a, b))

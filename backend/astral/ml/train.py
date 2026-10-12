"""Reproducible training and evaluation.

Candidates:
  rule_miss          documented rule baseline: score = -log10(miss)
  logistic           standardised logistic regression (class_weight balanced)
  hist_gbm           histogram gradient boosting (sklearn), early stopping off

Hyperparameters are selected on the validation split by average precision;
the test split is touched once, after selection. Rare-event setting:
accuracy is not reported as a headline metric because a classifier that
always predicts "low priority" would score highly.
"""

from __future__ import annotations

import io
import json
from importlib.metadata import version as pkg_version
from typing import Any

import joblib
import numpy as np
from sklearn.calibration import calibration_curve
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, confusion_matrix, precision_recall_curve, precision_score, recall_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .. import __version__
from .dataset import split
from .features import FEATURES, SCHEMA_VERSION


class RuleBaseline:
    """score = -log10(miss); monotone in miss distance. Not probabilistic."""

    def predict_score(self, x: np.ndarray) -> np.ndarray:
        return -x[:, FEATURES.index("log10_miss_km")]


def _candidates(seed: int) -> dict[str, list[tuple[dict, Any]]]:
    return {
        "logistic": [({"C": c}, make_pipeline(StandardScaler(), LogisticRegression(C=c, class_weight="balanced", max_iter=2000, random_state=seed)))
                     for c in (0.1, 1.0, 10.0)],
        "hist_gbm": [({"max_depth": d, "learning_rate": lr},
                      HistGradientBoostingClassifier(max_depth=d, learning_rate=lr, max_iter=300, random_state=seed, early_stopping=False))
                     for d in (3, 6) for lr in (0.05, 0.1)],
    }


def _metrics(y: np.ndarray, score: np.ndarray, prob: np.ndarray | None, regimes: np.ndarray | None, threshold: float | None) -> dict:
    out: dict[str, Any] = {"n": int(len(y)), "positives": int(y.sum()), "prevalence": float(y.mean())}
    out["average_precision"] = float(average_precision_score(y, score))
    p, r, t = precision_recall_curve(y, score)
    keep = np.unique(np.linspace(0, len(p) - 1, min(len(p), 60)).astype(int))
    out["pr_curve"] = {"precision": p[keep].round(5).tolist(), "recall": r[keep].round(5).tolist()}
    if prob is not None and threshold is not None:
        pred = (prob >= threshold).astype(int)
        tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
        out.update({
            "threshold": threshold,
            "precision": float(precision_score(y, pred, zero_division=0)),
            "recall": float(recall_score(y, pred, zero_division=0)),
            "false_negative_rate": float(fn / max(fn + tp, 1)),
            "false_positive_rate": float(fp / max(fp + tn, 1)),
            "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
            "brier": float(brier_score_loss(y, prob)),
        })
        fr, mp = calibration_curve(y, prob, n_bins=10, strategy="quantile")
        out["calibration"] = {"fraction_positive": fr.round(4).tolist(), "mean_predicted": mp.round(4).tolist()}
    if regimes is not None:
        per = {}
        for reg in np.unique(regimes):
            m = regimes == reg
            if y[m].sum() > 0 and (1 - y[m]).sum() > 0:
                per[str(reg)] = {"n": int(m.sum()), "average_precision": float(average_precision_score(y[m], score[m]))}
        out["by_regime"] = per
    return out


def train(data: dict, seed: int = 0) -> dict:
    sp = split(data)
    X, y = data["X"], data["y"]
    tr, va, te = sp["train"], sp["val"], sp["test"]
    # Leakage guards (asserted, not assumed)
    g = data["groups"]
    if (set(g[tr]) & set(g[te])) or (set(g[va]) & set(g[te])) or (set(g[tr]) & set(g[va])):
        raise RuntimeError("event-group leakage between splits")
    if data["created"][te].min() < data["created"][tr].max() - 1.0:  # temporal ordering by group creation
        raise RuntimeError("temporal leakage: test events precede training events")
    selection = {}
    best_overall = None
    for name, cands in _candidates(seed).items():
        best = None
        for params, model in cands:
            model.fit(X[tr], y[tr])
            ap = average_precision_score(y[va], model.predict_proba(X[va])[:, 1])
            if best is None or ap > best[0]:
                best = (ap, params, model)
        selection[name] = {"params": best[1], "val_average_precision": float(best[0])}
        if best_overall is None or best[0] > best_overall[0]:
            best_overall = (best[0], name, best[1], best[2])
    _, name, params, model = best_overall
    # refit chosen config on train+val, evaluate once on test
    trva = np.concatenate([tr, va])
    model.fit(X[trva], y[trva])
    prob_te = model.predict_proba(X[te])[:, 1]
    rule = RuleBaseline()
    test_metrics = {
        name: _metrics(y[te], prob_te, prob_te, data["regime"][te], 0.5),
        "rule_miss": _metrics(y[te], rule.predict_score(X[te]), None, data["regime"][te], None),
    }
    ranges = {"min": X[trva].min(axis=0).tolist(), "max": X[trva].max(axis=0).tolist()}
    buf = io.BytesIO()
    joblib.dump(model, buf)
    meta = {
        "name": "encounter-priority",
        "algorithm": name,
        "params": params,
        "selection": selection,
        "metrics": {"test": test_metrics, "split_sizes": {k: int(len(v)) for k, v in sp.items()}},
        "feature_schema": {"version": SCHEMA_VERSION, "features": FEATURES, "training_ranges": ranges},
        "seed": seed,
        "data_seed": data["seed"],
        "training_data_sha256": data["sha256"],
        "training_data_origin": data["origin"],
        "label_definition": data["label_definition"],
        "code_version": __version__,
        "sklearn_version": pkg_version("scikit-learn"),
        "status": "experimental",
    }
    return {"model_bytes": buf.getvalue(), "meta": meta, "model": model}


def meta_json(meta: dict) -> str:
    return json.dumps(meta, indent=2, sort_keys=True)

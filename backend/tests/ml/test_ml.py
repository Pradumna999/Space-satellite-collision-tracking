"""ML verification: determinism, leakage guards, schema, metrics, persistence,
OOD flags, and fallback when no model is active."""

import io

import joblib
import numpy as np
import pytest

from astral.ml.dataset import generate, split
from astral.ml.features import FEATURES, matrix
from astral.ml.train import RuleBaseline, train


@pytest.fixture(scope="module")
def data():
    return generate(600, seed=1)


def test_generation_is_deterministic(data):
    again = generate(600, seed=1)
    assert again["sha256"] == data["sha256"]
    assert generate(600, seed=2)["sha256"] != data["sha256"]


def test_rare_event_and_origin(data):
    assert data["origin"] == "simulated"
    assert 0.005 < data["y"].mean() < 0.15


def test_split_group_disjoint_and_temporal(data):
    sp = split(data)
    g = data["groups"]
    assert not (set(g[sp["train"]]) & set(g[sp["test"]]))
    assert not (set(g[sp["val"]]) & set(g[sp["test"]]))
    assert data["created"][sp["test"]].min() > data["created"][sp["train"]].max() - 1


def test_training_reproducible_and_metrics_consistent(data):
    a = train(data, seed=3)
    b = train(data, seed=3)
    assert a["meta"]["metrics"] == b["meta"]["metrics"]
    m = a["meta"]["metrics"]["test"][a["meta"]["algorithm"]]
    cm = m["confusion_matrix"]
    assert cm["tp"] + cm["fn"] == m["positives"]
    if cm["tp"] + cm["fp"]:
        assert m["precision"] == pytest.approx(cm["tp"] / (cm["tp"] + cm["fp"]))
    assert m["recall"] == pytest.approx(cm["tp"] / max(cm["tp"] + cm["fn"], 1))
    assert a["meta"]["status"] == "experimental"
    assert "rule_miss" in a["meta"]["metrics"]["test"]


def test_persistence_round_trip(data):
    out = train(data, seed=0)
    model = joblib.load(io.BytesIO(out["model_bytes"]))
    x = data["X"][:20]
    assert np.allclose(model.predict_proba(x), out["model"].predict_proba(x))


def test_feature_schema_enforced():
    with pytest.raises(ValueError):
        matrix([[1.0, 2.0]])
    assert matrix([[0.0] * len(FEATURES)]).shape == (1, len(FEATURES))


def test_rule_baseline_monotone_in_miss():
    x = np.zeros((3, len(FEATURES)))
    x[:, FEATURES.index("log10_miss_km")] = [-1, 0, 1]
    s = RuleBaseline().predict_score(x)
    assert s[0] > s[1] > s[2]


def test_ood_flag_and_fallback(app, users):
    from astral.db.models import MLModel
    from astral.db.session import SessionLocal
    from astral.ml.infer import LoadedModel, load_active

    db = SessionLocal()
    assert load_active(db) is None  # no active model -> physical pipeline unaffected
    d = generate(300, seed=4)
    out = train(d, seed=0)
    row = MLModel(name="t", version="1", status="experimental", artefact_key="", artefact_sha256="", training_data_sha256="",
                  training_data_origin="simulated", params={}, metrics={}, feature_schema=out["meta"]["feature_schema"], seed=0, code_version="t")
    lm = LoadedModel(row, out["model"])
    x = d["X"][:2].copy()
    x[1, FEATURES.index("altitude_km")] = 36000.0
    _, ood = lm.score(x)
    assert ood[0] == [] and "altitude_km" in ood[1]
    db.close()

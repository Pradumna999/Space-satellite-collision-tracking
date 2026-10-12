"""Inference with out-of-distribution flagging. If no active model exists or
loading fails, callers get ``None`` and the physical pipeline is unaffected."""

from __future__ import annotations

import io
import logging

import joblib
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import MLModel
from ..services import storage
from .features import FEATURES, SCHEMA_VERSION

log = logging.getLogger(__name__)


class LoadedModel:
    def __init__(self, row: MLModel, model):
        self.row = row
        self.model = model
        r = row.feature_schema["training_ranges"]
        self.lo = np.asarray(r["min"])
        self.hi = np.asarray(r["max"])

    @property
    def version(self) -> str:
        return f"{self.row.name}:{self.row.version}"

    def score(self, x: np.ndarray) -> tuple[np.ndarray, list[list[str]]]:
        prob = self.model.predict_proba(x)[:, 1]
        ood = []
        for row in x:
            out = [FEATURES[i] for i in range(len(FEATURES)) if row[i] < self.lo[i] or row[i] > self.hi[i]]
            ood.append(out)
        return prob, ood


def load_active(db: Session) -> LoadedModel | None:
    row = db.scalar(select(MLModel).where(MLModel.status == "active_experimental").order_by(MLModel.created_at.desc()))
    if row is None:
        return None
    if row.feature_schema.get("version") != SCHEMA_VERSION:
        log.warning("active model %s has incompatible feature schema; ML disabled", row.version)
        return None
    try:
        data = storage.get(row.artefact_key)
        if storage.sha256(data) != row.artefact_sha256:
            log.error("model artefact hash mismatch for %s; ML disabled", row.version)
            return None
        return LoadedModel(row, joblib.load(io.BytesIO(data)))  # noqa: S301 - artefact written by ASTRAL, hash-verified
    except Exception:  # model failure must never break screening
        log.exception("failed to load model %s; ML disabled", row.version)
        return None

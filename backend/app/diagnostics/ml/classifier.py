"""diagnostics/ml/classifier.py

Runtime vibration/acoustic classifier with graceful degradation:

1. Conv-BiLSTM (PyTorch) if torch is importable and the artifact loads.
2. Otherwise a rule-based envelope-order classifier, so the channel keeps working.

Either way the output is a `ChannelVerdict` with source=ml_classifier and
`details.backend` saying which path produced it.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from app.diagnostics.features import FEATURE_NAMES, N_FEATURES
from app.diagnostics.ml.dataset import CLASSES, SEQ_LEN
from app.diagnostics.schema import ChannelVerdict, DiagFault, DiagSource

log = logging.getLogger(__name__)
ARTIFACT = Path(__file__).parent / "artifacts" / "conv_bilstm.pt"
_IDX = {n: i for i, n in enumerate(FEATURE_NAMES)}
_Y = N_FEATURES      # offset of the vib_y channel (load-zone direction)
_Z = 2 * N_FEATURES  # offset of the vib_z (axial) channel


def _f(vec: np.ndarray, name: str, offset: int = _Y) -> float:
    return float(vec[offset + _IDX[name]])


def severity_from_features(fault: str, vec: np.ndarray) -> float:
    """Map the latest window's features to a [0, 1] severity for the given class."""
    if fault.startswith("bearing"):
        return float(np.clip((_f(vec, "rms") - 0.1) / 1.6, 0.0, 1.0))
    if fault == "unbalance":
        return float(np.clip(_f(vec, "order_1x") / 1.4, 0.0, 1.0))
    if fault == "misalignment":
        return float(np.clip(_f(vec, "order_2x") / 1.1, 0.0, 1.0))
    return 0.0


def rule_classify(vec: np.ndarray) -> tuple[str, float]:
    env = {"bearing_outer": _f(vec, "env_bpfo"), "bearing_inner": _f(vec, "env_bpfi"), "bearing_ball": _f(vec, "env_2bsf")}
    best = max(env, key=env.get)
    if env[best] > 0.3 and _f(vec, "kurtosis") > 4.0:
        return best, float(min(1.0, 0.5 + env[best] / 2))
    o1, o2, z1 = _f(vec, "order_1x"), _f(vec, "order_2x"), _f(vec, "order_1x", _Z)
    if o2 > 0.2 and (z1 > 0.15 or o2 > o1):
        return "misalignment", float(min(1.0, 0.5 + o2))
    if o1 > 0.25:
        return "unbalance", float(min(1.0, 0.5 + o1 / 2))
    return "healthy", 0.7


class MechanicalClassifier:
    def __init__(self, artifact: Path = ARTIFACT, use_ml: bool = True):
        self.model = None
        self.mean = self.std = None
        self.backend = "rules"
        self.load_error: str | None = None
        if use_ml:
            self._try_load(artifact)

    def _try_load(self, artifact: Path) -> None:
        try:
            import torch

            from app.diagnostics.ml.model import ConvBiLSTM

            ckpt = torch.load(artifact, map_location="cpu", weights_only=True)
            if list(ckpt["classes"]) != CLASSES or int(ckpt["seq_len"]) != SEQ_LEN:
                raise ValueError("artifact classes/seq_len do not match code")
            model = ConvBiLSTM(int(ckpt["n_features"]), len(CLASSES))
            model.load_state_dict(ckpt["state_dict"])
            model.eval()
            self.model, self._torch = model, torch
            self.mean, self.std = ckpt["mean"].numpy(), ckpt["std"].numpy()
            self.backend = "conv_bilstm"
        except Exception as exc:  # noqa: BLE001 - any failure => degrade to rules
            self.load_error = f"{type(exc).__name__}: {exc}"
            log.warning("ML classifier unavailable, using rule-based fallback: %s", self.load_error)

    def classify(self, seq: np.ndarray) -> ChannelVerdict:
        """seq: (SEQ_LEN, F) window features, most recent last."""
        latest = seq[-1]
        probs = None
        if self.model is not None:
            try:
                x = ((seq - self.mean) / self.std).astype(np.float32)[None]
                with self._torch.no_grad():
                    logits = self.model(self._torch.tensor(x))
                    probs = self._torch.softmax(logits, dim=1)[0].numpy()
                fault = CLASSES[int(np.argmax(probs))]
                conf = float(np.max(probs))
                backend = "conv_bilstm"
            except Exception as exc:  # noqa: BLE001
                log.exception("ML inference failed; falling back to rules")
                self.load_error = f"inference: {exc}"
                probs = None
        if probs is None:
            fault, conf = rule_classify(latest)
            backend = "rules"
        details = {"backend": backend}
        if probs is not None:
            details["probabilities"] = {c: round(float(p), 4) for c, p in zip(CLASSES, probs, strict=True)}
        return ChannelVerdict(DiagSource.ML_CLASSIFIER, DiagFault(fault), conf,
                              severity_from_features(fault, latest), True, details)

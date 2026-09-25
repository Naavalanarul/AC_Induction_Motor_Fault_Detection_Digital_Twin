"""diagnostics/ml/train.py

Train and evaluate the Conv-BiLSTM with a leak-safe protocol:

* split by simulation run (group), never by frame
* normalization statistics fitted on the training split only
* repeated over several seeds (different splits + inits); mean +/- std reported

Usage (from backend/):
    python -m app.diagnostics.ml.train --runs-per-class 40 --seeds 0 1 2
Writes app/diagnostics/ml/artifacts/{conv_bilstm.pt, metrics.json}.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn

from app.diagnostics.features import CHANNELS, FEATURE_NAMES
from app.diagnostics.ml.dataset import CLASSES, SEQ_LEN, build_dataset, group_split
from app.diagnostics.ml.model import ConvBiLSTM

ARTIFACT_DIR = Path(__file__).parent / "artifacts"


def _fit(model, Xtr, ytr, Xva, yva, epochs: int, seed: int):
    torch.manual_seed(seed)
    opt = torch.optim.Adam(model.parameters(), lr=2e-3, weight_decay=1e-4)
    loss_fn = nn.CrossEntropyLoss()
    Xtr_t, ytr_t = torch.tensor(Xtr), torch.tensor(ytr)
    Xva_t = torch.tensor(Xva)
    best, best_state = -1.0, None
    g = torch.Generator().manual_seed(seed)
    for _ in range(epochs):
        model.train()
        perm = torch.randperm(len(Xtr_t), generator=g)
        for i in range(0, len(perm), 64):
            idx = perm[i:i + 64]
            if len(idx) < 2:
                continue
            opt.zero_grad()
            loss = loss_fn(model(Xtr_t[idx]), ytr_t[idx])
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            acc = float((model(Xva_t).argmax(1).numpy() == yva).mean())
        if acc >= best:
            best, best_state = acc, {k: v.clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    return best


def evaluate(model, X, y) -> dict:
    model.eval()
    with torch.no_grad():
        pred = model(torch.tensor(X)).argmax(1).numpy()
    k = len(CLASSES)
    cm = np.zeros((k, k), dtype=int)
    for t, p in zip(y, pred, strict=True):
        cm[t, p] += 1
    f1s = []
    for c in range(k):
        tp = cm[c, c]
        prec = tp / max(1, cm[:, c].sum())
        rec = tp / max(1, cm[c, :].sum())
        f1s.append(0.0 if prec + rec == 0 else 2 * prec * rec / (prec + rec))
    return {"accuracy": float((pred == y).mean()), "macro_f1": float(np.mean(f1s)), "confusion": cm.tolist()}


def normalize_stats(X: np.ndarray):
    flat = X.reshape(-1, X.shape[-1])
    mean, std = flat.mean(0), flat.std(0)
    return mean, np.where(std < 1e-8, 1.0, std)


def run(runs_per_class: int, seeds: list[int], epochs: int, seconds: float, out_dir: Path = ARTIFACT_DIR) -> dict:
    t0 = time.time()
    data = build_dataset(runs_per_class, seed=1234, seconds=seconds)
    print(f"dataset: {data.X.shape} from {len(np.unique(data.groups))} runs in {time.time() - t0:.1f}s")
    per_seed, final = [], None
    for seed in seeds:
        tr, va, te = group_split(data.groups, seed=seed)
        assert not (set(data.groups[tr]) & set(data.groups[te])), "group leakage"
        mean, std = normalize_stats(data.X[tr])  # train split only

        def nz(a, mean=mean, std=std):
            return ((a - mean) / std).astype(np.float32)

        torch.manual_seed(seed)
        model = ConvBiLSTM(data.X.shape[-1], len(CLASSES))
        val_acc = _fit(model, nz(data.X[tr]), data.y[tr], nz(data.X[va]), data.y[va], epochs, seed)
        res = evaluate(model, nz(data.X[te]), data.y[te])
        res.update(seed=seed, val_accuracy=val_acc, n_train_runs=len(np.unique(data.groups[tr])),
                   n_test_runs=len(np.unique(data.groups[te])))
        print(f"seed {seed}: val={val_acc:.3f} test acc={res['accuracy']:.3f} macroF1={res['macro_f1']:.3f}")
        per_seed.append(res)
        if final is None:
            final = (model, mean, std)
    accs = [r["accuracy"] for r in per_seed]
    f1s = [r["macro_f1"] for r in per_seed]
    metrics = {
        "protocol": "group split by simulation run (60/20/20), train-only normalization, multi-seed",
        "data": "simulated only (this project's generator); not validated on real hardware",
        "classes": CLASSES, "seq_len": SEQ_LEN, "channels": CHANNELS, "features_per_channel": len(FEATURE_NAMES),
        "runs_per_class": runs_per_class, "run_seconds": seconds, "epochs": epochs,
        "accuracy_mean": float(np.mean(accs)), "accuracy_std": float(np.std(accs)),
        "macro_f1_mean": float(np.mean(f1s)), "macro_f1_std": float(np.std(f1s)),
        "per_seed": per_seed,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    model, mean, std = final
    torch.save({"state_dict": model.state_dict(), "mean": torch.tensor(mean), "std": torch.tensor(std),
                "n_features": int(data.X.shape[-1]), "classes": CLASSES, "seq_len": SEQ_LEN},
               out_dir / "conv_bilstm.pt")
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(f"accuracy {metrics['accuracy_mean']:.3f} +/- {metrics['accuracy_std']:.3f} "
          f"(macro-F1 {metrics['macro_f1_mean']:.3f}); total {time.time() - t0:.1f}s")
    return metrics


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-per-class", type=int, default=40)
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--seconds", type=float, default=3.0)
    args = ap.parse_args()
    run(args.runs_per_class, args.seeds, args.epochs, args.seconds)


if __name__ == "__main__":
    main()

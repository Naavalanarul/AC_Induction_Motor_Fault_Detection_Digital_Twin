"""validation/model_comparison.py — Deep neural models vs baselines on identical grouped splits.

Compares:
1. Conv-BiLSTM (PyTorch)
2. 1D-CNN (PyTorch)
3. BiLSTM (PyTorch)
4. MLP (PyTorch)
5. Random Forest (Scikit-Learn)
6. Logistic Regression (Scikit-Learn)
7. Rule-Based Fallback (diagnostics/ml/classifier.py)

Metrics: Macro-F1, per-class precision & recall, confusion matrix, ECE, Brier score,
parameter count, and inference latency per window.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import torch
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score
from sklearn.preprocessing import StandardScaler

from app.diagnostics.ml.baselines import count_parameters, get_baseline_model
from app.diagnostics.ml.classifier import rule_classify
from app.diagnostics.ml.dataset import CLASSES, build_dataset, build_hard_dataset, group_split
from app.diagnostics.ml.train import _fit, normalize_stats
from app.validation import metrics as M
from app.validation.reporting import git_commit, git_dirty


def evaluate_predictions(
    y_true: np.ndarray,
    proba: np.ndarray,
    classes: list[str],
) -> dict[str, Any]:
    """Compute comprehensive classification metrics from predicted probabilities."""
    y_pred = proba.argmax(axis=1)
    k = len(classes)
    prec_per_class = precision_score(y_true, y_pred, labels=list(range(k)), average=None, zero_division=0)
    rec_per_class = recall_score(y_true, y_pred, labels=list(range(k)), average=None, zero_division=0)
    cm = confusion_matrix(y_true, y_pred, labels=list(range(k)))

    class_names_true = [classes[i] for i in y_true]
    return {
        "accuracy": float(np.mean(y_true == y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "precision_macro": float(np.mean(prec_per_class)),
        "recall_macro": float(np.mean(rec_per_class)),
        "per_class_precision": {classes[i]: float(prec_per_class[i]) for i in range(k)},
        "per_class_recall": {classes[i]: float(rec_per_class[i]) for i in range(k)},
        "confusion_matrix": cm.tolist(),
        "ece": float(M.ece(class_names_true, proba, classes)),
        "brier": float(M.brier(class_names_true, proba, classes)),
    }


def measure_inference_time_ms(infer_fn, sample: Any, n_repeats: int = 150) -> float:
    """Measure single-window inference latency in milliseconds."""
    # Warmup
    for _ in range(15):
        infer_fn(sample)
    t0 = time.perf_counter()
    for _ in range(n_repeats):
        infer_fn(sample)
    t1 = time.perf_counter()
    return ((t1 - t0) / n_repeats) * 1000.0


def run_comparison(
    seeds: list[int],
    out_dir: Path,
    runs_per_class: int = 30,
    epochs: int = 30,
    seconds: float = 3.0,
    dataset_type: str = "default",
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    t_start = time.time()

    # 1. Dataset Generation
    print(f"Generating {dataset_type} dataset (runs_per_class={runs_per_class})...")
    if dataset_type == "hard":
        data = build_hard_dataset(runs_per_class=runs_per_class, seed=42, seconds=seconds)
    else:
        data = build_dataset(runs_per_class=runs_per_class, seed=42, seconds=seconds)

    n_samples, seq_len, n_features = data.X.shape
    k_classes = len(CLASSES)
    print(f"Dataset generated: {data.X.shape} across {len(np.unique(data.groups))} runs.")

    model_names = [
        "Conv-BiLSTM",
        "1D-CNN",
        "BiLSTM",
        "MLP",
        "Random Forest",
        "Logistic Regression",
        "Rule-Based Heuristic",
    ]

    all_seed_results: list[dict[str, Any]] = []

    for seed in seeds:
        print(f"\n--- Running Seed {seed} ---")
        tr, va, te = group_split(data.groups, fractions=(0.6, 0.2, 0.2), seed=seed)

        # STRICT GROUP DISJOINTNESS ASSERTION
        tr_groups = set(data.groups[tr])
        te_groups = set(data.groups[te])
        assert len(tr_groups & te_groups) == 0, f"DATA LEAKAGE: groups overlap between train and test! {tr_groups & te_groups}"

        # Neural Pre-processing (Normalization on train only)
        mean, std = normalize_stats(data.X[tr])

        def nz(arr, m=mean, s=std):
            return ((arr - m) / s).astype(np.float32)

        Xtr_nz, ytr = nz(data.X[tr]), data.y[tr]
        Xva_nz, yva = nz(data.X[va]), data.y[va]
        Xte_nz, yte = nz(data.X[te]), data.y[te]

        # Flattened features for sklearn models
        X_flat = data.X.reshape(n_samples, -1)
        scaler = StandardScaler()
        Xtr_flat = scaler.fit_transform(X_flat[tr])
        Xte_flat = scaler.transform(X_flat[te])

        # Benchmark each model
        for mname in model_names:
            torch.manual_seed(seed)
            np.random.seed(seed)

            if mname in ("Conv-BiLSTM", "1D-CNN", "BiLSTM", "MLP"):
                mapping = {
                    "Conv-BiLSTM": "conv_bilstm",
                    "1D-CNN": "1d_cnn",
                    "BiLSTM": "bilstm",
                    "MLP": "mlp",
                }
                model = get_baseline_model(mapping[mname], n_features, k_classes, seq_len=seq_len)
                n_params = count_parameters(model)
                _fit(model, Xtr_nz, ytr, Xva_nz, yva, epochs=epochs, seed=seed)

                model.eval()
                with torch.no_grad():
                    logits = model(torch.tensor(Xte_nz))
                    proba = torch.softmax(logits, dim=-1).cpu().numpy()

                sample_tensor = torch.tensor(Xte_nz[:1])
                lat_ms = measure_inference_time_ms(lambda x, cur_m=model: cur_m(x), sample_tensor)

            elif mname == "Random Forest":
                clf = RandomForestClassifier(n_estimators=100, min_samples_leaf=2, random_state=seed, n_jobs=1)
                clf.fit(Xtr_flat, ytr)
                proba = clf.predict_proba(Xte_flat)
                n_params = sum(tree.tree_.node_count for tree in clf.estimators_)
                sample_flat = Xte_flat[:1]
                lat_ms = measure_inference_time_ms(lambda x, cur_clf=clf: cur_clf.predict_proba(x), sample_flat)

            elif mname == "Logistic Regression":
                clf = LogisticRegression(max_iter=1000, random_state=seed)
                clf.fit(Xtr_flat, ytr)
                proba = clf.predict_proba(Xte_flat)
                n_params = clf.coef_.size + clf.intercept_.size
                sample_flat = Xte_flat[:1]
                lat_ms = measure_inference_time_ms(lambda x, cur_clf=clf: cur_clf.predict_proba(x), sample_flat)

            elif mname == "Rule-Based Heuristic":
                # Fallback rule classifier operates on last window features
                n_params = 0  # Heuristic threshold lookup rules
                test_windows = data.X[te, -1, :]  # (N_te, n_features)
                proba_list = []
                for w in test_windows:
                    pred_cls, conf = rule_classify(w)
                    p = np.full(k_classes, (1.0 - conf) / max(1, k_classes - 1))
                    if pred_cls in CLASSES:
                        p[CLASSES.index(pred_cls)] = conf
                    else:
                        p[CLASSES.index("healthy")] = conf
                    proba_list.append(p / p.sum())
                proba = np.array(proba_list)
                lat_ms = measure_inference_time_ms(lambda w: rule_classify(w), test_windows[0])

            else:
                raise ValueError(f"Unknown model: {mname}")

            metrics = evaluate_predictions(yte, proba, CLASSES)
            metrics.update({
                "model": mname,
                "seed": seed,
                "dataset_type": dataset_type,
                "param_count": n_params,
                "latency_ms": lat_ms,
            })
            all_seed_results.append(metrics)
            print(f"  [{mname:<20}] Macro-F1: {metrics['macro_f1']:.4f} | Acc: {metrics['accuracy']:.4f} | ECE: {metrics['ece']:.4f} | Latency: {lat_ms:.3f} ms")

    # 2. Aggregations (Mean +/- Std)
    summary: dict[str, Any] = {}

    for mname in model_names:
        m_runs = [r for r in all_seed_results if r["model"] == mname]
        f1s = [r["macro_f1"] for r in m_runs]
        accs = [r["accuracy"] for r in m_runs]
        eces = [r["ece"] for r in m_runs]
        briers = [r["brier"] for r in m_runs]
        lats = [r["latency_ms"] for r in m_runs]
        params = m_runs[0]["param_count"]

        summary[mname] = {
            "param_count": params,
            "macro_f1_mean": float(np.mean(f1s)),
            "macro_f1_std": float(np.std(f1s)),
            "accuracy_mean": float(np.mean(accs)),
            "accuracy_std": float(np.std(accs)),
            "ece_mean": float(np.mean(eces)),
            "ece_std": float(np.std(eces)),
            "brier_mean": float(np.mean(briers)),
            "brier_std": float(np.std(briers)),
            "latency_ms_mean": float(np.mean(lats)),
            "latency_ms_std": float(np.std(lats)),
            "per_class_recall": {
                c: {
                    "mean": float(np.mean([r["per_class_recall"][c] for r in m_runs])),
                    "std": float(np.std([r["per_class_recall"][c] for r in m_runs])),
                }
                for c in CLASSES
            },
            "per_class_precision": {
                c: {
                    "mean": float(np.mean([r["per_class_precision"][c] for r in m_runs])),
                    "std": float(np.std([r["per_class_precision"][c] for r in m_runs])),
                }
                for c in CLASSES
            },
        }

    # 3. Write metrics.csv
    csv_file = out_dir / "metrics.csv"
    with open(csv_file, "w", newline="") as f:
        fieldnames = ["model", "seed", "macro_f1", "accuracy", "ece", "brier", "latency_ms", "param_count"]
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in all_seed_results:
            writer.writerow(r)

    # 4. Write summary.json
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    # 5. Write meta.json
    meta = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "git_commit": git_commit(),
        "git_dirty": git_dirty(),
        "python_version": sys.version,
        "seeds": seeds,
        "dataset_type": dataset_type,
        "runs_per_class": runs_per_class,
        "run_seconds": seconds,
        "epochs": epochs,
        "classes": CLASSES,
        "models_evaluated": model_names,
        "command": " ".join(sys.argv),
        "duration_s": float(time.time() - t_start),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    # 6. Generate LaTeX Table (table.tex)
    generate_latex_table(out_dir / "table.tex", summary)

    # 7. Generate Comparison Figures (PNG and PDF)
    generate_comparison_plots(out_dir, summary)

    print(f"\nModel comparison finished in {time.time() - t_start:.1f}s. Artifacts written to {out_dir}/")
    return summary


def generate_latex_table(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Model Comparison on Identical Grouped Simulation Splits (Mean $\pm$ Std Over Seeds)}",
        r"\label{tab:model_comparison}",
        r"\begin{tabular}{lrrrrrr}",
        r"\toprule",
        r"Model & Params & Latency (ms) & Macro-F1 & Accuracy & ECE $\downarrow$ & Brier $\downarrow$ \\",
        r"\midrule",
    ]
    for model, s in summary.items():
        params_str = f"{s['param_count']:,}" if s['param_count'] > 0 else "---"
        f1_str = f"{s['macro_f1_mean']:.3f} $\\pm$ {s['macro_f1_std']:.3f}"
        acc_str = f"{s['accuracy_mean']:.3f} $\\pm$ {s['accuracy_std']:.3f}"
        ece_str = f"{s['ece_mean']:.3f} $\\pm$ {s['ece_std']:.3f}"
        brier_str = f"{s['brier_mean']:.3f} $\\pm$ {s['brier_std']:.3f}"
        lat_str = f"{s['latency_ms_mean']:.2f}"
        lines.append(f"{model} & {params_str} & {lat_str} & {f1_str} & {acc_str} & {ece_str} & {brier_str} \\\\")
    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ])
    path.write_text("\n".join(lines))


def generate_comparison_plots(out_dir: Path, summary: dict[str, Any]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    models = list(summary.keys())
    f1_means = [summary[m]["macro_f1_mean"] for m in models]
    f1_stds = [summary[m]["macro_f1_std"] for m in models]
    ece_means = [summary[m]["ece_mean"] for m in models]

    x = np.arange(len(models))
    width = 0.38

    fig, ax1 = plt.subplots(figsize=(8.0, 4.5))
    ax1.bar(x - width/2, f1_means, width, yerr=f1_stds, label="Macro-F1", capsize=4, color="#2a78d6")
    ax1.set_ylabel("Macro-F1 Score", color="#2a78d6", fontsize=10)
    ax1.set_ylim(0.0, 1.05)
    ax1.tick_params(axis="y", labelcolor="#2a78d6")

    ax2 = ax1.twinx()
    ax2.bar(x + width/2, ece_means, width, label="ECE (lower is better)", color="#eb6834", alpha=0.85)
    ax2.set_ylabel("Expected Calibration Error (ECE)", color="#eb6834", fontsize=10)
    ax2.tick_params(axis="y", labelcolor="#eb6834")

    ax1.set_xticks(x)
    ax1.set_xticklabels(models, rotation=25, ha="right", fontsize=9)
    ax1.set_title("Vibration/Acoustic Model Comparison on Identical Grouped Splits", fontsize=11, fontweight="bold")
    ax1.grid(axis="y", linestyle="--", alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_dir / "model_comparison.png", dpi=200)
    fig.savefig(out_dir / "model_comparison.pdf")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Model comparison on identical grouped splits.")
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2, 3, 4], help="Random seeds")
    parser.add_argument("--out", type=str, default="reports/paper/model_comparison", help="Output directory")
    parser.add_argument("--runs-per-class", type=int, default=25, help="Simulation runs per class")
    parser.add_argument("--epochs", type=int, default=30, help="Training epochs for neural models")
    parser.add_argument("--seconds", type=float, default=3.0, help="Duration in seconds per run")
    parser.add_argument("--dataset", type=str, default="default", choices=["default", "hard", "both"])
    args = parser.parse_args()

    out_base = Path(args.out)
    if args.dataset in ("default", "both"):
        print("\n=== RUNNING ON DEFAULT SIMULATOR DATASET ===")
        run_comparison(
            seeds=args.seeds,
            out_dir=out_base if args.dataset == "default" else out_base / "default",
            runs_per_class=args.runs_per_class,
            epochs=args.epochs,
            seconds=args.seconds,
            dataset_type="default",
        )
    if args.dataset in ("hard", "both"):
        print("\n=== RUNNING ON HARD SIMULATOR DATASET (Parameter Mismatch, Low Severity, High Noise) ===")
        run_comparison(
            seeds=args.seeds,
            out_dir=out_base if args.dataset == "hard" else out_base / "hard",
            runs_per_class=args.runs_per_class,
            epochs=args.epochs,
            seconds=args.seconds,
            dataset_type="hard",
        )


if __name__ == "__main__":
    main()

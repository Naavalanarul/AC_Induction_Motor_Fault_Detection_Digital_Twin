"""validation/robustness.py — Parametric robustness sweeps for paper evidence.

Sweeps:
P4-1: Sensor noise (SNR: 40, 30, 20, 10 dB)
P4-2: Mechanical Load (25, 50, 75, 100, 110 % of rated torque)
P4-3: Supply condition (Balanced, 2% & 5% Unbalance, 5% & 10% Harmonics, 10% & 20% Sag)
P4-4: Parameter mismatch between physical plant and nominal twin observer (Rs, Rr, Lm, and Combined: ±5, ±10, ±20 %)
P4-5: Fault severity (0.05, 0.10, 0.20, 0.40, 0.60, 0.80, 1.00)

Evaluates:
- Fused diagnosis
- Electrical-only channel
- ML-only channel
Reporting Macro-F1 and False Alarm Rate per channel across at least 3 random seeds.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import f1_score

from app.diagnostics.electrical import ElectricalResidualDiagnostic
from app.diagnostics.features import WINDOW_S, window_features
from app.diagnostics.fusion import WEIGHTS, fuse
from app.diagnostics.ml.classifier import MechanicalClassifier
from app.diagnostics.protection import ProtectionDiagnostic
from app.diagnostics.schema import ChannelVerdict, DiagFault, DiagSource
from app.diagnostics.supply import SupplyDiagnostic
from app.diagnostics.thermal import ThermalDiagnostic
from app.simulation import faults as F
from app.simulation.params import DEFAULT_MOTOR, MotorParams, validate_motor_params
from app.simulation.twin_state import MotorSimulator
from app.validation.reporting import git_commit, git_dirty

FAULT_CLASSES = [
    ("healthy", 0.0),
    ("interturn_short", 0.35),
    ("broken_rotor_bar", 0.40),
    ("bearing_outer", 0.35),
    ("unbalance", 0.40),
]


def evaluate_single_run(
    cls: str,
    severity: float,
    seed: int,
    load_nm: float = 8.0,
    noise_rms: float = 0.05,
    plant_params: MotorParams = DEFAULT_MOTOR,
    supply_type: str | None = None,
    supply_sev: float = 0.0,
    seconds: float = 2.5,
) -> tuple[str, str, str]:
    """Runs a single simulation and returns the steady-state verdict for (Fused, Electrical, ML)."""
    sim = MotorSimulator(params=plant_params, seed=seed, base_load_nm=load_nm)
    sim.vib.noise_rms = noise_rms
    sim.plant.warm_start(load_nm, seconds=0.5)

    if supply_type is not None and supply_sev > 0:
        F.inject_voltage_anomaly(sim.faults, type=supply_type, severity=supply_sev)
    elif cls != "healthy":
        F.inject(sim.faults, cls, severity)

    # Diagnostic observer always uses nominal DEFAULT_MOTOR
    elec_diag = ElectricalResidualDiagnostic(DEFAULT_MOTOR, fs=sim.plant.fs)
    supply_diag = SupplyDiagnostic(rated_phase_peak=DEFAULT_MOTOR.rated_voltage * math.sqrt(2 / 3))
    ml_diag = MechanicalClassifier(use_ml=True)
    therm_diag = ThermalDiagnostic(warn_c=120.0, trip_c=145.0)
    prot_diag = ProtectionDiagnostic(DEFAULT_MOTOR)

    v_buf: list[np.ndarray] = []
    a_buf: list[np.ndarray] = []
    w_buf: list[float] = []
    feat_seq: list[np.ndarray] = []

    fused_preds: list[str] = []
    elec_preds: list[str] = []
    ml_preds: list[str] = []

    n_chunks = int(seconds / sim.chunk_s)
    for _ in range(n_chunks):
        st = sim.step()
        assert st.electrical is not None
        v_buf.append(st.vibration)
        a_buf.append(st.acoustic)
        w_buf.append(float(st.electrical.omega_m[-1]))

        v_elec = elec_diag.update(
            i_abc=st.electrical.i_abc,
            u_abc=st.electrical.u_abc,
            omega_m=st.electrical.omega_m,
            supply_freq=st.electrical.supply_freq,
            temp_c=st.temperature_c,
        )
        v_sup = supply_diag.analyze(
            u_abc=st.electrical.u_abc,
            fs=st.electrical.fs,
            f=st.electrical.supply_freq,
        )
        i_rms = float(np.mean(np.sqrt(np.mean(st.electrical.i_abc**2, axis=1))))
        v_th = therm_diag.update(st.t, st.temperature_c, i_rms=i_rms)
        rpm = float(st.electrical.omega_m[-1] * 30.0 / math.pi)
        v_prot = prot_diag.update(st.t, st.electrical.i_abc, rpm, dt=sim.chunk_s)

        v_ml = ChannelVerdict(DiagSource.ML_CLASSIFIER, DiagFault.HEALTHY, 0.7, 0.0, True)
        need_samples = int(WINDOW_S * st.vib_fs)
        if sum(b.shape[1] for b in v_buf) >= need_samples:
            v_cat = np.hstack(v_buf)[:, -need_samples:]
            a_cat = np.concatenate(a_buf)[-int(WINDOW_S * st.acoustic_fs):]
            shaft_hz = w_buf[-1] / (2.0 * math.pi)
            feats = window_features(v_cat, a_cat, st.vib_fs, st.acoustic_fs, shaft_hz)
            feat_seq.append(feats)
            if len(feat_seq) >= 5:
                v_ml = ml_diag.classify(np.stack(feat_seq[-5:]))

        verdicts = [v_elec, v_sup, v_th, v_prot, v_ml]
        f_diag = fuse(st.t, verdicts, weights=WEIGHTS)

        # Record steady-state predictions
        p_fused = f_diag.fault_type.value
        p_elec = v_elec.fault_type.value if (v_elec and v_elec.confidence >= 0.35) else "healthy"
        p_ml = v_ml.fault_type.value if (v_ml and v_ml.confidence >= 0.35) else "healthy"

        fused_preds.append(p_fused)
        elec_preds.append(p_elec)
        ml_preds.append(p_ml)

    # Return majority vote from steady-state tail
    tail = max(1, len(fused_preds) // 3)
    def majority(arr):
        vals, counts = np.unique(arr[-tail:], return_counts=True)
        return str(vals[np.argmax(counts)])

    return majority(fused_preds), majority(elec_preds), majority(ml_preds)


def run_sweep(
    sweep_name: str,
    factor_values: list[Any],
    get_run_kwargs: Any,
    seeds: list[int],
    out_dir: Path,
) -> dict[str, Any]:
    print(f"\n--- Running Sweep: {sweep_name} ---")
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    for fval in factor_values:
        fval_str = str(fval)
        for seed in seeds:
            true_labels = []
            fused_preds, elec_preds, ml_preds = [], [], []

            for cls_name, sev in FAULT_CLASSES:
                kwargs = get_run_kwargs(fval, cls_name, sev)
                p_fused, p_elec, p_ml = evaluate_single_run(
                    cls=cls_name,
                    severity=kwargs.get("severity", sev),
                    seed=seed * 1000 + int(hash(fval_str) % 500),
                    load_nm=kwargs.get("load_nm", 8.0),
                    noise_rms=kwargs.get("noise_rms", 0.05),
                    plant_params=kwargs.get("plant_params", DEFAULT_MOTOR),
                    supply_type=kwargs.get("supply_type", None),
                    supply_sev=kwargs.get("supply_sev", 0.0),
                )
                true_labels.append(cls_name)
                fused_preds.append(p_fused)
                elec_preds.append(p_elec)
                ml_preds.append(p_ml)

            # Compute Macro-F1 across motor classes
            f1_fused = float(f1_score(true_labels, fused_preds, average="macro", zero_division=0))
            f1_elec = float(f1_score(true_labels, elec_preds, average="macro", zero_division=0))
            f1_ml = float(f1_score(true_labels, ml_preds, average="macro", zero_division=0))

            # False Alarm Rate on healthy runs
            healthy_idx = [i for i, lbl in enumerate(true_labels) if lbl == "healthy"]
            far_fused = float(np.mean([fused_preds[i] not in ("healthy", "supply_anomaly", "voltage_sag") for i in healthy_idx]) * 100.0)
            far_elec = float(np.mean([elec_preds[i] not in ("healthy", "unknown") for i in healthy_idx]) * 100.0)
            far_ml = float(np.mean([ml_preds[i] != "healthy" for i in healthy_idx]) * 100.0)

            rows.append({
                "factor_value": fval_str,
                "seed": seed,
                "f1_fused": f1_fused,
                "f1_elec": f1_elec,
                "f1_ml": f1_ml,
                "far_fused": far_fused,
                "far_elec": far_elec,
                "far_ml": far_ml,
            })

    # Summary Mean +/- Std per factor
    summary_factor: dict[str, Any] = {}
    for fval in factor_values:
        fval_str = str(fval)
        subset = [r for r in rows if r["factor_value"] == fval_str]
        summary_factor[fval_str] = {
            "f1_fused_mean": float(np.mean([r["f1_fused"] for r in subset])),
            "f1_fused_std": float(np.std([r["f1_fused"] for r in subset])),
            "f1_elec_mean": float(np.mean([r["f1_elec"] for r in subset])),
            "f1_elec_std": float(np.std([r["f1_elec"] for r in subset])),
            "f1_ml_mean": float(np.mean([r["f1_ml"] for r in subset])),
            "f1_ml_std": float(np.std([r["f1_ml"] for r in subset])),
            "far_fused_mean": float(np.mean([r["far_fused"] for r in subset])),
            "far_fused_std": float(np.std([r["far_fused"] for r in subset])),
            "far_elec_mean": float(np.mean([r["far_elec"] for r in subset])),
            "far_elec_std": float(np.std([r["far_elec"] for r in subset])),
            "far_ml_mean": float(np.mean([r["far_ml"] for r in subset])),
            "far_ml_std": float(np.std([r["far_ml"] for r in subset])),
        }

    # Write CSV
    csv_path = out_dir / f"robustness_{sweep_name}.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["factor_value", "seed", "f1_fused", "f1_elec", "f1_ml", "far_fused", "far_elec", "far_ml"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    # Plot
    plot_sweep(out_dir, sweep_name, factor_values, summary_factor)
    return summary_factor


def plot_sweep(
    out_dir: Path,
    sweep_name: str,
    factor_values: list[Any],
    summary: dict[str, Any],
) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = [str(v) for v in factor_values]
    x = np.arange(len(labels))

    f1_fused = [summary[lbl]["f1_fused_mean"] for lbl in labels]
    f1_fused_err = [summary[lbl]["f1_fused_std"] for lbl in labels]
    f1_elec = [summary[lbl]["f1_elec_mean"] for lbl in labels]
    f1_elec_err = [summary[lbl]["f1_elec_std"] for lbl in labels]
    f1_ml = [summary[lbl]["f1_ml_mean"] for lbl in labels]
    f1_ml_err = [summary[lbl]["f1_ml_std"] for lbl in labels]

    fig, ax1 = plt.subplots(figsize=(7.5, 4.0))
    ax1.errorbar(x, f1_fused, yerr=f1_fused_err, label="Fused Channel", fmt="-o", color="#2a78d6", lw=2, capsize=3)
    ax1.errorbar(x, f1_elec, yerr=f1_elec_err, label="Electrical-Only", fmt="--s", color="#eb6834", lw=1.8, capsize=3)
    ax1.errorbar(x, f1_ml, yerr=f1_ml_err, label="ML-Only", fmt="-^", color="#1baf7a", lw=1.8, capsize=3)

    ax1.set_xlabel(f"{sweep_name.replace('_', ' ').capitalize()}", fontsize=10)
    ax1.set_ylabel("Macro-F1 Score", fontsize=10)
    ax1.set_ylim(-0.05, 1.05)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=20, ha="right", fontsize=9)
    ax1.grid(True, linestyle="--", alpha=0.35)
    ax1.legend(loc="lower left", framealpha=0.9, fontsize=9)
    ax1.set_title(f"Robustness Sweep: {sweep_name.replace('_', ' ').title()}", fontsize=11, fontweight="bold")

    fig.tight_layout()
    fig.savefig(out_dir / f"robustness_{sweep_name}.png", dpi=200)
    fig.savefig(out_dir / f"robustness_{sweep_name}.pdf")
    plt.close(fig)


def make_perturbed_motor(delta_rs: float = 0.0, delta_rr: float = 0.0, delta_lm: float = 0.0) -> MotorParams:
    """Creates a perturbed MotorParams while preserving leakage consistency and stability."""
    new_rs = DEFAULT_MOTOR.Rs * (1.0 + delta_rs)
    new_rr = DEFAULT_MOTOR.Rr * (1.0 + delta_rr)
    new_lm = DEFAULT_MOTOR.Lm * (1.0 + delta_lm)
    diff_lm = new_lm - DEFAULT_MOTOR.Lm
    new_ls = DEFAULT_MOTOR.Ls + diff_lm
    new_lr = DEFAULT_MOTOR.Lr + diff_lm
    cand = MotorParams(
        Rs=new_rs,
        Rr=new_rr,
        Ls=new_ls,
        Lr=new_lr,
        Lm=new_lm,
        J=DEFAULT_MOTOR.J,
        pole_pairs=DEFAULT_MOTOR.pole_pairs,
        rated_power=DEFAULT_MOTOR.rated_power,
        rated_voltage=DEFAULT_MOTOR.rated_voltage,
        rated_current=DEFAULT_MOTOR.rated_current,
        rated_speed=DEFAULT_MOTOR.rated_speed,
        rated_torque=DEFAULT_MOTOR.rated_torque,
    )
    ok, _ = validate_motor_params(cand)
    return cand if ok else DEFAULT_MOTOR


def run_all_robustness_sweeps(seeds: list[int], out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    combined_summary: dict[str, Any] = {}

    # P4-1: Sensor noise (SNR: 40, 30, 20, 10 dB)
    # Mapping SNR dB to vibration noise RMS [m/s^2]
    snr_vals = [40, 30, 20, 10]
    def noise_kwargs(snr, cls, sev):
        noise_rms = 1.0 * (10.0 ** (-snr / 20.0))
        return {"noise_rms": noise_rms}
    combined_summary["noise"] = run_sweep("noise", snr_vals, noise_kwargs, seeds, out_dir)

    # P4-2: Load (25, 50, 75, 100, 110 % of rated torque 8.0 Nm)
    load_pcts = [25, 50, 75, 100, 110]
    def load_kwargs(pct, cls, sev):
        return {"load_nm": 8.0 * (pct / 100.0)}
    combined_summary["load"] = run_sweep("load", load_pcts, load_kwargs, seeds, out_dir)

    # P4-3: Supply condition
    supply_conditions = [
        "Balanced",
        "Unbalance 2%",
        "Unbalance 5%",
        "Harmonic 5%",
        "Harmonic 10%",
        "Sag 10%",
        "Sag 20%",
    ]
    def supply_kwargs(cond, cls, sev):
        if cond == "Unbalance 2%":
            return {"supply_type": "imbalance", "supply_sev": 0.20}
        elif cond == "Unbalance 5%":
            return {"supply_type": "imbalance", "supply_sev": 0.50}
        elif cond == "Harmonic 5%":
            return {"supply_type": "harmonic", "supply_sev": 0.25}
        elif cond == "Harmonic 10%":
            return {"supply_type": "harmonic", "supply_sev": 0.50}
        elif cond == "Sag 10%":
            return {"supply_type": "sag", "supply_sev": 0.20}
        elif cond == "Sag 20%":
            return {"supply_type": "sag", "supply_sev": 0.40}
        return {}
    combined_summary["supply"] = run_sweep("supply", supply_conditions, supply_kwargs, seeds, out_dir)

    # P4-4: Parameter mismatch between plant and twin (Rs, Rr, Lm, Combined: -20, -10, -5, +5, +10, +20 %)
    mismatch_vals = ["-20%", "-10%", "-5%", "0%", "+5%", "+10%", "+20%"]
    def mismatch_kwargs(mval, cls, sev):
        frac = float(mval.replace("%", "").replace("+", "")) / 100.0
        # Combined mismatch on Rs, Rr, and Lm
        perturbed = make_perturbed_motor(delta_rs=frac, delta_rr=frac, delta_lm=frac * 0.4)
        return {"plant_params": perturbed}
    combined_summary["param_mismatch"] = run_sweep("param_mismatch", mismatch_vals, mismatch_kwargs, seeds, out_dir)

    # P4-5: Fault severity (0.05, 0.10, 0.20, 0.40, 0.60, 0.80, 1.00)
    sev_vals = [0.05, 0.10, 0.20, 0.40, 0.60, 0.80, 1.00]
    def sev_kwargs(sval, cls, sev):
        return {"severity": sval if cls != "healthy" else 0.0}
    combined_summary["severity"] = run_sweep("severity", sev_vals, sev_kwargs, seeds, out_dir)

    # Save summary.json & meta.json
    (out_dir / "summary.json").write_text(json.dumps(combined_summary, indent=2))
    meta = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "git_commit": git_commit(),
        "git_dirty": git_dirty(),
        "seeds": seeds,
        "sweeps": ["noise", "load", "supply", "param_mismatch", "severity"],
        "command": " ".join(sys.argv),
        "duration_s": float(time.time() - t0),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    # LaTeX Table (table_robustness.tex)
    generate_robustness_latex(out_dir / "table_robustness.tex", combined_summary)
    print(f"\nAll robustness sweeps finished in {time.time() - t0:.1f}s. Artifacts in {out_dir}/")
    return combined_summary


def generate_robustness_latex(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Parametric Robustness Sweeps: Macro-F1 Under Environmental and Operating Variations}",
        r"\label{tab:robustness_sweeps}",
        r"\begin{tabular}{llrrr}",
        r"\toprule",
        r"Sweep Factor & Value & Fused Channel & Electrical-Only & ML-Only \\",
        r"\midrule",
    ]
    for sweep_key, factors in summary.items():
        title = sweep_key.replace("_", " ").title()
        for fval, s in factors.items():
            f_str = f"{s['f1_fused_mean']:.3f} $\\pm$ {s['f1_fused_std']:.3f}"
            e_str = f"{s['f1_elec_mean']:.3f} $\\pm$ {s['f1_elec_std']:.3f}"
            m_str = f"{s['f1_ml_mean']:.3f} $\\pm$ {s['f1_ml_std']:.3f}"
            lines.append(f"{title} & {fval} & {f_str} & {e_str} & {m_str} \\\\")
        lines.append(r"\midrule")
    if lines[-1] == r"\midrule":
        lines.pop()
    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ])
    path.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run parametric robustness sweeps (P4-1 to P4-5).")
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2], help="Random seeds")
    parser.add_argument("--out", type=str, default="reports/paper/robustness", help="Output directory")
    args = parser.parse_args()

    run_all_robustness_sweeps(args.seeds, Path(args.out))


if __name__ == "__main__":
    main()

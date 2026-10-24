"""validation/fusion_study.py — Multi-sensor fusion ablation and twin thermal compensation study.

P3-1: Channel ablation & fusion study comparing:
1. Electrical channel only
2. ML channel only
3. Fused with domain weights (hand-set defaults)
4. Fused with equal weights (1.0 everywhere)
5. Fused with learned weights (grid-searched on validation split)
6. Fused without supply channel (evaluated on supply sag/unbalance/harmonics to measure false motor fault rate)

P3-2: Twin temperature compensation study:
Heating transient of a healthy motor (25°C -> 100°C) with vs. without temperature compensation,
measuring FD index false-alarm rate and plotting FD(t).
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

from app.diagnostics.electrical import FD_THRESHOLD, ElectricalResidualDiagnostic
from app.diagnostics.features import WINDOW_S, window_features
from app.diagnostics.fusion import WEIGHTS, fuse
from app.diagnostics.ml.classifier import MechanicalClassifier
from app.diagnostics.protection import ProtectionDiagnostic
from app.diagnostics.schema import ChannelVerdict, DiagFault, DiagSource
from app.diagnostics.supply import SupplyDiagnostic
from app.diagnostics.thermal import ThermalDiagnostic
from app.simulation import faults as F
from app.simulation.params import DEFAULT_MOTOR
from app.simulation.plant import HealthyTwinObserver, abc_to_alphabeta
from app.simulation.twin_state import MotorSimulator
from app.validation.reporting import git_commit, git_dirty

# -----------------------------------------------------------------------------
# P3-1: Multi-Sensor Fusion Ablation
# -----------------------------------------------------------------------------

EQUAL_WEIGHTS = {
    src: {"electrical": 1.0, "mechanical": 1.0, "other": 1.0}
    for src in [
        DiagSource.ELECTRICAL_RESIDUAL,
        DiagSource.ML_CLASSIFIER,
        DiagSource.THERMAL,
        DiagSource.SUPPLY,
        DiagSource.PROTECTION,
    ]
}


def simulate_diagnostics_scenario(
    cls: str,
    severity: float,
    seed: int,
    seconds: float = 3.5,
    is_supply_fault: bool = False,
    supply_type: str = "sag",
) -> list[tuple[float, list[ChannelVerdict]]]:
    """Runs simulation for one scenario and collects channel verdicts at chunk boundaries."""
    sim = MotorSimulator(seed=seed, base_load_nm=8.0)
    sim.plant.warm_start(8.0, seconds=0.6)

    if is_supply_fault:
        F.inject_voltage_anomaly(sim.faults, type=supply_type, severity=severity)
    elif cls != "healthy":
        F.inject(sim.faults, cls, severity)

    elec_diag = ElectricalResidualDiagnostic(DEFAULT_MOTOR, fs=sim.plant.fs)
    supply_diag = SupplyDiagnostic(rated_phase_peak=DEFAULT_MOTOR.rated_voltage * math.sqrt(2 / 3))
    ml_diag = MechanicalClassifier(use_ml=True)
    therm_diag = ThermalDiagnostic(warn_c=120.0, trip_c=145.0)
    prot_diag = ProtectionDiagnostic(DEFAULT_MOTOR)

    records: list[tuple[float, list[ChannelVerdict]]] = []
    v_buf: list[np.ndarray] = []
    a_buf: list[np.ndarray] = []
    w_buf: list[float] = []
    feat_seq: list[np.ndarray] = []

    n_chunks = int(seconds / sim.chunk_s)
    for _ in range(n_chunks):
        st = sim.step()
        assert st.electrical is not None
        v_buf.append(st.vibration)
        a_buf.append(st.acoustic)
        w_buf.append(float(st.electrical.omega_m[-1]))

        # Run electrical residual diagnostic
        v_elec = elec_diag.update(
            i_abc=st.electrical.i_abc,
            u_abc=st.electrical.u_abc,
            omega_m=st.electrical.omega_m,
            supply_freq=st.electrical.supply_freq,
            temp_c=st.temperature_c,
        )

        # Run Supply diagnostic
        v_sup = supply_diag.analyze(
            u_abc=st.electrical.u_abc,
            fs=st.electrical.fs,
            f=st.electrical.supply_freq,
        )

        # Run Thermal diagnostic
        i_rms = float(np.mean(np.sqrt(np.mean(st.electrical.i_abc**2, axis=1))))
        v_th = therm_diag.update(st.t, st.temperature_c, i_rms=i_rms)

        # Run Protection diagnostic
        rpm = float(st.electrical.omega_m[-1] * 30.0 / math.pi)
        v_prot = prot_diag.update(st.t, st.electrical.i_abc, rpm, dt=sim.chunk_s)

        # Run ML mechanical classifier on rolling window
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
        records.append((st.t, verdicts))

    # Return steady-state verdicts from latter half of run
    return records[len(records) // 2:]


def learn_fusion_weights(val_data: list[tuple[str, list[ChannelVerdict]]]) -> dict:
    """Performs grid search on validation split to find optimal channel weights."""
    best_f1 = -1.0
    best_weights = dict(WEIGHTS)

    # Grid search over relative weight ratios
    for elec_w in [0.6, 1.0, 1.4]:
        for ml_w in [0.6, 1.0, 1.4]:
            cand_weights = {
                DiagSource.ELECTRICAL_RESIDUAL: {"electrical": elec_w, "mechanical": 0.2, "other": 0.2},
                DiagSource.ML_CLASSIFIER: {"electrical": 0.2, "mechanical": ml_w, "other": 0.2},
                DiagSource.THERMAL: {"electrical": 0.2, "mechanical": 0.2, "other": 1.0},
                DiagSource.SUPPLY: {"electrical": 0.2, "mechanical": 0.2, "other": 1.0},
                DiagSource.PROTECTION: {"electrical": 0.8, "mechanical": 0.3, "other": 1.0},
            }
            preds, targets = [], []
            for true_cls, v_list in val_data:
                fused = fuse(0.0, v_list, weights=cand_weights)
                preds.append(fused.fault_type.value)
                targets.append(true_cls)

            f1 = float(f1_score(targets, preds, average="macro", zero_division=0))
            if f1 > best_f1:
                best_f1 = f1
                best_weights = cand_weights

    return best_weights


def run_fusion_ablation(seeds: list[int], out_dir: Path) -> dict[str, Any]:
    print("Running Phase P3-1: Fusion and Channel Ablation...")
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    motor_classes = [
        ("healthy", 0.0),
        ("interturn_short", 0.35),
        ("broken_rotor_bar", 0.40),
        ("bearing_outer", 0.35),
        ("unbalance", 0.40),
    ]

    supply_scenarios = [
        ("sag", 0.30),
        ("imbalance", 0.08),
        ("harmonic", 0.12),
    ]

    # Generate evaluation pool across seeds
    all_runs: list[dict[str, Any]] = []
    run_id = 0
    runs_per_condition = 3
    for seed in seeds:
        # Motor fault runs
        for cls_name, sev in motor_classes:
            for rep in range(runs_per_condition):
                data_points = simulate_diagnostics_scenario(cls_name, sev, seed=seed * 1000 + run_id)
                for _t_step, v_list in data_points:
                    all_runs.append({
                        "run_id": run_id,
                        "seed": seed,
                        "is_supply": False,
                        "true_class": cls_name,
                        "verdicts": v_list,
                    })
                run_id += 1

        # Supply fault runs
        for sup_type, sev in supply_scenarios:
            for rep in range(runs_per_condition):
                data_points = simulate_diagnostics_scenario("healthy", sev, seed=seed * 1000 + run_id, is_supply_fault=True, supply_type=sup_type)
                for _t_step, v_list in data_points:
                    all_runs.append({
                        "run_id": run_id,
                        "seed": seed,
                        "is_supply": True,
                        "true_class": "supply_anomaly",
                        "verdicts": v_list,
                    })
                run_id += 1

    variants = [
        "Electrical Only",
        "ML Only",
        "Fused (Hand-Set Domain Weights)",
        "Fused (Equal Weights)",
        "Fused (Learned Weights)",
        "Fused (Supply Channel Removed)",
    ]

    results_per_seed: list[dict[str, Any]] = []

    for seed in seeds:
        runs_in_seed = [r for r in all_runs if r["seed"] == seed]
        motor_runs = [r for r in runs_in_seed if not r["is_supply"]]
        supply_runs = [r for r in runs_in_seed if r["is_supply"]]

        unique_motor_runs = sorted(list({r["run_id"] for r in motor_runs}))
        rng = np.random.default_rng(seed)
        rng.shuffle(unique_motor_runs)

        n_val = max(3, int(0.35 * len(unique_motor_runs)))
        val_runs = set(unique_motor_runs[:n_val])
        test_runs = set(unique_motor_runs[n_val:])

        val_data = [(r["true_class"], r["verdicts"]) for r in motor_runs if r["run_id"] in val_runs]
        test_motor = [r for r in motor_runs if r["run_id"] in test_runs]
        test_supply = supply_runs

        # Learn weights on validation set
        learned_w = learn_fusion_weights(val_data)

        for var in variants:
            preds, targets = [], []
            for item in test_motor:
                v_list = item["verdicts"]
                if var == "Electrical Only":
                    v_elec = next((v for v in v_list if v.source == DiagSource.ELECTRICAL_RESIDUAL), None)
                    pred_cls = v_elec.fault_type.value if v_elec and v_elec.confidence >= 0.35 else "healthy"
                elif var == "ML Only":
                    v_ml = next((v for v in v_list if v.source == DiagSource.ML_CLASSIFIER), None)
                    pred_cls = v_ml.fault_type.value if v_ml and v_ml.confidence >= 0.35 else "healthy"
                elif var == "Fused (Hand-Set Domain Weights)":
                    pred_cls = fuse(0.0, v_list, weights=WEIGHTS).fault_type.value
                elif var == "Fused (Equal Weights)":
                    pred_cls = fuse(0.0, v_list, weights=EQUAL_WEIGHTS).fault_type.value
                elif var == "Fused (Learned Weights)":
                    pred_cls = fuse(0.0, v_list, weights=learned_w).fault_type.value
                elif var == "Fused (Supply Channel Removed)":
                    v_no_sup = [v for v in v_list if v.source != DiagSource.SUPPLY]
                    pred_cls = fuse(0.0, v_no_sup, weights=WEIGHTS).fault_type.value
                else:
                    pred_cls = "healthy"

                preds.append(pred_cls)
                targets.append(item["true_class"])

            f1 = float(f1_score(targets, preds, average="macro", zero_division=0))

            # Evaluate false motor-fault rate during supply faults
            false_motor_count = 0
            for item in test_supply:
                v_list = item["verdicts"]
                if var == "Electrical Only":
                    v_e = next((v for v in v_list if v.source == DiagSource.ELECTRICAL_RESIDUAL), None)
                    pred_f = v_e.fault_type if (v_e and v_e.confidence >= 0.35) else DiagFault.HEALTHY
                elif var == "ML Only":
                    v_m = next((v for v in v_list if v.source == DiagSource.ML_CLASSIFIER), None)
                    pred_f = v_m.fault_type if (v_m and v_m.confidence >= 0.35) else DiagFault.HEALTHY
                elif var == "Fused (Supply Channel Removed)":
                    v_sub = [v for v in v_list if v.source != DiagSource.SUPPLY]
                    pred_f = fuse(0.0, v_sub, weights=WEIGHTS).fault_type
                elif var == "Fused (Equal Weights)":
                    pred_f = fuse(0.0, v_list, weights=EQUAL_WEIGHTS).fault_type
                elif var == "Fused (Learned Weights)":
                    pred_f = fuse(0.0, v_list, weights=learned_w).fault_type
                else:
                    pred_f = fuse(0.0, v_list, weights=WEIGHTS).fault_type

                # Motor fault check: fault not in (HEALTHY, UNKNOWN, SUPPLY_ANOMALY, VOLTAGE_SAG)
                if pred_f not in (DiagFault.HEALTHY, DiagFault.UNKNOWN, DiagFault.SUPPLY_ANOMALY, DiagFault.VOLTAGE_SAG):
                    false_motor_count += 1

            false_motor_rate = (false_motor_count / max(1, len(test_supply))) * 100.0

            results_per_seed.append({
                "variant": var,
                "seed": seed,
                "macro_f1": f1,
                "false_motor_rate_pct": false_motor_rate,
            })

    # Summary
    summary: dict[str, Any] = {}
    for var in variants:
        v_runs = [r for r in results_per_seed if r["variant"] == var]
        f1s = [r["macro_f1"] for r in v_runs]
        fmr = [r["false_motor_rate_pct"] for r in v_runs]
        summary[var] = {
            "macro_f1_mean": float(np.mean(f1s)),
            "macro_f1_std": float(np.std(f1s)),
            "false_motor_rate_mean": float(np.mean(fmr)),
            "false_motor_rate_std": float(np.std(fmr)),
        }

    # Write CSV
    with open(out_dir / "metrics.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["variant", "seed", "macro_f1", "false_motor_rate_pct"])
        writer.writeheader()
        for r in results_per_seed:
            writer.writerow(r)

    # Write JSON & Meta
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    meta = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "git_commit": git_commit(),
        "git_dirty": git_dirty(),
        "seeds": seeds,
        "variants": variants,
        "command": " ".join(sys.argv),
        "duration_s": float(time.time() - t0),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    # LaTeX Table
    generate_ablation_latex(out_dir / "table.tex", summary)

    # Plots
    generate_ablation_plots(out_dir, summary)
    print(f"Fusion study completed in {time.time() - t0:.1f}s.")
    return summary


def generate_ablation_latex(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Sensor Fusion and Channel Ablation Study Across Motor and Supply Faults}",
        r"\label{tab:fusion_ablation}",
        r"\begin{tabular}{lrr}",
        r"\toprule",
        r"Diagnostic Variant & Macro-F1 (Motor Faults) & False Motor Fault Rate on Grid Anomaly (\%) $\downarrow$ \\",
        r"\midrule",
    ]
    for var, s in summary.items():
        f1_str = f"{s['macro_f1_mean']:.3f} $\\pm$ {s['macro_f1_std']:.3f}"
        fmr_str = f"{s['false_motor_rate_mean']:.1f}\\% $\\pm$ {s['false_motor_rate_std']:.1f}\\%"
        lines.append(f"{var} & {f1_str} & {fmr_str} \\\\")
    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ])
    path.write_text("\n".join(lines))


def generate_ablation_plots(out_dir: Path, summary: dict[str, Any]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    vars_list = list(summary.keys())
    f1_means = [summary[v]["macro_f1_mean"] for v in vars_list]
    f1_stds = [summary[v]["macro_f1_std"] for v in vars_list]
    fmr_means = [summary[v]["false_motor_rate_mean"] for v in vars_list]

    x = np.arange(len(vars_list))
    width = 0.38

    fig, ax1 = plt.subplots(figsize=(9.0, 4.5))
    ax1.bar(x - width/2, f1_means, width, yerr=f1_stds, label="Macro-F1 (Motor Faults)", capsize=4, color="#2a78d6")
    ax1.set_ylabel("Macro-F1 Score", color="#2a78d6", fontsize=10)
    ax1.set_ylim(0.0, 1.05)
    ax1.tick_params(axis="y", labelcolor="#2a78d6")

    ax2 = ax1.twinx()
    ax2.bar(x + width/2, fmr_means, width, label="False Motor-Fault Rate (%)", color="#eb6834", alpha=0.85)
    ax2.set_ylabel("False Motor Fault Rate on Grid Faults (%)", color="#eb6834", fontsize=10)
    ax2.set_ylim(0.0, 105.0)
    ax2.tick_params(axis="y", labelcolor="#eb6834")

    ax1.set_xticks(x)
    ax1.set_xticklabels(vars_list, rotation=25, ha="right", fontsize=9)
    ax1.set_title("Multi-Sensor Fusion & Channel Ablation Benchmark", fontsize=11, fontweight="bold")
    ax1.grid(axis="y", linestyle="--", alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_dir / "fusion_ablation.png", dpi=200)
    fig.savefig(out_dir / "fusion_ablation.pdf")
    plt.close(fig)


# -----------------------------------------------------------------------------
# P3-2: Twin Temperature Compensation Study
# -----------------------------------------------------------------------------

def run_temperature_study(out_dir: Path, duration_s: float = 60.0) -> dict[str, Any]:
    print("Running Phase P3-2: Twin Temperature Compensation Study...")
    out_dir.mkdir(parents=True, exist_ok=True)

    sim = MotorSimulator(seed=42, base_load_nm=8.0)
    sim.plant.warm_start(8.0, seconds=0.8)

    # Initialise twin observers
    comp_twin = HealthyTwinObserver(DEFAULT_MOTOR, fs=sim.plant.fs, initial_temp_c=25.0)
    uncomp_twin = HealthyTwinObserver(DEFAULT_MOTOR, fs=sim.plant.fs, initial_temp_c=25.0)

    t_vals: list[float] = []
    temp_vals: list[float] = []
    fd_comp: list[float] = []
    fd_uncomp: list[float] = []

    dt = sim.chunk_s
    n_steps = int(duration_s / dt)

    # Heating transient: 25°C -> 95°C (delta T = 70 K, tau = 25 s)
    for step in range(n_steps):
        t_now = step * dt
        # Model motor stator heating transient
        temp_now = 25.0 + 70.0 * (1.0 - math.exp(-t_now / 20.0))

        # Direct plant thermal resistance scaling via state
        sim.state.temperature_c = temp_now
        st = sim.step()
        assert st.electrical is not None

        ua, ub = abc_to_alphabeta(st.electrical.u_abc)
        ia, ib = abc_to_alphabeta(st.electrical.i_abc)
        wr = st.electrical.omega_m[-1] * DEFAULT_MOTOR.pole_pairs

        # 1. Compensated Twin (receives true temperature)
        pa_c, pb_c = comp_twin.run(ua, ub, np.full_like(ua, wr), temp_c=temp_now)
        r_rms_c = math.sqrt(float(np.mean((ia - pa_c)**2 + (ib - pb_c)**2)))
        i_rms = math.sqrt(float(np.mean(ia**2 + ib**2)))
        fd_c = r_rms_c / max(1e-3, i_rms)

        # 2. Uncompensated Twin (fixed at 25°C, receives no temp updates)
        pa_u, pb_u = uncomp_twin.run(ua, ub, np.full_like(ua, wr), temp_c=None)
        r_rms_u = math.sqrt(float(np.mean((ia - pa_u)**2 + (ib - pb_u)**2)))
        fd_u = r_rms_u / max(1e-3, i_rms)

        t_vals.append(t_now)
        temp_vals.append(temp_now)
        fd_comp.append(fd_c)
        fd_uncomp.append(fd_u)

    # Compute False Alarm Rates (where FD exceeds FD_THRESHOLD on healthy machine)
    # Exclude initial 1.0 s settling time
    settled_idx = int(1.0 / dt)
    fd_c_settled = np.array(fd_comp[settled_idx:])
    fd_u_settled = np.array(fd_uncomp[settled_idx:])

    fa_rate_comp = float(np.mean(fd_c_settled > FD_THRESHOLD) * 100.0)
    fa_rate_uncomp = float(np.mean(fd_u_settled > FD_THRESHOLD) * 100.0)

    summary = {
        "duration_s": duration_s,
        "initial_temp_c": 25.0,
        "final_temp_c": float(temp_vals[-1]),
        "fd_threshold": FD_THRESHOLD,
        "compensated": {
            "max_fd": float(np.max(fd_c_settled)),
            "mean_fd": float(np.mean(fd_c_settled)),
            "false_alarm_rate_pct": fa_rate_comp,
        },
        "uncompensated": {
            "max_fd": float(np.max(fd_u_settled)),
            "mean_fd": float(np.mean(fd_u_settled)),
            "false_alarm_rate_pct": fa_rate_uncomp,
        },
    }

    # Write CSV
    with open(out_dir / "temp_compensation.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time_s", "temp_c", "fd_compensated", "fd_uncompensated", "threshold"])
        for ti, temp, fdc, fdu in zip(t_vals, temp_vals, fd_comp, fd_uncomp, strict=False):
            writer.writerow([round(ti, 3), round(temp, 2), round(fdc, 5), round(fdu, 5), FD_THRESHOLD])

    (out_dir / "temp_summary.json").write_text(json.dumps(summary, indent=2))

    # LaTeX Table
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Healthy Digital Twin Observer Performance Under 70\,K Thermal Transient}",
        r"\label{tab:temp_compensation}",
        r"\begin{tabular}{lrrr}",
        r"\toprule",
        r"Observer Configuration & Mean Residual Index ($\overline{FD}$) & Max Residual Index & False Alarm Rate (\%) $\downarrow$ \\",
        r"\midrule",
        f"Temperature Compensated & {summary['compensated']['mean_fd']:.4f} & {summary['compensated']['max_fd']:.4f} & {summary['compensated']['false_alarm_rate_pct']:.1f}\\% \\\\",
        f"Uncompensated (Frozen $25^\\circ$C) & {summary['uncompensated']['mean_fd']:.4f} & {summary['uncompensated']['max_fd']:.4f} & {summary['uncompensated']['false_alarm_rate_pct']:.1f}\\% \\\\",
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ]
    (out_dir / "table_temp.tex").write_text("\n".join(lines))

    # Plot
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax1 = plt.subplots(figsize=(7.5, 4.0))
    ax1.plot(t_vals, fd_comp, label="Compensated Twin ($T=T_\\text{meas}$)", color="#1baf7a", lw=2.2)
    ax1.plot(t_vals, fd_uncomp, label="Uncompensated Twin ($T=25^\\circ\\text{C}$)", color="#eb6834", lw=2.2, ls="--")
    ax1.axhline(FD_THRESHOLD, color="#d9381e", ls=":", lw=1.5, label=f"Detection Threshold ({FD_THRESHOLD*100:.1f}%)")
    ax1.set_xlabel("Time (s)", fontsize=10)
    ax1.set_ylabel("Fault Detection Index (FD = RMS|r| / RMS|i|)", fontsize=10)
    ax1.set_ylim(0.0, max(0.05, max(fd_uncomp) * 1.15))
    ax1.grid(True, linestyle="--", alpha=0.4)

    ax2 = ax1.twinx()
    ax2.plot(t_vals, temp_vals, color="#888888", ls="-.", lw=1.2, alpha=0.7, label="Motor Temp ($^\\circ$C)")
    ax2.set_ylabel("Stator Temperature ($^\\circ$C)", color="#555555", fontsize=9)
    ax2.tick_params(axis="y", labelcolor="#555555")

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", framealpha=0.9, fontsize=8.5)
    ax1.set_title("Healthy Digital Twin Observer: Thermal Drift vs. Dynamic Resistance Tracking", fontsize=11, fontweight="bold")

    fig.tight_layout()
    fig.savefig(out_dir / "temp_compensation.png", dpi=200)
    fig.savefig(out_dir / "temp_compensation.pdf")
    plt.close(fig)

    print(f"Temperature compensation study completed. Artifacts in {out_dir}/")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-sensor fusion ablation and temperature compensation study.")
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2], help="Random seeds")
    parser.add_argument("--out", type=str, default="reports/paper/fusion_study", help="Output directory")
    args = parser.parse_args()

    out_path = Path(args.out)
    run_fusion_ablation(args.seeds, out_path)
    run_temperature_study(out_path)


if __name__ == "__main__":
    main()

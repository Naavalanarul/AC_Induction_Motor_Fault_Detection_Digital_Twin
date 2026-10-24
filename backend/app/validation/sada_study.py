"""validation/sada_study.py — State-Aware Derating & Alert (SADA) supervisor evaluation.

P5-1: Scripted scenarios (Slow ramp, Step, Noisy hover, Transient spike, Sensor loss, Healthy with noise)
P5-2: Variants (Naive, EMA only, EMA+hysteresis, Full SADA, No confidence gate, No dwell)
P5-3: Metrics (Chatter / state changes per min, False trips, Missed trips, Action delay, Unnecessary derate, Load TV)
P5-4: Sensitivity sweeps (watch, derate, trip, ema_alpha ±20%)
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from app.diagnostics.schema import DiagFault, FusedDiagnosis
from app.supervisory.sada import SadaConfig, SadaOutput, SadaState, SadaSupervisor
from app.validation.reporting import git_commit, git_dirty

# -----------------------------------------------------------------------------
# Baseline Naive Supervisor
# -----------------------------------------------------------------------------

class NaiveSupervisor:
    """Immediate threshold trip rule without smoothing, hysteresis, dwell or confidence gating."""

    def __init__(self, watch: float = 0.3, derate: float = 0.5, trip: float = 0.8):
        self.watch = watch
        self.derate = derate
        self.trip = trip
        self.state = SadaState.NORMAL
        self.load_cmd = 1.0

    def update(
        self,
        d: FusedDiagnosis,
        dt: float = 0.1,
        critical_sensors_ok: bool = True,
        current_temp: float | None = None,
    ) -> SadaOutput:
        sev = d.severity
        prev_state = self.state
        if not critical_sensors_ok:
            self.state = SadaState.TRIP
            self.load_cmd = 0.0
        elif sev >= self.trip:
            self.state = SadaState.TRIP
            self.load_cmd = 0.0
        elif sev >= self.derate:
            self.state = SadaState.DERATE
            frac = (sev - self.derate) / max(1e-4, self.trip - self.derate)
            self.load_cmd = max(0.5, 1.0 - 0.5 * frac)
        elif sev >= self.watch:
            self.state = SadaState.WATCH
            self.load_cmd = 1.0
        else:
            self.state = SadaState.NORMAL
            self.load_cmd = 1.0

        return SadaOutput(
            state=self.state,
            load_cmd=self.load_cmd,
            reason_code="NAIVE",
            trip=(self.state == SadaState.TRIP),
            smoothed_severity=sev,
            fault_type=d.fault_type.value,
            manual_override=False,
            changed=(self.state != prev_state),
        )


# -----------------------------------------------------------------------------
# Scenario Generation
# -----------------------------------------------------------------------------

@dataclass
class Scenario:
    name: str
    t_vals: np.ndarray
    true_severity: np.ndarray
    confidence: np.ndarray
    critical_sensors_ok: np.ndarray
    trip_threshold_time: float | None  # ground truth crossing time of 0.8


def generate_scenarios(seed: int) -> dict[str, Scenario]:
    rng = np.random.default_rng(seed)
    dt = 0.1
    scenarios: dict[str, Scenario] = {}

    # 1. Slow Ramp: 0 -> 1 over 60 s (crossing 0.8 at t = 48 s)
    t1 = np.arange(0.0, 60.0 + 1e-6, dt)
    s1 = t1 / 60.0
    c1 = np.full_like(t1, 0.90)
    scenarios["slow_ramp"] = Scenario("slow_ramp", t1, s1, c1, np.ones(len(t1), bool), trip_threshold_time=48.0)

    # 2. Step: 0 for 5 s, then 0.9 for 25 s (crossing 0.8 at t = 5.0 s)
    t2 = np.arange(0.0, 30.0 + 1e-6, dt)
    s2 = np.where(t2 < 5.0, 0.0, 0.90)
    c2 = np.where(t2 < 5.0, 0.95, 0.85)
    scenarios["step"] = Scenario("step", t2, s2, c2, np.ones(len(t2), bool), trip_threshold_time=5.0)

    # 3. Noisy Hover: hovers near 0.50 with noise N(0, 0.05) for 60 s (never exceeds 0.75)
    t3 = np.arange(0.0, 60.0 + 1e-6, dt)
    noise3 = rng.normal(0.0, 0.05, size=len(t3))
    s3 = np.clip(0.50 + noise3, 0.30, 0.72)
    c3 = np.full_like(t3, 0.80)
    scenarios["noisy_hover"] = Scenario("noisy_hover", t3, s3, c3, np.ones(len(t3), bool), trip_threshold_time=None)

    # 4. Transient Spike: 0 except single 1-step spike to 0.90 at t = 10 s
    t4 = np.arange(0.0, 25.0 + 1e-6, dt)
    s4 = np.zeros_like(t4)
    spike_idx = int(10.0 / dt)
    s4[spike_idx] = 0.90
    c4 = np.full_like(t4, 0.80)
    c4[spike_idx] = 0.70  # Lower confidence spike
    scenarios["transient_spike"] = Scenario("transient_spike", t4, s4, c4, np.ones(len(t4), bool), trip_threshold_time=None)

    # 5. Sensor Loss: 1s loss, 5s loss, 20s loss
    t5 = np.arange(0.0, 35.0 + 1e-6, dt)
    s5 = np.zeros_like(t5)
    c5 = np.full_like(t5, 0.90)
    # 5s loss starting at t = 10.0s (ends at 15.0s, > 3.0s grace period)
    ok5 = np.ones(len(t5), bool)
    ok5[(t5 >= 10.0) & (t5 < 15.0)] = False
    scenarios["sensor_loss_5s"] = Scenario("sensor_loss_5s", t5, s5, c5, ok5, trip_threshold_time=13.0)

    # 6. Healthy with Noise: 60 s of 0 severity with sensor noise
    t6 = np.arange(0.0, 60.0 + 1e-6, dt)
    s6 = np.clip(np.abs(rng.normal(0.0, 0.04, size=len(t6))), 0.0, 0.25)
    c6 = np.full_like(t6, 0.85)
    scenarios["healthy_noise"] = Scenario("healthy_noise", t6, s6, c6, np.ones(len(t6), bool), trip_threshold_time=None)

    return scenarios


# -----------------------------------------------------------------------------
# Evaluation Runner
# -----------------------------------------------------------------------------

def evaluate_supervisor(
    supervisor: Any,
    scen: Scenario,
    dt: float = 0.1,
) -> dict[str, Any]:
    states: list[SadaState] = []
    loads: list[float] = []
    trips: list[bool] = []

    for t, sev, conf, ok in zip(scen.t_vals, scen.true_severity, scen.confidence, scen.critical_sensors_ok, strict=False):
        d = FusedDiagnosis(
            t=float(t),
            fault_type=DiagFault.BEARING_OUTER if sev > 0.3 else DiagFault.HEALTHY,
            severity=float(sev),
            confidence=float(conf),
            per_sensor_scores={},
        )
        out = supervisor.update(d, dt=dt, critical_sensors_ok=bool(ok))
        states.append(out.state)
        loads.append(out.load_cmd)
        trips.append(out.trip)

    # Metrics computation
    n_changes = sum(1 for i in range(1, len(states)) if states[i] != states[i - 1])
    duration_min = scen.t_vals[-1] / 60.0
    chatter_per_min = n_changes / max(1e-4, duration_min)

    # False trip: tripped when true severity < 0.8 and sensors ok
    false_trips = 0
    if scen.trip_threshold_time is None and any(trips):
        false_trips = 1

    # Missed trip: scenario had true severity >= 0.8 but never tripped
    missed_trips = 0
    if scen.trip_threshold_time is not None and not any(trips):
        missed_trips = 1

    # Action delay: time from threshold crossing to first TRIP state
    delay_s = float("nan")
    if scen.trip_threshold_time is not None and any(trips):
        trip_idx = trips.index(True)
        delay_s = max(0.0, scen.t_vals[trip_idx] - scen.trip_threshold_time)

    # Unnecessary derate: time spent in DERATE while true severity < 0.5
    unnec_derate_s = sum(dt for s, st in zip(scen.true_severity, states, strict=False) if st == SadaState.DERATE and s < 0.45)

    # Load command variation: sum of absolute differences
    load_tv = float(np.sum(np.abs(np.diff(loads))))

    return {
        "chatter_per_min": chatter_per_min,
        "false_trips": false_trips,
        "missed_trips": missed_trips,
        "action_delay_s": delay_s,
        "unnec_derate_s": unnec_derate_s,
        "load_tv": load_tv,
        "states": states,
        "loads": loads,
        "t_vals": scen.t_vals,
    }


def make_supervisor_variant(name: str) -> Any:
    if name == "Naive":
        return NaiveSupervisor()
    elif name == "EMA Only":
        cfg = SadaConfig(confidence_gate=0.0, hysteresis=0.0, derate_min_dwell_s=0.0)
        return SadaSupervisor(cfg)
    elif name == "EMA + Hysteresis":
        cfg = SadaConfig(confidence_gate=0.0, hysteresis=0.05, derate_min_dwell_s=0.0)
        return SadaSupervisor(cfg)
    elif name == "Full SADA (Default)":
        return SadaSupervisor(SadaConfig())
    elif name == "Full SADA (No Confidence Gate)":
        cfg = SadaConfig(confidence_gate=0.0)
        return SadaSupervisor(cfg)
    elif name == "Full SADA (No Dwell Time)":
        cfg = SadaConfig(derate_min_dwell_s=0.0)
        return SadaSupervisor(cfg)
    else:
        raise ValueError(f"Unknown variant: {name}")


def run_sada_study(seeds: list[int], out_dir: Path) -> dict[str, Any]:
    print("Running Phase P5: SADA Supervisory Layer Evaluation...")
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    variant_names = [
        "Naive",
        "EMA Only",
        "EMA + Hysteresis",
        "Full SADA (Default)",
        "Full SADA (No Confidence Gate)",
        "Full SADA (No Dwell Time)",
    ]

    all_results: list[dict[str, Any]] = []
    noisy_hover_timeline: dict[str, Any] = {}

    for seed in seeds:
        scenarios = generate_scenarios(seed)
        for vname in variant_names:
            chatter_list, false_trip_list, missed_trip_list = [], [], []
            delay_list, unnec_derate_list, load_tv_list = [], [], []

            for sname, scen in scenarios.items():
                sup = make_supervisor_variant(vname)
                res = evaluate_supervisor(sup, scen)

                chatter_list.append(res["chatter_per_min"])
                false_trip_list.append(res["false_trips"])
                missed_trip_list.append(res["missed_trips"])
                if not math.isnan(res["action_delay_s"]):
                    delay_list.append(res["action_delay_s"])
                unnec_derate_list.append(res["unnec_derate_s"])
                load_tv_list.append(res["load_tv"])

                # Store timeline for noisy hover figure
                if sname == "noisy_hover" and seed == seeds[0] and vname in ("Naive", "Full SADA (Default)"):
                    noisy_hover_timeline[vname] = {
                        "t": res["t_vals"].tolist(),
                        "states": [s.value for s in res["states"]],
                        "loads": res["loads"],
                        "severity": scen.true_severity.tolist(),
                    }

            all_results.append({
                "variant": vname,
                "seed": seed,
                "chatter_per_min": float(np.mean(chatter_list)),
                "false_trips": int(np.sum(false_trip_list)),
                "missed_trips": int(np.sum(missed_trip_list)),
                "action_delay_s": float(np.mean(delay_list)) if delay_list else 0.0,
                "unnec_derate_s": float(np.sum(unnec_derate_list)),
                "load_tv": float(np.sum(load_tv_list)),
            })

    # Summary by Variant
    summary: dict[str, Any] = {}
    for vname in variant_names:
        v_runs = [r for r in all_results if r["variant"] == vname]
        summary[vname] = {
            "chatter_per_min_mean": float(np.mean([r["chatter_per_min"] for r in v_runs])),
            "chatter_per_min_std": float(np.std([r["chatter_per_min"] for r in v_runs])),
            "false_trips_mean": float(np.mean([r["false_trips"] for r in v_runs])),
            "missed_trips_mean": float(np.mean([r["missed_trips"] for r in v_runs])),
            "action_delay_s_mean": float(np.mean([r["action_delay_s"] for r in v_runs])),
            "action_delay_s_std": float(np.std([r["action_delay_s"] for r in v_runs])),
            "unnec_derate_s_mean": float(np.mean([r["unnec_derate_s"] for r in v_runs])),
            "unnec_derate_s_std": float(np.std([r["unnec_derate_s"] for r in v_runs])),
            "load_tv_mean": float(np.mean([r["load_tv"] for r in v_runs])),
            "load_tv_std": float(np.std([r["load_tv"] for r in v_runs])),
        }

    # Write CSV
    with open(out_dir / "metrics.csv", "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["variant", "seed", "chatter_per_min", "false_trips", "missed_trips", "action_delay_s", "unnec_derate_s", "load_tv"],
        )
        writer.writeheader()
        for r in all_results:
            writer.writerow(r)

    # Write JSON summary
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    # Write Meta
    meta = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "git_commit": git_commit(),
        "git_dirty": git_dirty(),
        "seeds": seeds,
        "variants": variant_names,
        "command": " ".join(sys.argv),
        "duration_s": float(time.time() - t0),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    # LaTeX Table
    generate_sada_latex(out_dir / "table_sada_variants.tex", summary)

    # Plot Noisy Hover Timeline (Naive vs Full SADA)
    plot_noisy_hover_timeline(out_dir, noisy_hover_timeline)

    # P5-4: Sensitivity Analysis
    sensitivity_summary = run_sensitivity_sweeps(seeds, out_dir)

    print(f"SADA study completed in {time.time() - t0:.1f}s. Artifacts in {out_dir}/")
    return {"variants": summary, "sensitivity": sensitivity_summary}


def generate_sada_latex(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Supervisory Layer (SADA) Variant Benchmark Across Dynamic Scenarios}",
        r"\label{tab:sada_variants}",
        r"\begin{tabular}{lrrrrrr}",
        r"\toprule",
        r"Variant & Chatter/min $\downarrow$ & False Trips $\downarrow$ & Missed Trips $\downarrow$ & Delay (s) & Unnec. Derate (s) $\downarrow$ & Load TV $\downarrow$ \\",
        r"\midrule",
    ]
    for vname, s in summary.items():
        chatter_str = f"{s['chatter_per_min_mean']:.1f}"
        ft_str = f"{s['false_trips_mean']:.1f}"
        mt_str = f"{s['missed_trips_mean']:.1f}"
        del_str = f"{s['action_delay_s_mean']:.2f}"
        ud_str = f"{s['unnec_derate_s_mean']:.1f}"
        tv_str = f"{s['load_tv_mean']:.1f}"
        lines.append(f"{vname} & {chatter_str} & {ft_str} & {mt_str} & {del_str} & {ud_str} & {tv_str} \\\\")
    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ])
    path.write_text("\n".join(lines))


def plot_noisy_hover_timeline(out_dir: Path, data: dict[str, Any]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if "Naive" not in data or "Full SADA (Default)" not in data:
        return

    t = data["Naive"]["t"]
    sev = data["Naive"]["severity"]

    state_map = {"NORMAL": 0, "WATCH": 1, "DERATE": 2, "TRIP": 3}
    naive_st = [state_map[s] for s in data["Naive"]["states"]]
    sada_st = [state_map[s] for s in data["Full SADA (Default)"]["states"]]

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(8.0, 5.5), sharex=True)

    # 1. Severity input
    ax1.plot(t, sev, color="#555555", lw=1.2, label="Raw Injected Severity")
    ax1.axhline(0.50, color="#eb6834", ls="--", lw=1.2, label="Derate Threshold (0.50)")
    ax1.set_ylabel("Severity", fontsize=9)
    ax1.set_ylim(0.2, 0.8)
    ax1.legend(loc="upper right", fontsize=8)
    ax1.grid(True, linestyle="--", alpha=0.3)
    ax1.set_title("Supervisory State Tracking in Noisy Hover Scenario: Naive vs. SADA", fontsize=11, fontweight="bold")

    # 2. Naive State
    ax2.step(t, naive_st, color="#d9381e", lw=1.8, label="Naive Supervisor (Chattering)")
    ax2.set_yticks([0, 1, 2, 3])
    ax2.set_yticklabels(["NORMAL", "WATCH", "DERATE", "TRIP"], fontsize=8)
    ax2.set_ylabel("State", fontsize=9)
    ax2.legend(loc="upper right", fontsize=8)
    ax2.grid(True, linestyle="--", alpha=0.3)

    # 3. Full SADA State
    ax3.step(t, sada_st, color="#1baf7a", lw=2.0, label="Full SADA (Hysteresis + Dwell)")
    ax3.set_yticks([0, 1, 2, 3])
    ax3.set_yticklabels(["NORMAL", "WATCH", "DERATE", "TRIP"], fontsize=8)
    ax3.set_ylabel("State", fontsize=9)
    ax3.set_xlabel("Time (s)", fontsize=9)
    ax3.legend(loc="upper right", fontsize=8)
    ax3.grid(True, linestyle="--", alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_dir / "sada_timeline_noisy_hover.png", dpi=200)
    fig.savefig(out_dir / "sada_timeline_noisy_hover.pdf")
    plt.close(fig)


# -----------------------------------------------------------------------------
# P5-4: Sensitivity Sweeps (±20% on thresholds and EMA alpha)
# -----------------------------------------------------------------------------

def run_sensitivity_sweeps(seeds: list[int], out_dir: Path) -> dict[str, Any]:
    print("Running P5-4: SADA Threshold Sensitivity Sweeps...")
    param_variations = {
        "watch": [0.24, 0.30, 0.36],
        "derate": [0.40, 0.50, 0.60],
        "trip": [0.64, 0.80, 0.96],
        "ema_alpha": [0.064, 0.080, 0.096],
    }

    sens_results: list[dict[str, Any]] = []

    for param, vals in param_variations.items():
        for val in vals:
            for seed in seeds:
                scenarios = generate_scenarios(seed)
                cfg_kwargs = {param: val}
                sup = SadaSupervisor(SadaConfig(**cfg_kwargs))

                chatter_list, delay_list, unnec_list = [], [], []
                for _sname, scen in scenarios.items():
                    res = evaluate_supervisor(sup, scen)
                    chatter_list.append(res["chatter_per_min"])
                    if not math.isnan(res["action_delay_s"]):
                        delay_list.append(res["action_delay_s"])
                    unnec_list.append(res["unnec_derate_s"])

                sens_results.append({
                    "param": param,
                    "value": val,
                    "delta": f"{(val / param_variations[param][1] - 1.0) * 100:+.0f}%",
                    "seed": seed,
                    "chatter": float(np.mean(chatter_list)),
                    "delay_s": float(np.mean(delay_list)) if delay_list else 0.0,
                    "unnec_derate_s": float(np.sum(unnec_list)),
                })

    # Summary table
    sens_summary: dict[str, Any] = {}
    for param, vals in param_variations.items():
        for val in vals:
            delta_str = f"{(val / param_variations[param][1] - 1.0) * 100:+.0f}%"
            k = f"{param}_{delta_str}"
            sub = [r for r in sens_results if r["param"] == param and r["value"] == val]
            sens_summary[k] = {
                "param": param,
                "nominal": param_variations[param][1],
                "value": val,
                "delta": delta_str,
                "chatter_mean": float(np.mean([r["chatter"] for r in sub])),
                "delay_mean": float(np.mean([r["delay_s"] for r in sub])),
                "unnec_derate_mean": float(np.mean([r["unnec_derate_s"] for r in sub])),
            }

    # LaTeX Sensitivity Table
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{SADA Parameter Sensitivity: Impact of $\pm 20$\% Variations on Operational Metrics}",
        r"\label{tab:sada_sensitivity}",
        r"\begin{tabular}{lrrrrr}",
        r"\toprule",
        r"Parameter & Nominal & Variation & Chatter/min $\downarrow$ & Delay (s) & Unnec. Derate (s) $\downarrow$ \\",
        r"\midrule",
    ]
    for _k, s in sens_summary.items():
        lines.append(
            f"{s['param']} & {s['nominal']} & {s['delta']} & {s['chatter_mean']:.1f} & {s['delay_mean']:.2f} & {s['unnec_derate_mean']:.1f} \\\\"
        )
    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ])
    (out_dir / "table_sada_sensitivity.tex").write_text("\n".join(lines))

    # Heatmap/Bar chart of sensitivity
    plot_sensitivity(out_dir, sens_summary)
    return sens_summary


def plot_sensitivity(out_dir: Path, summary: dict[str, Any]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = list(summary.keys())
    chatters = [summary[k]["chatter_mean"] for k in labels]
    delays = [summary[k]["delay_mean"] for k in labels]

    x = np.arange(len(labels))
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8.5, 5.0), sharex=True)

    ax1.bar(x, chatters, color="#2a78d6", alpha=0.85, width=0.55)
    ax1.set_ylabel("Chatter / min", fontsize=9)
    ax1.grid(True, linestyle="--", alpha=0.3)
    ax1.set_title(r"SADA Parameter Sensitivity Analysis ($\pm$20% Variations)", fontsize=11, fontweight="bold")

    ax2.bar(x, delays, color="#eb6834", alpha=0.85, width=0.55)
    ax2.set_ylabel("Trip Delay (s)", fontsize=9)
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, rotation=35, ha="right", fontsize=8.5)
    ax2.grid(True, linestyle="--", alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_dir / "sada_sensitivity.png", dpi=200)
    fig.savefig(out_dir / "sada_sensitivity.pdf")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate SADA supervisor and baseline variants.")
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2], help="Random seeds")
    parser.add_argument("--out", type=str, default="reports/paper/sada", help="Output directory")
    args = parser.parse_args()

    run_sada_study(args.seeds, Path(args.out))


if __name__ == "__main__":
    main()

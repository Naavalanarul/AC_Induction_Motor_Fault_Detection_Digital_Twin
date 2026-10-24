"""validation/latency_study.py — Phase P7: Detection Latency and Long-Run False-Alarm Study.

Evaluates:
1. P7-1 Latency to detection and supervisory trip:
   - Injects faults at t_fault = 2.0 s across all fault classes
     (broken_rotor_bar, interturn_short, eccentricity, bearing_outer)
     and severities (0.05, 0.10, 0.20, 0.40, 0.60, 0.80, 1.00).
   - Measures time until:
     a) Fused diagnosis first correctly names the fault.
     b) SADA enters WATCH.
     c) SADA enters DERATE.
     d) SADA enters TRIP.
   - Computes median and 90th percentile latencies across random seeds.
   - Generates detection-delay vs severity plot (png and pdf).

2. P7-2 Long-run false-alarm study:
   - Runs extended healthy simulations (up to 36,000 steps = 1.0 simulated hour at 10 Hz).
   - Evaluates across loads (25%, 50%, 75%, 100%), noise levels, and parameter mismatch.
   - Counts false detections per hour and false supervisory trips per hour.
   - Ablates supply channel filtering (with vs without supply diagnostic).
   - Ablates SADA EMA filtering (EMA alpha=0.15 vs unfiltered alpha=1.0).

Outputs written to reports/paper/latency/:
- table_latency.tex
- metrics.csv
- summary.json, meta.json
- detection_delay.png, detection_delay.pdf
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from app.diagnostics.engine import DiagnosticEngine
from app.diagnostics.schema import DiagFault, FusedDiagnosis
from app.sensors.base import SensorMode, SensorType
from app.sensors.registry import SensorRegistry
from app.simulation.faults import FaultType, inject
from app.simulation.params import DEFAULT_MOTOR, MotorParams
from app.simulation.twin_state import MotorSimulator
from app.supervisory.sada import SadaState, SadaSupervisor
from app.validation.reporting import git_commit, git_dirty, write_csv


async def measure_single_latency(
    fault_type: str,
    severity: float,
    seed: int = 0,
    t_fault: float = 2.0,
    sim_duration: float = 10.0,
    load_nm: float = 8.0,
) -> dict[str, Any]:
    """Runs one simulation episode and measures detection, watch, derate, and trip latencies."""
    sim = MotorSimulator(DEFAULT_MOTOR, seed=seed, base_load_nm=load_nm)
    reg = SensorRegistry(sim.state, seed=seed)
    eng = DiagnosticEngine(DEFAULT_MOTOR, sim.fs)
    sada = SadaSupervisor()

    total_steps = int(round(sim_duration / sim.chunk_s))
    fault_step = int(round(t_fault / sim.chunk_s))

    t_detect: float | None = None
    t_watch: float | None = None
    t_derate: float | None = None
    t_trip: float | None = None

    for step in range(total_steps):
        if step == fault_step:
            inject(sim.faults, fault_type, severity)

        st = sim.step()
        frames = await reg.read_all()
        diag = eng.process(st.t, frames, sim.chunk_s)
        out = sada.update(diag, dt=sim.chunk_s)

        if step >= fault_step:
            t_curr = float(st.t)
            # Check fault diagnosis match
            diag_str = diag.fault_type.value if hasattr(diag.fault_type, "value") else str(diag.fault_type)
            if t_detect is None and (diag_str == fault_type or (fault_type.startswith("bearing") and "bearing" in diag_str)):
                t_detect = t_curr - t_fault

            if t_watch is None and out.state in (SadaState.WATCH, SadaState.DERATE, SadaState.TRIP):
                t_watch = t_curr - t_fault

            if t_derate is None and out.state in (SadaState.DERATE, SadaState.TRIP):
                t_derate = t_curr - t_fault

            if t_trip is None and out.state == SadaState.TRIP:
                t_trip = t_curr - t_fault

    return {
        "fault_type": fault_type,
        "severity": severity,
        "seed": seed,
        "latency_detect_s": round(t_detect, 2) if t_detect is not None else None,
        "latency_watch_s": round(t_watch, 2) if t_watch is not None else None,
        "latency_derate_s": round(t_derate, 2) if t_derate is not None else None,
        "latency_trip_s": round(t_trip, 2) if t_trip is not None else None,
    }


async def run_latency_sweep(
    fault_classes: list[str],
    severities: list[float],
    seeds: list[int] = (0, 1, 2),
) -> list[dict[str, Any]]:
    """Runs latency measurements across all fault classes, severities, and seeds."""
    records: list[dict[str, Any]] = []
    for fc in fault_classes:
        for sev in severities:
            for seed in seeds:
                res = await measure_single_latency(
                    fault_type=fc,
                    severity=sev,
                    seed=seed,
                    t_fault=2.0,
                    sim_duration=10.0,
                    load_nm=8.0,
                )
                records.append(res)
    return records


async def run_false_alarm_condition(
    condition_name: str,
    steps: int = 1200,
    load_nm: float = 8.0,
    param_mismatch: bool = False,
    extra_noise: bool = False,
    disable_supply_channel: bool = False,
    disable_sada_ema: bool = False,
    transient_spike: bool = False,
    seed: int = 0,
) -> dict[str, Any]:
    """Runs a simulated long-run healthy monitoring scenario and counts false alarms."""
    plant_params = DEFAULT_MOTOR
    if param_mismatch:
        import dataclasses
        plant_params = dataclasses.replace(
            DEFAULT_MOTOR,
            Rs=DEFAULT_MOTOR.Rs * 1.15,  # 15% stator resistance mismatch
            Lm=DEFAULT_MOTOR.Lm * 1.10,  # 10% magnetizing inductance mismatch
        )

    sim = MotorSimulator(plant_params, seed=seed, base_load_nm=load_nm)
    reg = SensorRegistry(sim.state, seed=seed)
    eng = DiagnosticEngine(DEFAULT_MOTOR, sim.fs)
    sada = SadaSupervisor()
    if disable_sada_ema:
        sada.alpha = 1.0  # Instantaneous unfiltered response

    false_detections = 0
    false_watch = 0
    false_derate = 0
    false_trips = 0
    prev_state = SadaState.NORMAL

    rng = np.random.default_rng(seed)

    for step in range(steps):
        st = sim.step()

        # Simulate extra measurement noise if requested
        if extra_noise and sim.state.electrical is not None:
            sim.state.electrical.i_abc += rng.normal(0.0, 0.20, size=sim.state.electrical.i_abc.shape)

        # Simulate an isolated transient spike at step 100 if requested
        if transient_spike and step == 100 and sim.state.electrical is not None:
            sim.state.electrical.i_abc += 15.0

        frames = await reg.read_all()

        # If supply channel disabled, strip voltage frames
        if disable_supply_channel:
            frames.pop(SensorType.VOLTAGE, None)

        diag = eng.process(st.t, frames, sim.chunk_s)
        out = sada.update(diag, dt=sim.chunk_s)

        # Skip initial 1.0s (10 steps) settling period for false alarm counting
        if step >= 10:
            if diag.fault_type not in (DiagFault.HEALTHY, DiagFault.UNKNOWN):
                false_detections += 1

            if out.state == SadaState.WATCH and prev_state == SadaState.NORMAL:
                false_watch += 1
            elif out.state == SadaState.DERATE and prev_state in (SadaState.NORMAL, SadaState.WATCH):
                false_derate += 1
            elif out.state == SadaState.TRIP and prev_state != SadaState.TRIP:
                false_trips += 1

        prev_state = out.state

    simulated_hours = (steps * sim.chunk_s) / 3600.0
    scale = 1.0 / max(1e-4, simulated_hours)

    return {
        "condition": condition_name,
        "steps": steps,
        "simulated_hours": round(simulated_hours, 2),
        "false_detections_per_hour": round(false_detections * scale, 1),
        "false_watch_per_hour": round(false_watch * scale, 1),
        "false_derate_per_hour": round(false_derate * scale, 1),
        "false_trips_per_hour": round(false_trips * scale, 1),
    }


def plot_detection_delay(
    latency_records: list[dict[str, Any]],
    out_path_png: Path,
    out_path_pdf: Path,
) -> None:
    """Plots detection and supervisory response latencies as a function of severity."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.size": 9,
        "axes.edgecolor": "#52514e",
        "axes.labelcolor": "#0b0b0b",
        "xtick.color": "#52514e",
        "ytick.color": "#52514e",
        "axes.grid": True,
        "grid.color": "#e1e0d9",
        "grid.linestyle": ":",
        "figure.facecolor": "#ffffff",
        "axes.facecolor": "#ffffff",
    })

    severities = sorted(list(set(r["severity"] for r in latency_records)))

    # Aggregate medians across fault types
    med_detect = []
    med_watch = []
    med_derate = []
    med_trip = []

    for sev in severities:
        recs = [r for r in latency_records if r["severity"] == sev]

        dets = [r["latency_detect_s"] for r in recs if r["latency_detect_s"] is not None]
        watches = [r["latency_watch_s"] for r in recs if r["latency_watch_s"] is not None]
        derates = [r["latency_derate_s"] for r in recs if r["latency_derate_s"] is not None]
        trips = [r["latency_trip_s"] for r in recs if r["latency_trip_s"] is not None]

        med_detect.append(float(np.median(dets)) if dets else float("nan"))
        med_watch.append(float(np.median(watches)) if watches else float("nan"))
        med_derate.append(float(np.median(derates)) if derates else float("nan"))
        med_trip.append(float(np.median(trips)) if trips else float("nan"))

    fig, ax = plt.subplots(figsize=(6.5, 4.0))

    ax.plot(severities, med_detect, marker="o", color="#2a78d6", lw=2, label="Diagnostic Detection")
    ax.plot(severities, med_watch, marker="s", color="#eb6834", lw=2, label="SADA WATCH Transition")
    ax.plot(severities, med_derate, marker="^", color="#9a3412", lw=2, label="SADA DERATE Transition")
    ax.plot(severities, med_trip, marker="d", color="#b91c1c", lw=2, label="SADA TRIP Action")

    ax.set_xlabel("Fault Severity $s$")
    ax.set_ylabel("Response Latency (seconds)")
    ax.set_title("Fault Detection and Supervisory Action Latencies vs. Severity")
    ax.set_xlim(0.0, 1.05)
    ax.set_ylim(0.0, 6.0)
    ax.legend(loc="upper right", framealpha=0.9, fontsize=8.5)

    fig.tight_layout()
    fig.savefig(out_path_png, dpi=300)
    fig.savefig(out_path_pdf)
    plt.close(fig)


def generate_latency_latex_table(
    path: Path,
    latency_summary: list[dict[str, Any]],
    false_alarm_summary: list[dict[str, Any]],
) -> None:
    """Generates LaTeX table summarizing detection latencies and long-run false alarm rates."""
    lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\small",
        r"\caption{Fault detection latency, supervisory action delays, and long-run false-alarm rates.}",
        r"\label{tab:latency_study}",
        r"\begin{tabular}{lcccc}",
        r"\toprule",
        r"\textbf{Fault Severity $s$} & \textbf{Detection Latency} & \textbf{WATCH Latency} & \textbf{DERATE Latency} & \textbf{TRIP Latency} \\",
        r"\midrule",
    ]

    for r in latency_summary:
        sev = r["severity"]
        d_lat = f"{r['detect_med']:.2f}s [{r['detect_p90']:.2f}s]" if not math.isnan(r["detect_med"]) else "--"
        w_lat = f"{r['watch_med']:.2f}s [{r['watch_p90']:.2f}s]" if not math.isnan(r["watch_med"]) else "--"
        de_lat = f"{r['derate_med']:.2f}s [{r['derate_p90']:.2f}s]" if not math.isnan(r["derate_med"]) else "--"
        tr_lat = f"{r['trip_med']:.2f}s [{r['trip_p90']:.2f}s]" if not math.isnan(r["trip_med"]) else "--"
        lines.append(f"{sev:.2f} & {d_lat} & {w_lat} & {de_lat} & {tr_lat} \\\\")

    lines.extend([
        r"\midrule",
        r"\multicolumn{5}{l}{\textbf{Long-Run Healthy Operational Stability (False Alarms per Simulated Hour):}} \\",
        r"\midrule",
        r"\textbf{Evaluation Condition} & \textbf{Sim Hours} & \textbf{False Detect / hr} & \textbf{False Watch / hr} & \textbf{False Trip / hr} \\",
        r"\midrule",
    ])

    for fa in false_alarm_summary:
        c_name = fa["condition"].replace("_", " ").capitalize()
        hrs = fa["simulated_hours"]
        f_det = fa["false_detections_per_hour"]
        f_wat = fa["false_watch_per_hour"]
        f_trp = fa["false_trips_per_hour"]
        lines.append(f"{c_name} & {hrs:.2f}h & {f_det} & {f_wat} & {f_trp} \\\\")

    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"\begin{tablenotes}",
        r"\small",
        r"\item \textit{Note:} Latencies reported as median [90th percentile] across 3 seeds and 4 fault classes.",
        r"False alarms measured under 10 Hz continuous supervisory cycle ($3{,}600$--$36{,}000$ steps).",
        r"\end{tablenotes}",
        r"\end{table}",
    ])
    path.write_text("\n".join(lines) + "\n")


async def run_latency_and_false_alarm_study(
    out_dir: Path,
    steps_per_condition: int = 3600,
    seeds: list[int] = (0, 1, 2),
) -> None:
    """Executes full Phase P7 evaluation suite and produces paper artifacts."""
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Running P7-1: Latency to detection and trip sweeps...")
    fault_classes = ["broken_rotor_bar", "interturn_short", "eccentricity", "bearing_outer"]
    severities = [0.05, 0.10, 0.20, 0.40, 0.60, 0.80, 1.00]

    latency_records = await run_latency_sweep(fault_classes, severities, seeds=seeds)

    # Compute median and 90th percentile by severity
    latency_summary: list[dict[str, Any]] = []
    for sev in severities:
        recs = [r for r in latency_records if r["severity"] == sev]
        dets = [r["latency_detect_s"] for r in recs if r["latency_detect_s"] is not None]
        watches = [r["latency_watch_s"] for r in recs if r["latency_watch_s"] is not None]
        derates = [r["latency_derate_s"] for r in recs if r["latency_derate_s"] is not None]
        trips = [r["latency_trip_s"] for r in recs if r["latency_trip_s"] is not None]

        latency_summary.append({
            "severity": sev,
            "detect_med": float(np.median(dets)) if dets else float("nan"),
            "detect_p90": float(np.percentile(dets, 90)) if dets else float("nan"),
            "watch_med": float(np.median(watches)) if watches else float("nan"),
            "watch_p90": float(np.percentile(watches, 90)) if watches else float("nan"),
            "derate_med": float(np.median(derates)) if derates else float("nan"),
            "derate_p90": float(np.percentile(derates, 90)) if derates else float("nan"),
            "trip_med": float(np.median(trips)) if trips else float("nan"),
            "trip_p90": float(np.percentile(trips, 90)) if trips else float("nan"),
        })

    # Plot detection delay
    plot_detection_delay(latency_records, out_dir / "detection_delay.png", out_dir / "detection_delay.pdf")

    print(f"Running P7-2: Long-run false alarm study ({steps_per_condition} steps per condition)...")
    false_alarm_conditions = [
        {"name": "load_25pct", "load_nm": 2.0},
        {"name": "load_50pct", "load_nm": 4.0},
        {"name": "load_75pct", "load_nm": 6.0},
        {"name": "load_100pct", "load_nm": 8.0},
        {"name": "high_sensor_noise", "load_nm": 8.0, "extra_noise": True},
        {"name": "parameter_mismatch_15pct", "load_nm": 8.0, "param_mismatch": True},
        {"name": "with_supply_channel", "load_nm": 8.0, "disable_supply_channel": False},
        {"name": "without_supply_channel", "load_nm": 8.0, "disable_supply_channel": True},
        {"name": "sada_with_ema", "load_nm": 8.0, "transient_spike": True, "disable_sada_ema": False},
        {"name": "sada_without_ema", "load_nm": 8.0, "transient_spike": True, "disable_sada_ema": True},
    ]

    fa_results: list[dict[str, Any]] = []
    for cond in false_alarm_conditions:
        res = await run_false_alarm_condition(
            condition_name=cond["name"],
            steps=steps_per_condition,
            load_nm=cond.get("load_nm", 8.0),
            param_mismatch=cond.get("param_mismatch", False),
            extra_noise=cond.get("extra_noise", False),
            disable_supply_channel=cond.get("disable_supply_channel", False),
            disable_sada_ema=cond.get("disable_sada_ema", False),
            transient_spike=cond.get("transient_spike", False),
            seed=0,
        )
        fa_results.append(res)

    # Write metrics CSV
    write_csv(out_dir / "metrics.csv", latency_records + fa_results)

    # Generate LaTeX table
    generate_latency_latex_table(out_dir / "table_latency.tex", latency_summary, fa_results)

    # Write summary JSON
    summary = {
        "p7_1_latency": {
            "evaluated_severities": severities,
            "evaluated_fault_classes": fault_classes,
            "summary_by_severity": latency_summary,
        },
        "p7_2_false_alarms": {
            "steps_per_condition": steps_per_condition,
            "conditions": fa_results,
        },
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    # Write meta JSON
    meta = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "git_commit": git_commit(),
        "git_dirty": git_dirty(),
        "command": " ".join(sys.argv),
        "seeds": list(seeds),
        "steps_per_condition": steps_per_condition,
        "python_version": sys.version,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"P7 study completed. Results saved to {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="P7: Detection Latency and False-Alarm Study")
    parser.add_argument("--out", type=Path, default=Path("reports/paper/latency"), help="Output directory")
    parser.add_argument("--steps", type=int, default=1200, help="Steps per false alarm condition (1200=2min, 36000=1h)")
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2], help="Random seeds")
    args = parser.parse_args()

    asyncio.run(run_latency_and_false_alarm_study(
        out_dir=args.out,
        steps_per_condition=args.steps,
        seeds=args.seeds,
    ))


if __name__ == "__main__":
    main()

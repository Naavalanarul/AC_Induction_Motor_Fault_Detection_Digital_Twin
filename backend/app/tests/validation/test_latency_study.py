"""tests/validation/test_latency_study.py — Unit tests for Phase P7 Latency and False-Alarm Study."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.validation.latency_study import (
    measure_single_latency,
    run_false_alarm_condition,
    run_latency_and_false_alarm_study,
)


def test_measure_single_latency():
    res = asyncio.run(measure_single_latency(
        fault_type="broken_rotor_bar",
        severity=0.6,
        seed=0,
        t_fault=2.0,
        sim_duration=5.0,
        load_nm=8.0,
    ))
    assert res["fault_type"] == "broken_rotor_bar"
    assert res["severity"] == 0.6
    assert res["latency_detect_s"] is not None
    assert res["latency_detect_s"] < 1.0  # Detected within 1 second of injection
    assert res["latency_watch_s"] is not None


def test_false_alarm_healthy():
    res = asyncio.run(run_false_alarm_condition(
        condition_name="test_healthy",
        steps=50,
        load_nm=8.0,
        seed=0,
    ))
    assert res["false_trips_per_hour"] == 0.0


def test_latency_study_smoke(tmp_path: Path):
    asyncio.run(run_latency_and_false_alarm_study(
        out_dir=tmp_path,
        steps_per_condition=50,
        seeds=[0],
    ))

    expected_files = [
        "metrics.csv",
        "table_latency.tex",
        "detection_delay.png",
        "detection_delay.pdf",
        "summary.json",
        "meta.json",
    ]

    for fname in expected_files:
        p = tmp_path / fname
        assert p.exists(), f"Expected file {fname} not found in {tmp_path}"
        assert p.stat().st_size > 0, f"File {fname} is empty"

    summary = json.loads((tmp_path / "summary.json").read_text())
    assert "p7_1_latency" in summary
    assert "p7_2_false_alarms" in summary

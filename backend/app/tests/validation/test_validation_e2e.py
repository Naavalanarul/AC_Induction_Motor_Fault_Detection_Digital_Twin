"""End-to-end tests of the validation CLI on tiny stand-in files (never real data)."""

from __future__ import annotations

import csv
import dataclasses
import json

import pytest

from app.simulation.params import DEFAULT_MOTOR
from app.tests.validation import stand_in
from app.validation import calibration as CAL
from app.validation.preprocessing import prepare
from app.validation.run import EXIT_DATASET_UNAVAILABLE, main
from app.validation.simdata import SimConfig, simulate_record


def test_cli_exits_cleanly_when_dataset_missing(tmp_path, capsys):
    rc = main(["--dataset", "liman_c", "--protocol", "zero_shot", "--data-root", str(tmp_path / "nope"),
               "--out", str(tmp_path / "out")])
    assert rc == EXIT_DATASET_UNAVAILABLE
    err = capsys.readouterr().err
    assert "does not exist" in err and "never substituted" in err
    assert not (tmp_path / "out" / "liman_c" / "zero_shot").exists()


def test_cli_rejects_real_protocols_for_sim(tmp_path):
    assert main(["--dataset", "sim", "--protocol", "zero_shot", "--out", str(tmp_path)]) == 1


def test_calibration_recovers_parameters_with_known_slip():
    lm = DEFAULT_MOTOR.Lm * 1.1
    true = dataclasses.replace(DEFAULT_MOTOR, Rs=DEFAULT_MOTOR.Rs * 1.3, Rr=DEFAULT_MOTOR.Rr * 0.8, Lm=lm,
                               Ls=lm + DEFAULT_MOTOR.Ls - DEFAULT_MOTOR.Lm, Lr=lm + DEFAULT_MOTOR.Lr - DEFAULT_MOTOR.Lm)
    preps = []
    for i, load in enumerate((25, 50, 75, 100)):
        r = simulate_record("healthy", 0.0, load, 50 + i, SimConfig(params=true, seconds=3.0))
        p = prepare(r)
        p.slip, p.slip_source = 1 - r.meta["true_rpm"] * 2 / 60 / 50, "speed"
        preps.append(p)
    res = CAL.fit(preps)
    assert res.fitted_circuit
    assert res.impedance_rel_error_fitted < 0.2 * res.impedance_rel_error_default
    assert res.params.Rr == pytest.approx(true.Rr, rel=0.1)
    assert res.params.Lm == pytest.approx(true.Lm, rel=0.05)


def test_calibration_without_voltage_only_fits_noise():
    r = simulate_record("healthy", 0.0, 60, 1, SimConfig(seconds=3.0))
    for k in ("va", "vb", "vc"):
        r.signals.pop(k)
    res = CAL.fit([prepare(r)])
    assert not res.fitted_circuit and any("NOT fitted" in n for n in res.notes)


@pytest.mark.slow
def test_protocols_end_to_end_on_stand_in(tmp_path):
    data = tmp_path / "bruinsma"
    stand_in.write_bruinsma(data, {"healthy": 3, "brb": 3, "bearing": 3}, seconds=3.0)
    out = tmp_path / "reports"
    for protocol in ("zero_shot", "real_only", "domain_shift", "severity"):
        rc = main(["--dataset", "bruinsma", "--data-root", str(data), "--protocol", protocol, "--seeds", "0",
                   "--sim-runs-per-class", "3", "--sim-seconds", "3", "--out", str(out)])
        assert rc == 0, protocol
        d = out / "bruinsma" / protocol
        assert (d / "metrics.csv").exists() and (d / "table.tex").exists()
        meta = json.loads((d / "meta.json").read_text())
        for key in ("dataset", "dataset_version", "seeds", "git_commit", "channels_evaluated", "licence"):
            assert key in meta, (protocol, key)
        assert meta["channels_evaluated"]["thermal"].startswith("NOT evaluable")
    zs = out / "bruinsma" / "zero_shot"
    assert (zs / "confusion.png").exists()
    rows = list(csv.DictReader((zs / "metrics.csv").open()))
    assert rows and {"gap_accuracy", "ece", "brier", "auroc_healthy_vs_fault"} <= set(rows[0])
    sev = json.loads((out / "bruinsma" / "severity" / "meta.json").read_text())
    assert "NOT validated" in sev["rul"]
    assert "split" in json.loads((zs / "meta.json").read_text())

"""Phase 3: each fault injector must produce its known signature (assertions on spectra)."""

import math

import numpy as np
import pytest
from scipy.signal import hilbert

from app.simulation import faults as F
from app.simulation.mechanical_signals import BPFI, BPFO
from app.simulation.plant import abc_to_alphabeta
from app.simulation.twin_state import MotorSimulator
from app.tests.conftest import peak_near, spectrum


def collect(sim: MotorSimulator, seconds: float):
    cur, vib, w, u = [], [], [], []
    for _ in range(int(seconds / sim.chunk_s)):
        st = sim.step()
        assert st is not None and st.electrical is not None
        cur.append(st.electrical.i_abc)
        u.append(st.electrical.u_abc)
        vib.append(st.vibration)
        w.append(st.electrical.omega_m)
    return np.hstack(cur), np.hstack(vib), np.concatenate(w), np.hstack(u)


def warm(fault=None, sev=0.5, params=None, load=10.0):
    sim = MotorSimulator(base_load_nm=load)
    sim.plant.warm_start(load, 1.5)
    if fault:
        F.inject(sim.faults, fault, sev, params or {})
    return sim


def test_injector_validates_severity():
    with pytest.raises(ValueError):
        F.inject_unbalance(F.FaultState(), 1.5)
    with pytest.raises(ValueError):
        F.inject_interturn_short(F.FaultState(), phase="d")


def test_broken_rotor_bar_produces_mcsa_sidebands():
    healthy, faulty = warm(), warm("broken_rotor_bar", params={"count": 4})
    out = {}
    for name, sim in (("h", healthy), ("f", faulty)):
        i, _, w, _ = collect(sim, 4.0)
        fr = w.mean() / (2 * math.pi)
        s = (50 - 2 * fr) / 50
        freqs, sp = spectrum(i[0], sim.fs)
        out[name] = (peak_near(freqs, sp, 50 * (1 - 2 * s), 0.3) / peak_near(freqs, sp, 50.0), s)
    ratio_f, s = out["f"]
    assert s > 0.01
    assert ratio_f > 10 * out["h"][0]
    assert 20 * math.log10(ratio_f) > -45  # visible (1-2s)f sideband


def test_interturn_short_unbalances_phase_currents():
    sim = warm("interturn_short", 0.6, {"phase": "c"})
    i, *_ = collect(sim, 1.0)
    rms = np.sqrt(np.mean(i**2, axis=1))
    assert int(np.argmax(rms)) == 2
    assert rms[2] > 1.05 * rms[:2].mean()
    assert abs(i.sum(axis=0)).max() < 1e-6  # three-wire: KCL holds


def test_dynamic_eccentricity_produces_rotor_frequency_sidebands():
    sim = warm("eccentricity", 0.6, {"type": "dynamic"})
    i, _, w, _ = collect(sim, 2.0)
    fr = w.mean() / (2 * math.pi)
    freqs, sp = spectrum(i[0], sim.fs)
    assert peak_near(freqs, sp, 50 + fr) / peak_near(freqs, sp, 50) > 10 ** (-40 / 20)


@pytest.mark.parametrize("defect,order", [("bearing_outer", BPFO), ("bearing_inner", BPFI)])
def test_bearing_fault_shows_defect_frequency_in_envelope(defect, order):
    sim = warm(defect, 0.6)
    _, v, w, _ = collect(sim, 1.0)
    fr = w.mean() / (2 * math.pi)
    env = np.abs(hilbert(v[1]))
    freqs, sp = spectrum(env, sim.state.vib_fs)
    at_defect = peak_near(freqs, sp, order * fr, 2.0)
    assert at_defect > 5 * np.median(sp[(freqs > 20) & (freqs < 400)])


def test_unbalance_and_misalignment_orders():
    for fault, harmonic in (("unbalance", 1), ("misalignment", 2)):
        sim = warm(fault, 0.7)
        _, v, w, _ = collect(sim, 1.0)
        fr = w.mean() / (2 * math.pi)
        freqs, sp = spectrum(v[0], sim.state.vib_fs)
        assert peak_near(freqs, sp, harmonic * fr, 2.0) > 0.3


def test_interturn_short_heats_winding_faster():
    temps = {}
    for fault in (None, "interturn_short"):
        sim = warm(fault, 1.0)
        collect(sim, 20.0)
        temps[fault] = sim.state.temperature_c
    assert temps["interturn_short"] > temps[None] + 2.0


def test_voltage_imbalance_creates_negative_sequence():
    sim = warm("voltage_anomaly", 0.8, {"type": "imbalance"})
    *_, u = collect(sim, 0.2)
    ua, ub = abc_to_alphabeta(u)
    spec = np.fft.fft(ua + 1j * ub)
    freqs = np.fft.fftfreq(len(ua), 1 / sim.fs)
    neg = abs(spec[np.argmin(abs(freqs + 50))])
    pos = abs(spec[np.argmin(abs(freqs - 50))])
    assert neg / pos == pytest.approx(0.08, rel=0.1)

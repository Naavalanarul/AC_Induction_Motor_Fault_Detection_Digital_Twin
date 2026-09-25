import asyncio

import numpy as np
import pytest

from app.diagnostics.engine import DiagnosticEngine
from app.diagnostics.ml.classifier import MechanicalClassifier
from app.sensors import SensorRegistry
from app.simulation import faults as F
from app.simulation.twin_state import MotorSimulator


def run_pipeline(fault=None, severity=0.5, params=None, chunks=40, load=8.0, use_ml=False, sada=None):
    """Simulate `chunks` x 0.1 s with a fault injected from the start; return last diagnosis."""
    sim = MotorSimulator(base_load_nm=load)
    reg = SensorRegistry(sim.state)
    eng = DiagnosticEngine(sim.state.params, sim.fs, classifier=MechanicalClassifier(use_ml=use_ml))
    if fault:
        F.inject(sim.faults, fault, severity, params or {})
    diag = out = None
    for _ in range(chunks):
        st = sim.step()
        frames = asyncio.run(reg.read_all())
        diag = eng.process(st.t, frames, sim.chunk_s)
        if sada is not None:
            out = sada.update(diag)
            sim.state.load_cmd, sim.state.tripped = out.load_cmd, out.trip
    return diag, out, sim, eng


@pytest.fixture
def pipeline():
    return run_pipeline


def spectrum(x: np.ndarray, fs: float):
    win = np.hanning(len(x))
    s = np.abs(np.fft.rfft((x - x.mean()) * win)) / (win.sum() / 2)
    return np.fft.rfftfreq(len(x), 1 / fs), s


def peak_near(freqs, spec, f, tol=1.0):
    m = np.abs(freqs - f) <= tol
    return float(spec[m].max())

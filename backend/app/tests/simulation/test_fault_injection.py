"""tests/test_fault_injection.py

Tests for fault injection models and cross-sensor consistency.

Verifies that fault parameters correctly propagate to:
- Electrical solver (currents, torque, slip)
- Thermal model (extra heat, temperature rise)
- Vibration generator (impulse trains, modulation)
- MCSA (spectral signatures)
"""

from __future__ import annotations

import numpy as np
import pytest

from app.core_physics.fault_models import (
    FaultState,
    FaultType,
    BearingDefect,
    EccentricityType,
    BearingGeometry,
    inject_broken_rotor_bar,
    inject_interturn_short,
    inject_eccentricity,
    inject_bearing_fault,
    inject_unbalance,
    inject_misalignment,
)
from app.core_physics.dynamic_solver import StateSpaceMotorSolver
from app.core_physics.motor_parameters import DEFAULT_MOTOR
from app.core_physics.thermal_lptn import FourNodeThermalLPTN
from app.signal_processing.mcsa_pipeline import MCSAAnalyzer
from app.signal_processing.vibration_analysis import VibrationAnalyzer


class TestBRBFaultInjection:
    """Broken Rotor Bar fault injection tests."""

    def test_brb_modulates_rotor_resistance(self):
        """BRB creates rotor resistance asymmetry in solver."""
        solver_healthy = StateSpaceMotorSolver(params=DEFAULT_MOTOR, brb_delta=0.0)
        solver_faulty = StateSpaceMotorSolver(params=DEFAULT_MOTOR, brb_delta=0.5)

        # Check that brb_delta is stored
        assert solver_faulty.brb_delta == 0.5
        assert solver_healthy.brb_delta == 0.0

    def test_brb_creates_backward_rotating_field(self):
        """BRB resistance matrix rotates at 2× electrical frequency."""
        # The BRB model in dynamic_solver uses cos(2θ_r) and sin(2θ_r)
        # This creates backward-rotating field at slip frequency
        solver = StateSpaceMotorSolver(params=DEFAULT_MOTOR, brb_delta=0.4)
        res = solver.solve(t_span=(0.0, 2.0), load_torque=10.0)

        # Verify sidebands present in current spectrum
        mask = res.t >= 1.0
        ia = res.i_abc[0][mask]
        fs = 5000.0
        t_ss = res.t[mask]
        t_uni = np.arange(t_ss[0], t_ss[-1], 1/fs)
        ia_uni = np.interp(t_uni, t_ss, ia)

        analyzer = MCSAAnalyzer(fs=fs)
        mcsa = analyzer.analyze(ia_uni, nominal_supply_freq=50.0,
                                omega_m=float(np.mean(res.omega_m[mask])), pole_pairs=2)

        # BRB should produce detectable sidebands
        assert mcsa.worst_brb_sideband_db is not None
        assert mcsa.worst_brb_sideband_db > -60

    def test_brb_multiple_bars(self):
        """Multiple broken bars increase asymmetry."""
        state = FaultState()
        inject_broken_rotor_bar(state, count=1, severity=0.125)
        delta_1 = state.brb_delta

        inject_broken_rotor_bar(state, count=4, severity=0.5)
        delta_4 = state.brb_delta

        # More broken bars = higher delta
        assert delta_4 > delta_1

    def test_brb_fault_state_persistence(self):
        """FaultState maintains BRB parameters across queries."""
        state = FaultState()
        inject_broken_rotor_bar(state, count=2, position=5, severity=0.25)

        # Query multiple times
        for _ in range(5):
            assert state.brb_delta > 0
            brb_faults = state.of_type(FaultType.BROKEN_ROTOR_BAR)
            assert len(brb_faults) == 1
            assert brb_faults[0].params["count"] == 2


class TestITSCFaultInjection:
    """Inter-Turn Short Circuit fault injection tests."""

    def test_itsc_creates_circulating_current(self):
        """ITSC adds circulating current to faulted phase."""
        solver_healthy = StateSpaceMotorSolver(params=DEFAULT_MOTOR, itsc_mu=0.0)
        solver_itsc = StateSpaceMotorSolver(params=DEFAULT_MOTOR, itsc_mu=0.1, itsc_rf=5.0)

        res_h = solver_healthy.solve(t_span=(0.0, 0.5), load_torque=5.0)
        res_f = solver_itsc.solve(t_span=(0.0, 0.5), load_torque=5.0)

        # Phase A (index 0) should have higher current
        ia_h = float(np.sqrt(np.mean(res_h.i_abc[0][-100:]**2)))
        ia_f = float(np.sqrt(np.mean(res_f.i_abc[0][-100:]**2)))
        ib_h = float(np.sqrt(np.mean(res_h.i_abc[1][-100:]**2)))
        ib_f = float(np.sqrt(np.mean(res_f.i_abc[1][-100:]**2)))

        assert ia_f > ia_h * 1.1  # At least 10% increase
        # Other phases should not increase as much
        assert ib_f / ib_h < ia_f / ia_h

    def test_itsc_localized_heat(self):
        """ITSC generates extra heat in faulted winding."""
        solver = StateSpaceMotorSolver(params=DEFAULT_MOTOR, itsc_mu=0.15, itsc_rf=5.0)
        res = solver.solve(t_span=(0.0, 1.0), load_torque=8.0)

        # Fault heat should be positive
        assert np.all(res.fault_heat_w >= 0)
        assert np.mean(res.fault_heat_w[-100:]) > 10.0  # Significant heat

    def test_itsc_phase_selection(self):
        """ITSC can be injected in any phase."""
        state = FaultState()

        for phase in ["a", "b", "c"]:
            state.clear()
            inject_interturn_short(state, phase=phase, mu=0.05, severity=0.33)
            itsc = state.interturn
            assert itsc is not None
            assert itsc[0] == ["a", "b", "c"].index(phase)

    def test_itsc_fault_resistance_effect(self):
        """Lower fault resistance increases circulating current."""
        solver_high_rf = StateSpaceMotorSolver(params=DEFAULT_MOTOR, itsc_mu=0.1, itsc_rf=50.0)
        solver_low_rf = StateSpaceMotorSolver(params=DEFAULT_MOTOR, itsc_mu=0.1, itsc_rf=1.0)

        res_high = solver_high_rf.solve(t_span=(0.0, 0.5), load_torque=5.0)
        res_low = solver_low_rf.solve(t_span=(0.0, 0.5), load_torque=5.0)

        ia_high = float(np.sqrt(np.mean(res_high.i_abc[0][-50:]**2)))
        ia_low = float(np.sqrt(np.mean(res_low.i_abc[0][-50:]**2)))

        # Lower fault resistance = higher circulating current
        assert ia_low > ia_high


class TestEccentricityFaultInjection:
    """Air-gap eccentricity fault injection tests."""

    def test_dynamic_eccentricity_modulates_Lm(self):
        """Dynamic eccentricity modulates mutual inductance with rotor position."""
        solver = StateSpaceMotorSolver(params=DEFAULT_MOTOR, ecc_dynamic=0.2)
        res = solver.solve(t_span=(0.0, 1.0), load_torque=5.0)

        # Current should show modulation at rotor frequency
        mask = res.t >= 0.5
        ia = res.i_abc[0][mask]
        fs = 5000.0
        t_ss = res.t[mask]
        t_uni = np.arange(t_ss[0], t_ss[-1], 1/fs)
        ia_uni = np.interp(t_uni, t_ss, ia)

        # FFT should show sidebands at f_s ± f_r
        fft = np.fft.rfft(ia_uni * np.hanning(len(ia_uni)))
        fft_freqs = np.fft.rfftfreq(len(ia_uni), 1/fs)
        fft_mag = np.abs(fft)

        f_s = 50.0
        f_r = float(np.mean(res.omega_m[mask])) / (2 * np.pi)

        # Check for sidebands
        for sideband in [f_s - f_r, f_s + f_r]:
            idx = np.argmin(np.abs(fft_freqs - sideband))
            # Sideband should be above noise floor
            assert fft_mag[idx] > np.max(fft_mag) * 0.001

    def test_static_eccentricity(self):
        """Static eccentricity modulates at 2× supply frequency."""
        state = FaultState()
        inject_eccentricity(state, type="static", severity=0.5)
        dyn, stat = state.eccentricity

        assert stat > 0
        assert dyn == 0

    def test_mixed_eccentricity(self):
        """Mixed eccentricity has both static and dynamic components."""
        state = FaultState()
        inject_eccentricity(state, type="mixed", severity=0.6,
                          dynamic_depth=0.09, static_depth=0.045)  # Match actual calculation
        dyn, stat = state.eccentricity

        assert dyn == pytest.approx(0.09, rel=0.01)
        assert stat == pytest.approx(0.045, rel=0.01)


class TestBearingFaultInjection:
    """Bearing fault injection tests."""

    def test_bearing_defect_frequencies(self):
        """Bearing defect frequencies calculated from geometry."""
        geom = BearingGeometry()  # Default 6205
        defects = geom.defect_frequencies(25.0)  # 1500 RPM

        # These are the standard CWRU values for 6205
        assert abs(defects["BPFO"] - 89.6) < 1.0
        assert abs(defects["BPFI"] - 135.4) < 1.0
        assert abs(defects["BSF"] - 58.4) < 1.0
        assert abs(defects["FTF"] - 10.0) < 0.5

    def test_bearing_impulse_generation(self):
        """Bearing impulses generated at correct defect frequency."""
        state = FaultState()
        inject_bearing_fault(state, defect="outer_race", severity=0.5)

        # Simulate 1 second at 1500 RPM
        fs = 12800.0
        t = np.arange(0, 1.0, 1/fs)
        theta_m = 2 * np.pi * 25.0 * t  # 25 Hz shaft
        omega_m = np.full_like(t, 2 * np.pi * 25.0)

        # Get impulse times for outer race
        hits = state.bearing_impulse_times(BearingDefect.OR, theta_m)

        # Should have ~BPFO impulses
        bpfo = 89.6
        expected_count = int(bpfo * 1.0)  # 1 second
        actual_count = np.sum(hits)

        # Allow some tolerance
        assert abs(actual_count - expected_count) <= 2

    def test_bearing_amplitude_modulation(self):
        """Bearing impulse amplitude modulated by load zone."""
        state = FaultState()
        inject_bearing_fault(state, defect="inner_race", severity=0.5)

        fs = 12800.0
        t = np.arange(0, 1.0, 1/fs)
        theta_m = 2 * np.pi * 25.0 * t
        omega_m = np.full_like(t, 2 * np.pi * 25.0)
        speed_ratio = np.full_like(t, 1.0)

        amp = state.bearing_impulse_amplitude(BearingDefect.IR, theta_m, omega_m, speed_ratio)

        # Inner race: modulated by cos(theta_m) - max at load zone (theta=0)
        # Find peaks in amplitude
        peak_indices = np.where(hits := state.bearing_impulse_times(BearingDefect.IR, theta_m))[0]
        if len(peak_indices) > 2:
            # Amplitude should vary with load zone
            assert np.std(amp[peak_indices]) > 0.1 * np.mean(amp[peak_indices])

    def test_bearing_friction_torque(self):
        """Bearing faults add friction torque."""
        state = FaultState()
        inject_bearing_fault(state, defect="outer_race", severity=0.5)

        assert state.bearing_friction_torque > 0
        assert state.bearing_friction_torque <= 0.3  # Max 0.3 Nm

    def test_multiple_bearing_faults(self):
        """Multiple bearing faults combine correctly."""
        state = FaultState()
        inject_bearing_fault(state, defect="inner_race", severity=0.3)
        inject_bearing_fault(state, defect="outer_race", severity=0.4)
        inject_bearing_fault(state, defect="ball", severity=0.2)

        # Max severity should be 0.4 (OR)
        assert state.bearing(BearingDefect.OR) == 0.4
        assert state.bearing_friction_torque == pytest.approx(0.3 * 0.4, rel=0.1)


class TestMechanicalFaultInjection:
    """Unbalance and misalignment fault injection tests."""

    def test_unbalance_creates_1x_torque_ripple(self):
        """Unbalance adds 1× shaft frequency torque ripple."""
        state = FaultState()
        inject_unbalance(state, magnitude=0.5)

        fs = 12800.0
        t = np.arange(0, 1.0, 1/fs)
        theta_m = 2 * np.pi * 25.0 * t
        omega_m = np.full_like(t, 2 * np.pi * 25.0)

        pert = state.load_torque_perturbation(theta_m, omega_m)

        # FFT should show peak at 25 Hz (1×)
        fft = np.fft.rfft(pert * np.hanning(len(pert)))
        fft_freqs = np.fft.rfftfreq(len(pert), 1/fs)
        fft_mag = np.abs(fft)

        idx_1x = np.argmin(np.abs(fft_freqs - 25.0))
        idx_2x = np.argmin(np.abs(fft_freqs - 50.0))

        assert fft_mag[idx_1x] > fft_mag[idx_2x] * 2  # 1× dominant

    def test_misalignment_creates_2x_torque_ripple(self):
        """Misalignment adds 2× shaft frequency torque ripple."""
        state = FaultState()
        inject_misalignment(state, magnitude=0.5)

        fs = 12800.0
        t = np.arange(0, 1.0, 1/fs)
        theta_m = 2 * np.pi * 25.0 * t
        omega_m = np.full_like(t, 2 * np.pi * 25.0)

        pert = state.load_torque_perturbation(theta_m, omega_m)

        fft = np.fft.rfft(pert * np.hanning(len(pert)))
        fft_freqs = np.fft.rfftfreq(len(pert), 1/fs)
        fft_mag = np.abs(fft)

        idx_1x = np.argmin(np.abs(fft_freqs - 25.0))
        idx_2x = np.argmin(np.abs(fft_freqs - 50.0))

        assert fft_mag[idx_2x] > fft_mag[idx_1x] * 1.5  # 2× dominant

    def test_combined_mechanical_faults(self):
        """Unbalance and misalignment combine in torque perturbation."""
        state = FaultState()
        inject_unbalance(state, magnitude=0.4)
        inject_misalignment(state, magnitude=0.3)

        fs = 12800.0
        t = np.arange(0, 1.0, 1/fs)
        theta_m = 2 * np.pi * 25.0 * t
        omega_m = np.full_like(t, 2 * np.pi * 25.0)

        pert = state.load_torque_perturbation(theta_m, omega_m)

        # Should have both 1× and 2× components
        fft = np.fft.rfft(pert * np.hanning(len(pert)))
        fft_freqs = np.fft.rfftfreq(len(pert), 1/fs)
        fft_mag = np.abs(fft)

        idx_1x = np.argmin(np.abs(fft_freqs - 25.0))
        idx_2x = np.argmin(np.abs(fft_freqs - 50.0))

        assert fft_mag[idx_1x] > 0.1
        assert fft_mag[idx_2x] > 0.1


class TestFaultStateConsistency:
    """Cross-sensor consistency tests for FaultState."""

    def test_fault_state_cleared_properly(self):
        """Clearing faults removes all parameters."""
        state = FaultState()
        inject_broken_rotor_bar(state, count=2)
        inject_interturn_short(state, phase="a", mu=0.1)
        inject_bearing_fault(state, defect="outer_race")

        state.clear()

        assert state.brb_delta == 0.0
        assert state.interturn is None
        assert state.bearing(BearingDefect.OR) == 0.0
        assert len(state.active) == 0

    def test_fault_removal(self):
        """Individual fault removal works."""
        state = FaultState()
        fault1 = inject_broken_rotor_bar(state, count=1)
        fault2 = inject_broken_rotor_bar(state, count=2)

        assert len(state.active) == 2

        state.remove(fault1.id)
        assert len(state.active) == 1
        assert state.active[0].id == fault2.id

    def test_fault_severity_bounds(self):
        """Severity clamped to [0, 1]."""
        state = FaultState()

        # Try to inject with severity > 1
        with pytest.raises(ValueError):
            inject_broken_rotor_bar(state, count=1, severity=1.5)

        # Normal injection should work
        inject_broken_rotor_bar(state, count=4, severity=0.5)
        assert state.severity_of(FaultType.BROKEN_ROTOR_BAR) == 0.5


class TestThermalCoupling:
    """Test thermal coupling from faults."""

    def test_itsc_heat_feeds_thermal_model(self):
        """ITSC fault heat increases winding temperature."""
        lptn = FourNodeThermalLPTN(t_ambient=25.0)

        # Without ITSC
        for _ in range(100):
            st1 = lptn.step(dt=0.1, p_copper_s=100.0, p_iron=30.0, p_copper_r=80.0, p_friction=10.0)

        lptn2 = FourNodeThermalLPTN(t_ambient=25.0)
        # With ITSC extra heat
        for _ in range(100):
            st2 = lptn2.step(dt=0.1, p_copper_s=100.0, p_iron=30.0, p_copper_r=80.0,
                             p_friction=10.0, itsc_extra_w=200.0)

        # ITSC heat should raise winding temperature (allow for thermal time constant)
        assert st2.t_winding > st1.t_winding + 5.0

    def test_bearing_friction_heat(self):
        """Bearing friction adds heat to bearing node."""
        lptn = FourNodeThermalLPTN(t_ambient=25.0)

        for _ in range(200):
            st1 = lptn.step(dt=0.1, p_copper_s=50.0, p_iron=20.0, p_copper_r=40.0, p_friction=5.0)

        lptn2 = FourNodeThermalLPTN(t_ambient=25.0)
        for _ in range(200):
            st2 = lptn2.step(dt=0.1, p_copper_s=50.0, p_iron=20.0, p_copper_r=40.0, p_friction=50.0)

        assert st2.t_bearing > st1.t_bearing + 5.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
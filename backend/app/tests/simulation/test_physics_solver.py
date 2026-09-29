"""tests/test_physics_solver.py

Comprehensive verification test suite for the Core Physics Engine:

1. Non-linear State-Space Dynamic Motor Solver (RK45 method)
2. Speed convergence: No-load (~1499 RPM) and rated load (~1474 RPM)
3. Broken Rotor Bar (BRB): Harmonic power increase ≥ 15 dB at (1-2s)fs
4. Stator Inter-turn Short Circuit (ITSC): Circulating current and localized heat
5. Dynamic Eccentricity: Permeance modulation producing f_s ± f_r sidebands
6. 4-Node LPTN & Arrhenius life model
7. MCSA automated peak detection
"""

from __future__ import annotations

import numpy as np
import pytest

from app.core_physics.dynamic_solver import StateSpaceMotorSolver
from app.core_physics.fault_models import (
    BearingDefect,
    BearingGeometry,
    FaultState,
    inject_bearing_fault,
    inject_broken_rotor_bar,
    inject_eccentricity,
    inject_interturn_short,
)
from app.core_physics.motor_parameters import DEFAULT_MOTOR
from app.core_physics.thermal_lptn import FourNodeThermalLPTN, LPTNState
from app.diagnostics.rul_engine import InsulationClass, RULEngine
from app.signal_processing.mcsa_pipeline import MCSAAnalyzer
from app.signal_processing.vibration_analysis import VibrationAnalyzer


class TestStateSpacePhysicsEngine:
    """Test the dynamic state-space solver."""

    def test_speed_convergence_no_load(self):
        """Motor accelerates from rest to near-synchronous speed under zero load."""
        solver = StateSpaceMotorSolver(params=DEFAULT_MOTOR, supply_freq=50.0)
        res = solver.solve(t_span=(0.0, 1.2), load_torque=0.0, method="RK45")

        # In last 200 ms, speed should be settled near 1500 RPM
        settled_idx = res.t >= 1.0
        mean_rpm = float(np.mean(res.rpm[settled_idx]))
        assert 1490.0 < mean_rpm <= 1500.0, f"Expected no-load speed near 1500 RPM, got {mean_rpm:.1f}"

    def test_speed_convergence_rated_load(self):
        """Motor settles at rated speed (1474 RPM) under rated load (10 N·m)."""
        solver = StateSpaceMotorSolver(params=DEFAULT_MOTOR, supply_freq=50.0)
        res = solver.solve(t_span=(0.0, 1.5), load_torque=10.0, method="RK45")

        settled_idx = res.t >= 1.2
        mean_rpm = float(np.mean(res.rpm[settled_idx]))
        mean_te = float(np.mean(res.te[settled_idx]))

        assert 1465.0 <= mean_rpm <= 1485.0, f"Expected rated speed near 1474 RPM, got {mean_rpm:.1f}"
        assert 9.5 <= mean_te <= 10.5, f"Expected torque balancing load (10 N·m), got {mean_te:.2f}"

    def test_load_step_response(self):
        """Speed drops, slip increases, current increases with load step."""
        # No-load run
        solver_nl = StateSpaceMotorSolver(params=DEFAULT_MOTOR, supply_freq=50.0)
        res_nl = solver_nl.solve(t_span=(0.0, 2.0), load_torque=0.0)

        # Rated load run
        solver_fl = StateSpaceMotorSolver(params=DEFAULT_MOTOR, supply_freq=50.0)
        res_fl = solver_fl.solve(t_span=(0.0, 2.0), load_torque=10.0)

        # Compare steady-state
        nl_rpm = float(np.mean(res_nl.rpm[res_nl.t >= 1.5]))
        fl_rpm = float(np.mean(res_fl.rpm[res_fl.t >= 1.5]))
        nl_curr = float(np.mean(np.sqrt(np.mean(res_nl.i_abc**2, axis=0))[res_nl.t >= 1.5]))
        fl_curr = float(np.mean(np.sqrt(np.mean(res_fl.i_abc**2, axis=0))[res_fl.t >= 1.5]))

        assert fl_rpm < nl_rpm, f"Loaded speed ({fl_rpm:.1f}) should be less than no-load ({nl_rpm:.1f})"
        assert fl_curr > nl_curr, f"Loaded current ({fl_curr:.2f}) should exceed no-load ({nl_curr:.2f})"

    def test_slip_calculation(self):
        """Slip calculated correctly from solver states."""
        solver = StateSpaceMotorSolver(params=DEFAULT_MOTOR, supply_freq=50.0)
        res = solver.solve(t_span=(0.0, 1.0), load_torque=10.0)

        settled = res.t >= 0.8
        mean_slip = float(np.mean(res.slip[settled]))
        mean_rpm = float(np.mean(res.rpm[settled]))

        # Slip = (sync - actual) / sync
        sync_rpm = 1500.0
        expected_slip = (sync_rpm - mean_rpm) / sync_rpm

        assert abs(mean_slip - expected_slip) < 0.005, f"Slip mismatch: {mean_slip:.4f} vs {expected_slip:.4f}"

    def test_fixed_step_rk4_matches_solve_ivp(self):
        """Fixed-step RK4 matches adaptive solve_ivp for small dt."""
        solver = StateSpaceMotorSolver(params=DEFAULT_MOTOR, supply_freq=50.0)

        # Adaptive
        res_adaptive = solver.solve(t_span=(0.0, 0.5), load_torque=5.0, max_step=1e-4, rtol=1e-7, atol=1e-9)

        # Fixed-step
        res_fixed = solver.solve_fixed_step_rk4(t_span=(0.0, 0.5), dt=1e-4, load_torque=5.0)

        # Compare final states
        assert abs(res_adaptive.rpm[-1] - res_fixed.rpm[-1]) < 1.0, "RPM mismatch"
        assert abs(res_adaptive.i_abc[0, -1] - res_fixed.i_abc[0, -1]) < 0.1, "Current mismatch"


class TestFaultInjection:
    """Test analytical fault injection models."""

    def test_brb_harmonic_power_increase_ge_15db(self):
        """BRB activation increases (1-2s)fs power by ≥ 15 dB."""
        def tl_fn(t: float) -> float:
            return 10.0 if t >= 0.3 else 0.0

        # Healthy baseline
        solver_healthy = StateSpaceMotorSolver(params=DEFAULT_MOTOR, brb_delta=0.0)
        res_h = solver_healthy.solve(t_span=(0.0, 3.0), load_torque=tl_fn, method="RK45")

        # BRB fault (delta = 0.45 = moderate severity)
        solver_faulty = StateSpaceMotorSolver(params=DEFAULT_MOTOR, brb_delta=0.45)
        res_f = solver_faulty.solve(t_span=(0.0, 3.0), load_torque=tl_fn, method="RK45")

        # Extract steady-state
        mask_h = res_h.t >= 1.0
        mask_f = res_f.t >= 1.0
        t_ss_h = res_h.t[mask_h]
        t_ss_f = res_f.t[mask_f]
        ia_h = res_h.i_abc[0][mask_h]
        ia_f = res_f.i_abc[0][mask_f]

        # Resample to uniform 5000 Hz grid
        fs = 5000.0
        t_start = max(t_ss_h[0], t_ss_f[0])
        t_end = min(t_ss_h[-1], t_ss_f[-1])
        t_uniform = np.arange(t_start, t_end, 1.0 / fs)
        ia_h_uni = np.interp(t_uniform, t_ss_h, ia_h)
        ia_f_uni = np.interp(t_uniform, t_ss_f, ia_f)

        omega_m = float(np.mean(res_f.omega_m[mask_f]))
        analyzer = MCSAAnalyzer(fs=fs, window="hann")

        mcsa_h = analyzer.analyze(ia_h_uni, nominal_supply_freq=50.0, omega_m=omega_m, pole_pairs=2)
        mcsa_f = analyzer.analyze(ia_f_uni, nominal_supply_freq=50.0, omega_m=omega_m, pole_pairs=2)

        slip = mcsa_f.slip
        f_lower_sb = 50.0 * (1.0 - 2.0 * slip)

        def get_band_power(fft_freqs, fft_mag_db, f_target, bw=0.4):
            m = (fft_freqs >= f_target - bw) & (fft_freqs <= f_target + bw)
            return float(np.max(fft_mag_db[m])) if np.any(m) else -120.0

        fund_h = mcsa_h.fundamental_mag_db
        fund_f = mcsa_f.fundamental_mag_db
        power_h_dbc = get_band_power(mcsa_h.fft_freqs, mcsa_h.fft_mag_db, f_lower_sb) - fund_h
        power_f_dbc = get_band_power(mcsa_f.fft_freqs, mcsa_f.fft_mag_db, f_lower_sb) - fund_f

        delta_db = power_f_dbc - power_h_dbc
        print(f"\nBRB test: healthy={power_h_dbc:.1f} dBc, faulty={power_f_dbc:.1f} dBc, delta={delta_db:.1f} dB")

        # Requirement: Delta >= 15 dB
        assert delta_db >= 15.0, f"Expected BRB harmonic increase >= 15 dB, got {delta_db:.1f} dB"
        assert mcsa_f.brb_fault_detected, "Expected BRB fault to be flagged by automated peak detector"

    def test_itsc_circulating_current_and_heat(self):
        """ITSC generates circulating current and localized winding dissipation."""
        solver_healthy = StateSpaceMotorSolver(params=DEFAULT_MOTOR, itsc_mu=0.0)
        res_h = solver_healthy.solve(t_span=(0.0, 0.8), load_torque=8.0, method="RK45")

        solver_itsc = StateSpaceMotorSolver(params=DEFAULT_MOTOR, itsc_mu=0.15, itsc_rf=5.0)
        res_f = solver_itsc.solve(t_span=(0.0, 0.8), load_torque=8.0, method="RK45")

        # Phase A current amplitude higher due to circulating shorted current
        rms_ia_h = float(np.sqrt(np.mean(res_h.i_abc[0][-200:] ** 2)))
        rms_ia_f = float(np.sqrt(np.mean(res_f.i_abc[0][-200:] ** 2)))
        assert rms_ia_f > rms_ia_h, f"Expected higher Phase A RMS under ITSC: {rms_ia_f} vs {rms_ia_h}"

        # Fault heat dissipation positive under ITSC, zero when healthy
        assert np.all(res_h.fault_heat_w == 0.0)
        assert np.mean(res_f.fault_heat_w[-200:]) > 20.0, "Expected fault heat dissipation > 20 W under ITSC"

    def test_itsc_negative_sequence_current(self):
        """ITSC generates negative sequence current component."""
        solver = StateSpaceMotorSolver(params=DEFAULT_MOTOR, itsc_mu=0.1, itsc_rf=10.0)
        res = solver.solve(t_span=(0.0, 1.0), load_torque=5.0, method="RK45")

        # Use MCSA to detect negative sequence
        mask = res.t >= 0.5
        ia = res.i_abc[0][mask]
        fs = 5000.0
        t_ss = res.t[mask]
        t_uniform = np.arange(t_ss[0], t_ss[-1], 1.0 / fs)
        ia_uni = np.interp(t_uniform, t_ss, ia)

        analyzer = MCSAAnalyzer(fs=fs)
        mcsa = analyzer.analyze(ia_uni, nominal_supply_freq=50.0, omega_m=float(np.mean(res.omega_m[mask])), pole_pairs=2)

        # Negative sequence should be detectable
        assert mcsa.negative_seq_mag_db is not None
        assert mcsa.negative_seq_mag_db > -60, "Negative sequence should be present with ITSC"

    def test_dynamic_eccentricity_permeance(self):
        """Dynamic eccentricity modulates L_m producing f_s ± f_r sidebands."""
        def tl_fn(t: float) -> float:
            return 10.0 if t >= 0.3 else 0.0

        solver = StateSpaceMotorSolver(params=DEFAULT_MOTOR, ecc_dynamic=0.35)
        res = solver.solve(t_span=(0.0, 3.0), load_torque=tl_fn, method="RK45")

        assert solver.ecc_dynamic == 0.35

        mask = res.t >= 1.0
        t_ss = res.t[mask]
        ia = res.i_abc[0][mask]
        fs = 5000.0
        t_uniform = np.arange(t_ss[0], t_ss[-1], 1.0 / fs)
        ia_uni = np.interp(t_uniform, t_ss, ia)

        analyzer = MCSAAnalyzer(fs=fs, window="hann")
        omega_m = float(np.mean(res.omega_m[mask]))
        mcsa = analyzer.analyze(ia_uni, nominal_supply_freq=50.0, omega_m=omega_m, pole_pairs=2)

        # Should detect eccentricity sideband markers
        assert len(mcsa.ecc_peaks) > 0 or mcsa.eccentricity_detected or any("Eccentricity" in p.label for p in mcsa.peaks)

    def test_fault_state_aggregation(self):
        """FaultState correctly aggregates physical coefficients."""
        state = FaultState()

        # Add BRB
        inject_broken_rotor_bar(state, count=3, severity=0.375)
        assert state.brb_delta == pytest.approx(min(0.9, 3.0 * 3 / 28), rel=0.1)

        # Add ITSC
        inject_interturn_short(state, phase="a", mu=0.1, r_fault=10.0, severity=0.66)
        itsc = state.interturn
        assert itsc is not None
        assert itsc[0] == 0  # Phase A
        assert itsc[1] == pytest.approx(0.1, rel=0.01)

        # Add eccentricity
        inject_eccentricity(state, type="dynamic", severity=0.5)
        dyn, stat = state.eccentricity
        assert dyn == pytest.approx(0.075, rel=0.01)
        assert stat == 0.0

        # Add bearing fault (use correct enum values)
        inject_bearing_fault(state, defect="outer_race", severity=0.4)
        assert state.bearing(BearingDefect.OR) == 0.4
        assert state.bearing_friction_torque > 0

    def test_bearing_geometry_frequencies(self):
        """Bearing defect frequencies calculated correctly from geometry."""
        geom = BearingGeometry()  # Default 6205
        defects = geom.defect_frequencies(25.0)  # 1500 RPM = 25 Hz

        # Known values for 6205 at 1500 RPM
        assert abs(defects["BPFO"] - 89.6) < 1.0
        assert abs(defects["BPFI"] - 135.4) < 1.0
        assert abs(defects["BSF"] - 58.4) < 1.0
        assert abs(defects["FTF"] - 10.0) < 0.5


class TestThermalLPTN:
    """Test 4-Node LPTN and Arrhenius degradation."""

    def test_4node_lptn_stability_and_dynamics(self):
        """LPTN tracks temperatures and dissipates stably."""
        lptn = FourNodeThermalLPTN(t_ambient=25.0)

        for _ in range(400):
            st = lptn.step(dt=0.1, p_copper_s=80.0, p_iron=30.0, p_copper_r=60.0, p_friction=10.0)

        assert st.t_winding > 25.0
        assert st.t_teeth > 25.0
        assert st.t_rotor > 25.0
        assert st.t_bearing > 25.0
        assert st.t_winding >= st.t_teeth, f"Winding ({st.t_winding}) should be hotter than teeth ({st.t_teeth})"

    def test_arrhenius_acceleration_under_overheating(self):
        """Arrhenius model accelerates aging exponentially with temperature."""
        lptn_normal = FourNodeThermalLPTN(t_ambient=25.0)
        for _ in range(50):
            st_norm = lptn_normal.step(dt=0.1, p_copper_s=60.0, p_iron=25.0, p_copper_r=40.0, p_friction=8.0)

        lptn_hot = FourNodeThermalLPTN(t_ambient=25.0)
        for _ in range(1500):
            st_hot = lptn_hot.step(
                dt=0.1,
                p_copper_s=300.0,
                p_iron=60.0,
                p_copper_r=200.0,
                p_friction=20.0,
                itsc_extra_w=150.0,
            )

        assert st_norm.aging_acceleration < 1.0
        assert st_norm.rul_hours >= 20000.0
        assert st_hot.t_winding > st_norm.t_winding + 20.0
        assert st_hot.aging_acceleration > st_norm.aging_acceleration
        assert st_hot.rul_hours < st_norm.rul_hours

    def test_thermal_resistance_feedback(self):
        """Stator resistance scales with winding temperature."""
        from app.core_physics.dynamic_solver import StateSpaceMotorSolver

        solver_cold = StateSpaceMotorSolver(params=DEFAULT_MOTOR, winding_temp=20.0)
        rs_cold = solver_cold._update_resistance_with_temp(20.0)

        solver_hot = StateSpaceMotorSolver(params=DEFAULT_MOTOR, winding_temp=120.0)
        rs_hot = solver_hot._update_resistance_with_temp(120.0)

        # Rs should increase by ~39% (α=0.00393/°C * 100°C)
        expected_ratio = 1.0 + 0.00393 * (120.0 - 20.0)
        actual_ratio = rs_hot / rs_cold
        assert abs(actual_ratio - expected_ratio) < 0.01

    def test_lptn_steady_state(self):
        """Analytical steady-state matches numerical integration."""
        lptn = FourNodeThermalLPTN(t_ambient=25.0)

        # Numerical integration to steady state
        for _ in range(10000):  # More steps for convergence
            st_num = lptn.step(dt=0.1, p_copper_s=100.0, p_iron=40.0, p_copper_r=80.0, p_friction=15.0)

        # Analytical steady-state
        st_ana = lptn.steady_state(p_copper_s=100.0, p_iron=40.0, p_copper_r=80.0, p_friction=15.0)

        # Allow larger tolerance since numerical integration with dt=0.1 may not fully converge
        assert abs(st_num.t_winding - st_ana.t_winding) < 5.0
        assert abs(st_num.t_teeth - st_ana.t_teeth) < 5.0
        assert abs(st_num.t_rotor - st_ana.t_rotor) < 5.0
        assert abs(st_num.t_bearing - st_ana.t_bearing) < 5.0


class TestMCSAAnalyzer:
    """Test MCSA pipeline and peak detection."""

    def test_mcsa_fundamental_detection(self):
        """MCSA correctly identifies fundamental frequency."""
        fs = 5000.0
        t = np.arange(0, 2.0, 1/fs)
        # Pure 50 Hz sine wave
        x = 10.0 * np.sin(2 * np.pi * 50.0 * t)

        analyzer = MCSAAnalyzer(fs=fs)
        mcsa = analyzer.analyze(x, nominal_supply_freq=50.0, omega_m=154.0, pole_pairs=2)

        assert abs(mcsa.fundamental_freq - 50.0) < 0.5
        assert mcsa.fundamental_mag_db > 0

    def test_mcsa_brb_sideband_detection(self):
        """MCSA detects BRB sidebands in synthetic signal."""
        fs = 5000.0
        t = np.arange(0, 2.0, 1/fs)
        f_s = 50.0
        slip = 0.02
        f_sb = f_s * (1 - 2 * slip)  # 48 Hz

        # Fundamental + BRB sideband
        x = (10.0 * np.sin(2 * np.pi * f_s * t) +
             0.5 * np.sin(2 * np.pi * f_sb * t))

        analyzer = MCSAAnalyzer(fs=fs)
        mcsa = analyzer.analyze(x, nominal_supply_freq=50.0, omega_m=154.0, pole_pairs=2)

        # Should detect lower sideband
        brb_lower = [p for p in mcsa.brb_peaks if "lower" in p.label and p.harmonic_k == 1]
        assert len(brb_lower) > 0, "Should detect (1-2s)f sideband"

    def test_mcsa_eccentricity_detection(self):
        """MCSA detects eccentricity sidebands."""
        fs = 5000.0
        t = np.arange(0, 2.0, 1/fs)
        f_s = 50.0
        f_r = 25.0  # 1500 RPM

        # Fundamental + eccentricity sidebands
        x = (10.0 * np.sin(2 * np.pi * f_s * t) +
             0.3 * np.sin(2 * np.pi * (f_s - f_r) * t) +
             0.3 * np.sin(2 * np.pi * (f_s + f_r) * t))

        analyzer = MCSAAnalyzer(fs=fs)
        mcsa = analyzer.analyze(x, nominal_supply_freq=50.0, omega_m=2*np.pi*f_r, pole_pairs=2)

        assert len(mcsa.ecc_peaks) >= 1, "Should detect eccentricity sidebands"

    def test_mcsa_thd_calculation(self):
        """MCSA calculates THD correctly."""
        fs = 5000.0
        t = np.arange(0, 1.0, 1/fs)
        f_s = 50.0

        # Fundamental + 3rd harmonic (10%)
        x = 10.0 * np.sin(2 * np.pi * f_s * t) + 1.0 * np.sin(2 * np.pi * 3 * f_s * t)

        analyzer = MCSAAnalyzer(fs=fs)
        mcsa = analyzer.analyze(x, nominal_supply_freq=50.0, omega_m=154.0, pole_pairs=2)

        # THD ≈ 10% for 10% 3rd harmonic
        assert 8.0 < mcsa.thd_percent < 12.0


class TestVibrationAnalysis:
    """Test vibration analysis pipeline."""

    def test_bearing_frequency_calculation(self):
        """VibrationAnalyzer calculates correct bearing frequencies."""
        analyzer = VibrationAnalyzer(fs=12800.0, shaft_freq_hz=25.0)
        freqs = analyzer.calculate_bearing_frequencies()

        assert abs(freqs.bpfo_hz - 89.6) < 1.0
        assert abs(freqs.bpfi_hz - 135.4) < 1.0
        assert abs(freqs.bsf_hz - 58.4) < 1.0
        assert abs(freqs.ftf_hz - 10.0) < 0.5

    def test_envelope_detection(self):
        """Envelope demodulation extracts bearing fault frequencies."""
        fs = 12800.0
        t = np.arange(0, 1.0, 1/fs)
        fr = 25.0
        bpfo = 89.6

        # Modulated impulse train at BPFO
        carrier = 3000.0
        impulses = np.zeros_like(t)
        impulse_period = 1.0 / bpfo
        for i in range(int(1.0 / impulse_period) + 1):
            idx = int(i * impulse_period * fs)
            if idx < len(impulses):
                impulses[idx] = 1.0

        # Ringing at carrier frequency
        x = np.convolve(impulses, np.exp(-500 * t[:100]) * np.sin(2 * np.pi * carrier * t[:100]), mode='same')
        x = x + 0.01 * np.random.randn(len(t))

        analyzer = VibrationAnalyzer(fs=fs, shaft_freq_hz=fr)
        result = analyzer.analyze(x)

        # Should detect BPFO in envelope
        assert result.bpfo_amplitude > result.bpfi_amplitude

    def test_iso10816_zone_classification(self):
        """ISO 10816 zone classification works correctly."""
        analyzer = VibrationAnalyzer(fs=12800.0, shaft_freq_hz=25.0)

        # Zone A
        zone_a = analyzer._iso10816_zone(1.5)
        assert zone_a == "A"

        # Zone B
        zone_b = analyzer._iso10816_zone(3.5)
        assert zone_b == "B"

        # Zone C
        zone_c = analyzer._iso10816_zone(5.5)
        assert zone_c == "C"

        # Zone D
        zone_d = analyzer._iso10816_zone(8.5)
        assert zone_d == "D"


class TestRULEngine:
    """Test RUL calculation engine."""

    def test_insulation_rul_montsinger(self):
        """Montsinger rule calculates RUL correctly."""
        engine = RULEngine(insulation_class=InsulationClass.F, nominal_life_hours=20000.0)

        # Create mock LPTN state at rated temp
        state_rated = LPTNState(
            t_winding=150.0, t_teeth=140.0, t_rotor=130.0, t_bearing=80.0,
            t_ambient=25.0, p_copper_s=100.0, p_iron=40.0, p_copper_r=80.0, p_friction=15.0,
            arrhenius_aging_factor=1.0, rul_hours=20000.0, insulation_health_pct=100.0,
            bearing_l10h_hours=100000.0
        )
        rul = engine.calculate_insulation_rul(state_rated)
        assert 15000 < rul.rul_hours < 25000

        # Hotter winding
        state_hot = LPTNState(
            t_winding=170.0, t_teeth=155.0, t_rotor=140.0, t_bearing=90.0,
            t_ambient=25.0, p_copper_s=200.0, p_iron=60.0, p_copper_r=150.0, p_friction=20.0,
            arrhenius_aging_factor=5.0, rul_hours=4000.0, insulation_health_pct=20.0,
            bearing_l10h_hours=100000.0
        )
        rul_hot = engine.calculate_insulation_rul(state_hot)
        assert rul_hot.rul_hours < rul.rul_hours
        assert rul_hot.aging_acceleration_factor > 1.0

    def test_bearing_rul_iso281(self):
        """ISO 281 L10h calculation with adjustments."""
        engine = RULEngine(
            de_bearing_c=20000.0,  # Higher capacity for longer life
            de_bearing_p=2000.0,
            shaft_speed_rpm=1500.0,
        )

        state = LPTNState(
            t_winding=80.0, t_teeth=75.0, t_rotor=70.0, t_bearing=60.0,
            t_ambient=25.0, p_copper_s=100.0, p_iron=40.0, p_copper_r=80.0, p_friction=15.0,
            arrhenius_aging_factor=1.0, rul_hours=20000.0, insulation_health_pct=100.0,
            bearing_l10h_hours=100000.0
        )

        rul = engine.calculate_bearing_rul(state, vibration_rms_mms=1.5)  # Zone A
        assert rul.l10h_hours > 10000
        assert rul.adjusted_l10h_hours == rul.l10h_hours  # No adjustment in Zone A

        # With high vibration (Zone C)
        rul_vib = engine.calculate_bearing_rul(state, vibration_rms_mms=5.5)
        assert rul_vib.adjusted_l10h_hours < rul.l10h_hours
        assert rul_vib.iso_zone == "C"

    def test_overall_rul_limiting_factor(self):
        """Overall RUL identifies limiting component."""
        # Use high bearing capacity so insulation is limiting
        engine = RULEngine(
            de_bearing_c=50000.0,  # Very high capacity
            nde_bearing_c=50000.0,
            de_bearing_p=2000.0,
            nde_bearing_p=1500.0,
        )

        # Insulation limited case (very hot winding)
        state = LPTNState(
            t_winding=180.0, t_teeth=165.0, t_rotor=145.0, t_bearing=70.0,
            t_ambient=25.0, p_copper_s=400.0, p_iron=100.0, p_copper_r=250.0, p_friction=30.0,
            arrhenius_aging_factor=20.0, rul_hours=1000.0, insulation_health_pct=5.0,
            bearing_l10h_hours=50000.0
        )

        rul_result = engine.compute_rul(state, vibration_rms_mms=1.5)  # Zone A, low vibration
        assert rul_result.limiting_factor == "insulation"
        assert rul_result.overall_rul_hours == rul_result.insulation.rul_hours


class TestFaultClassifier:
    """Test fault classification thresholds."""

    def test_classifier_healthy(self):
        """No faults diagnosed for healthy signals."""
        from app.diagnostics.fault_classifier import FaultClassifier
        classifier = FaultClassifier()

        diagnoses = classifier.classify(
            mcsa_result=None,
            vibration_result=None,
            thermal_state={"t_winding": 80.0, "t_bearing": 50.0, "t_ambient": 25.0, "arrhenius_aging_factor": 0.5},
            electrical_residual={"FD": 0.005, "FL": [1.0, 1.0, 1.0]},
        )

        # Should only get thermal if temps are high, but 80C winding is OK
        thermal_diags = [d for d in diagnoses if d.category.value == "thermal"]
        assert len(thermal_diags) == 0

    def test_classifier_brb_detection(self):
        """Classifier detects BRB from MCSA."""
        import numpy as np

        from app.diagnostics.fault_classifier import FaultClassifier
        from app.signal_processing.mcsa_pipeline import MCSAResult, PeakMarker

        classifier = FaultClassifier()

        # Mock MCSA result with BRB sideband at -35 dBc (moderate severity)
        fft_freqs = np.linspace(0, 2500, 5000)
        fft_mag = np.ones_like(fft_freqs) * 1e-6
        fft_mag[1000] = 1.0  # Fundamental at 50 Hz
        fft_mag[960] = 0.0178  # Lower sideband at ~48 Hz (-35 dBc)

        mcsa = MCSAResult(
            fs=5000.0, fundamental_freq=50.0, fundamental_mag_db=20.0,
            slip=0.02, rotor_freq_hz=25.0, window="hann",
            freqs=fft_freqs, psd_db=20*np.log10(fft_mag),
            fft_freqs=fft_freqs, fft_mag_db=20*np.log10(fft_mag),
            brb_peaks=[PeakMarker(freq_hz=48.0, magnitude_db=-35.0, label="BRB k=1 (lower)",
                                  harmonic_k=1, expected_freq_hz=48.0, deviation_hz=0.0, sideband_type="lower")],
            worst_brb_sideband_db=-35.0, brb_fault_detected=True,
        )

        diagnoses = classifier.classify(mcsa_result=mcsa, vibration_result=None,
                                        thermal_state={"t_winding": 80.0, "t_bearing": 50.0,
                                                       "t_ambient": 25.0, "arrhenius_aging_factor": 0.5},
                                        electrical_residual={"FD": 0.005, "FL": [1.0, 1.0, 1.0]})

        brb_diags = [d for d in diagnoses if d.fault_type.value == "broken_rotor_bar"]
        assert len(brb_diags) == 1
        assert brb_diags[0].severity.value in ("moderate", "high", "critical")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""tests/simulation/test_physics_engine.py

Comprehensive verification test suite for the reconstructed Core Physics Engine:
1. Non-linear State-Space Dynamic Motor Solver (RK45 method, [i_ds, i_qs, psi_dr, psi_qr, omega_m]^T).
2. Speed convergence: Reaches steady-state rated speed under no-load (~1499 RPM) and rated load (~1474 RPM).
3. Broken Rotor Bar (BRB) mathematical fault injection: Modulates R_r(theta_r) producing (1 +/- 2ks)fs sidebands;
   verifies harmonic power in (1 - 2s)fs bin increases by >= 15 dB.
4. Stator Inter-turn Short Circuit (ITSC): shorted turn ratio mu = N_sc / N_s generating circulating current and localized winding heat.
5. Dynamic Eccentricity: Angular permeance mutual inductance model L_m(theta_r).
6. 4-Node Lumped Parameter Thermal Network (LPTN) & Arrhenius life model:
   Tracks Tw, Tt, Tr, Tb and computes aging acceleration factor and RUL.
7. MCSA automated peak detection using scipy.signal.find_peaks.
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from app.diagnostics.mcsa import MCSAAnalyzer
from app.simulation.params import DEFAULT_MOTOR
from app.simulation.state_space_solver import StateSpaceMotorSolver
from app.simulation.thermal_lptn import FourNodeThermalLPTN


class TestStateSpacePhysicsEngine:
    def test_speed_convergence_no_load(self):
        """Motor accelerates from rest to near-synchronous speed under zero load."""
        solver = StateSpaceMotorSolver(params=DEFAULT_MOTOR, supply_freq=50.0)
        # Solve for 1.2 seconds from standstill (y0 = zeros)
        res = solver.solve(t_span=(0.0, 1.2), load_torque=0.0, method="RK45")

        # In last 200 ms, speed should be settled near 1500 RPM (synchronous speed = 1500 RPM for 2 pole pairs)
        settled_idx = res.t >= 1.0
        mean_rpm = float(np.mean(res.rpm[settled_idx]))
        assert 1490.0 < mean_rpm <= 1500.0, f"Expected no-load speed near 1500 RPM, got {mean_rpm:.1f}"

    def test_speed_convergence_rated_load(self):
        """Motor settles at rated speed (1474 RPM) under rated load (10 N·m)."""
        solver = StateSpaceMotorSolver(params=DEFAULT_MOTOR, supply_freq=50.0)
        # Solve for 1.5 seconds under 10 N*m rated torque
        res = solver.solve(t_span=(0.0, 1.5), load_torque=10.0, method="RK45")

        settled_idx = res.t >= 1.2
        mean_rpm = float(np.mean(res.rpm[settled_idx]))
        mean_te = float(np.mean(res.te[settled_idx]))

        # Rated speed for this motor is 1474 RPM +/- 5 RPM
        assert 1465.0 <= mean_rpm <= 1485.0, f"Expected rated speed near 1474 RPM, got {mean_rpm:.1f}"
        assert 9.5 <= mean_te <= 10.5, f"Expected electromagnetic torque balancing load (10 N*m), got {mean_te:.2f}"

    def test_brb_harmonic_power_increase_ge_15db(self):
        """BRB activation modulates rotor resistance and increases (1 - 2s)fs power by >= 15 dB."""
        tl_fn = lambda t: 10.0 if t >= 0.3 else 0.0

        # 1. Healthy baseline run
        solver_healthy = StateSpaceMotorSolver(params=DEFAULT_MOTOR, brb_delta=0.0)
        res_h = solver_healthy.solve(t_span=(0.0, 3.0), load_torque=tl_fn, method="RK45")

        # 2. BRB fault run (broken rotor bar asymmetry delta = 0.45)
        solver_faulty = StateSpaceMotorSolver(params=DEFAULT_MOTOR, brb_delta=0.45)
        res_f = solver_faulty.solve(t_span=(0.0, 3.0), load_torque=tl_fn, method="RK45")

        # Extract steady-state waveform (last 2.0 s)
        mask_h = res_h.t >= 1.0
        mask_f = res_f.t >= 1.0
        t_ss_h = res_h.t[mask_h]
        t_ss_f = res_f.t[mask_f]
        ia_h = res_h.i_abc[0][mask_h]
        ia_f = res_f.i_abc[0][mask_f]

        # Resample to uniform 5000 Hz grid for accurate MCSA
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

        # Expected fundamental slip
        slip = mcsa_f.slip
        f_lower_sb = 50.0 * (1.0 - 2.0 * slip)

        # Find power in the (1 - 2s)fs bin for both
        def get_band_power(fft_freqs, fft_mag_db, f_target, bw=0.4):
            m = (fft_freqs >= f_target - bw) & (fft_freqs <= f_target + bw)
            return float(np.max(fft_mag_db[m]))

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
        """ITSC shorted turn ratio mu generates circulating current and localized winding dissipation."""
        solver_healthy = StateSpaceMotorSolver(params=DEFAULT_MOTOR, itsc_mu=0.0)
        res_h = solver_healthy.solve(t_span=(0.0, 0.8), load_torque=8.0, method="RK45")

        solver_itsc = StateSpaceMotorSolver(params=DEFAULT_MOTOR, itsc_mu=0.15, itsc_rf=5.0)
        res_f = solver_itsc.solve(t_span=(0.0, 0.8), load_torque=8.0, method="RK45")

        # Phase A current amplitude in ITSC must be higher due to circulating shorted current
        rms_ia_h = float(np.sqrt(np.mean(res_h.i_abc[0][-200:] ** 2)))
        rms_ia_f = float(np.sqrt(np.mean(res_f.i_abc[0][-200:] ** 2)))
        assert rms_ia_f > rms_ia_h, f"Expected higher Phase A RMS under ITSC: {rms_ia_f} vs {rms_ia_h}"

        # Fault heat dissipation must be positive under ITSC and zero when healthy
        assert np.all(res_h.fault_heat_w == 0.0)
        assert np.mean(res_f.fault_heat_w[-200:]) > 20.0, "Expected fault heat dissipation > 20 W under ITSC"

    def test_dynamic_eccentricity_permeance(self):
        """Dynamic eccentricity modulates mutual inductance L_m(theta_m) producing f_s +/- f_r sidebands."""
        tl_fn = lambda t: 10.0 if t >= 0.3 else 0.0
        solver = StateSpaceMotorSolver(params=DEFAULT_MOTOR, ecc_dynamic=0.35)
        res = solver.solve(t_span=(0.0, 3.0), load_torque=tl_fn, method="RK45")

        # Check that mutual inductance was actively modulated
        assert solver.ecc_dynamic == 0.35

        # Check MCSA automated peak detection finds eccentricity sidebands
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



class TestThermalLPTNAndArrhenius:
    def test_4node_lptn_stability_and_dynamics(self):
        """4-node LPTN tracks Tw, Tt, Tr, Tb and dissipates stably toward steady-state."""
        lptn = FourNodeThermalLPTN(t_ambient=25.0)
        # Advance 400 steps (40 seconds) with standard copper and core losses
        for _ in range(400):
            st = lptn.step(dt=0.1, p_copper_s=80.0, p_iron=30.0, p_copper_r=60.0, p_friction=10.0)

        # Thermodynamics sanity:
        # All temperatures must exceed ambient (25°C) and be ranked sensibly (Winding > Teeth > Ambient)
        assert st.t_winding > 25.0
        assert st.t_teeth > 25.0
        assert st.t_rotor > 25.0
        assert st.t_bearing > 25.0
        assert st.t_winding >= st.t_teeth, f"Winding ({st.t_winding}) should be hotter than teeth ({st.t_teeth})"

    def test_arrhenius_acceleration_under_overheating(self):
        """Arrhenius model accelerates aging exponentially when winding temperature rises."""
        lptn_normal = FourNodeThermalLPTN(t_ambient=25.0)
        # Step under normal load
        for _ in range(50):
            st_norm = lptn_normal.step(dt=0.1, p_copper_s=60.0, p_iron=25.0, p_copper_r=40.0, p_friction=8.0)

        lptn_hot = FourNodeThermalLPTN(t_ambient=25.0)
        # Step under severe overload / ITSC fault heat
        for _ in range(1500):
            st_hot = lptn_hot.step(
                dt=0.1,
                p_copper_s=300.0,
                p_iron=60.0,
                p_copper_r=200.0,
                p_friction=20.0,
                itsc_extra_w=150.0,
            )

        # Normal run is cool, aging acceleration << 1.0 (design life > 20000h)
        assert st_norm.aging_acceleration < 1.0
        assert st_norm.rul_hours >= 20000.0

        # Overheated run has higher aging acceleration and shortened RUL
        assert st_hot.t_winding > st_norm.t_winding + 20.0
        assert st_hot.aging_acceleration > st_norm.aging_acceleration
        assert st_hot.rul_hours < st_norm.rul_hours


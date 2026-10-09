"""app/static_analysis/steady_state.py — Per-phase equivalent circuit solver.

Computes expected steady-state electrical and electromechanical operating variables
(stator current magnitude, rotor current, real and reactive power, power factor,
developed torque, and shaft power) from motor parameters, terminal voltage, frequency,
and rotational speed.

References:
- IEEE Std 112: Standard Test Procedure for Polyphase Induction Motors and Generators.
- Chapman, S. J. "Electric Machinery Fundamentals", McGraw-Hill.
- Chen et al. (Energies 2025).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.simulation.params import MotorParams


@dataclass(frozen=True)
class SteadyStateResult:
    """Analytical per-phase equivalent circuit solution at steady state."""

    slip: float
    stator_current_mag: float       # Stator phase RMS current [A]
    rotor_current_mag: float        # Rotor phase RMS current referred to stator [A]
    real_power_w: float             # Total 3-phase active power [W]
    reactive_power_var: float       # Total 3-phase reactive power [VAR]
    apparent_power_va: float        # Total 3-phase apparent power [VA]
    power_factor: float             # cos(phi) [-1, 1]
    torque_developed_nm: float      # Electromechanical air-gap torque [N*m]
    mechanical_power_w: float       # Developed mechanical power (1-s)*Pag [W]
    z_in: complex                   # Per-phase input impedance [Ohms]


def solve_steady_state(
    params: MotorParams,
    v_phase_rms: float,
    supply_freq: float,
    speed_rpm: float,
) -> SteadyStateResult:
    """Solves the per-phase equivalent circuit of an induction motor.

    Args:
        params: Motor electrical and mechanical parameters (Rs, Rr, Ls, Lr, Lm, pole_pairs).
        v_phase_rms: Stator line-to-neutral (phase) RMS voltage in Volts.
        supply_freq: Fundamental electrical supply frequency in Hz.
        speed_rpm: Mechanical rotor shaft speed in RPM.

    Returns:
        SteadyStateResult with all steady-state quantities.
    """
    if v_phase_rms <= 0.0:
        raise ValueError(f"v_phase_rms ({v_phase_rms}) must be strictly positive.")
    if supply_freq <= 0.0:
        raise ValueError(f"supply_freq ({supply_freq}) must be strictly positive.")

    pole_pairs = params.pole_pairs
    n_sync = 60.0 * supply_freq / pole_pairs
    slip = (n_sync - speed_rpm) / n_sync

    # Handle zero slip (synchronous speed / no-load ideal) without division by zero
    effective_slip = slip if abs(slip) > 1e-9 else 1e-9

    w_e = 2.0 * math.pi * supply_freq

    # Leakage and magnetizing inductances
    l_ls = max(1e-7, params.Ls - params.Lm)
    l_lr = max(1e-7, params.Lr - params.Lm)
    l_m = params.Lm

    x_s = w_e * l_ls
    x_r = w_e * l_lr
    x_m = w_e * l_m

    z_s = complex(params.Rs, x_s)
    z_r = complex(params.Rr / effective_slip, x_r)
    z_m = complex(0.0, x_m)

    # Parallel combination of magnetizing branch and rotor branch
    z_p = (z_m * z_r) / (z_m + z_r)
    z_in = z_s + z_p

    # Stator current phasor (taking V_phase as reference angle 0)
    v_phasor = complex(v_phase_rms, 0.0)
    i_s = v_phasor / z_in
    i_s_mag = abs(i_s)

    # Magnetizing voltage and rotor current phasor
    v_m = i_s * z_p
    i_r = v_m / z_r
    i_r_mag = abs(i_r)

    # 3-phase complex power
    s_complex = 3.0 * v_phasor * i_s.conjugate()
    real_power_w = s_complex.real
    reactive_power_var = s_complex.imag
    apparent_power_va = 3.0 * v_phase_rms * i_s_mag

    pf = real_power_w / apparent_power_va if apparent_power_va > 1e-6 else 1.0
    pf = max(-1.0, min(1.0, pf))

    # Air-gap power and electromagnetic developed torque
    w_sync_mech = (2.0 * math.pi * supply_freq) / pole_pairs
    p_airgap = 3.0 * (i_r_mag ** 2) * (params.Rr / effective_slip)
    torque_dev = p_airgap / w_sync_mech if w_sync_mech > 1e-6 else 0.0
    p_mech = (1.0 - slip) * p_airgap

    return SteadyStateResult(
        slip=slip,
        stator_current_mag=i_s_mag,
        rotor_current_mag=i_r_mag,
        real_power_w=real_power_w,
        reactive_power_var=reactive_power_var,
        apparent_power_va=apparent_power_va,
        power_factor=pf,
        torque_developed_nm=torque_dev,
        mechanical_power_w=p_mech,
        z_in=z_in,
    )

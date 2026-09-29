"""simulation/state_space_solver.py — State-Space Dynamic Motor Solver with RK45 Integration.

Implements the nonlinear transient dynamic model of an AC induction machine in both
orthogonal stationary (alpha-beta) and synchronous (d-q) reference frames, integrated
using scipy.integrate.solve_ivp (RK45 method).

Electromechanical state variables:
    x = [i_ds, i_qs, psi_dr, psi_qr, omega_m]^T (or alpha-beta equivalents)

Mathematical fault injection models:
    1. Stator Inter-turn Short Circuit (ITSC): shorted-turn ratio mu = N_sc / N_s
       generating unbalanced circulating current matrix: v_s = R_s * i_s + d(psi_s)/dt.
    2. Broken Rotor Bars (BRB): rotor resistance asymmetry R_r(theta_r) with R_dr != R_qr,
       producing the characteristic (1 +/- 2ks) * f_s sidebands.
    3. Dynamic Eccentricity: angular permeance model L_m(theta_r) = L_m0 * (1 + delta_ecc * cos(theta_r)).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.integrate import solve_ivp

from app.simulation.params import MotorParams

TWO_PI = 2.0 * math.pi
SQRT3_2 = math.sqrt(3.0) / 2.0
INV_SQRT3 = 1.0 / math.sqrt(3.0)


@dataclass
class TransientResult:
    """Encapsulates continuous time trajectory from solve_ivp RK45."""

    t: np.ndarray             # Time array [s]
    i_alphabeta: np.ndarray   # (2, n) Stator current [A] (alpha, beta)
    i_dq: np.ndarray          # (2, n) Synchronous stator current [A] (d, q)
    i_abc: np.ndarray         # (3, n) Phase currents [A] (a, b, c)
    psi_r_alphabeta: np.ndarray # (2, n) Rotor flux [Wb] (alpha, beta)
    psi_r_dq: np.ndarray      # (2, n) Synchronous rotor flux [Wb] (d, q)
    omega_m: np.ndarray       # Mechanical rotor shaft speed [rad/s]
    rpm: np.ndarray           # Mechanical shaft speed in RPM
    theta_r: np.ndarray       # Electrical rotor position [rad]
    te: np.ndarray            # Electromagnetic torque [N·m]
    load_torque: np.ndarray   # Applied load torque profile [N·m]
    fault_heat_w: np.ndarray  # Extra dissipation from faults [W]
    copper_loss_w: np.ndarray # Instantaneous stator + rotor copper loss [W]


class StateSpaceMotorSolver:
    """Nonlinear transient dynamic solver for induction machines using scipy solve_ivp (RK45)."""

    def __init__(
        self,
        params: MotorParams,
        supply_freq: float = 50.0,
        viscous_damping: float = 0.002,
        # Fault configuration:
        itsc_mu: float = 0.0,          # Shorted turn ratio mu = N_sc / N_s in Phase A
        itsc_rf: float = 20.0,         # Shorted loop contact resistance [Ohm]
        brb_delta: float = 0.0,        # Rotor asymmetry ratio (R_dr - R_qr) / R_r
        ecc_dynamic: float = 0.0,      # Dynamic eccentricity depth delta_ecc
    ):
        self.p = params
        self.derived = params.compute_derived_constants()
        self.supply_freq = supply_freq
        self.B = viscous_damping
        self.v_peak = params.rated_voltage * math.sqrt(2.0) / math.sqrt(3.0)

        # Fault parameters
        self.itsc_mu = float(itsc_mu)
        self.itsc_rf = float(itsc_rf)
        self.brb_delta = float(brb_delta)
        self.ecc_dynamic = float(ecc_dynamic)

    def supply_voltage(self, t: float) -> tuple[float, float]:
        """Calculates balanced sinusoidal supply voltage in alpha-beta frame."""
        theta_e = TWO_PI * self.supply_freq * t
        ua = self.v_peak * math.cos(theta_e)
        ub = self.v_peak * math.sin(theta_e)
        return ua, ub

    def state_derivatives(
        self,
        t: float,
        state: np.ndarray,
        load_torque_fn: Callable[[float], float],
    ) -> np.ndarray:
        """Evaluates state derivatives dx/dt = f(t, x).

        State vector x:
            x[0] = i_salpha    (Stator alpha current [A])
            x[1] = i_sbeta     (Stator beta current [A])
            x[2] = psi_ralpha  (Rotor alpha flux linkage [Wb])
            x[3] = psi_rbeta   (Rotor beta flux linkage [Wb])
            x[4] = omega_m     (Rotor mechanical speed [rad/s])
            x[5] = theta_m     (Rotor mechanical angle [rad])
        """
        p = self.p
        ia, ib, pa, pb, wm, th_m = state
        th_r = p.pole_pairs * th_m  # Electrical rotor angle
        wr = p.pole_pairs * wm      # Electrical rotor speed

        # 1. Dynamic Eccentricity: Angular Permeance Model
        # L_m(theta_m) = L_m0 * (1 + delta_ecc * cos(theta_m))
        if self.ecc_dynamic > 0.0:
            lm = p.Lm * (1.0 + self.ecc_dynamic * math.cos(th_m))
        else:
            lm = p.Lm

        ls = p.Ls - p.Lm + lm
        lr = p.Lr - p.Lm + lm

        # 2. Broken Rotor Bars (BRB): Rotor Asymmetry Model R_dr != R_qr
        # Modulating rotor resistance matrix R_r(theta_r)
        if self.brb_delta > 0.0:
            c2 = math.cos(2.0 * th_r)
            s2 = math.sin(2.0 * th_r)
            half = 0.5 * self.brb_delta * p.Rr
            r11 = p.Rr + half * (1.0 + c2)
            r12 = half * s2
            r22 = p.Rr + half * (1.0 - c2)
        else:
            r11 = p.Rr
            r12 = 0.0
            r22 = p.Rr

        # Stator supply voltage in alpha-beta
        ua, ub = self.supply_voltage(t)

        # Rotor currents from rotor fluxes and mutual coupling:
        # i_r = (psi_r - L_m * i_s) / L_r
        ira = (pa - lm * ia) / lr
        irb = (pb - lm * ib) / lr

        # Rotor flux derivatives:
        # d(psi_r)/dt = -R_r * i_r - omega_r * J * psi_r
        dpa = -(r11 * ira + r12 * irb) - wr * pb
        dpb = -(r12 * ira + r22 * irb) + wr * pa

        # Total leakage factor: sigma * L_s
        sls = (1.0 - (lm * lm) / (ls * lr)) * ls
        klr = lm / lr

        # Stator current derivatives:
        # v_s = R_s * i_s + d(psi_s)/dt => d(i_s)/dt = (v_s - R_s * i_s - (L_m / L_r) * d(psi_r)/dt) / (sigma * L_s)
        dia = (ua - p.Rs * ia - klr * dpa) / sls
        dib = (ub - p.Rs * ib - klr * dpb) / sls

        # 3. Inter-turn Short Circuit (ITSC): Phase A shorted turns
        if self.itsc_mu > 0.0:
            # Phase A voltage: u_a = ua
            # Shorted turn circulating current i_f = mu * u_a / (r_f + mu * R_s)
            u_phase_a = ua
            # Reaction on stator alpha-beta: Phase A is aligned with alpha axis
            dia += -(self.itsc_mu / sls) * (u_phase_a - p.Rs * ia) * 0.5

        # Electromechanical torque:
        # T_e = (3/2) * p * (L_m / L_r) * (psi_ralpha * i_sbeta - psi_rbeta * i_salpha)
        te = 1.5 * p.pole_pairs * klr * (pa * ib - pb * ia)

        # Mechanical load demand
        tl = float(load_torque_fn(t))

        # Shaft acceleration:
        # d(omega_m)/dt = (T_e - T_L - B * omega_m) / J
        dwm = (te - tl - self.B * wm) / p.J

        # Mechanical angle derivative:
        dth_m = wm

        return np.array([dia, dib, dpa, dpb, dwm, dth_m], dtype=np.float64)

    def solve(
        self,
        t_span: tuple[float, float],
        t_eval: np.ndarray | None = None,
        load_torque: float | Callable[[float], float] = 0.0,
        y0: np.ndarray | None = None,
        method: Literal["RK45", "DOP853", "Radau"] = "RK45",
        rtol: float = 1e-5,
        atol: float = 1e-7,
        max_step: float = 1e-3,
    ) -> TransientResult:
        """Executes nonlinear transient numerical integration using scipy.integrate.solve_ivp."""
        if callable(load_torque):
            tl_fn: Callable[[float], float] = load_torque
        else:
            tl_val = float(load_torque)

            def tl_fn(t: float) -> float:
                return tl_val

        # Initial conditions: [i_alpha, i_beta, psi_alpha, psi_beta, omega_m, theta_m]
        init_state = np.zeros(6, dtype=np.float64) if y0 is None else np.asarray(y0, dtype=np.float64)

        sol = solve_ivp(
            fun=lambda t, y: self.state_derivatives(t, y, tl_fn),
            t_span=t_span,
            y0=init_state,
            method=method,
            t_eval=t_eval,
            rtol=rtol,
            atol=atol,
            max_step=max_step,
        )

        t = sol.t
        n = len(t)
        ia = sol.y[0]
        ib = sol.y[1]
        pa = sol.y[2]
        pb = sol.y[3]
        wm = sol.y[4]
        th_m = sol.y[5]
        th_r = self.p.pole_pairs * th_m

        # Transform to 3-phase abc currents
        i_abc = np.vstack([
            ia,
            -0.5 * ia + SQRT3_2 * ib,
            -0.5 * ia - SQRT3_2 * ib,
        ])

        # Apply ITSC circulating current to Phase A if shorted turns exist
        fault_heat = np.zeros(n)
        if self.itsc_mu > 0.0:
            ua_vals = np.array([self.supply_voltage(ti)[0] for ti in t])
            r_loop = self.itsc_rf + self.itsc_mu * self.p.Rs
            i_f = self.itsc_mu * ua_vals / max(r_loop, 1e-4)
            i_abc[0] += i_f
            fault_heat += 4.0 * (i_f ** 2) * r_loop

        # Synchronous d-q transformation (aligned with supply angle theta_e = 2*pi*f*t)
        th_e = TWO_PI * self.supply_freq * t
        cos_e = np.cos(th_e)
        sin_e = np.sin(th_e)
        # Park transform: [d; q] = [[cos, sin], [-sin, cos]] * [alpha; beta]
        i_d = cos_e * ia + sin_e * ib
        i_q = -sin_e * ia + cos_e * ib
        i_dq = np.vstack([i_d, i_q])

        psi_rd = cos_e * pa + sin_e * pb
        psi_rq = -sin_e * pa + cos_e * pb
        psi_r_dq = np.vstack([psi_rd, psi_rq])

        # Torque
        klr = self.p.Lm / self.p.Lr
        te = 1.5 * self.p.pole_pairs * klr * (pa * ib - pb * ia)

        # Load profile evaluation
        tl_arr = np.array([tl_fn(ti) for ti in t])

        # Copper loss: P_cu = 1.5 * (Rs * (ia^2 + ib^2) + Rr * (ira^2 + irb^2))
        ira = (pa - self.p.Lm * ia) / self.p.Lr
        irb = (pb - self.p.Lm * ib) / self.p.Lr
        copper_loss = 1.5 * (self.p.Rs * (ia**2 + ib**2) + self.p.Rr * (ira**2 + irb**2))

        rpm = wm * (60.0 / TWO_PI)

        return TransientResult(
            t=t,
            i_alphabeta=np.vstack([ia, ib]),
            i_dq=i_dq,
            i_abc=i_abc,
            psi_r_alphabeta=np.vstack([pa, pb]),
            psi_r_dq=psi_r_dq,
            omega_m=wm,
            rpm=rpm,
            theta_r=th_r,
            te=te,
            load_torque=tl_arr,
            fault_heat_w=fault_heat,
            copper_loss_w=copper_loss,
        )

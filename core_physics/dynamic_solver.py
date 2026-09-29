"""core_physics/dynamic_solver.py

4th-order Runge-Kutta / solve_ivp state-space ODE engine for induction motor.

Implements the 3-phase induction motor state-space model in the stationary
α-β reference frame using scipy.integrate.solve_ivp (method='RK45' or 'LSODA').

State variables:
- Stator currents (i_αs, i_βs)
- Rotor flux linkages (ψ_αr, ψ_βr)
- Rotor mechanical angular velocity (ω_m)
- Rotor mechanical angle (θ_m)

Torque balance equation:
    dω_m/dt = (1/J) * (T_e - T_L - B·ω_m)

Electromechanical torque:
    T_e = (3/2) * p * (ψ_αr * i_βs - ψ_βr * i_αs)

Rotor electrical speed: ω_r = p * ω_m
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Literal

import numpy as np
from scipy.integrate import solve_ivp

from core_physics.motor_parameters import DerivedConstants, MotorParams

TWO_PI = 2.0 * math.pi
SQRT3_2 = math.sqrt(3.0) / 2.0
INV_SQRT3 = 1.0 / math.sqrt(3.0)


@dataclass
class TransientResult:
    """Encapsulates continuous time trajectory from solve_ivp RK45."""

    t: np.ndarray  # Time array [s]
    i_alphabeta: np.ndarray  # (2, n) Stator current [A] (alpha, beta)
    i_dq: np.ndarray  # (2, n) Synchronous stator current [A] (d, q)
    i_abc: np.ndarray  # (3, n) Phase currents [A] (a, b, c)
    psi_r_alphabeta: np.ndarray  # (2, n) Rotor flux [Wb] (alpha, beta)
    psi_r_dq: np.ndarray  # (2, n) Synchronous rotor flux [Wb] (d, q)
    omega_m: np.ndarray  # Mechanical rotor shaft speed [rad/s]
    rpm: np.ndarray  # Mechanical shaft speed in RPM
    theta_r: np.ndarray  # Electrical rotor position [rad]
    te: np.ndarray  # Electromagnetic torque [N·m]
    load_torque: np.ndarray  # Applied load torque profile [N·m]
    fault_heat_w: np.ndarray  # Extra dissipation from faults [W]
    copper_loss_w: np.ndarray  # Instantaneous stator + rotor copper loss [W]
    slip: np.ndarray  # Instantaneous slip


class StateSpaceMotorSolver:
    """Nonlinear transient dynamic solver for induction machines using scipy.integrate.solve_ivp.

    Implements the state-space model in the stationary α-β reference frame.
    The 6-state vector is:
        x = [i_αs, i_βs, ψ_αr, ψ_βr, ω_m, θ_m]^T
    """

    def __init__(
        self,
        params: MotorParams,
        supply_freq: float = 50.0,
        supply_voltage: float | None = None,
        # Fault configuration:
        itsc_mu: float = 0.0,  # Shorted turn ratio μ = N_sc / N_s in Phase A
        itsc_rf: float = 20.0,  # Shorted loop contact resistance [Ω]
        brb_delta: float = 0.0,  # Rotor asymmetry ratio (R_dr - R_qr) / R_r
        ecc_dynamic: float = 0.0,  # Dynamic eccentricity depth δ_ecc
        # Thermal coupling
        winding_temp: float = 20.0,  # Initial winding temperature [°C]
    ):
        self.p = params
        self.derived = params.compute_derived_constants()
        self.supply_freq = supply_freq
        self.supply_voltage_ll = supply_voltage if supply_voltage is not None else params.rated_voltage
        self.v_peak = self.supply_voltage_ll * math.sqrt(2.0) / math.sqrt(3.0)

        # Fault parameters
        self.itsc_mu = float(itsc_mu)
        self.itsc_rf = float(itsc_rf)
        self.brb_delta = float(brb_delta)
        self.ecc_dynamic = float(ecc_dynamic)

        # Thermal state
        self.winding_temp = winding_temp
        self.alpha_cu = 0.00393  # Copper temperature coefficient [1/°C]

    def _update_resistance_with_temp(self, temp_c: float) -> float:
        """Update stator resistance based on winding temperature.

        R_s(T) = R_s0 * [1 + α_cu * (T_winding - 20)]
        """
        return self.p.Rs * (1.0 + self.alpha_cu * (temp_c - 20.0))

    def supply_voltage(self, t: float) -> tuple[float, float]:
        """Calculates balanced sinusoidal supply voltage in α-β frame.

        V_α = V_peak * cos(ω_s * t)
        V_β = V_peak * sin(ω_s * t)
        """
        theta_e = TWO_PI * self.supply_freq * t
        ua = self.v_peak * math.cos(theta_e)
        ub = self.v_peak * math.sin(theta_e)
        return ua, ub

    def state_derivatives(
        self,
        t: float,
        state: np.ndarray,
        load_torque_fn: Callable[[float], float],
        winding_temp: float | None = None,
    ) -> np.ndarray:
        """Evaluates state derivatives dx/dt = f(t, x).

        State vector x:
            x[0] = i_sα    (Stator alpha current [A])
            x[1] = i_sβ    (Stator beta current [A])
            x[2] = ψ_rα    (Rotor alpha flux linkage [Wb])
            x[3] = ψ_rβ    (Rotor beta flux linkage [Wb])
            x[4] = ω_m     (Rotor mechanical speed [rad/s])
            x[5] = θ_m     (Rotor mechanical angle [rad])
        """
        p = self.p
        ia, ib, pa, pb, wm, th_m = state
        th_r = p.pole_pairs * th_m  # Electrical rotor angle
        wr = p.pole_pairs * wm  # Electrical rotor speed

        # Use provided temperature or current stored temperature
        temp = winding_temp if winding_temp is not None else self.winding_temp
        rs_temp = self._update_resistance_with_temp(temp)

        # 1. Dynamic Eccentricity: Angular Permeance Model
        # L_m(θ_m) = L_m0 * (1 + δ_ecc * cos(θ_m))
        if self.ecc_dynamic > 0.0:
            lm = p.Lm * (1.0 + self.ecc_dynamic * math.cos(th_m))
        else:
            lm = p.Lm

        ls = p.Ls - p.Lm + lm
        lr = p.Lr - p.Lm + lm

        # 2. Broken Rotor Bars (BRB): Rotor Asymmetry Model R_dr ≠ R_qr
        # Modulating rotor resistance matrix R_r(θ_r) in stationary frame
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

        # Stator supply voltage in α-β
        ua, ub = self.supply_voltage(t)

        # Rotor currents from rotor fluxes and mutual coupling:
        # i_r = (ψ_r - L_m * i_s) / L_r
        ira = (pa - lm * ia) / lr
        irb = (pb - lm * ib) / lr

        # Rotor flux derivatives:
        # dψ_r/dt = -R_r * i_r - ω_r * J * ψ_r
        dpa = -(r11 * ira + r12 * irb) - wr * pb
        dpb = -(r12 * ira + r22 * irb) + wr * pa

        # Total leakage factor: σ * L_s
        sls = (1.0 - (lm * lm) / (ls * lr)) * ls
        klr = lm / lr

        # Stator current derivatives:
        # v_s = R_s * i_s + dψ_s/dt => d(i_s)/dt = (v_s - R_s * i_s - (L_m / L_r) * dψ_r/dt) / (σ * L_s)
        dia = (ua - rs_temp * ia - klr * dpa) / sls
        dib = (ub - rs_temp * ib - klr * dpb) / sls

        # 3. Inter-turn Short Circuit (ITSC): Phase A shorted turns
        if self.itsc_mu > 0.0:
            # Phase A voltage: u_a = ua (α-axis aligned with Phase A)
            # Shorted turn circulating current i_f = μ * u_a / (r_f + μ * R_s)
            u_phase_a = ua
            r_loop = self.itsc_rf + self.itsc_mu * rs_temp
            i_f = self.itsc_mu * u_phase_a / max(r_loop, 1e-4)
            # Reaction on stator α-β: Phase A is aligned with α axis
            # This adds to the α-axis current derivative
            dia += -(self.itsc_mu / sls) * (u_phase_a - rs_temp * ia) * 0.5

        # Electromechanical torque:
        # T_e = (3/2) * p * (L_m / L_r) * (ψ_αr * i_βs - ψ_βr * i_αs)
        te = 1.5 * p.pole_pairs * klr * (pa * ib - pb * ia)

        # Mechanical load demand
        tl = float(load_torque_fn(t))

        # Shaft acceleration:
        # dω_m/dt = (T_e - T_L - B * ω_m) / J
        dwm = (te - tl - p.B * wm) / p.J

        # Mechanical angle derivative:
        dth_m = wm

        return np.array([dia, dib, dpa, dpb, dwm, dth_m], dtype=np.float64)

    def solve(
        self,
        t_span: tuple[float, float],
        t_eval: np.ndarray | None = None,
        load_torque: float | Callable[[float], float] = 0.0,
        y0: np.ndarray | None = None,
        method: Literal["RK45", "DOP853", "Radau", "LSODA"] = "RK45",
        rtol: float = 1e-6,
        atol: float = 1e-8,
        max_step: float = 1e-3,
        winding_temp: float | None = None,
    ) -> TransientResult:
        """Executes nonlinear transient numerical integration using scipy.integrate.solve_ivp.

        Args:
            t_span: (t_start, t_end) time span for integration [s]
            t_eval: Time points at which to store the solution
            load_torque: Constant load torque [N·m] or callable T_L(t)
            y0: Initial state [i_α, i_β, ψ_α, ψ_β, ω_m, θ_m]
            method: Integration method ('RK45', 'DOP853', 'Radau', 'LSODA')
            rtol: Relative tolerance
            atol: Absolute tolerance
            max_step: Maximum step size [s]
            winding_temp: Winding temperature for thermal coupling [°C]

        Returns:
            TransientResult with full trajectory data
        """
        if callable(load_torque):
            tl_fn = load_torque
        else:
            tl_val = float(load_torque)
            tl_fn = lambda t: tl_val

        # Initial conditions: [i_α, i_β, ψ_α, ψ_β, ω_m, θ_m]
        init_state = np.zeros(6, dtype=np.float64) if y0 is None else np.asarray(y0, dtype=np.float64)

        # Wrapper to include winding temperature
        def ode_func(t: float, y: np.ndarray) -> np.ndarray:
            return self.state_derivatives(t, y, tl_fn, winding_temp)

        sol = solve_ivp(
            fun=ode_func,
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
            r_loop = self.itsc_rf + self.itsc_mu * self._update_resistance_with_temp(
                winding_temp if winding_temp is not None else self.winding_temp
            )
            i_f = self.itsc_mu * ua_vals / max(r_loop, 1e-4)
            i_abc[0] += i_f
            fault_heat += 4.0 * (i_f**2) * r_loop

        # Synchronous d-q transformation (aligned with supply angle θ_e = 2πf*t)
        th_e = TWO_PI * self.supply_freq * t
        cos_e = np.cos(th_e)
        sin_e = np.sin(th_e)
        # Park transform: [d; q] = [[cos, sin], [-sin, cos]] * [α; β]
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

        # Copper loss: P_cu = 1.5 * (Rs * (ia² + ib²) + Rr * (ira² + irb²))
        ira = (pa - self.p.Lm * ia) / self.p.Lr
        irb = (pb - self.p.Lm * ib) / self.p.Lr
        rs_used = self._update_resistance_with_temp(winding_temp if winding_temp is not None else self.winding_temp)
        copper_loss = 1.5 * (rs_used * (ia**2 + ib**2) + self.p.Rr * (ira**2 + irb**2))

        # Slip calculation
        ws = TWO_PI * self.supply_freq  # Synchronous electrical speed [rad/s]
        slip = (ws - self.p.pole_pairs * wm) / ws

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
            slip=slip,
        )

    def solve_fixed_step_rk4(
        self,
        t_span: tuple[float, float],
        dt: float,
        load_torque: float | Callable[[float], float] = 0.0,
        y0: np.ndarray | None = None,
        winding_temp: float | None = None,
    ) -> TransientResult:
        """Fixed-step 4th-order Runge-Kutta integration for real-time applications.

        Args:
            t_span: (t_start, t_end) time span for integration [s]
            dt: Fixed time step [s]
            load_torque: Constant load torque [N·m] or callable T_L(t)
            y0: Initial state [i_α, i_β, ψ_α, ψ_β, ω_m, θ_m]
            winding_temp: Winding temperature for thermal coupling [°C]

        Returns:
            TransientResult with full trajectory data
        """
        if callable(load_torque):
            tl_fn = load_torque
        else:
            tl_val = float(load_torque)
            tl_fn = lambda t: tl_val

        t_start, t_end = t_span
        n_steps = int((t_end - t_start) / dt) + 1
        t = np.linspace(t_start, t_end, n_steps)

        # Initial conditions
        state = np.zeros(6, dtype=np.float64) if y0 is None else np.asarray(y0, dtype=np.float64)

        # Storage arrays
        ia_arr = np.zeros(n_steps)
        ib_arr = np.zeros(n_steps)
        pa_arr = np.zeros(n_steps)
        pb_arr = np.zeros(n_steps)
        wm_arr = np.zeros(n_steps)
        th_m_arr = np.zeros(n_steps)
        te_arr = np.zeros(n_steps)
        tl_arr = np.zeros(n_steps)
        fault_heat_arr = np.zeros(n_steps)
        copper_loss_arr = np.zeros(n_steps)

        for i in range(n_steps):
            ti = t[i]
            ia_arr[i], ib_arr[i], pa_arr[i], pb_arr[i], wm_arr[i], th_m_arr[i] = state

            # Evaluate load torque at current time
            tl = float(tl_fn(ti))
            tl_arr[i] = tl

            # Store outputs
            ia, ib, pa, pb, wm, th_m = state
            th_r = self.p.pole_pairs * th_m
            klr = self.p.Lm / self.p.Lr
            te_arr[i] = 1.5 * self.p.pole_pairs * klr * (pa * ib - pb * ia)

            # Fixed-step RK4
            k1 = self.state_derivatives(ti, state, tl_fn, winding_temp)
            k2 = self.state_derivatives(ti + 0.5 * dt, state + 0.5 * dt * k1, tl_fn, winding_temp)
            k3 = self.state_derivatives(ti + 0.5 * dt, state + 0.5 * dt * k2, tl_fn, winding_temp)
            k4 = self.state_derivatives(ti + dt, state + dt * k3, tl_fn, winding_temp)
            state = state + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)

        # Post-process
        th_r = self.p.pole_pairs * th_m_arr
        ia = ia_arr
        ib = ib_arr
        pa = pa_arr
        pb = pb_arr
        wm = wm_arr

        i_abc = np.vstack([
            ia,
            -0.5 * ia + SQRT3_2 * ib,
            -0.5 * ia - SQRT3_2 * ib,
        ])

        fault_heat = np.zeros(n_steps)
        if self.itsc_mu > 0.0:
            ua_vals = np.array([self.supply_voltage(ti)[0] for ti in t])
            r_loop = self.itsc_rf + self.itsc_mu * self._update_resistance_with_temp(
                winding_temp if winding_temp is not None else self.winding_temp
            )
            i_f = self.itsc_mu * ua_vals / max(r_loop, 1e-4)
            i_abc[0] += i_f
            fault_heat += 4.0 * (i_f**2) * r_loop

        th_e = TWO_PI * self.supply_freq * t
        cos_e = np.cos(th_e)
        sin_e = np.sin(th_e)
        i_d = cos_e * ia + sin_e * ib
        i_q = -sin_e * ia + cos_e * ib
        i_dq = np.vstack([i_d, i_q])

        psi_rd = cos_e * pa + sin_e * pb
        psi_rq = -sin_e * pa + cos_e * pb
        psi_r_dq = np.vstack([psi_rd, psi_rq])

        ira = (pa - self.p.Lm * ia) / self.p.Lr
        irb = (pb - self.p.Lm * ib) / self.p.Lr
        rs_used = self._update_resistance_with_temp(winding_temp if winding_temp is not None else self.winding_temp)
        copper_loss = 1.5 * (rs_used * (ia**2 + ib**2) + self.p.Rr * (ira**2 + irb**2))

        ws = TWO_PI * self.supply_freq
        slip = (ws - self.p.pole_pairs * wm) / ws
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
            te=te_arr,
            load_torque=tl_arr,
            fault_heat_w=fault_heat,
            copper_loss_w=copper_loss,
            slip=slip,
        )
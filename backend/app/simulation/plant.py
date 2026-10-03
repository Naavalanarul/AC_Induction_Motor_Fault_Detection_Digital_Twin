"""simulation/plant.py

Real-time capable induction motor plant and healthy-state digital twin.

`MotorPlant` is the "physical" (faultable) motor used by the live system. It
integrates the same alpha-beta state-space model as `dynamics.py` (Chen et al.
Eq. 3, 13, 14) with fixed-step RK4 at the electrical sample rate, but assumes an
*averaged* inverter / sinusoidal supply instead of resolving individual PWM
switching events. The event-driven PWM model in `motor_twin.py` is kept as the
high-fidelity reference; `tests/simulation/test_plant.py` checks the two agree on
the fundamental current.

The inner loop is written with plain Python floats on purpose: for a 5-state
system, NumPy's per-call overhead is larger than the arithmetic.

`HealthyTwinObserver` is the frozen-parameter healthy digital twin used by the
electrical diagnostic (DT current-residual method): it is driven by the
*measured* stator voltage and *measured* shaft speed and predicts the stator
current a healthy machine would draw.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from app.simulation.faults import FaultState
from app.simulation.params import MotorParams

TWO_PI = 2.0 * math.pi
SQRT3_2 = math.sqrt(3.0) / 2.0
INV_SQRT3 = 1.0 / math.sqrt(3.0)
HOT_SPOT_FACTOR = 4.0


@dataclass
class PlantChunk:
    """Ground-truth waveforms for one simulation chunk (all arrays length n)."""

    t: np.ndarray
    u_abc: np.ndarray       # (3, n) phase-to-neutral supply voltage [V]
    i_abc: np.ndarray       # (3, n) terminal stator currents [A]
    omega_m: np.ndarray     # mechanical shaft speed [rad/s]
    theta_m: np.ndarray     # mechanical shaft angle [rad] (unwrapped)
    te: np.ndarray          # electromagnetic torque [N*m]
    load_torque: np.ndarray # applied load torque [N*m]
    supply_freq: float      # supply fundamental [Hz]
    fs: float               # sample rate [Hz]
    fault_heat_w: float     # mean extra heat from faults [W]
    copper_loss_w: float    # mean stator + rotor copper loss [W]
    has_nonfinite: bool = False


def abc_to_alphabeta(abc: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Amplitude-invariant Clarke transform, vectorized. abc shape (3, n)."""
    a, b, c = abc
    return (2.0 / 3.0) * (a - 0.5 * b - 0.5 * c), INV_SQRT3 * (b - c)


def alphabeta_to_abc(al: np.ndarray, be: np.ndarray) -> np.ndarray:
    return np.vstack([al, -0.5 * al + SQRT3_2 * be, -0.5 * al - SQRT3_2 * be])


class MotorPlant:
    """Faultable induction motor with sinusoidal (averaged-inverter) supply."""

    def __init__(
        self,
        params: MotorParams,
        faults: FaultState | None = None,
        fs: float = 5000.0,
        supply_freq: float = 50.0,
        viscous_damping: float = 0.002,
    ):
        self.p = params
        self.faults = faults if faults is not None else FaultState()
        self.fs = fs
        self.h = 1.0 / fs
        self.supply_freq = supply_freq
        self.B = viscous_damping
        # Rated phase peak voltage (star connection)
        self.v_peak = params.rated_voltage * math.sqrt(2.0) / math.sqrt(3.0)
        self.voltage_scale = 1.0   # 0 = supply off (trip)
        self.t = 0.0
        self.theta_m = 0.0
        self.nonfinite_tripped = False
        # [i_alpha, i_beta, psi_alpha, psi_beta, omega_m]
        self.x = [0.0, 0.0, 0.0, 0.0, 0.0]

    # -- supply ----------------------------------------------------------
    def _supply_ab(self, t: float) -> tuple[float, float]:
        sag, imb, harm = self.faults.voltage
        v = self.v_peak * (1.0 - sag) * self.voltage_scale
        if v == 0.0:
            return 0.0, 0.0
        th = TWO_PI * self.supply_freq * t
        c, s = math.cos(th), math.sin(th)
        ua = v * c
        ub = v * s
        if imb:
            ua += imb * v * c
            ub -= imb * v * s
        if harm:
            ua += harm * v * math.cos(5 * th) + 0.7 * harm * v * math.cos(7 * th)
            ub += -harm * v * math.sin(5 * th) + 0.7 * harm * v * math.sin(7 * th)
        return ua, ub

    # -- ODE -------------------------------------------------------------
    def _deriv(self, x, ua, ub, r11, r12, r22, lm, tl):
        """General form allowing an asymmetric rotor resistance matrix [[r11, r12], [r12, r22]].

        Rotor:  dpsi_r/dt = -R_r (psi_r - Lm i_s) / Lr + omega_r J psi_r
        Stator: di_s/dt   = (u_s - Rs i_s - (Lm/Lr) dpsi_r/dt) / (sigma Ls)
        With R_r = Rr * I this is exactly Chen et al. Eq. (3).
        """
        p = self.p
        rs = p.Rs
        # Leakage inductances stay fixed when the magnetizing path is modulated
        ls = p.Ls - p.Lm + lm
        lr = p.Lr - p.Lm + lm
        ia, ib, pa, pb, wm = x
        wr = p.pole_pairs * wm
        ira = (pa - lm * ia) / lr
        irb = (pb - lm * ib) / lr
        dpa = -(r11 * ira + r12 * irb) - wr * pb
        dpb = -(r12 * ira + r22 * irb) + wr * pa
        sls = (1.0 - lm * lm / (ls * lr)) * ls
        klr = lm / lr
        dia = (ua - rs * ia - klr * dpa) / sls
        dib = (ub - rs * ib - klr * dpb) / sls
        te = 1.5 * p.pole_pairs * klr * (pa * ib - pb * ia)
        dwm = (te - tl - self.B * wm) / p.J
        return (dia, dib, dpa, dpb, dwm), te

    def simulate(self, n: int, load_torque: float) -> PlantChunk:
        """Advance n samples at fs with the given mean load torque."""
        p, f = self.p, self.faults
        h, hh = self.h, 0.5 * self.h
        brb = f.brb_delta
        ecc_dyn, ecc_stat = f.eccentricity
        unb, mis = f.unbalance, f.misalignment
        fric = f.bearing_friction_torque
        itsc = f.interturn
        tr = p.pole_pairs

        t_arr = np.empty(n)
        ua_arr = np.empty(n)
        ub_arr = np.empty(n)
        ia_arr = np.empty(n)
        ib_arr = np.empty(n)
        wm_arr = np.empty(n)
        th_arr = np.empty(n)
        te_arr = np.empty(n)
        tl_arr = np.empty(n)

        x = self.x
        t = self.t
        th_m = self.theta_m
        for j in range(n):
            # Fault-modulated parameters, piecewise constant over one step
            if brb:
                # Broken bars: resistance rises along one rotor axis. Rotated into the
                # stationary frame this is R_r = Rr[(1+d/2)I + d/2 [[c2, s2], [s2, -c2]]].
                c2, s2 = math.cos(2.0 * tr * th_m), math.sin(2.0 * tr * th_m)
                half = 0.5 * brb * p.Rr
                r11, r12, r22 = p.Rr + half * (1.0 + c2), half * s2, p.Rr + half * (1.0 - c2)
            else:
                r11, r12, r22 = p.Rr, 0.0, p.Rr
            lm = p.Lm
            # Pure static eccentricity is not observable in a lumped alpha-beta model;
            # it is modelled as mixed eccentricity with a weaker rotating component.
            ecc = ecc_dyn + 0.5 * ecc_stat
            if ecc:
                lm *= 1.0 + ecc * math.cos(th_m)
            tl = load_torque + (fric if x[4] > 1.0 else 0.0)
            if unb:
                tl += 0.6 * unb * math.cos(th_m)
            if mis:
                tl += 0.6 * mis * math.cos(2.0 * th_m)

            u0 = self._supply_ab(t)
            u1 = self._supply_ab(t + hh)
            u2 = self._supply_ab(t + h)
            k1, te = self._deriv(x, u0[0], u0[1], r11, r12, r22, lm, tl)
            x2 = [x[i] + hh * k1[i] for i in range(5)]
            k2, _ = self._deriv(x2, u1[0], u1[1], r11, r12, r22, lm, tl)
            x3 = [x[i] + hh * k2[i] for i in range(5)]
            k3, _ = self._deriv(x3, u1[0], u1[1], r11, r12, r22, lm, tl)
            x4 = [x[i] + h * k3[i] for i in range(5)]
            k4, _ = self._deriv(x4, u2[0], u2[1], r11, r12, r22, lm, tl)
            wm_old = x[4]
            x = [x[i] + (h / 6.0) * (k1[i] + 2.0 * k2[i] + 2.0 * k3[i] + k4[i]) for i in range(5)]
            if not all(math.isfinite(val) for val in x):
                self.voltage_scale = 0.0
                self.nonfinite_tripped = True
                self.x = [0.0, 0.0, 0.0, 0.0, 0.0]
                t_arr[j:] = t + h * np.arange(n - j)
                ua_arr[j:] = 0.0
                ub_arr[j:] = 0.0
                ia_arr[j:] = 0.0
                ib_arr[j:] = 0.0
                wm_arr[j:] = 0.0
                th_arr[j:] = th_m
                te_arr[j:] = 0.0
                tl_arr[j:] = tl
                break
            if x[4] < 0.0 and load_torque >= 0.0:
                x[4] = 0.0  # passive load cannot drive the rotor backwards
            th_m += 0.5 * (wm_old + x[4]) * h
            t += h

            t_arr[j] = t
            ua_arr[j], ub_arr[j] = u2
            ia_arr[j], ib_arr[j] = x[0], x[1]
            wm_arr[j] = x[4]
            th_arr[j] = th_m
            te_arr[j] = te
            tl_arr[j] = tl

        self.x, self.t, self.theta_m = x, t, th_m

        u_abc = alphabeta_to_abc(ua_arr, ub_arr)
        i_abc = alphabeta_to_abc(ia_arr, ib_arr)
        fault_heat = 0.0
        if itsc is not None:
            phase, eta, r_f = itsc
            i_f = eta * u_abc[phase] / (r_f + eta * p.Rs)
            # Shorted-loop current seen at the terminals as an equivalent parallel
            # load on the faulted phase, returning through the other two (KCL holds).
            i_abc = i_abc - 0.5 * i_f
            i_abc[phase] += 1.5 * i_f
            # Shorted-turn loss is dissipated locally around the embedded winding sensor;
            # HOT_SPOT_FACTOR approximates that local concentration (lumped-model assumption).
            fault_heat += HOT_SPOT_FACTOR * float(np.mean(i_f**2)) * (r_f + eta * p.Rs)
        wm_mean = float(np.mean(wm_arr)) if n else 0.0
        fault_heat += fric * wm_mean
        i_sq = float(np.mean(ia_arr**2 + ib_arr**2)) if n else 0.0
        copper = 1.5 * (p.Rs + p.Rr) * i_sq * 0.5 + 40.0 * (self.voltage_scale > 0)

        has_nonfinite = self.nonfinite_tripped or not (
            np.all(np.isfinite(u_abc))
            and np.all(np.isfinite(i_abc))
            and np.all(np.isfinite(wm_arr))
            and np.all(np.isfinite(te_arr))
        )
        if has_nonfinite:
            self.nonfinite_tripped = True
            self.voltage_scale = 0.0
            u_abc = np.nan_to_num(u_abc, nan=0.0, posinf=0.0, neginf=0.0)
            i_abc = np.nan_to_num(i_abc, nan=0.0, posinf=0.0, neginf=0.0)
            wm_arr = np.nan_to_num(wm_arr, nan=0.0, posinf=0.0, neginf=0.0)
            te_arr = np.nan_to_num(te_arr, nan=0.0, posinf=0.0, neginf=0.0)
            fault_heat = 0.0 if not math.isfinite(fault_heat) else fault_heat
            copper = 0.0 if not math.isfinite(copper) else copper

        return PlantChunk(
            t=t_arr, u_abc=u_abc, i_abc=i_abc, omega_m=wm_arr, theta_m=th_arr,
            te=te_arr, load_torque=tl_arr, supply_freq=self.supply_freq, fs=self.fs,
            fault_heat_w=fault_heat, copper_loss_w=copper,
            has_nonfinite=has_nonfinite,
        )

    def warm_start(self, load_torque: float, seconds: float = 1.5) -> None:
        """Run to (near) steady state without recording (used by tests/training)."""
        chunk = int(self.fs * 0.1)
        for _ in range(int(seconds / 0.1)):
            self.simulate(chunk, load_torque)


class HealthyTwinObserver:
    """Frozen-parameter healthy digital twin (electrical part only).

    Inputs are measured alpha-beta voltage and measured electrical rotor speed;
    output is the predicted healthy alpha-beta stator current.
    """

    def __init__(self, params: MotorParams, fs: float):
        self.p = params
        self.h = 1.0 / fs
        ls, lr, lm, rs, rr = params.Ls, params.Lr, params.Lm, params.Rs, params.Rr
        self.inv_tr = rr / lr
        self.sls = (1.0 - lm * lm / (ls * lr)) * ls
        self.gamma = (rs + lm * lm * rr / (lr * lr)) / self.sls
        self.k = lm / (self.sls * lr)
        self.lm = lm
        self.x = [0.0, 0.0, 0.0, 0.0]
        self._last_u: tuple[float, float] | None = None
        self._last_w: float | None = None

    def reset(self) -> None:
        self.x = [0.0, 0.0, 0.0, 0.0]
        self._last_u = None
        self._last_w = None

    def _d(self, x, ua, ub, wr):
        g, k, itr, lm, sls = self.gamma, self.k, self.inv_tr, self.lm, self.sls
        ia, ib, pa, pb = x
        return (
            -g * ia + k * itr * pa + k * wr * pb + ua / sls,
            -g * ib + k * itr * pb - k * wr * pa + ub / sls,
            lm * itr * ia - itr * pa - wr * pb,
            lm * itr * ib - itr * pb + wr * pa,
        )

    def run(self, u_alpha: np.ndarray, u_beta: np.ndarray, omega_r: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Predict healthy currents for a chunk of measured samples.

        Sample k of the outputs corresponds to the state *at* sample k's timestamp,
        integrating from sample k-1 with linearly interpolated inputs.
        """
        n = len(u_alpha)
        out_a = np.empty(n)
        out_b = np.empty(n)
        h, hh = self.h, 0.5 * self.h
        x = self.x
        ua_prev, ub_prev = self._last_u if self._last_u else (float(u_alpha[0]), float(u_beta[0]))
        w_prev = self._last_w if self._last_w is not None else float(omega_r[0])
        ual, ube, wrs = u_alpha.tolist(), u_beta.tolist(), omega_r.tolist()
        for j in range(n):
            ua1, ub1, w1 = ual[j], ube[j], wrs[j]
            uam, ubm, wm = 0.5 * (ua_prev + ua1), 0.5 * (ub_prev + ub1), 0.5 * (w_prev + w1)
            k1 = self._d(x, ua_prev, ub_prev, w_prev)
            k2 = self._d([x[i] + hh * k1[i] for i in range(4)], uam, ubm, wm)
            k3 = self._d([x[i] + hh * k2[i] for i in range(4)], uam, ubm, wm)
            k4 = self._d([x[i] + h * k3[i] for i in range(4)], ua1, ub1, w1)
            x = [x[i] + (h / 6.0) * (k1[i] + 2.0 * k2[i] + 2.0 * k3[i] + k4[i]) for i in range(4)]
            out_a[j], out_b[j] = x[0], x[1]
            ua_prev, ub_prev, w_prev = ua1, ub1, w1
        self.x = x
        self._last_u = (ua_prev, ub_prev)
        self._last_w = w_prev
        return out_a, out_b

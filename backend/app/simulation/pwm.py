"""simulation/pwm.py

Models the 2-level three-phase Voltage Source Inverter (VSI), SPWM generation,
and event-driven switching instant (crossing) detection.

References:
    Chen et al. (Energies 2025), Eq. (1)-(2) & Section 2 / Fig. 3.
    Zhu et al. (IEEE TPEL 2019), "Discrete state event-driven framework..."
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from app.simulation.transforms import PhaseABC


@dataclass(frozen=True)
class InverterLegStates:
    """Switching states for all 6 IGBTs/switches.

    Complementary condition per Eq. (2):
        S2k-1 + S2k = 1 for k in {1, 2, 3}
    """

    s1: int  # Leg A upper
    s2: int  # Leg A lower = 1 - s1
    s3: int  # Leg B upper
    s4: int  # Leg B lower = 1 - s3
    s5: int  # Leg C upper
    s6: int  # Leg C lower = 1 - s5

    @classmethod
    def from_upper_switches(cls, sa: int, sb: int, sc: int) -> InverterLegStates:
        """Construct all 6 switch states enforcing complementary pairs."""
        sa_i = int(bool(sa))
        sb_i = int(bool(sb))
        sc_i = int(bool(sc))
        return cls(
            s1=sa_i, s2=1 - sa_i,
            s3=sb_i, s4=1 - sb_i,
            s5=sc_i, s6=1 - sc_i
        )


def phase_voltages(switches: InverterLegStates, udc: float) -> PhaseABC:
    """Calculate motor phase-to-neutral voltages (uan, ubn, ucn).

    Formula from Chen et al. Eq. (1):
        uan = (Udc / 3) * (2*Sa - Sb - Sc)
        ubn = (Udc / 3) * (2*Sb - Sa - Sc)
        ucn = (Udc / 3) * (2*Sc - Sa - Sb)
    where Sa = S1, Sb = S3, Sc = S5.
    """
    sa = switches.s1
    sb = switches.s3
    sc = switches.s5

    factor = udc / 3.0
    uan = factor * (2 * sa - sb - sc)
    ubn = factor * (2 * sb - sa - sc)
    ucn = factor * (2 * sc - sa - sb)

    return PhaseABC(a=uan, b=ubn, c=ucn)


class CarrierWaveGenerator:
    """Generates a symmetric triangular carrier wave normalized to [-1.0, 1.0]."""

    def __init__(self, carrier_freq_hz: float):
        if carrier_freq_hz <= 0:
            raise ValueError("Carrier frequency must be strictly positive.")
        self.freq = carrier_freq_hz
        self.period = 1.0 / carrier_freq_hz

    def __call__(self, t: float) -> float:
        """Returns carrier amplitude at time t.

        Normalized symmetric triangle with slope +4/T and -4/T between -1 and +1.
        """
        tau = (t % self.period) / self.period  # Phase in [0, 1)
        if tau < 0.5:
            # Rises from -1 to +1
            return 4.0 * tau - 1.0
        else:
            # Falls from +1 to -1
            return 3.0 - 4.0 * tau


class ModulatingWaveGenerator:
    """Generates balanced 3-phase sinusoidal modulating reference waves in [-1.0, 1.0]."""

    def __init__(self, fund_freq_hz: float, modulation_index: float, initial_phase: float = 0.0):
        """
        Args:
            fund_freq_hz: Fundamental frequency of the output voltage (e.g., 50.0 Hz).
            modulation_index: Modulation depth m in [0.0, 1.0].
            initial_phase: Initial electrical phase angle in radians.
        """
        if not (0.0 <= modulation_index <= 1.0):
            raise ValueError("Linear modulation index must be within [0.0, 1.0].")
        self.omega = 2.0 * math.pi * fund_freq_hz
        self.m = modulation_index
        self.theta0 = initial_phase

    def __call__(self, t: float) -> PhaseABC:
        """Computes reference signals ma(t), mb(t), mc(t)."""
        theta = self.omega * t + self.theta0
        two_pi_over_3 = 2.0 * math.pi / 3.0

        ma = self.m * math.cos(theta)
        mb = self.m * math.cos(theta - two_pi_over_3)
        mc = self.m * math.cos(theta + two_pi_over_3)

        return PhaseABC(a=ma, b=mb, c=mc)


def get_instantaneous_switches(
    mod_wave: PhaseABC, carrier_val: float
) -> InverterLegStates:
    """Determines instantaneous switch states by comparator logic:

    If mod_ref >= carrier -> upper switch ON (1), lower switch OFF (0).
    """
    sa = 1 if mod_wave.a >= carrier_val else 0
    sb = 1 if mod_wave.b >= carrier_val else 0
    sc = 1 if mod_wave.c >= carrier_val else 0
    return InverterLegStates.from_upper_switches(sa, sb, sc)


def find_next_crossing(
    modulating_fn: Callable[[float], float],
    carrier_fn: Callable[[float], float],
    t_now: float,
    search_window: float,
    num_subdivisions: int = 40,
    tol: float = 1e-9,
    max_bisection_iter: int = 50,
) -> float | None:
    """Finds the next switching instant (event) where modulating_fn(t) == carrier_fn(t).

    Uses bracket stepping followed by bisection root-finding.

    Args:
        modulating_fn: Scalar function of time (one of phase a, b, or c modulating waves).
        carrier_fn: Triangular carrier wave function of time.
        t_now: Current simulation timestamp.
        search_window: Time window to scan (e.g., maximum integration step size or half carrier period).
        num_subdivisions: Number of scan slices within window to bracket sign changes.
        tol: Convergence tolerance for root time in seconds.
        max_bisection_iter: Maximum bisection iterations once bracketed.

    Returns:
        The exact crossing timestamp t in (t_now, t_now + search_window], or None if no event occurs.
    """
    def diff(t: float) -> float:
        return modulating_fn(t) - carrier_fn(t)

    dt_step = search_window / num_subdivisions
    t_left = t_now
    f_left = diff(t_left)

    # 1. Step through the window to locate a sign change bracket [t_a, t_b]
    for i in range(1, num_subdivisions + 1):
        t_right = t_now + i * dt_step
        f_right = diff(t_right)

        # Detect exact zero or sign transition
        if abs(f_right) < tol:
            return t_right

        if (f_left > 0 and f_right < 0) or (f_left < 0 and f_right > 0):
            # Bracket found: [t_left, t_right]
            a, b = t_left, t_right
            fa = f_left

            # 2. Bisection refinement
            for _ in range(max_bisection_iter):
                mid = 0.5 * (a + b)
                if (b - a) < 2.0 * tol:
                    return mid

                f_mid = diff(mid)
                if abs(f_mid) < tol:
                    return mid

                if (fa > 0 and f_mid < 0) or (fa < 0 and f_mid > 0):
                    b = mid
                else:
                    a = mid
                    fa = f_mid

            return 0.5 * (a + b)

        t_left = t_right
        f_left = f_right

    return None


def find_earliest_inverter_event(
    mod_gen: ModulatingWaveGenerator,
    carrier_gen: CarrierWaveGenerator,
    t_now: float,
    max_step: float,
) -> tuple[float | None, str | None]:
    """Scans all three phases (A, B, C) and identifies the earliest upcoming switching event.

    Returns:
        (t_event, phase_label): Timestamp of the next event and which phase triggered it.
    """
    phases = [
        ("A", lambda t: mod_gen(t).a),
        ("B", lambda t: mod_gen(t).b),
        ("C", lambda t: mod_gen(t).c),
    ]

    earliest_t = None
    triggering_phase = None

    for name, m_fn in phases:
        t_cross = find_next_crossing(m_fn, carrier_gen, t_now, search_window=max_step)
        if t_cross is not None:
            if earliest_t is None or t_cross < earliest_t:
                earliest_t = t_cross
                triggering_phase = name

    return earliest_t, triggering_phase

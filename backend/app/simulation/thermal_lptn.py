"""simulation/thermal_lptn.py — 4-Node Lumped Parameter Thermal Network (LPTN) & Arrhenius RUL Model.

Replaces single-node linear thermal estimates with a 4-Node Lumped Parameter Thermal
Network (LPTN) modeling:
    1. Stator Winding (T_w)
    2. Stator Teeth & Core (T_t)
    3. Rotor Cage & Bars (T_r)
    4. Bearings (T_b)

Calculates insulation degradation and remaining useful life (RUL) using the classical
Arrhenius thermal life equation:
    Life = A * exp(E_a / (k_B * T_w))
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Physical constants for Arrhenius thermal life model
KB = 8.617333262145e-5     # Boltzmann constant in eV/K
EA_EV = 1.034              # Activation energy for Class F/H motor winding insulation (~1.034 eV)
EA_OVER_KB = 12000.0       # Ea / kB ratio in Kelvin (Montsinger ~10 degC half-life rule)
NOMINAL_LIFE_HOURS = 20000.0 # Standard design life for Class F insulation at 155 °C
RATED_INSULATION_C = 155.0   # Class F maximum hot spot rating [°C]


@dataclass
class LPTNState:
    """Instantaneous temperatures and thermal degradation metrics."""

    t_winding: float  # Stator winding temperature [°C]
    t_teeth: float    # Stator teeth & core temperature [°C]
    t_rotor: float    # Rotor cage / bars temperature [°C]
    t_bearing: float  # Drive-end bearing temperature [°C]
    t_ambient: float  # Ambient temperature [°C]
    p_copper_s: float # Stator copper loss [W]
    p_iron: float     # Stator core loss [W]
    p_copper_r: float # Rotor copper loss [W]
    p_friction: float # Bearing mechanical friction loss [W]
    arrhenius_aging_factor: float # Relative thermal aging acceleration factor
    rul_hours: float  # Remaining useful insulation life in hours
    insulation_health_pct: float # Current thermal insulation condition [0..100%]

    @property
    def ambient(self) -> float:
        return self.t_ambient

    @property
    def aging_acceleration(self) -> float:
        return self.arrhenius_aging_factor



class FourNodeThermalLPTN:
    """4-Node Lumped Parameter Thermal Network (LPTN) with Arrhenius degradation solver."""

    def __init__(
        self,
        t_ambient: float = 25.0,
        # Thermal capacitances [J/K]:
        c_w: float = 180.0,   # Stator winding copper
        c_t: float = 420.0,   # Stator teeth & laminations
        c_r: float = 250.0,   # Rotor cage aluminum/copper
        c_b: float = 85.0,    # Bearing assembly
        # Thermal resistances [K/W]:
        r_wt: float = 0.22,   # Winding to teeth conduction
        r_ta: float = 0.45,   # Teeth to ambient convective frame
        r_tr: float = 0.65,   # Stator teeth to rotor airgap
        r_rb: float = 0.55,   # Rotor shaft to bearing conduction
        r_ba: float = 0.70,   # Bearing housing to ambient
    ):
        self.t_amb = float(t_ambient)
        # Node thermal capacities
        self.c_w = c_w
        self.c_t = c_t
        self.c_r = c_r
        self.c_b = c_b

        # Conductances G = 1 / R [W/K]
        self.g_wt = 1.0 / max(r_wt, 1e-4)
        self.g_ta = 1.0 / max(r_ta, 1e-4)
        self.g_tr = 1.0 / max(r_tr, 1e-4)
        self.g_rb = 1.0 / max(r_rb, 1e-4)
        self.g_ba = 1.0 / max(r_ba, 1e-4)

        # Initial temperatures equal ambient
        self.tw = self.t_amb
        self.tt = self.t_amb
        self.tr = self.t_amb
        self.tb = self.t_amb

    def step(
        self,
        dt: float,
        p_copper_s: float,
        p_iron: float,
        p_copper_r: float,
        p_friction: float,
        itsc_extra_w: float = 0.0,
    ) -> LPTNState:
        """Integrates 4-node coupled ODEs over time step dt [s]."""
        tw, tt, tr, tb = self.tw, self.tt, self.tr, self.tb
        tamb = self.t_amb

        # Heat inputs with fault hotspot additions
        p_w = max(0.0, p_copper_s + itsc_extra_w)
        p_fe = max(0.0, p_iron)
        p_r = max(0.0, p_copper_r)
        p_b = max(0.0, p_friction)

        # Node 1: Stator winding
        d_tw = (p_w - self.g_wt * (tw - tt)) / self.c_w

        # Node 2: Stator teeth & core
        d_tt = (p_fe + self.g_wt * (tw - tt) - self.g_tr * (tt - tr) - self.g_ta * (tt - tamb)) / self.c_t

        # Node 3: Rotor cage
        d_tr = (p_r + self.g_tr * (tt - tr) - self.g_rb * (tr - tb)) / self.c_r

        # Node 4: Bearings
        d_tb = (p_b + self.g_rb * (tr - tb) - self.g_ba * (tb - tamb)) / self.c_b

        # Euler / Heun step with positive thermal bounds
        tw = max(tamb, tw + d_tw * dt)
        tt = max(tamb, tt + d_tt * dt)
        tr = max(tamb, tr + d_tr * dt)
        tb = max(tamb, tb + d_tb * dt)

        self.tw, self.tt, self.tr, self.tb = tw, tt, tr, tb

        # Arrhenius Thermal Degradation Calculation:
        # Life(T_w) = A * exp(E_a / (k_B * T_w_kelvin))
        t_w_kelvin = tw + 273.15
        t_rated_kelvin = RATED_INSULATION_C + 273.15

        # Aging acceleration factor relative to rated temperature (155 °C)
        # F_aging = exp( (E_a / k_B) * (1 / T_rated - 1 / T_w) )
        exponent = EA_OVER_KB * (1.0 / t_rated_kelvin - 1.0 / t_w_kelvin)
        # Cap exponent to avoid overflow at extreme runaway temperatures
        exponent = max(-10.0, min(10.0, exponent))
        aging_factor = math.exp(exponent)

        # Remaining useful life under current thermal loading
        rul_h = max(0.0, min(100000.0, NOMINAL_LIFE_HOURS / max(aging_factor, 1e-4)))
        insulation_health = max(0.0, min(100.0, 100.0 / max(aging_factor, 1.0)))

        return LPTNState(
            t_winding=round(tw, 2),
            t_teeth=round(tt, 2),
            t_rotor=round(tr, 2),
            t_bearing=round(tb, 2),
            t_ambient=round(tamb, 2),
            p_copper_s=round(p_copper_s, 2),
            p_iron=round(p_iron, 2),
            p_copper_r=round(p_copper_r, 2),
            p_friction=round(p_friction, 2),
            arrhenius_aging_factor=round(aging_factor, 4),
            rul_hours=round(rul_h, 1),
            insulation_health_pct=round(insulation_health, 1),
        )

"""core_physics/thermal_lptn.py

4-Node Lumped Parameter Thermal Network (LPTN) & Arrhenius RUL Model.

Models thermal dynamics of:
1. Stator Winding (T_w)
2. Stator Teeth & Core (T_t)
3. Rotor Cage & Bars (T_r)
4. Bearings (T_b)

Calculates insulation degradation and remaining useful life (RUL) using the classical
Arrhenius thermal life equation (Montsinger's rule):
    Life = A * exp(E_a / (k_B * T_w))

And bearing fatigue life per ISO 281:
    L10h = (10^6 / (60 * n)) * (C / P)^p
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Physical constants for Arrhenius thermal life model
KB = 8.617333262145e-5  # Boltzmann constant in eV/K
EA_EV = 1.034  # Activation energy for Class F/H motor winding insulation (~1.034 eV)
EA_OVER_KB = 12000.0  # Ea / kB ratio in Kelvin (Montsinger ~10°C half-life rule)
NOMINAL_LIFE_HOURS = 20000.0  # Standard design life for Class F insulation at 155°C
RATED_INSULATION_C = 155.0  # Class F maximum hot spot rating [°C]

# Bearing fatigue constants (ISO 281)
BEARING_LIFE_EXPONENT = 3.0  # p = 3 for ball bearings, 10/3 for roller


@dataclass
class LPTNState:
    """Instantaneous temperatures and thermal degradation metrics."""

    t_winding: float  # Stator winding temperature [°C]
    t_teeth: float  # Stator teeth & core temperature [°C]
    t_rotor: float  # Rotor cage / bars temperature [°C]
    t_bearing: float  # Drive-end bearing temperature [°C]
    t_ambient: float  # Ambient temperature [°C]
    p_copper_s: float  # Stator copper loss [W]
    p_iron: float  # Stator core loss [W]
    p_copper_r: float  # Rotor copper loss [W]
    p_friction: float  # Bearing mechanical friction loss [W]
    arrhenius_aging_factor: float  # Relative thermal aging acceleration factor
    rul_hours: float  # Remaining useful insulation life in hours
    insulation_health_pct: float  # Current thermal insulation condition [0..100%]
    bearing_l10h_hours: float  # Bearing L10 fatigue life [hours]

    @property
    def ambient(self) -> float:
        return self.t_ambient

    @property
    def aging_acceleration(self) -> float:
        return self.arrhenius_aging_factor


@dataclass
class ThermalNetworkParams:
    """Configurable thermal network parameters (can be calibrated per motor)."""

    # Thermal capacitances [J/K]
    c_w: float = 180.0  # Stator winding copper
    c_t: float = 420.0  # Stator teeth & laminations
    c_r: float = 250.0  # Rotor cage aluminum/copper
    c_b: float = 85.0  # Bearing assembly

    # Thermal resistances [K/W]
    r_wt: float = 0.22  # Winding to teeth conduction
    r_ta: float = 0.45  # Teeth to ambient (frame convection)
    r_tr: float = 0.65  # Stator teeth to rotor (air gap)
    r_rb: float = 0.55  # Rotor shaft to bearing conduction
    r_ba: float = 0.70  # Bearing housing to ambient

    # Loss distribution factors
    stator_copper_to_winding: float = 1.0  # Fraction of stator copper loss to winding
    stator_copper_to_teeth: float = 0.0  # Fraction to teeth (usually small)
    rotor_copper_to_rotor: float = 1.0  # Fraction of rotor copper loss to rotor
    iron_loss_to_teeth: float = 0.8  # Fraction of iron loss to teeth
    iron_loss_to_winding: float = 0.2  # Fraction to winding
    friction_to_bearing: float = 1.0  # Fraction of friction loss to bearing


class FourNodeThermalLPTN:
    """4-Node Lumped Parameter Thermal Network (LPTN) with Arrhenius degradation solver.

    Thermal circuit:
    P_cu_s ---> [C_w] ---(G_wt)---> [C_t] ---(G_ta)---> T_amb
                     |                |
                     |                |--(G_tr)---> [C_r] ---(G_rb)---> [C_b] ---(G_ba)---> T_amb
                     |
                    P_fe (split)

    State equations:
    C_w * dT_w/dt = P_w - G_wt*(T_w - T_t)
    C_t * dT_t/dt = P_fe_t + G_wt*(T_w - T_t) - G_tr*(T_t - T_r) - G_ta*(T_t - T_amb)
    C_r * dT_r/dt = P_cu_r + G_tr*(T_t - T_r) - G_rb*(T_r - T_b)
    C_b * dT_b/dt = P_fric + G_rb*(T_r - T_b) - G_ba*(T_b - T_amb)
    """

    def __init__(
        self,
        t_ambient: float = 25.0,
        params: ThermalNetworkParams | None = None,
        bearing_dynamic_capacity: float = 12000.0,  # C [N] - bearing dynamic load rating
        bearing_equivalent_load: float = 2000.0,  # P [N] - equivalent dynamic load
        shaft_speed_rpm: float = 1500.0,  # Operating speed for bearing life calc
    ):
        self.p = params if params is not None else ThermalNetworkParams()
        self.t_amb = float(t_ambient)

        # Node thermal capacities
        self.c_w = self.p.c_w
        self.c_t = self.p.c_t
        self.c_r = self.p.c_r
        self.c_b = self.p.c_b

        # Conductances G = 1/R [W/K]
        self.g_wt = 1.0 / max(self.p.r_wt, 1e-6)
        self.g_ta = 1.0 / max(self.p.r_ta, 1e-6)
        self.g_tr = 1.0 / max(self.p.r_tr, 1e-6)
        self.g_rb = 1.0 / max(self.p.r_rb, 1e-6)
        self.g_ba = 1.0 / max(self.p.r_ba, 1e-6)

        # Bearing life parameters
        self.C = bearing_dynamic_capacity
        self.P = bearing_equivalent_load
        self.n_rpm = shaft_speed_rpm

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
        winding_temp_override: float | None = None,
    ) -> LPTNState:
        """Integrates 4-node coupled ODEs over time step dt [s] using forward Euler.

        Args:
            dt: Time step [s]
            p_copper_s: Stator copper loss [W]
            p_iron: Stator core (iron) loss [W]
            p_copper_r: Rotor copper loss [W]
            p_friction: Bearing friction loss [W]
            itsc_extra_w: Extra winding loss from ITSC fault [W]
            winding_temp_override: If provided, use this instead of computed T_w for RUL calc

        Returns:
            LPTNState with updated temperatures and degradation metrics
        """
        tw, tt, tr, tb = self.tw, self.tt, self.tr, self.tb
        tamb = self.t_amb

        # Heat inputs with fault hotspot additions
        # Stator copper loss primarily heats winding, some to teeth
        p_w = max(0.0, self.p.stator_copper_to_winding * p_copper_s + itsc_extra_w)
        p_w += self.p.stator_copper_to_teeth * p_copper_s

        # Iron loss primarily heats teeth, some to winding
        p_fe = max(0.0, self.p.iron_loss_to_teeth * p_iron)
        p_w += self.p.iron_loss_to_winding * p_iron

        # Rotor copper loss heats rotor
        p_r = max(0.0, self.p.rotor_copper_to_rotor * p_copper_r)

        # Friction loss heats bearing
        p_b = max(0.0, self.p.friction_to_bearing * p_friction)

        # Node 1: Stator winding
        d_tw = (p_w - self.g_wt * (tw - tt)) / self.c_w

        # Node 2: Stator teeth & core
        d_tt = (
            p_fe
            + self.g_wt * (tw - tt)
            - self.g_tr * (tt - tr)
            - self.g_ta * (tt - tamb)
        ) / self.c_t

        # Node 3: Rotor cage
        d_tr = (p_r + self.g_tr * (tt - tr) - self.g_rb * (tr - tb)) / self.c_r

        # Node 4: Bearings
        d_tb = (p_b + self.g_rb * (tr - tb) - self.g_ba * (tb - tamb)) / self.c_b

        # Euler step with positive thermal bounds (can't go below ambient)
        tw = max(tamb, tw + d_tw * dt)
        tt = max(tamb, tt + d_tt * dt)
        tr = max(tamb, tr + d_tr * dt)
        tb = max(tamb, tb + d_tb * dt)

        self.tw, self.tt, self.tr, self.tb = tw, tt, tr, tb

        # --- Arrhenius Thermal Degradation Calculation ---
        # Life(T_w) = A * exp(E_a / (k_B * T_w_kelvin))
        # Aging acceleration factor relative to rated temperature (155°C)
        # F_aging = exp((E_a/k_B) * (1/T_rated - 1/T_w))
        t_w_kelvin = (winding_temp_override if winding_temp_override is not None else tw) + 273.15
        t_rated_kelvin = RATED_INSULATION_C + 273.15

        exponent = EA_OVER_KB * (1.0 / t_rated_kelvin - 1.0 / t_w_kelvin)
        # Cap exponent to avoid overflow at extreme runaway temperatures
        exponent = max(-10.0, min(10.0, exponent))
        aging_factor = math.exp(exponent)

        # Remaining useful life under current thermal loading
        rul_h = max(0.0, min(100000.0, NOMINAL_LIFE_HOURS / max(aging_factor, 1e-4)))
        insulation_health = max(0.0, min(100.0, 100.0 / max(aging_factor, 1.0)))

        # --- Bearing Fatigue Life (ISO 281 L10h) ---
        # L10h = (10^6 / (60 * n)) * (C / P)^p
        if self.P > 0 and self.n_rpm > 0:
            bearing_l10h = (1e6 / (60.0 * self.n_rpm)) * (self.C / self.P) ** BEARING_LIFE_EXPONENT
            # Adjust for temperature (bearing life reduces at high temp)
            # Simple approximation: halve life for every 15°C above 70°C
            if tb > 70.0:
                temp_factor = 2.0 ** ((tb - 70.0) / 15.0)
                bearing_l10h /= temp_factor
        else:
            bearing_l10h = float("inf")

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
            bearing_l10h_hours=round(bearing_l10h, 1),
        )

    def steady_state(
        self,
        p_copper_s: float,
        p_iron: float,
        p_copper_r: float,
        p_friction: float,
        itsc_extra_w: float = 0.0,
    ) -> LPTNState:
        """Compute steady-state temperatures analytically (dT/dt = 0).

        Solves linear system: G * T = P + G_amb * T_amb
        """
        import numpy as np

        # Conductance matrix
        G = np.array([
            [self.g_wt, -self.g_wt, 0, 0],
            [-self.g_wt, self.g_wt + self.g_tr + self.g_ta, -self.g_tr, 0],
            [0, -self.g_tr, self.g_tr + self.g_rb, -self.g_rb],
            [0, 0, -self.g_rb, self.g_rb + self.g_ba],
        ])

        # Power vector
        P = np.array([
            max(0.0, self.p.stator_copper_to_winding * p_copper_s + self.p.iron_loss_to_winding * p_iron + itsc_extra_w),
            max(0.0, self.p.stator_copper_to_teeth * p_copper_s + self.p.iron_loss_to_teeth * p_iron),
            max(0.0, self.p.rotor_copper_to_rotor * p_copper_r),
            max(0.0, self.p.friction_to_bearing * p_friction),
        ])

        # Ambient coupling
        G_amb = np.array([0, self.g_ta, 0, self.g_ba])
        b = P + G_amb * self.t_amb

        T = np.linalg.solve(G, b)
        tw, tt, tr, tb = T[0], T[1], T[2], T[3]

        # Compute RUL at steady state
        t_w_kelvin = tw + 273.15
        t_rated_kelvin = RATED_INSULATION_C + 273.15
        exponent = EA_OVER_KB * (1.0 / t_rated_kelvin - 1.0 / t_w_kelvin)
        exponent = max(-10.0, min(10.0, exponent))
        aging_factor = math.exp(exponent)
        rul_h = max(0.0, min(100000.0, NOMINAL_LIFE_HOURS / max(aging_factor, 1e-4)))
        insulation_health = max(0.0, min(100.0, 100.0 / max(aging_factor, 1.0)))

        if self.P > 0 and self.n_rpm > 0:
            bearing_l10h = (1e6 / (60.0 * self.n_rpm)) * (self.C / self.P) ** BEARING_LIFE_EXPONENT
            if tb > 70.0:
                temp_factor = 2.0 ** ((tb - 70.0) / 15.0)
                bearing_l10h /= temp_factor
        else:
            bearing_l10h = float("inf")

        return LPTNState(
            t_winding=round(tw, 2),
            t_teeth=round(tt, 2),
            t_rotor=round(tr, 2),
            t_bearing=round(tb, 2),
            t_ambient=round(self.t_amb, 2),
            p_copper_s=round(p_copper_s, 2),
            p_iron=round(p_iron, 2),
            p_copper_r=round(p_copper_r, 2),
            p_friction=round(p_friction, 2),
            arrhenius_aging_factor=round(aging_factor, 4),
            rul_hours=round(rul_h, 1),
            insulation_health_pct=round(insulation_health, 1),
            bearing_l10h_hours=round(bearing_l10h, 1),
        )

    def reset(self, t_ambient: float | None = None) -> None:
        """Reset all node temperatures to ambient."""
        if t_ambient is not None:
            self.t_amb = float(t_ambient)
        self.tw = self.tt = self.tr = self.tb = self.t_amb
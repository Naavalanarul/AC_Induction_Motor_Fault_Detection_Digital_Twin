"""diagnostics/rul_engine.py

Remaining Useful Life (RUL) Calculation Engine.

Implements:
1. Winding Insulation RUL: Montsinger/Arrhenius thermal aging model
   RUL_thermal = Life_base * 2^(-(T_winding - T_rated) / 10)

2. Bearing Fatigue RUL: ISO 281 L10h life calculation
   L10h = (10^6 / (60 * n)) * (C / P)^p

Dynamic equivalent load P adapts based on vibration RMS and fault severity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

import numpy as np

from app.core_physics.fault_models import BearingDefect, FaultState
from app.core_physics.thermal_lptn import FourNodeThermalLPTN, LPTNState


class InsulationClass(str, Enum):
    A = "A"  # 105°C
    B = "B"  # 130°C
    F = "F"  # 155°C
    H = "H"  # 180°C
    N = "N"  # 200°C
    R = "R"  # 220°C


INSULATION_TEMP_LIMITS = {
    InsulationClass.A: 105.0,
    InsulationClass.B: 130.0,
    InsulationClass.F: 155.0,
    InsulationClass.H: 180.0,
    InsulationClass.N: 200.0,
    InsulationClass.R: 220.0,
}


@dataclass
class InsulationRUL:
    """Insulation RUL calculation result."""

    winding_temp_c: float
    hotspot_temp_c: float
    insulation_class: InsulationClass
    rated_hotspot_c: float
    aging_acceleration_factor: float
    nominal_life_hours: float
    rul_hours: float
    rul_years: float
    health_percent: float
    temp_margin_c: float  # Margin to rated hotspot


@dataclass
class BearingRUL:
    """Bearing RUL calculation result."""

    bearing_temp_c: float
    shaft_speed_rpm: float
    dynamic_capacity_c: float  # C [N]
    equivalent_load_p: float  # P [N]
    life_exponent: float  # p = 3 (ball) or 10/3 (roller)
    l10h_hours: float  # Basic L10 life
    adjusted_l10h_hours: float  # Temperature and contamination adjusted
    rul_hours: float
    rul_years: float
    health_percent: float
    vibration_rms_mms: float  # Current vibration velocity RMS [mm/s]
    iso_zone: str  # ISO 10816 zone


@dataclass
class RULResult:
    """Combined RUL result for motor."""

    insulation: InsulationRUL
    bearing_de: BearingRUL  # Drive end bearing
    bearing_nde: BearingRUL  # Non-drive end bearing
    overall_rul_hours: float
    overall_health_percent: float
    limiting_factor: Literal["insulation", "bearing_de", "bearing_nde"]
    timestamp: float = field(default_factory=lambda: 0.0)


class RULEngine:
    """RUL calculation engine combining thermal aging and bearing fatigue models."""

    # Montsinger's rule: Life halves for every 10°C above rating
    MONTINGER_HALF_LIFE_DEG = 10.0

    # Arrhenius parameters for common insulation classes
    ARRHENIUS_PARAMS = {
        InsulationClass.A: {"Ea_eV": 0.7, "A_hours": 1e4},
        InsulationClass.B: {"Ea_eV": 0.9, "A_hours": 2e4},
        InsulationClass.F: {"Ea_eV": 1.034, "A_hours": 2e4},
        InsulationClass.H: {"Ea_eV": 1.1, "A_hours": 2.5e4},
        InsulationClass.N: {"Ea_eV": 1.2, "A_hours": 3e4},
        InsulationClass.R: {"Ea_eV": 1.3, "A_hours": 4e4},
    }

    def __init__(
        self,
        insulation_class: InsulationClass = InsulationClass.F,
        nominal_life_hours: float = 20000.0,
        # Bearing parameters (drive end)
        de_bearing_c: float = 12000.0,  # Dynamic load rating [N]
        de_bearing_p: float = 2000.0,  # Equivalent dynamic load [N]
        de_bearing_type: Literal["ball", "roller"] = "ball",
        # Bearing parameters (non-drive end)
        nde_bearing_c: float = 10000.0,
        nde_bearing_p: float = 1500.0,
        nde_bearing_type: Literal["ball", "roller"] = "ball",
        # Operating conditions
        shaft_speed_rpm: float = 1500.0,
        ambient_temp_c: float = 25.0,
    ):
        self.insulation_class = insulation_class
        self.nominal_life_hours = nominal_life_hours
        self.rated_hotspot_c = INSULATION_TEMP_LIMITS[insulation_class]

        # Bearing parameters
        self.de_bearing_c = de_bearing_c
        self.de_bearing_p = de_bearing_p
        self.de_bearing_type = de_bearing_type
        self.de_life_exp = 3.0 if de_bearing_type == "ball" else 10.0 / 3.0

        self.nde_bearing_c = nde_bearing_c
        self.nde_bearing_p = nde_bearing_p
        self.nde_bearing_type = nde_bearing_type
        self.nde_life_exp = 3.0 if nde_bearing_type == "ball" else 10.0 / 3.0

        self.shaft_speed_rpm = shaft_speed_rpm
        self.ambient_temp_c = ambient_temp_c

        # Thermal model for temperature tracking
        self.thermal_model = FourNodeThermalLPTN(
            t_ambient=ambient_temp_c,
            bearing_dynamic_capacity=de_bearing_c,
            bearing_equivalent_load=de_bearing_p,
            shaft_speed_rpm=shaft_speed_rpm,
        )

    def calculate_insulation_rul(self, lptn_state: LPTNState) -> InsulationRUL:
        """Calculate insulation RUL using Montsinger/Arrhenius model.

        Two methods:
        1. Montsinger (simplified): Life = Life_rated * 2^((T_rated - T_actual) / 10)
        2. Arrhenius (physics-based): Life = A * exp(Ea / (k_B * T))

        We use Montsinger for consistency with industry practice,
        and Arrhenius for the aging acceleration factor.
        """
        t_w = lptn_state.t_winding
        t_hotspot = t_w + 5.0  # Hotspot typically 5-10°C above average winding

        # Montsinger's rule (base 2 exponential)
        temp_diff = t_hotspot - self.rated_hotspot_c
        montsinger_factor = 2.0 ** (-temp_diff / self.MONTINGER_HALF_LIFE_DEG)
        rul_montsinger = self.nominal_life_hours * montsinger_factor

        # Arrhenius aging acceleration factor
        # F_aging = exp((Ea/kB) * (1/T_rated - 1/T_actual))
        KB = 8.617333262145e-5  # eV/K
        params = self.ARRHENIUS_PARAMS[self.insulation_class]
        Ea = params["Ea_eV"]
        T_rated_k = self.rated_hotspot_c + 273.15
        T_actual_k = t_hotspot + 273.15
        exponent = (Ea / KB) * (1.0 / T_rated_k - 1.0 / T_actual_k)
        exponent = max(-15.0, min(15.0, exponent))  # Clamp for numerical stability
        aging_factor = math.exp(exponent)

        # Use Arrhenius for aging factor (more physical), Montsinger for RUL
        rul_hours = max(0.0, min(rul_montsinger, 100000.0))
        health = max(0.0, min(100.0, 100.0 / max(aging_factor, 1.0)))

        return InsulationRUL(
            winding_temp_c=round(t_w, 1),
            hotspot_temp_c=round(t_hotspot, 1),
            insulation_class=self.insulation_class,
            rated_hotspot_c=self.rated_hotspot_c,
            aging_acceleration_factor=round(aging_factor, 4),
            nominal_life_hours=self.nominal_life_hours,
            rul_hours=round(rul_hours, 1),
            rul_years=round(rul_hours / 8760.0, 2),
            health_percent=round(health, 1),
            temp_margin_c=round(self.rated_hotspot_c - t_hotspot, 1),
        )

    def calculate_bearing_rul(
        self,
        lptn_state: LPTNState,
        vibration_rms_mms: float,
        fault_state: FaultState | None = None,
        is_drive_end: bool = True,
    ) -> BearingRUL:
        """Calculate bearing RUL using ISO 281 L10h with condition adjustments.

        Basic L10h = (10^6 / (60 * n)) * (C / P)^p

        Adjustments:
        - Temperature: Life reduces at high temperatures
        - Vibration: Higher vibration indicates increased dynamic load
        - Fault severity: Bearing defects increase effective load
        """
        if is_drive_end:
            C = self.de_bearing_c
            P_base = self.de_bearing_p
            p = self.de_life_exp
            bearing_temp = lptn_state.t_bearing
        else:
            C = self.nde_bearing_c
            P_base = self.nde_bearing_p
            p = self.nde_life_exp
            # NDE bearing typically runs cooler
            bearing_temp = max(lptn_state.t_bearing - 5.0, lptn_state.t_ambient)

        n = self.shaft_speed_rpm

        # Basic L10h life [hours]
        l10h = (1e6 / (60.0 * n)) * (C / P_base) ** p

        # Temperature adjustment (SKF model)
        # For ball bearings, life reduction factor above 70°C
        temp_factor = 1.0
        if bearing_temp > 70.0:
            # Approximate: halve life for every 15°C above 70°C
            temp_factor = 2.0 ** ((bearing_temp - 70.0) / 15.0)

        # Vibration-based load adjustment
        # ISO 10816 zones correlate with dynamic load increases
        # Zone A (<2.3 mm/s): factor 1.0
        # Zone B (2.3-4.5): factor 1.2
        # Zone C (4.5-7.1): factor 1.5
        # Zone D (>7.1): factor 2.0+
        vib_factor = 1.0
        if vibration_rms_mms > 7.1:
            vib_factor = 2.0 + (vibration_rms_mms - 7.1) * 0.2
        elif vibration_rms_mms > 4.5:
            vib_factor = 1.5
        elif vibration_rms_mms > 2.3:
            vib_factor = 1.2

        # Fault severity adjustment
        fault_factor = 1.0
        if fault_state is not None:
            # Check for bearing faults
            max_bearing_sev = max(fault_state.bearing(d) for d in BearingDefect)
            if max_bearing_sev > 0:
                # Bearing defect increases effective load significantly
                fault_factor = 1.0 + 3.0 * max_bearing_sev  # Up to 4× load

        # Combined adjusted life
        total_factor = temp_factor * vib_factor * fault_factor
        adjusted_l10h = l10h / total_factor

        # RUL is adjusted L10h (assuming we're at time zero for new bearing)
        # In practice, would track elapsed life fraction
        rul_hours = max(0.0, min(adjusted_l10h, 100000.0))
        health = max(0.0, min(100.0, 100.0 / total_factor))

        # ISO 10816 zone
        iso_zone = self._iso10816_zone(vibration_rms_mms)

        return BearingRUL(
            bearing_temp_c=round(bearing_temp, 1),
            shaft_speed_rpm=n,
            dynamic_capacity_c=C,
            equivalent_load_p=round(P_base * vib_factor * fault_factor, 1),
            life_exponent=p,
            l10h_hours=round(l10h, 1),
            adjusted_l10h_hours=round(adjusted_l10h, 1),
            rul_hours=round(rul_hours, 1),
            rul_years=round(rul_hours / 8760.0, 2),
            health_percent=round(health, 1),
            vibration_rms_mms=round(vibration_rms_mms, 2),
            iso_zone=iso_zone,
        )

    def _iso10816_zone(self, vel_rms_mm_s: float) -> str:
        """Classify per ISO 10816-3 for 15-75 kW machines."""
        if vel_rms_mm_s < 2.3:
            return "A"
        elif vel_rms_mm_s < 4.5:
            return "B"
        elif vel_rms_mm_s < 7.1:
            return "C"
        else:
            return "D"

    def compute_rul(
        self,
        lptn_state: LPTNState,
        vibration_rms_mms: float,
        fault_state: FaultState | None = None,
        timestamp: float = 0.0,
    ) -> RULResult:
        """Compute complete RUL for motor.

        Args:
            lptn_state: Current thermal state from LPTN
            vibration_rms_mms: Overall vibration velocity RMS [mm/s]
            fault_state: Current fault state for bearing load adjustment
            timestamp: Current simulation time [hours]

        Returns:
            RULResult with insulation and bearing RUL
        """
        insulation = self.calculate_insulation_rul(lptn_state)
        bearing_de = self.calculate_bearing_rul(lptn_state, vibration_rms_mms, fault_state, is_drive_end=True)
        bearing_nde = self.calculate_bearing_rul(lptn_state, vibration_rms_mms * 0.8, fault_state, is_drive_end=False)

        # Overall RUL is minimum of all components
        rul_values: list[tuple[Literal["insulation", "bearing_de", "bearing_nde"], float]] = [
            ("insulation", insulation.rul_hours),
            ("bearing_de", bearing_de.rul_hours),
            ("bearing_nde", bearing_nde.rul_hours),
        ]
        limiting_factor, overall_rul = min(rul_values, key=lambda x: x[1])

        # Overall health is weighted average (insulation 50%, bearings 25% each)
        overall_health = (
            0.5 * insulation.health_percent
            + 0.25 * bearing_de.health_percent
            + 0.25 * bearing_nde.health_percent
        )

        return RULResult(
            insulation=insulation,
            bearing_de=bearing_de,
            bearing_nde=bearing_nde,
            overall_rul_hours=round(overall_rul, 1),
            overall_health_percent=round(overall_health, 1),
            limiting_factor=limiting_factor,
            timestamp=timestamp,
        )

    def predict_rul_from_trend(
        self,
        history: list[tuple[float, float]],  # (time_hours, health_percent)
        threshold_health: float = 20.0,
    ) -> tuple[float, float]:
        """Project RUL from health trend using linear extrapolation.

        Args:
            history: List of (time_hours, health_percent) points
            threshold_health: Health percentage at which replacement is needed

        Returns:
            (projected_rul_hours, confidence)
        """
        if len(history) < 3:
            return 0.0, 0.0

        times = np.array([h[0] for h in history])
        health = np.array([h[1] for h in history])

        # Linear fit
        coeffs = np.polyfit(times, health, 1)
        slope = coeffs[0]  # health loss per hour

        if slope >= 0:
            return float("inf"), 0.0  # Health improving or stable

        current_health = health[-1]
        if current_health <= threshold_health:
            return 0.0, 1.0

        rul = (current_health - threshold_health) / (-slope)

        # Confidence based on R²
        pred = np.polyval(coeffs, times)
        ss_res = np.sum((health - pred) ** 2)
        ss_tot = np.sum((health - np.mean(health)) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        return max(0.0, rul), float(max(0.0, r2))

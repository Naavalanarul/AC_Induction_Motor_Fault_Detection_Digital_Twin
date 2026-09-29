"""diagnostics/fault_classifier.py

Fault Classification Engine.

Implements threshold-based fault detection and classification using:
- MCSA spectral signatures (BRB, Eccentricity, ITSC)
- Vibration analysis (Bearing faults, Unbalance, Misalignment)
- Thermal monitoring (Overheating, Insulation degradation)
- ISO 10816 vibration severity standards
- Electrical residual analysis

Each fault type has specific spectral/temporal signatures and thresholds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

from app.core_physics.fault_models import FaultState, FaultType
from app.signal_processing.feature_extraction import SignalFeatures
from app.signal_processing.mcsa_pipeline import MCSAResult
from app.signal_processing.vibration_analysis import VibrationResult


class FaultSeverity(str, Enum):
    """Fault severity levels."""
    NONE = "none"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class FaultCategory(str, Enum):
    """Fault categories."""
    ELECTRICAL = "electrical"
    MECHANICAL = "mechanical"
    THERMAL = "thermal"
    BEARING = "bearing"


@dataclass
class FaultDiagnosis:
    """Individual fault diagnosis result."""

    fault_type: FaultType
    category: FaultCategory
    severity: FaultSeverity
    confidence: float  # 0.0 to 1.0
    evidence: list[str]  # Human-readable evidence
    metrics: dict[str, Any]  # Supporting quantitative metrics
    threshold_used: dict[str, Any]  # Thresholds that triggered
    recommended_action: str


@dataclass
class ISO10816Zone:
    """ISO 10816 vibration severity zone assessment."""

    zone: Literal["A", "B", "C", "D"]
    velocity_rms_mm_s: float
    velocity_peak_mm_s: float
    displacement_peak_um: float
    acceleration_rms_ms2: float
    machine_class: str
    assessment: str


# Thresholds for fault detection (configurable per motor size/type)
DEFAULT_THRESHOLDS = {
    # MCSA thresholds (dBc relative to fundamental)
    "brb_sideband_dbc": -45.0,  # BRB (1±2s)f sideband threshold
    "ecc_sideband_dbc": -45.0,  # Eccentricity f±fr sideband threshold
    "neg_seq_dbc": -40.0,  # Negative sequence for ITSC
    "thd_percent": 5.0,  # Total harmonic distortion
    # Vibration thresholds (ISO 10816-3 for 15-75 kW)
    "iso_zone_a_max": 2.3,  # mm/s velocity RMS
    "iso_zone_b_max": 4.5,
    "iso_zone_c_max": 7.1,
    # Bearing envelope thresholds (gE - envelope acceleration)
    "bearing_bpfo_ge": 0.5,
    "bearing_bpfi_ge": 0.5,
    "bearing_bsf_ge": 0.3,
    # Spectral kurtosis
    "spectral_kurtosis": 3.0,  # > 3 indicates impulsiveness
    # Thermal thresholds
    "winding_warn_c": 110.0,
    "winding_trip_c": 140.0,
    "bearing_warn_c": 80.0,
    "bearing_trip_c": 100.0,
    # Electrical residual
    "residual_fd_threshold": 0.015,  # Fault detection index
    "residual_fl_threshold": 1.25,  # Fault localization index
}


class FaultClassifier:
    """Threshold-based fault classifier for induction motors."""

    def __init__(
        self,
        thresholds: dict | None = None,
        motor_rated_power: float = 1500.0,  # W
        motor_rated_speed: float = 1474.0,  # RPM
    ):
        """Initialize classifier with thresholds.

        Args:
            thresholds: Custom thresholds (merged with defaults)
            motor_rated_power: Motor rated power [W]
            motor_rated_speed: Motor rated speed [RPM]
        """
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        self.motor_rated_power = motor_rated_power
        self.motor_rated_speed = motor_rated_speed

    def classify(
        self,
        mcsa_result: MCSAResult | None,
        vibration_result: VibrationResult | None,
        thermal_state: dict | None,
        electrical_residual: dict | None,
        fault_state: FaultState | None = None,
    ) -> list[FaultDiagnosis]:
        """Run complete fault classification.

        Args:
            mcsa_result: MCSA analysis result
            vibration_result: Vibration analysis result
            thermal_state: Thermal state dict (t_winding, t_bearing, etc.)
            electrical_residual: Electrical residual diagnostic result
            fault_state: Current injected faults (for reference)

        Returns:
            List of FaultDiagnosis objects (empty if no faults detected)
        """
        diagnoses = []

        # 1. MCSA-based faults
        if mcsa_result is not None:
            diagnoses.extend(self._classify_mcsa(mcsa_result))

        # 2. Vibration-based faults
        if vibration_result is not None:
            diagnoses.extend(self._classify_vibration(vibration_result))

        # 3. Thermal faults
        if thermal_state is not None:
            diagnoses.extend(self._classify_thermal(thermal_state))

        # 4. Electrical residual faults
        if electrical_residual is not None:
            diagnoses.extend(self._classify_electrical_residual(electrical_residual))

        # Sort by severity (critical first)
        severity_order = {
            FaultSeverity.CRITICAL: 0,
            FaultSeverity.HIGH: 1,
            FaultSeverity.MODERATE: 2,
            FaultSeverity.LOW: 3,
            FaultSeverity.NONE: 4,
        }
        diagnoses.sort(key=lambda d: severity_order.get(d.severity, 5))

        return diagnoses

    def _classify_mcsa(self, mcsa: MCSAResult) -> list[FaultDiagnosis]:
        """Classify faults from MCSA results."""
        diagnoses = []

        # --- Broken Rotor Bar (BRB) ---
        if mcsa.brb_peaks:
            worst_brb = max(mcsa.brb_peaks, key=lambda p: p.magnitude_db)
            threshold = self.thresholds["brb_sideband_dbc"]

            if worst_brb.magnitude_db > threshold:
                # Determine severity based on sideband level
                if worst_brb.magnitude_db > -30:
                    sev = FaultSeverity.CRITICAL
                elif worst_brb.magnitude_db > -35:
                    sev = FaultSeverity.HIGH
                elif worst_brb.magnitude_db > -40:
                    sev = FaultSeverity.MODERATE
                else:
                    sev = FaultSeverity.LOW

                diagnoses.append(FaultDiagnosis(
                    fault_type=FaultType.BROKEN_ROTOR_BAR,
                    category=FaultCategory.ELECTRICAL,
                    severity=sev,
                    confidence=min(1.0, (worst_brb.magnitude_db - threshold) / 15.0 + 0.5),
                    evidence=[
                        f"BRB sideband at {worst_brb.freq_hz:.1f} Hz "
                        f"({worst_brb.magnitude_db:.1f} dBc, k={worst_brb.harmonic_k}, {worst_brb.sideband_type})",
                        f"Slip: {mcsa.slip:.4f}, Expected: {mcsa.fundamental_freq * (1 - 2 * mcsa.slip):.1f} Hz",
                    ],
                    metrics={
                        "worst_brb_sideband_dbc": worst_brb.magnitude_db,
                        "slip": mcsa.slip,
                        "num_brb_peaks": len(mcsa.brb_peaks),
                    },
                    threshold_used={"brb_sideband_dbc": threshold},
                    recommended_action="Schedule rotor inspection/replacement. Monitor sideband growth trend."
                ))

        # --- Eccentricity ---
        if mcsa.ecc_peaks:
            worst_ecc = max(mcsa.ecc_peaks, key=lambda p: p.magnitude_db)
            threshold = self.thresholds["ecc_sideband_dbc"]

            if worst_ecc.magnitude_db > threshold:
                if worst_ecc.magnitude_db > -30:
                    sev = FaultSeverity.HIGH
                elif worst_ecc.magnitude_db > -35:
                    sev = FaultSeverity.MODERATE
                else:
                    sev = FaultSeverity.LOW

                diagnoses.append(FaultDiagnosis(
                    fault_type=FaultType.ECCENTRICITY,
                    category=FaultCategory.MECHANICAL,
                    severity=sev,
                    confidence=min(1.0, (worst_ecc.magnitude_db - threshold) / 15.0 + 0.5),
                    evidence=[
                        f"Eccentricity sideband at {worst_ecc.freq_hz:.1f} Hz "
                        f"({worst_ecc.magnitude_db:.1f} dBc, k={worst_ecc.harmonic_k}, {worst_ecc.sideband_type})",
                        f"Rotor freq: {mcsa.rotor_freq_hz:.1f} Hz",
                    ],
                    metrics={
                        "worst_ecc_sideband_dbc": worst_ecc.magnitude_db,
                        "rotor_freq_hz": mcsa.rotor_freq_hz,
                        "num_ecc_peaks": len(mcsa.ecc_peaks),
                    },
                    threshold_used={"ecc_sideband_dbc": threshold},
                    recommended_action="Check air-gap uniformity, bearing clearance, and shaft alignment."
                ))

        # --- Inter-Turn Short Circuit (ITSC) ---
        if mcsa.negative_seq_mag_db is not None:
            threshold = self.thresholds["neg_seq_dbc"]
            if mcsa.negative_seq_mag_db > threshold:
                sev = FaultSeverity.HIGH if mcsa.negative_seq_mag_db > -30 else FaultSeverity.MODERATE
                diagnoses.append(FaultDiagnosis(
                    fault_type=FaultType.INTERTURN_SHORT,
                    category=FaultCategory.ELECTRICAL,
                    severity=sev,
                    confidence=min(1.0, (mcsa.negative_seq_mag_db - threshold) / 10.0 + 0.5),
                    evidence=[
                        f"Negative sequence component: {mcsa.negative_seq_mag_db:.1f} dBc",
                        "Indicates phase imbalance from shorted turns",
                    ],
                    metrics={
                        "negative_seq_dbc": mcsa.negative_seq_mag_db,
                        "thd_percent": mcsa.thd_percent,
                    },
                    threshold_used={"neg_seq_dbc": threshold},
                    recommended_action="Immediate offline insulation testing (surge test). Plan winding repair."
                ))

        # --- High THD ---
        if mcsa.thd_percent > self.thresholds["thd_percent"]:
            diagnoses.append(FaultDiagnosis(
                fault_type=FaultType.VOLTAGE_ANOMALY if mcsa.thd_percent < 10 else FaultType.INTERTURN_SHORT,
                category=FaultCategory.ELECTRICAL,
                severity=FaultSeverity.MODERATE if mcsa.thd_percent < 10 else FaultSeverity.HIGH,
                confidence=0.7,
                evidence=[f"THD = {mcsa.thd_percent:.1f}% (threshold: {self.thresholds['thd_percent']}%)"],
                metrics={"thd_percent": mcsa.thd_percent},
                threshold_used={"thd_percent": self.thresholds["thd_percent"]},
                recommended_action="Check supply voltage quality. Verify VFD settings if applicable."
            ))

        return diagnoses

    def _classify_vibration(self, vib: VibrationResult) -> list[FaultDiagnosis]:
        """Classify faults from vibration analysis."""
        diagnoses = []

        # --- ISO 10816 Overall Severity ---
        iso_zone = self._assess_iso10816(vib.overall_velocity_rms, vib.bearing_freqs.bpfo_hz)
        if iso_zone.zone in ("C", "D"):
            sev = FaultSeverity.HIGH if iso_zone.zone == "C" else FaultSeverity.CRITICAL
            diagnoses.append(FaultDiagnosis(
                fault_type=FaultType.UNBALANCE,  # Generic mechanical
                category=FaultCategory.MECHANICAL,
                severity=sev,
                confidence=0.9,
                evidence=[
                    f"ISO 10816 Zone {iso_zone.zone}: "
                    f"Velocity RMS = {iso_zone.velocity_rms_mm_s:.1f} mm/s",
                    f"Assessment: {iso_zone.assessment}",
                ],
                metrics={
                    "velocity_rms_mm_s": iso_zone.velocity_rms_mm_s,
                    "velocity_peak_mm_s": iso_zone.velocity_peak_mm_s,
                    "iso_zone": iso_zone.zone,
                },
                threshold_used={
                    "iso_zone_c_max": self.thresholds["iso_zone_c_max"],
                    "iso_zone_d_min": self.thresholds["iso_zone_c_max"],
                },
                recommended_action=(
                    "Immediate investigation required. Check alignment, balance, bearings, and foundation."
                    if iso_zone.zone == "D"
                    else "Schedule detailed vibration analysis. Plan corrective action."
                )
            ))

        # --- Bearing Faults (envelope analysis) ---
        bearing_freqs = vib.bearing_freqs

        # BPFO - Outer race
        if vib.bpfo_amplitude > self.thresholds["bearing_bpfo_ge"]:
            sev = self._severity_from_amplitude(vib.bpfo_amplitude, self.thresholds["bearing_bpfo_ge"])
            diagnoses.append(FaultDiagnosis(
                fault_type=FaultType.BEARING_OUTER,
                category=FaultCategory.BEARING,
                severity=sev,
                confidence=min(1.0, vib.bpfo_amplitude / self.thresholds["bearing_bpfo_ge"] * 0.7),
                evidence=[
                    f"BPFO ({bearing_freqs.bpfo_hz:.1f} Hz) envelope amplitude: "
                    f"{vib.bpfo_amplitude:.2f} gE",
                    f"Spectral kurtosis: {vib.spectral_kurtosis:.2f}",
                ],
                metrics={
                    "bpfo_amplitude_ge": vib.bpfo_amplitude,
                    "bpfo_freq_hz": bearing_freqs.bpfo_hz,
                    "spectral_kurtosis": vib.spectral_kurtosis,
                },
                threshold_used={"bearing_bpfo_ge": self.thresholds["bearing_bpfo_ge"]},
                recommended_action="Plan bearing replacement. Monitor envelope trend weekly."
            ))

        # BPFI - Inner race
        if vib.bpfi_amplitude > self.thresholds["bearing_bpfi_ge"]:
            sev = self._severity_from_amplitude(vib.bpfi_amplitude, self.thresholds["bearing_bpfi_ge"])
            diagnoses.append(FaultDiagnosis(
                fault_type=FaultType.BEARING_INNER,
                category=FaultCategory.BEARING,
                severity=sev,
                confidence=min(1.0, vib.bpfi_amplitude / self.thresholds["bearing_bpfi_ge"] * 0.7),
                evidence=[
                    f"BPFI ({bearing_freqs.bpfi_hz:.1f} Hz) envelope amplitude: "
                    f"{vib.bpfi_amplitude:.2f} gE",
                ],
                metrics={
                    "bpfi_amplitude_ge": vib.bpfi_amplitude,
                    "bpfi_freq_hz": bearing_freqs.bpfi_hz,
                },
                threshold_used={"bearing_bpfi_ge": self.thresholds["bearing_bpfi_ge"]},
                recommended_action="Plan bearing replacement. Inner race faults progress faster - monitor closely."
            ))

        # BSF - Ball spin (2×BSF)
        if vib.bsf_amplitude > self.thresholds["bearing_bsf_ge"]:
            sev = self._severity_from_amplitude(vib.bsf_amplitude, self.thresholds["bearing_bsf_ge"])
            diagnoses.append(FaultDiagnosis(
                fault_type=FaultType.BEARING_BALL,
                category=FaultCategory.BEARING,
                severity=sev,
                confidence=min(1.0, vib.bsf_amplitude / self.thresholds["bearing_bsf_ge"] * 0.6),
                evidence=[
                    f"2×BSF ({bearing_freqs.bsf_hz:.1f} Hz) envelope amplitude: "
                    f"{vib.bsf_amplitude:.2f} gE",
                ],
                metrics={
                    "bsf_amplitude_ge": vib.bsf_amplitude,
                    "bsf_freq_hz": bearing_freqs.bsf_hz,
                },
                threshold_used={"bearing_bsf_ge": self.thresholds["bearing_bsf_ge"]},
                recommended_action="Ball defect detected. Schedule bearing replacement."
            ))

        # --- Spectral Kurtosis (general impulsiveness) ---
        if vib.spectral_kurtosis > self.thresholds["spectral_kurtosis"]:
            diagnoses.append(FaultDiagnosis(
                fault_type=FaultType.BEARING_BALL,
                category=FaultCategory.BEARING,
                severity=FaultSeverity.MODERATE,
                confidence=0.6,
                evidence=[
                    f"Spectral kurtosis = {vib.spectral_kurtosis:.2f} "
                    f"(threshold: {self.thresholds['spectral_kurtosis']})",
                    "Indicates impulsive vibration content, likely bearing defect",
                ],
                metrics={"spectral_kurtosis": vib.spectral_kurtosis},
                threshold_used={"spectral_kurtosis": self.thresholds["spectral_kurtosis"]},
                recommended_action="Perform detailed envelope analysis. Check all bearings."
            ))

        # --- Unbalance / Misalignment (from order tracking) ---
        if vib.order_1x > 2.0:  # Normalized threshold
            diagnoses.append(FaultDiagnosis(
                fault_type=FaultType.UNBALANCE,
                category=FaultCategory.MECHANICAL,
                severity=FaultSeverity.MODERATE,
                confidence=0.7,
                evidence=[f"1× shaft order amplitude: {vib.order_1x:.2f} (normalized)"],
                metrics={"order_1x": vib.order_1x, "order_2x": vib.order_2x},
                threshold_used={"order_1x": 2.0},
                recommended_action="Perform rotor balancing. Check for shaft bow or buildup."
            ))

        if vib.order_2x > 1.5 and vib.order_2x > vib.order_1x * 0.5:
            diagnoses.append(FaultDiagnosis(
                fault_type=FaultType.MISALIGNMENT,
                category=FaultCategory.MECHANICAL,
                severity=FaultSeverity.MODERATE,
                confidence=0.7,
                evidence=[f"2× shaft order amplitude: {vib.order_2x:.2f} (normalized)"],
                metrics={"order_1x": vib.order_1x, "order_2x": vib.order_2x},
                threshold_used={"order_2x": 1.5},
                recommended_action="Check coupling alignment. Verify soft foot condition."
            ))

        return diagnoses

    def _classify_thermal(self, thermal: dict) -> list[FaultDiagnosis]:
        """Classify thermal faults."""
        diagnoses = []

        t_winding = thermal.get("t_winding", 0.0)
        t_bearing = thermal.get("t_bearing", 0.0)
        t_ambient = thermal.get("t_ambient", 25.0)
        aging_factor = thermal.get("arrhenius_aging_factor", 1.0)

        # Winding overtemperature
        if t_winding > self.thresholds["winding_trip_c"]:
            sev = FaultSeverity.CRITICAL
        elif t_winding > self.thresholds["winding_warn_c"]:
            sev = FaultSeverity.HIGH
        else:
            sev = FaultSeverity.NONE

        if sev != FaultSeverity.NONE:
            diagnoses.append(FaultDiagnosis(
                fault_type=FaultType.VOLTAGE_ANOMALY,  # Closest match for overheating
                category=FaultCategory.THERMAL,
                severity=sev,
                confidence=0.95,
                evidence=[
                    f"Winding temperature: {t_winding:.1f}°C "
                    f"(warning: {self.thresholds['winding_warn_c']}°C, "
                    f"trip: {self.thresholds['winding_trip_c']}°C)",
                    f"Ambient: {t_ambient:.1f}°C, Rise: {t_winding - t_ambient:.1f}°C",
                    f"Aging acceleration: {aging_factor:.2f}×",
                ],
                metrics={
                    "t_winding_c": t_winding,
                    "temp_rise_c": t_winding - t_ambient,
                    "aging_factor": aging_factor,
                },
                threshold_used={
                    "winding_warn_c": self.thresholds["winding_warn_c"],
                    "winding_trip_c": self.thresholds["winding_trip_c"],
                },
                recommended_action=(
                    "EMERGENCY: Reduce load or shut down immediately. Check cooling, ventilation, and loading."
                    if sev == FaultSeverity.CRITICAL
                    else "Investigate cooling system. Reduce load if possible. Monitor closely."
                )
            ))

        # Bearing overtemperature
        if t_bearing > self.thresholds["bearing_trip_c"]:
            sev = FaultSeverity.CRITICAL
        elif t_bearing > self.thresholds["bearing_warn_c"]:
            sev = FaultSeverity.HIGH
        else:
            sev = FaultSeverity.NONE

        if sev != FaultSeverity.NONE:
            diagnoses.append(FaultDiagnosis(
                fault_type=FaultType.BEARING_OUTER,  # Generic bearing fault
                category=FaultCategory.THERMAL,
                severity=sev,
                confidence=0.9,
                evidence=[
                    f"Bearing temperature: {t_bearing:.1f}°C "
                    f"(warning: {self.thresholds['bearing_warn_c']}°C, "
                    f"trip: {self.thresholds['bearing_trip_c']}°C)",
                ],
                metrics={"t_bearing_c": t_bearing},
                threshold_used={
                    "bearing_warn_c": self.thresholds["bearing_warn_c"],
                    "bearing_trip_c": self.thresholds["bearing_trip_c"],
                },
                recommended_action=(
                    "Check bearing lubrication, alignment, and loading. Plan bearing replacement."
                    if sev == FaultSeverity.HIGH
                    else "EMERGENCY: Shut down. Bearing failure imminent."
                )
            ))

        return diagnoses

    def _classify_electrical_residual(self, residual: dict) -> list[FaultDiagnosis]:
        """Classify faults from electrical residual analysis."""
        diagnoses: list[FaultDiagnosis] = []

        fd = residual.get("FD", 0.0)
        fl = residual.get("FL", [1.0, 1.0, 1.0])
        fl_phase = residual.get("FL_phase", "a")
        energy_share = residual.get("energy_share", {})
        slip = residual.get("slip", 0.0)

        if fd < self.thresholds["residual_fd_threshold"]:
            return diagnoses

        # Determine fault type from energy distribution
        brb_energy = energy_share.get("brb", 0.0)
        ecc_energy = energy_share.get("ecc_dyn", 0.0)
        neg_energy = energy_share.get("neg", 0.0)
        fund_energy = energy_share.get("fund", 0.0)

        localized = max(fl) > self.thresholds["residual_fl_threshold"]

        if localized and (neg_energy + fund_energy) > 0.5:
            # ITSC - localized phase with negative sequence
            diagnoses.append(FaultDiagnosis(
                fault_type=FaultType.INTERTURN_SHORT,
                category=FaultCategory.ELECTRICAL,
                severity=FaultSeverity.HIGH,
                confidence=min(1.0, max(fl) - 1.0),
                evidence=[
                    f"Phase {fl_phase.upper()} residual FL = {max(fl):.2f} "
                    f"(threshold: {self.thresholds['residual_fl_threshold']})",
                    f"Negative sequence energy share: {neg_energy:.1%}",
                    f"FD index: {fd:.3f} (threshold: {self.thresholds['residual_fd_threshold']})",
                ],
                metrics={
                    "FD": fd,
                    "FL": fl,
                    "FL_phase": fl_phase,
                    "slip": slip,
                    "energy_share": energy_share,
                },
                threshold_used={
                    "residual_fd_threshold": self.thresholds["residual_fd_threshold"],
                    "residual_fl_threshold": self.thresholds["residual_fl_threshold"],
                },
                recommended_action="Offline surge testing recommended. Localized winding fault confirmed."
            ))
        elif ecc_energy > max(brb_energy, fund_energy):
            # Eccentricity
            diagnoses.append(FaultDiagnosis(
                fault_type=FaultType.ECCENTRICITY,
                category=FaultCategory.MECHANICAL,
                severity=FaultSeverity.MODERATE,
                confidence=ecc_energy * 1.5,
                evidence=[
                    f"Dynamic eccentricity energy share: {ecc_energy:.1%}",
                    f"FD index: {fd:.3f}",
                ],
                metrics={
                    "FD": fd,
                    "energy_share": energy_share,
                    "slip": slip,
                },
                threshold_used={"residual_fd_threshold": self.thresholds["residual_fd_threshold"]},
                recommended_action="Check air-gap uniformity and bearing clearances."
            ))
        elif brb_energy > 0.3:
            # Broken rotor bar
            diagnoses.append(FaultDiagnosis(
                fault_type=FaultType.BROKEN_ROTOR_BAR,
                category=FaultCategory.ELECTRICAL,
                severity=FaultSeverity.MODERATE,
                confidence=brb_energy + 0.5 * fund_energy,
                evidence=[
                    f"BRB sideband energy share: {brb_energy:.1%}",
                    f"FD index: {fd:.3f}, Slip: {slip:.4f}",
                ],
                metrics={
                    "FD": fd,
                    "energy_share": energy_share,
                    "slip": slip,
                },
                threshold_used={"residual_fd_threshold": self.thresholds["residual_fd_threshold"]},
                recommended_action="Monitor BRB sideband trend. Plan rotor inspection at next outage."
            ))

        return diagnoses

    def _severity_from_amplitude(self, amplitude: float, threshold: float) -> FaultSeverity:
        """Determine severity from amplitude vs threshold ratio."""
        ratio = amplitude / threshold
        if ratio > 3.0:
            return FaultSeverity.CRITICAL
        elif ratio > 2.0:
            return FaultSeverity.HIGH
        elif ratio > 1.5:
            return FaultSeverity.MODERATE
        else:
            return FaultSeverity.LOW

    def _assess_iso10816(self, vel_rms_mm_s: float, bpfo_hz: float) -> ISO10816Zone:
        """Assess ISO 10816 severity zone."""
        zone: Literal["A", "B", "C", "D"]
        if vel_rms_mm_s < self.thresholds["iso_zone_a_max"]:
            zone = "A"
            assessment = "Good - Newly commissioned or recently overhauled machines"
        elif vel_rms_mm_s < self.thresholds["iso_zone_b_max"]:
            zone = "B"
            assessment = "Acceptable - Normal operation, suitable for long-term operation"
        elif vel_rms_mm_s < self.thresholds["iso_zone_c_max"]:
            zone = "C"
            assessment = "Warning - Reduced bearing life, plan corrective action"
        else:
            zone = "D"
            assessment = "Danger - Immediate shutdown recommended, risk of failure"

        # Estimate peak velocity and displacement
        vel_peak = vel_rms_mm_s * math.sqrt(2)
        # Displacement ≈ velocity / (2πf) at dominant frequency (usually 1×)
        f_dom = max(bpfo_hz / 3.58, 25.0)  # Approximate shaft freq from BPFO
        disp_peak_um = (vel_peak / (2 * math.pi * f_dom)) * 1e6

        # Estimate acceleration
        acc_rms = vel_rms_mm_s * 2 * math.pi * f_dom / 1000  # m/s²

        return ISO10816Zone(
            zone=zone,
            velocity_rms_mm_s=vel_rms_mm_s,
            velocity_peak_mm_s=round(vel_peak, 2),
            displacement_peak_um=round(disp_peak_um, 1),
            acceleration_rms_ms2=round(acc_rms, 2),
            machine_class="15-75 kW (ISO 10816-3)",
            assessment=assessment,
        )

    def get_health_index(self, diagnoses: list[FaultDiagnosis]) -> float:
        """Calculate overall health index (0-100%) from diagnoses.

        Health index decreases with fault severity and count.
        """
        if not diagnoses:
            return 100.0

        # Severity weights
        sev_weight = {
            FaultSeverity.CRITICAL: 30,
            FaultSeverity.HIGH: 20,
            FaultSeverity.MODERATE: 10,
            FaultSeverity.LOW: 5,
            FaultSeverity.NONE: 0,
        }

        # Category weights (electrical faults more severe for motor health)
        cat_weight = {
            FaultCategory.ELECTRICAL: 1.5,
            FaultCategory.MECHANICAL: 1.2,
            FaultCategory.THERMAL: 1.3,
            FaultCategory.BEARING: 1.0,
        }

        total_deduction = 0.0
        for d in diagnoses:
            base = sev_weight.get(d.severity, 0)
            mult = cat_weight.get(d.category, 1.0)
            total_deduction += base * mult * d.confidence

        health = max(0.0, 100.0 - total_deduction)
        return round(health, 1)


def classify_from_features(features: SignalFeatures, thresholds: dict | None = None) -> FaultDiagnosis | None:
    """Quick classification from feature vector (for ML fallback).

    Uses simple threshold rules on extracted features.
    """
    # Bearing fault from kurtosis + crest factor
    if features.kurtosis > 5.0 and features.crest_factor > 4.0:
        return FaultDiagnosis(
            fault_type=FaultType.BEARING_BALL,
            category=FaultCategory.BEARING,
            severity=FaultSeverity.MODERATE,
            confidence=0.7,
            evidence=[
                f"Kurtosis: {features.kurtosis:.2f} (> 5.0)",
                f"Crest factor: {features.crest_factor:.2f} (> 4.0)",
            ],
            metrics={"kurtosis": features.kurtosis, "crest_factor": features.crest_factor},
            threshold_used={"kurtosis": 5.0, "crest_factor": 4.0},
            recommended_action="Check bearing condition with envelope analysis."
        )

    # Unbalance from high 1× order
    if features.order_1x > 3.0:
        return FaultDiagnosis(
            fault_type=FaultType.UNBALANCE,
            category=FaultCategory.MECHANICAL,
            severity=FaultSeverity.MODERATE,
            confidence=0.7,
            evidence=[f"1× order amplitude: {features.order_1x:.2f}"],
            metrics={"order_1x": features.order_1x},
            threshold_used={"order_1x": 3.0},
            recommended_action="Check rotor balance."
        )

    return None

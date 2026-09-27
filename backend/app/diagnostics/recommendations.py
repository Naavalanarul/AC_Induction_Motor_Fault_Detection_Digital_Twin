"""diagnostics/recommendations.py — Prescriptive maintenance recommendations.

Provides actionable maintenance guidance based on active fault type,
MHI condition zone (A, B, C, D), and SADA supervisory state.
"""

from __future__ import annotations

from typing import Any

from app.diagnostics.schema import DiagFault

RECOMMENDATIONS_CATALOG: dict[str, dict[str, dict[str, Any]]] = {
    "broken_rotor_bar": {
        "C": {
            "urgency": "prompt",
            "title": "Rotor Bar Degradation Alert",
            "action": "Inspect rotor cage and end-rings. Schedule MCSA confirmation and prepare replacement rotor.",
            "checklist": [
                "Perform Motor Current Signature Analysis (MCSA) sideband verification (f_s * (1 - 2s)).",
                "Measure acoustic emission in the 1-5 kHz range during steady-state loading.",
                "Verify torque ripple amplitude using motor drive telemetry.",
                "Order replacement rotor or schedule rotor bar re-brazing within 7 days.",
            ],
        },
        "D": {
            "urgency": "immediate",
            "title": "CRITICAL: Imminent Rotor Failure",
            "action": "EMERGENCY: High rotor bar break count. De-energize motor immediately to prevent stator core damage.",
            "checklist": [
                "De-energize and lock-out/tag-out (LOTO) motor drive immediately.",
                "Perform visual and borescope inspection of stator bore for metal scouring.",
                "Conduct full insulation resistance test before motor restart.",
                "Replace rotor assembly before energizing.",
            ],
        },
    },
    "interturn_short": {
        "C": {
            "urgency": "prompt",
            "title": "Stator Winding Insulation Warning",
            "action": "Perform winding insulation resistance and surge tests. Plan rewinding or replacement.",
            "checklist": [
                "Perform Megger DC insulation test and winding resistance balance check (phase-to-phase).",
                "Verify temperature rises across all phases using RTDs or thermal imager.",
                "Derate motor by 30% if continuous operation is unavoidable before maintenance.",
                "Schedule rewinding or stator replacement within 48 hours.",
            ],
        },
        "D": {
            "urgency": "immediate",
            "title": "CRITICAL: Stator Phase Breakdown",
            "action": "EMERGENCY: Immediate phase-to-phase short risk. Isolate motor immediately to prevent catastrophic stator fire.",
            "checklist": [
                "Immediately trip supply breaker and enforce LOTO.",
                "Inspect stator coil heads for thermal charring and copper spatter.",
                "Measure winding inductance balance and surge test to ground.",
                "Complete full stator rewinding and varnish dip.",
            ],
        },
    },
    "bearing_outer": {
        "C": {
            "urgency": "prompt",
            "title": "Outer Race Bearing Degradation",
            "action": "Inspect bearing lubrication and verify BPFO vibration harmonics. Plan bearing replacement.",
            "checklist": [
                "Check high-frequency acceleration enveloping at BPFO frequency.",
                "Verify grease/oil quality for particulate contamination or varnish.",
                "Monitor bearing housing temperature for thermal runaway.",
                "Schedule bearing replacement within 72 hours.",
            ],
        },
        "D": {
            "urgency": "immediate",
            "title": "CRITICAL: Imminent Bearing Seizure",
            "action": "CRITICAL: Bearing failure imminent. Stop motor immediately to avoid shaft scoring and rotor strike.",
            "checklist": [
                "Stop motor immediately and isolate power.",
                "Remove bearing housing and inspect outer race for flaking or spalling.",
                "Inspect shaft journal for runout or mechanical wear.",
                "Replace bearing assembly and repack with manufacturer-specified grease.",
            ],
        },
    },
    "bearing_inner": {
        "C": {
            "urgency": "prompt",
            "title": "Inner Race Bearing Degradation",
            "action": "Inspect bearing lubrication and verify BPFI vibration harmonics. Plan bearing replacement.",
            "checklist": [
                "Check vibration spectrum for BPFI harmonics and 1X running speed sidebands.",
                "Check bearing housing temperature and acoustic emission.",
                "Schedule bearing replacement within 72 hours.",
            ],
        },
        "D": {
            "urgency": "immediate",
            "title": "CRITICAL: Imminent Inner Race Failure",
            "action": "CRITICAL: Bearing cage/inner race disintegration risk. De-energize motor immediately.",
            "checklist": [
                "De-energize motor immediately and inspect shaft for overheating.",
                "Remove bearing inner race using induction heater.",
                "Check shaft seat tolerances before installing replacement bearing.",
            ],
        },
    },
    "bearing_ball": {
        "C": {
            "urgency": "prompt",
            "title": "Rolling Element Bearing Wear",
            "action": "Check ball spin frequency (BSF) harmonics and lubrication. Plan replacement.",
            "checklist": [
                "Inspect vibration acceleration envelope at 2x BSF.",
                "Replenish synthetic polyurea grease if lubrication dry.",
                "Schedule bearing replacement within 5 days.",
            ],
        },
        "D": {
            "urgency": "immediate",
            "title": "CRITICAL: Rolling Element Destruction",
            "action": "CRITICAL: Ball fracture risk. Shut down motor immediately.",
            "checklist": [
                "Shut down motor immediately.",
                "Flush bearing cavity and inspect for metallic debris.",
                "Replace complete rolling element bearing assembly.",
            ],
        },
    },
    "misalignment": {
        "C": {
            "urgency": "prompt",
            "title": "Shaft Misalignment Alert",
            "action": "Perform laser alignment on motor-load coupling. Inspect flexible coupling inserts.",
            "checklist": [
                "Measure 2X rotational frequency peak on radial vibration spectrum.",
                "Check coupling elastomeric elements for thermal degradation or extrusion.",
                "Perform hot laser shaft alignment check to compensate for thermal growth.",
                "Re-torque base foundation bolts to OEM specification.",
            ],
        },
        "D": {
            "urgency": "immediate",
            "title": "CRITICAL: Severe Mechanical Misalignment",
            "action": "CRITICAL: High shaft fatigue stress. Stop motor to prevent coupling rupture and bearing destruction.",
            "checklist": [
                "Stop motor and disconnect load coupling.",
                "Check for soft foot condition and foundation resonance.",
                "Perform precision reverse-dial or laser alignment within 0.05 mm tolerance.",
                "Inspect coupling sleeves and driven load bearings.",
            ],
        },
    },
    "unbalance": {
        "C": {
            "urgency": "prompt",
            "title": "Rotor Unbalance Warning",
            "action": "Inspect rotor/load for dirt accumulation or lost balance weights. Plan on-site dynamic balancing.",
            "checklist": [
                "Measure 1X rotational speed vibration amplitude and phase angle.",
                "Clean fan blades, sheaves, and exposed rotating assemblies.",
                "Perform single-plane or two-plane dynamic balancing on site.",
            ],
        },
        "D": {
            "urgency": "immediate",
            "title": "CRITICAL: Excessive Rotor Unbalance",
            "action": "CRITICAL: Severe 1X vibration. Stop motor immediately to prevent structural damage.",
            "checklist": [
                "Stop motor immediately.",
                "Inspect rotor for broken components, detached balance weights, or severe shaft bend.",
                "Perform dynamic balancing to ISO 1940 Grade G2.5 or better before returning to service.",
            ],
        },
    },
    "overheating": {
        "C": {
            "urgency": "prompt",
            "title": "Motor Overheating Alert",
            "action": "Verify cooling air passages, fan cowl clearance, and ambient temperature.",
            "checklist": [
                "Inspect motor fan cowl and clean cooling fins of dust/debris buildup.",
                "Check ambient air temperature and cooling air path.",
                "Verify load torque is within motor continuous duty rating (S1).",
            ],
        },
        "D": {
            "urgency": "immediate",
            "title": "CRITICAL: Thermal Runaway",
            "action": "CRITICAL: Winding insulation thermal limit exceeded. De-energize motor immediately to prevent burnout.",
            "checklist": [
                "Shut down motor immediately to prevent winding insulation breakdown.",
                "Allow forced air cooling until stator temperature drops below 60 °C.",
                "Conduct insulation resistance check prior to restarting.",
            ],
        },
    },
    "supply_anomaly": {
        "C": {
            "urgency": "prompt",
            "title": "Power Supply Quality Warning",
            "action": "Check line voltage balance, VFD output waveform, and phase symmetry.",
            "checklist": [
                "Measure phase voltage unbalance factor (VUF). Ensure VUF < 2%.",
                "Check for harmonic distortion (THD) from neighboring non-linear loads.",
                "Inspect supply contactors and cable terminations for loose connections.",
            ],
        },
        "D": {
            "urgency": "immediate",
            "title": "CRITICAL: Severe Supply Anomaly / Phase Loss",
            "action": "CRITICAL: Phase loss or extreme voltage sag. Trip breaker to prevent stator overcurrent.",
            "checklist": [
                "Isolate supply immediately to prevent single-phasing current surge.",
                "Inspect upstream transformer, fuses, and protection relays.",
                "Verify voltage phase presence and balance before re-energizing.",
            ],
        },
    },
}


def get_recommendation(
    motor_id: int,
    fault_type: str | DiagFault,
    zone: str,
    mhi: float,
) -> dict[str, Any]:
    """Generates structured maintenance recommendations based on fault type, zone, and MHI."""
    flt_val = fault_type.value if isinstance(fault_type, DiagFault) else str(fault_type).lower()

    if zone == "A":
        return {
            "motor_id": motor_id,
            "fault_type": flt_val,
            "zone": "A",
            "mhi": mhi,
            "urgency": "routine",
            "title": "Normal Operation",
            "action": "Motor is operating within normal parameters. Continue standard routine monitoring.",
            "checklist": [
                "Record baseline electrical, vibration, and thermal parameters.",
                "Perform scheduled visual inspection and periodic lubrication as per OEM schedule.",
            ],
        }

    if zone == "B":
        return {
            "motor_id": motor_id,
            "fault_type": flt_val,
            "zone": "B",
            "mhi": mhi,
            "urgency": "planned",
            "title": f"Minor Degradation ({flt_val.replace('_', ' ').title()})",
            "action": f"Minor degradation detected ({flt_val}). Schedule inspection during next planned maintenance window.",
            "checklist": [
                "Log diagnostic trend and verify if severity is stable or increasing.",
                "Schedule detailed vibration / current signature check during next scheduled turnaround.",
                "Check motor grease and operating temperature.",
            ],
        }

    # Zone C or D
    fault_catalog = RECOMMENDATIONS_CATALOG.get(flt_val, {})
    rec = fault_catalog.get(zone)
    if rec:
        return {
            "motor_id": motor_id,
            "fault_type": flt_val,
            "zone": zone,
            "mhi": mhi,
            "urgency": rec["urgency"],
            "title": rec["title"],
            "action": rec["action"],
            "checklist": rec["checklist"],
        }

    # Generic Zone C/D fallback
    urgency = "immediate" if zone == "D" else "prompt"
    title = f"{'CRITICAL: ' if zone == 'D' else 'Warning: '}{flt_val.replace('_', ' ').title()}"
    action = f"{'De-energize motor immediately and investigate active fault.' if zone == 'D' else 'Inspect motor systems and monitor diagnostic severity trends closely.'}"
    return {
        "motor_id": motor_id,
        "fault_type": flt_val,
        "zone": zone,
        "mhi": mhi,
        "urgency": urgency,
        "title": title,
        "action": action,
        "checklist": [
            "Perform comprehensive diagnostic scan across all channels.",
            "Inspect physical motor, coupling, and electrical supply.",
            "Follow safety procedures before opening electrical enclosures.",
        ],
    }

"""tests/static_analysis/test_schemas.py

Validates Pydantic schema validation, basis transformations, and plausibility rules.
"""

import math

import pytest
from pydantic import ValidationError

from app.static_analysis.schemas import (
    NameplateBlock,
    StaticMeasurement,
    ValueBasis,
    VoltageBasis,
)


def sample_nameplate() -> NameplateBlock:
    return NameplateBlock(
        rated_power_w=1500.0,
        rated_voltage_v=380.0,
        rated_current_a=4.7,
        rated_speed_rpm=1474.0,
        rated_torque_nm=10.0,
        pole_pairs=2,
        supply_freq_hz=50.0,
        insulation_class="F",
    )


def test_voltage_and_value_basis_transformations():
    # Line-line RMS 380V -> Phase RMS 219.39V
    m1 = StaticMeasurement(
        nameplate=sample_nameplate(),
        v_a=380.0,
        v_b=380.0,
        v_c=380.0,
        voltage_basis=VoltageBasis.LINE_LINE,
        value_basis=ValueBasis.RMS,
        i_a=4.7,
        i_b=4.7,
        i_c=4.7,
        speed_rpm=1474.0,
        supply_freq_hz=50.0,
    )
    va, vb, vc = m1.to_phase_rms_voltages()
    assert va == pytest.approx(380.0 / math.sqrt(3.0), rel=1e-4)

    # Line-neutral Peak 310.27V -> Phase RMS 219.39V
    v_ln_peak = (380.0 / math.sqrt(3.0)) * math.sqrt(2.0)
    m2 = StaticMeasurement(
        nameplate=sample_nameplate(),
        v_a=v_ln_peak,
        v_b=v_ln_peak,
        v_c=v_ln_peak,
        voltage_basis=VoltageBasis.LINE_NEUTRAL,
        value_basis=ValueBasis.PEAK,
        i_a=4.7,
        i_b=4.7,
        i_c=4.7,
        speed_rpm=1474.0,
        supply_freq_hz=50.0,
    )
    va2, vb2, vc2 = m2.to_phase_rms_voltages()
    assert va2 == pytest.approx(380.0 / math.sqrt(3.0), rel=1e-4)


def test_validation_rejects_speed_above_synchronous():
    with pytest.raises(ValidationError, match="must be strictly below synchronous speed"):
        StaticMeasurement(
            nameplate=sample_nameplate(),
            v_a=380.0,
            v_b=380.0,
            v_c=380.0,
            i_a=4.7,
            i_b=4.7,
            i_c=4.7,
            speed_rpm=1505.0,  # Sync is 1500 for 50 Hz, 2 pole pairs
            supply_freq_hz=50.0,
        )


def test_validation_rejects_negative_or_zero_values():
    with pytest.raises(ValidationError):
        StaticMeasurement(
            nameplate=sample_nameplate(),
            v_a=-380.0,
            v_b=380.0,
            v_c=380.0,
            i_a=4.7,
            i_b=4.7,
            i_c=4.7,
            speed_rpm=1474.0,
        )

    with pytest.raises(ValidationError):
        StaticMeasurement(
            nameplate=sample_nameplate(),
            v_a=380.0,
            v_b=380.0,
            v_c=380.0,
            i_a=0.0,
            i_b=4.7,
            i_c=4.7,
            speed_rpm=1474.0,
        )


def test_validation_rejects_insane_multiples_of_nameplate():
    # Voltage 10x rated
    with pytest.raises(ValidationError, match="deviates excessively from rated"):
        StaticMeasurement(
            nameplate=sample_nameplate(),
            v_a=3800.0,
            v_b=3800.0,
            v_c=3800.0,
            i_a=4.7,
            i_b=4.7,
            i_c=4.7,
            speed_rpm=1474.0,
        )

    # Current 20x rated
    with pytest.raises(ValidationError, match="deviates excessively from rated"):
        StaticMeasurement(
            nameplate=sample_nameplate(),
            v_a=380.0,
            v_b=380.0,
            v_c=380.0,
            i_a=150.0,  # Rated is 4.7 A -> >30x
            i_b=4.7,
            i_c=4.7,
            speed_rpm=1474.0,
        )


def test_validation_requires_motor_id_or_nameplate():
    with pytest.raises(ValidationError, match="Either motor_id or nameplate must be provided"):
        StaticMeasurement(
            v_a=380.0,
            v_b=380.0,
            v_c=380.0,
            i_a=4.7,
            i_b=4.7,
            i_c=4.7,
            speed_rpm=1474.0,
            supply_freq_hz=50.0,
        )


def test_nameplate_converts_to_motor_params():
    np_block = sample_nameplate()
    p = np_block.to_motor_params()
    assert p.rated_power == 1500.0
    assert p.rated_voltage == 380.0
    assert p.Rs > 0
    assert p.Rr > 0
    assert p.Ls > p.Lm
    assert p.Lr > p.Lm

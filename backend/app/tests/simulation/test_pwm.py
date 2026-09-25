import math

from app.simulation.pwm import (
    CarrierWaveGenerator,
    InverterLegStates,
    ModulatingWaveGenerator,
    find_earliest_inverter_event,
    phase_voltages,
)


def test_complementary_switches():
    s = InverterLegStates.from_upper_switches(1, 0, 1)
    assert (s.s1 + s.s2, s.s3 + s.s4, s.s5 + s.s6) == (1, 1, 1)


def test_phase_voltages_sum_to_zero():
    for sa in (0, 1):
        for sb in (0, 1):
            for sc in (0, 1):
                v = phase_voltages(InverterLegStates.from_upper_switches(sa, sb, sc), 600.0)
                assert math.isclose(v.a + v.b + v.c, 0.0, abs_tol=1e-9)


def test_carrier_is_symmetric_triangle():
    c = CarrierWaveGenerator(1000.0)
    assert math.isclose(c(0.0), -1.0)
    assert math.isclose(c(0.0005), 1.0)
    assert math.isclose(c(0.00025), 0.0, abs_tol=1e-12)


def test_event_detection_finds_crossing_inside_window():
    mod = ModulatingWaveGenerator(50.0, 0.8)
    car = CarrierWaveGenerator(5000.0)
    t_evt, phase = find_earliest_inverter_event(mod, car, 0.0, max_step=1e-4)
    assert t_evt is not None and 0.0 < t_evt <= 1e-4
    assert phase in {"A", "B", "C"}
    # at the event the chosen phase's reference equals the carrier
    ref = getattr(mod(t_evt), phase.lower())
    # bisection tolerance is 1 ns in time; carrier slope is 4*f_c per second
    assert math.isclose(ref, car(t_evt), abs_tol=4 * 5000.0 * 2e-9 * 2)

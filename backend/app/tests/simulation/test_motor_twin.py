from app.simulation.motor_twin import InverterCommand, MotorTwin
from app.simulation.params import DEFAULT_MOTOR


def test_pwm_twin_accelerates_and_lands_on_events():
    twin = MotorTwin(DEFAULT_MOTOR, max_step_size=2e-5)
    cmd = InverterCommand(u_dc=600.0, fund_freq_hz=50.0, modulation_index=0.9)
    steps = 0
    while twin.t < 0.02:
        state = twin.tick(cmd, load_torque=0.0)
        steps += 1
    assert state.omega_m > 0.0
    # more ticks than a pure fixed-step run: the controller shortened steps at switching events
    assert steps > 0.02 / 2e-5

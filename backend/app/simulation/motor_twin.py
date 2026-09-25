"""simulation/motor_twin.py

Stateful digital twin wrapper for the inverter-driven induction motor.
Integrates coordinate transforms, PWM switching, electrical RK4 integration,
and mechanical dynamics into a unified step-transition model.

Reference:
    Chen et al. (Energies 2025), Section 2, Eq. (3)-(6) & (13)-(14).
"""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np

from app.simulation.params import MotorParams
from app.simulation.transforms import ClarkeTransformer, PhaseABC, AlphaBeta
from app.simulation.pwm import (
    InverterLegStates,
    phase_voltages,
    CarrierWaveGenerator,
    ModulatingWaveGenerator,
    find_earliest_inverter_event,
    get_instantaneous_switches,
)
from app.simulation.dynamics import (
    ElectricalState,
    InductionMotorElectricalDynamics,
)
from app.simulation.mechanical import (
    MechanicalState,
    InductionMotorMechanicalDynamics,
)
from app.simulation.integrators import RungeKutta4, EventDrivenStepController


@dataclass(frozen=True)
class InverterCommand:
    """Control setpoints and electrical drive bus parameters."""

    u_dc: float                # DC link bus voltage [V]
    fund_freq_hz: float        # Desired stator fundamental frequency [Hz]
    modulation_index: float    # Modulation depth m in [0.0, 1.0]


@dataclass(frozen=True)
class MotorState:
    """Immutable snapshot of the motor state at time t."""

    t: float
    # Phase & stationary currents
    i_abc: PhaseABC
    i_alphabeta: AlphaBeta
    # Rotor flux linkages
    psi_r: AlphaBeta
    # Mechanical quantities
    te: float              # Electromagnetic torque [N·m]
    load_torque: float     # Load torque [N·m]
    omega_r: float         # Electrical rotor speed [rad/s]
    omega_m: float         # Mechanical shaft speed [rad/s]
    rpm: float             # Shaft speed [RPM]
    theta_r: float         # Electrical angle [rad]
    # Inverter switching states & applied voltages
    switches: InverterLegStates
    u_phase: PhaseABC
    u_alphabeta: AlphaBeta


class MotorTwin:
    """Stateful digital twin of an inverter-fed induction motor.

    This is the sole state-holding class orchestrating time progression,
    inverter event detection, electrical ODE integration, and mechanical updates.
    """

    def __init__(
        self,
        params: MotorParams,
        pwm_freq_hz: float = 5000.0,
        max_step_size: float = 2e-5,
        viscous_damping: float = 0.001,
        initial_electrical: ElectricalState | None = None,
        initial_mechanical: MechanicalState | None = None,
        t0: float = 0.0,
    ):
        """
        Args:
            params: Motor physical and rated parameters.
            pwm_freq_hz: Inverter carrier triangle frequency [Hz].
            max_step_size: Solver maximum allowable integration step h_max [s].
            viscous_damping: Mechanical friction damping B [N·m·s/rad].
            initial_electrical: Initial currents/fluxes (defaults to 0).
            initial_mechanical: Initial speed/position (defaults to 0).
            t0: Starting simulation timestamp [s].
        """
        self.params = params
        self.t = t0

        # Subsystem engines
        self.carrier = CarrierWaveGenerator(carrier_freq_hz=pwm_freq_hz)
        self.electrical = InductionMotorElectricalDynamics(params)
        self.mechanical = InductionMotorMechanicalDynamics(params, damping=viscous_damping)
        self.rk4 = RungeKutta4()
        self.step_controller = EventDrivenStepController(h_max=max_step_size)

        # Stateful components
        self._elec_state = initial_electrical if initial_electrical is not None else ElectricalState.zero()
        self._mech_state = initial_mechanical if initial_mechanical is not None else MechanicalState.standstill()

        # Cache last computed telemetry
        self._last_te: float = 0.0
        self._last_load_torque: float = 0.0
        self._last_switches = InverterLegStates.from_upper_switches(0, 0, 0)
        self._last_u_phase = PhaseABC(0.0, 0.0, 0.0)
        self._last_u_alphabeta = AlphaBeta(0.0, 0.0)

    def tick(self, cmd: InverterCommand, load_torque: float) -> MotorState:
        """Advances the digital twin forward to the next adaptive event or max timestep.

        Execution pipeline:
            1. Formulate modulating wave and determine next PWM crossing event.
            2. Compute adaptive step size h (landing on switching event if scheduled).
            3. Evaluate current inverter switching state and terminal phase voltages.
            4. Convert u_abc to u_alphabeta via Clarke transform.
            5. Integrate electrical states using RK4.
            6. Compute electromagnetic torque Te and advance mechanical speed.
            7. Advance self.t and return a snapshot MotorState.

        Args:
            cmd: InverterCommand with modulation setpoint and DC bus voltage.
            load_torque: Opposing mechanical load torque TL [N·m].

        Returns:
            MotorState snapshot after advancement.
        """
        # 1. Modulating wave setup & event-driven crossing scan
        modulator = ModulatingWaveGenerator(
            fund_freq_hz=cmd.fund_freq_hz,
            modulation_index=cmd.modulation_index,
        )

        t_next_event, _ = find_earliest_inverter_event(
            mod_gen=modulator,
            carrier_gen=self.carrier,
            t_now=self.t,
            max_step=self.step_controller.h_max,
        )

        # 2. Determine integration step h
        h = self.step_controller.compute_step(self.t, t_next_event)

        # 3. Inverter comparator logic at midpoint/start of the piecewise-constant step
        t_sample = self.t + 0.5 * h
        mod_val = modulator(t_sample)
        carrier_val = self.carrier(t_sample)
        switches = get_instantaneous_switches(mod_val, carrier_val)

        # 4. Phase-to-neutral voltages and Clarke transformation
        u_phase = phase_voltages(switches, udc=cmd.u_dc)
        u_alphabeta = ClarkeTransformer.to_alpha_beta(u_phase)

        # 5. Advance 4th-order electrical state via RK4
        state_vec = self._elec_state.to_numpy()
        input_vec = np.array([u_alphabeta.alpha, u_alphabeta.beta], dtype=np.float64)

        derivative_adapter = self.electrical.as_vector_derivative_function(omega_r=self._mech_state.omega_r)
        new_state_vec = self.rk4.step(
            state=state_vec,
            t=self.t,
            h=h,
            f=derivative_adapter,
            inputs=input_vec,
        )
        self._elec_state = ElectricalState.from_numpy(new_state_vec)

        # 6. Torque production and mechanical rotor update
        te = self.mechanical.compute_electromagnetic_torque(
            stator_current=self._elec_state.stator_current,
            rotor_flux=self._elec_state.rotor_flux,
        )

        self._mech_state = self.mechanical.step_euler(
            state=self._mech_state,
            Te=te,
            load_torque=load_torque,
            dt=h,
        )

        # Update cached records & clock
        self.t += h
        self._last_te = te
        self._last_load_torque = load_torque
        self._last_switches = switches
        self._last_u_phase = u_phase
        self._last_u_alphabeta = u_alphabeta

        return self.get_state()

    def get_state(self) -> MotorState:
        """Returns the current immutable telemetry snapshot of the digital twin."""
        i_alphabeta = self._elec_state.stator_current
        i_abc = ClarkeTransformer.to_abc(i_alphabeta)

        return MotorState(
            t=self.t,
            i_abc=i_abc,
            i_alphabeta=i_alphabeta,
            psi_r=self._elec_state.rotor_flux,
            te=self._last_te,
            load_torque=self._last_load_torque,
            omega_r=self._mech_state.omega_r,
            omega_m=self._mech_state.omega_m(self.params.pole_pairs),
            rpm=self._mech_state.rpm(self.params.pole_pairs),
            theta_r=self._mech_state.theta_r,
            switches=self._last_switches,
            u_phase=self._last_u_phase,
            u_alphabeta=self._last_u_alphabeta,
        )

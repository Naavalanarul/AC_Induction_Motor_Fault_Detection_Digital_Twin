"""core_physics/motor_parameters.py

Motor nameplate ratings & default equivalent circuit values.
All parameters are physically meaningful and traceable to standard motor testing.
"""

from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True)
class DerivedConstants:
    """Pre-computed constants for state-space equations (Chen et al. 2025 formulation)."""

    sigma: float  # Total leakage factor σ = 1 - Lm²/(Ls·Lr)
    Tr: float  # Rotor time constant Tr = Lr/Rr [s]
    gamma: float  # Stator damping coefficient λ = (Rs + Lm²/(Lr·Tr)) / (σ·Ls)
    K: float  # Flux-to-current coupling K = Lm / (σ·Ls·Lr)

    @property
    def lambda_(self) -> float:
        """Alias matching Chen et al. Eq. (3) symbol."""
        return self.gamma


@dataclass(frozen=True)
class MotorParams:
    """Core electrical and mechanical parameters for AC induction motor simulation.

    Parameters are derived from standard no-load and locked-rotor tests.
    All values are for a 1.5 kW, 4-pole, 50 Hz, 380 V (line-line) motor.
    """

    # Electrical parameters (per-phase equivalent circuit, star connection)
    Rs: float  # Stator resistance [Ω]
    Rr: float  # Rotor resistance referred to stator [Ω]
    Ls: float  # Stator self-inductance [H]
    Lr: float  # Rotor self-inductance referred to stator [H]
    Lm: float  # Mutual inductance [H]

    # Mechanical parameters
    J: float  # Rotor moment of inertia [kg·m²]
    pole_pairs: int  # Number of pole pairs (p)
    B: float  # Viscous damping coefficient [N·m·s/rad]

    # Nameplate ratings (for validation and normalization)
    rated_power: float  # Rated mechanical output power [W]
    rated_voltage: float  # Rated line-to-line voltage [V]
    rated_current: float  # Rated phase current [A]
    rated_speed: float  # Rated mechanical speed [RPM]
    rated_torque: float  # Rated torque [N·m]
    rated_freq: float  # Rated supply frequency [Hz]
    insulation_class: str  # Insulation class (e.g., "F", "H")
    ambient_temp: float  # Rated ambient temperature [°C]
    temp_rise: float  # Rated temperature rise [°C]

    def compute_derived_constants(self) -> DerivedConstants:
        """Pre-compute derived constants used directly in state-space dynamic model.

        Formulations from Chen et al. (2025), beneath Eq. (3):
        - σ  = 1 - Lm² / (Ls · Lr)
        - Tr = Lr / Rr
        - λ  = (Rs + Lm² / (Lr · Tr)) / (σ · Ls)
        - K  = Lm / (σ · Ls · Lr)
        """
        sigma = 1.0 - self.Lm**2 / (self.Ls * self.Lr)
        Tr = self.Lr / self.Rr
        gamma = (self.Rs + self.Lm**2 / (self.Lr * Tr)) / (sigma * self.Ls)
        K = self.Lm / (sigma * self.Ls * self.Lr)
        return DerivedConstants(sigma=sigma, Tr=Tr, gamma=gamma, K=K)

    @property
    def synchronous_speed_rpm(self) -> float:
        """Synchronous speed in RPM."""
        return 60.0 * self.rated_freq / self.pole_pairs

    @property
    def rated_slip(self) -> float:
        """Rated slip (per unit)."""
        return (self.synchronous_speed_rpm - self.rated_speed) / self.synchronous_speed_rpm

    @property
    def rated_angular_velocity(self) -> float:
        """Rated mechanical angular velocity [rad/s]."""
        return self.rated_speed * 2.0 * 3.14159265359 / 60.0

    @classmethod
    def create_default(cls) -> Self:
        """Create default 1.5 kW motor parameter set.

        Based on widely used 1.5 kW, 4-pole, 50 Hz parameter set from
        field-oriented control literature. Validated against simulated
        no-load/locked-rotor tests.
        """
        return cls(
            # Equivalent circuit (star, per phase)
            Rs=1.405,
            Rr=1.395,
            Ls=0.178039,
            Lr=0.178039,
            Lm=0.1722,
            # Mechanical
            J=0.0131,
            pole_pairs=2,
            B=0.002,
            # Nameplate
            rated_power=1500.0,
            rated_voltage=380.0,
            rated_current=4.7,
            rated_speed=1474.0,
            rated_torque=10.0,
            rated_freq=50.0,
            insulation_class="F",
            ambient_temp=40.0,
            temp_rise=105.0,
        )

    @classmethod
    def create_from_nameplate(
        cls,
        rated_power: float,
        rated_voltage: float,
        rated_current: float,
        rated_speed: float,
        rated_freq: float = 50.0,
        pole_pairs: int = 2,
        insulation_class: str = "F",
    ) -> Self:
        """Estimate equivalent circuit parameters from nameplate data only.

        Uses standard approximations for initial simulation setup.
        Should be refined with no-load/locked-rotor test data.
        """
        sync_speed = 60.0 * rated_freq / pole_pairs
        slip = (sync_speed - rated_speed) / sync_speed
        rated_torque = rated_power / (rated_speed * 2.0 * 3.14159265359 / 60.0)

        # Approximate parameters for standard IEC frame motors
        # These are rough estimates - real values need test data
        phase_voltage = rated_voltage / 3.0**0.5
        # Assume power factor ~0.8, efficiency ~0.85 at rated load
        pf = 0.8
        eff = 0.85

        # Rough estimates based on typical motor designs
        Rs_est = phase_voltage / rated_current * 0.05
        Rr_est = Rs_est * 1.2
        Lm_est = phase_voltage / (rated_current * 0.3 * 2 * 3.14159 * rated_freq)
        Ls_est = Lm_est * 1.03
        Lr_est = Lm_est * 1.03
        J_est = 0.001 * rated_power**0.75  # Rough scaling

        return cls(
            Rs=Rs_est,
            Rr=Rr_est,
            Ls=Ls_est,
            Lr=Lr_est,
            Lm=Lm_est,
            J=J_est,
            pole_pairs=pole_pairs,
            B=0.002,
            rated_power=rated_power,
            rated_voltage=rated_voltage,
            rated_current=rated_current,
            rated_speed=rated_speed,
            rated_torque=rated_torque,
            rated_freq=rated_freq,
            insulation_class=insulation_class,
            ambient_temp=40.0,
            temp_rise=105.0 if insulation_class == "F" else 125.0,
        )


# Default motor instance for the digital twin
DEFAULT_MOTOR = MotorParams.create_default()
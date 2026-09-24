"""simulation/transforms.py

Object-Oriented implementation of coordinate transformations between
the 3-phase stationary frame (abc) and the 2-phase stationary frame (alpha-beta).

Conventions:
    Standard amplitude-invariant Clarke transform (peak amplitude of alpha equals peak of a).
"""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class PhaseABC:
    """Represents a balanced or unbalanced 3-phase physical vector (a, b, c)."""

    a: float
    b: float
    c: float

    @property
    def is_balanced(self, tolerance: float = 1e-6) -> bool:
        """Checks if the zero-sequence component is effectively zero (a + b + c ≈ 0)."""
        return abs(self.a + self.b + self.c) < tolerance


@dataclass(frozen=True)
class AlphaBeta:
    """Represents a 2-phase orthogonal stationary frame vector (alpha, beta)."""

    alpha: float
    beta: float

    @property
    def magnitude(self) -> float:
        """Instantaneous vector magnitude / envelope."""
        return math.hypot(self.alpha, self.beta)

    @property
    def angle(self) -> float:
        """Phase angle in radians (-pi to +pi)."""
        return math.atan2(self.beta, self.alpha)


class ClarkeTransformer:
    """Encapsulates forward and inverse Clarke transformations.

    Uses precomputed mathematical invariants for numerical efficiency.
    """

    # Precomputed transformation scale constants
    SQRT3: float = math.sqrt(3.0)
    ONE_BY_SQRT3: float = 1.0 / SQRT3
    SQRT3_OVER_2: float = SQRT3 / 2.0
    TWO_THIRDS: float = 2.0 / 3.0

    @classmethod
    def to_alpha_beta(cls, phase: PhaseABC) -> AlphaBeta:
        """Transforms a 3-phase vector (abc) into a 2-phase stationary vector (alpha, beta).

        Amplitude-invariant formulation:
            alpha = (2/3) * (a - 0.5*b - 0.5*c)
            beta  = (b - c) / sqrt(3)
        """
        alpha = cls.TWO_THIRDS * (phase.a - 0.5 * phase.b - 0.5 * phase.c)
        beta = cls.ONE_BY_SQRT3 * (phase.b - phase.c)
        return AlphaBeta(alpha=alpha, beta=beta)

    @classmethod
    def to_abc(cls, stationary: AlphaBeta) -> PhaseABC:
        """Transforms a 2-phase stationary vector (alpha, beta) back to 3-phase (abc).

        Inverse formulation:
            a = alpha
            b = -0.5 * alpha + (sqrt(3)/2) * beta
            c = -0.5 * alpha - (sqrt(3)/2) * beta
        """
        a = stationary.alpha
        b = -0.5 * stationary.alpha + cls.SQRT3_OVER_2 * stationary.beta
        c = -0.5 * stationary.alpha - cls.SQRT3_OVER_2 * stationary.beta
        return PhaseABC(a=a, b=b, c=c)

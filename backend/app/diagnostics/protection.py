"""diagnostics/protection.py — Current-based electrical protection channel.

Implements standard industrial motor protection functions (IEEE C37.96 / IEC 60255):
1. I^2 t Inverse-Time Thermal Overload: Protects against sustained mechanical overload.
2. Instantaneous Overcurrent: Rapid trip on extreme current spikes.
3. Locked-Rotor / Stall Protection: Detects shaft collapse with high current draw.
4. Single-Phasing / Phase-Loss Protection: Detects missing phase or severe current unbalance.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from app.diagnostics.schema import ChannelVerdict, DiagFault, DiagSource
from app.simulation.params import MotorParams


class ProtectionDiagnostic:
    def __init__(
        self,
        params: MotorParams,
        tau_ovl_s: float = 15.0,
        tau_cool_s: float = 60.0,
        inst_oc_mult: float = 5.0,
        stall_current_mult: float = 2.0,
        stall_speed_ratio: float = 0.25,
    ):
        self.params = params
        self.i_rated = float(params.rated_current)
        self.rated_speed = float(params.rated_speed)
        self.tau_ovl = tau_ovl_s
        self.tau_cool = tau_cool_s
        self.inst_oc_mult = inst_oc_mult
        self.stall_current_mult = stall_current_mult
        self.stall_speed_ratio = stall_speed_ratio

        # State accumulators
        self.thermal_accumulator = 0.0  # [0.0, 1.5] pu thermal energy
        self._stall_timer = 0.0
        self._phase_loss_timer = 0.0

    def reset(self) -> None:
        self.thermal_accumulator = 0.0
        self._stall_timer = 0.0
        self._phase_loss_timer = 0.0

    def update(
        self,
        t: float,
        i_abc: np.ndarray,
        rpm: float,
        dt: float,
    ) -> ChannelVerdict:
        """Evaluates current waveforms and rotor speed against protection limits.

        Args:
            t: Current timestamp in seconds.
            i_abc: 3-phase currents array of shape (3, N) in Amperes.
            rpm: Rotor mechanical speed in RPM.
            dt: Time step duration in seconds.

        Returns:
            ChannelVerdict with source DiagSource.PROTECTION.
        """
        if i_abc.shape[0] < 3 or i_abc.shape[1] == 0:
            return ChannelVerdict(
                DiagSource.PROTECTION,
                DiagFault.UNKNOWN,
                0.0,
                0.0,
                False,
                {"reason": "no current data"},
            )

        # Calculate RMS current per phase
        ia_rms = float(np.sqrt(np.mean(i_abc[0] ** 2)))
        ib_rms = float(np.sqrt(np.mean(i_abc[1] ** 2)))
        ic_rms = float(np.sqrt(np.mean(i_abc[2] ** 2)))

        i_rms = float(math.sqrt((ia_rms**2 + ib_rms**2 + ic_rms**2) / 3.0))
        i_pu = i_rms / max(1e-3, self.i_rated)

        details: dict[str, Any] = {
            "i_rms": round(i_rms, 2),
            "i_pu": round(i_pu, 3),
            "ia_rms": round(ia_rms, 2),
            "ib_rms": round(ib_rms, 2),
            "ic_rms": round(ic_rms, 2),
            "rpm": round(rpm, 1),
            "thermal_pu": round(self.thermal_accumulator, 3),
        }

        is_running = t > 0.5 and rpm > 0.4 * self.rated_speed

        # 1. Instantaneous Overcurrent Protection
        # During DOL startup subtransient inrush (t <= 0.5s), current can reach 8-11x. Trip if > 15x.
        # Once running (t > 0.5s), trip at configured inst_oc_mult (5.0x).
        oc_threshold = self.inst_oc_mult if (t > 0.5 and is_running) else 15.0
        if i_pu >= oc_threshold:
            details["trip_type"] = "instantaneous_overcurrent"
            return ChannelVerdict(
                DiagSource.PROTECTION,
                DiagFault.OVERCURRENT,
                confidence=1.0,
                severity=1.0,
                available=True,
                details=details,
            )

        # 2. Locked Rotor / Stall Protection
        # Detect failure to accelerate past 0.5s, or speed collapse while running
        is_stalled = (
            (t >= 0.5 or is_running)
            and i_pu >= self.stall_current_mult
            and rpm <= self.stall_speed_ratio * self.rated_speed
        )
        if is_stalled:
            self._stall_timer += dt
            if self._stall_timer >= 0.5:
                details["trip_type"] = "locked_rotor_stall"
                details["stall_duration_s"] = round(self._stall_timer, 2)
                return ChannelVerdict(
                    DiagSource.PROTECTION,
                    DiagFault.STALL,
                    confidence=1.0,
                    severity=1.0,
                    available=True,
                    details=details,
                )
        else:
            self._stall_timer = max(0.0, self._stall_timer - dt)

        # 3. Single-Phasing / Phase-Loss Protection
        # Detect lost phase when running or past starting window
        i_mean = (ia_rms + ib_rms + ic_rms) / 3.0
        if (is_running or t > 1.0) and i_mean >= 0.25 * self.i_rated:
            i_min = min(ia_rms, ib_rms, ic_rms)
            i_max = max(ia_rms, ib_rms, ic_rms)
            unbalance = (i_max - i_min) / max(1e-3, i_mean)
            details["current_unbalance"] = round(unbalance, 3)

            is_phase_loss = i_min < 0.10 * i_mean or (unbalance > 1.10 and i_min < 0.15 * i_mean)
            if is_phase_loss:
                self._phase_loss_timer += dt
                if self._phase_loss_timer >= 0.3:
                    details["trip_type"] = "phase_loss_single_phasing"
                    return ChannelVerdict(
                        DiagSource.PROTECTION,
                        DiagFault.PHASE_LOSS,
                        confidence=1.0,
                        severity=0.95,
                        available=True,
                        details=details,
                    )
            else:
                self._phase_loss_timer = max(0.0, self._phase_loss_timer - dt)
        else:
            self._phase_loss_timer = 0.0

        # 4. I^2 t Inverse-Time Thermal Overload
        if (is_running or t > 0.8) and i_pu > 1.05:
            delta = ((i_pu**2) - 1.0) * (dt / self.tau_ovl)
            self.thermal_accumulator = min(1.5, self.thermal_accumulator + delta)
        else:
            cooling_delta = dt / self.tau_cool
            self.thermal_accumulator = max(0.0, self.thermal_accumulator - cooling_delta)

        details["thermal_pu"] = round(self.thermal_accumulator, 3)

        if self.thermal_accumulator >= 1.0:
            details["trip_type"] = "thermal_overload_i2t"
            return ChannelVerdict(
                DiagSource.PROTECTION,
                DiagFault.OVERLOAD,
                confidence=1.0,
                severity=1.0,
                available=True,
                details=details,
            )
        elif self.thermal_accumulator >= 0.40:
            # Escalating warning / derate prior to full trip
            sev = min(0.9, 0.35 + 0.55 * self.thermal_accumulator)
            return ChannelVerdict(
                DiagSource.PROTECTION,
                DiagFault.OVERLOAD,
                confidence=0.90,
                severity=round(sev, 3),
                available=True,
                details=details,
            )

        return ChannelVerdict(
            DiagSource.PROTECTION,
            DiagFault.HEALTHY,
            confidence=0.95,
            severity=0.0,
            available=True,
            details=details,
        )

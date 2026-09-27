"""diagnostics/prognosis.py — Remaining Useful Life (RUL) and threshold time estimation.

Uses ordinary least squares linear regression (numpy polyfit) on rolling
fault severity history to project time until SADA DERATE (0.5) and TRIP (0.8) thresholds.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def estimate_time_to_threshold(
    history: list[tuple[float, float]] | list[list[float]],
    derate_thresh: float = 0.5,
    trip_thresh: float = 0.8,
) -> dict[str, Any]:
    """Projects time until severity crosses derate and trip thresholds.

    Args:
        history: Sequence of (timestamp, severity) pairs, ordered by time.
        derate_thresh: Severity threshold for SADA DERATE (default 0.5).
        trip_thresh: Severity threshold for SADA TRIP (default 0.8).

    Returns:
        dict containing:
            - current_severity: float
            - slope_per_s: float (rate of severity increase per second)
            - time_to_derate_s: float | None (projected seconds to derate threshold)
            - time_to_trip_s: float | None (projected seconds to trip threshold)
            - trend: "increasing" | "decreasing" | "stable"
            - sample_count: int
    """
    if not history or len(history) < 5:
        cur_sev = float(history[-1][1]) if history else 0.0
        return {
            "current_severity": round(cur_sev, 4),
            "slope_per_s": 0.0,
            "time_to_derate_s": None,
            "time_to_trip_s": None,
            "trend": "stable",
            "sample_count": len(history),
        }

    times = np.array([h[0] for h in history], dtype=np.float64)
    sevs = np.array([h[1] for h in history], dtype=np.float64)

    # Relative time from start of window to prevent numerical precision issues
    t_rel = times - times[0]
    dt = float(t_rel[-1])
    cur_sev = float(sevs[-1])

    if dt <= 0:
        return {
            "current_severity": round(cur_sev, 4),
            "slope_per_s": 0.0,
            "time_to_derate_s": None,
            "time_to_trip_s": None,
            "trend": "stable",
            "sample_count": len(history),
        }

    # Fit 1st-degree polynomial: sev(t) = slope * t + intercept
    slope, _ = np.polyfit(t_rel, sevs, 1)
    slope = float(slope)

    if slope > 1e-4:
        trend = "increasing"
    elif slope < -1e-4:
        trend = "decreasing"
    else:
        trend = "stable"

    time_to_derate: float | None = None
    time_to_trip: float | None = None

    if slope > 1e-5:
        if cur_sev >= derate_thresh:
            time_to_derate = 0.0
        else:
            time_to_derate = max(0.0, (derate_thresh - cur_sev) / slope)

        if cur_sev >= trip_thresh:
            time_to_trip = 0.0
        else:
            time_to_trip = max(0.0, (trip_thresh - cur_sev) / slope)

    return {
        "current_severity": round(cur_sev, 4),
        "slope_per_s": round(slope, 6),
        "time_to_derate_s": round(time_to_derate, 1) if time_to_derate is not None else None,
        "time_to_trip_s": round(time_to_trip, 1) if time_to_trip is not None else None,
        "trend": trend,
        "sample_count": len(history),
    }

"""diagnostics/prognosis.py — Remaining Useful Life (RUL) and threshold time estimation.

Implements calibrated linear trend extrapolation on rolling fault severity/health history:
1. Minimum observation window: requires at least 30 samples before emitting RUL.
2. Monotonicity filter: applies cumulative maximum on severity history.
3. Statistical significance: checks R^2 >= 0.5 and positive degradation slope.
4. Confidence interval: computes 95% prediction interval on the failure horizon.
5. Explicit labeling: method labeled as "linear_trend" empirical extrapolation.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.stats import t as student_t

MIN_RUL_SAMPLES = 30
MIN_R2_THRESHOLD = 0.50


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
            - slope_per_s: float
            - time_to_derate_s: float | None
            - time_to_trip_s: float | None
            - trend: "increasing" | "decreasing" | "stable"
            - sample_count: int
            - status: "accumulating_data" | "stable" | "degrading"
            - method: "linear_trend"
            - r2: float | None
            - rul_hours: float | None
            - rul_lower_hours: float | None
            - rul_upper_hours: float | None
    """
    sample_count = len(history) if history else 0
    cur_sev = float(history[-1][1]) if history else 0.0

    if not history or sample_count < 5:
        return {
            "current_severity": round(cur_sev, 4),
            "slope_per_s": 0.0,
            "time_to_derate_s": None,
            "time_to_trip_s": None,
            "trend": "stable",
            "sample_count": sample_count,
            "status": "accumulating_data",
            "method": "linear_trend",
            "r2": None,
            "rul_hours": None,
            "rul_lower_hours": None,
            "rul_upper_hours": None,
        }

    times = np.array([h[0] for h in history], dtype=np.float64)
    sevs = np.array([h[1] for h in history], dtype=np.float64)

    t_rel = times - times[0]
    dt_total = float(t_rel[-1])

    if dt_total <= 0:
        return {
            "current_severity": round(cur_sev, 4),
            "slope_per_s": 0.0,
            "time_to_derate_s": None,
            "time_to_trip_s": None,
            "trend": "stable",
            "sample_count": sample_count,
            "status": "accumulating_data",
            "method": "linear_trend",
            "r2": None,
            "rul_hours": None,
            "rul_lower_hours": None,
            "rul_upper_hours": None,
        }

    # Fit raw series for trend direction and statistical significance
    coeffs_raw = np.polyfit(t_rel, sevs, 1)
    slope_raw = float(coeffs_raw[0])
    intercept_raw = float(coeffs_raw[1])
    pred_raw = slope_raw * t_rel + intercept_raw
    ss_res_raw = float(np.sum((sevs - pred_raw) ** 2))
    ss_tot_raw = float(np.sum((sevs - np.mean(sevs)) ** 2))
    r2_raw = float(max(0.0, min(1.0, 1.0 - (ss_res_raw / ss_tot_raw)))) if ss_tot_raw > 1e-12 else 0.0

    trend = "increasing" if slope_raw > 1e-4 else "decreasing" if slope_raw < -1e-4 else "stable"

    # If observation history is less than minimum window for confident RUL
    if sample_count < MIN_RUL_SAMPLES:
        time_to_derate: float | None = None
        time_to_trip: float | None = None
        if slope_raw > 1e-5:
            if cur_sev >= derate_thresh:
                time_to_derate = 0.0
            else:
                time_to_derate = max(0.0, (derate_thresh - cur_sev) / slope_raw)
            if cur_sev >= trip_thresh:
                time_to_trip = 0.0
            else:
                time_to_trip = max(0.0, (trip_thresh - cur_sev) / slope_raw)
        return {
            "current_severity": round(cur_sev, 4),
            "slope_per_s": round(slope_raw, 6),
            "time_to_derate_s": round(time_to_derate, 1) if time_to_derate is not None else None,
            "time_to_trip_s": round(time_to_trip, 1) if time_to_trip is not None else None,
            "trend": trend,
            "sample_count": sample_count,
            "status": "accumulating_data",
            "method": "linear_trend",
            "r2": round(r2_raw, 4),
            "rul_hours": None,
            "rul_lower_hours": None,
            "rul_upper_hours": None,
        }

    # With >= 30 samples: check statistical significance of degradation
    if slope_raw <= 1e-5 or r2_raw < MIN_R2_THRESHOLD:
        return {
            "current_severity": round(cur_sev, 4),
            "slope_per_s": round(slope_raw, 6),
            "time_to_derate_s": None,
            "time_to_trip_s": None,
            "trend": trend,
            "sample_count": sample_count,
            "status": "stable",
            "method": "linear_trend",
            "r2": round(r2_raw, 4),
            "rul_hours": None,
            "rul_lower_hours": None,
            "rul_upper_hours": None,
        }

    # Statistically significant degradation trend: apply monotonicity filter
    sevs_mono = np.maximum.accumulate(sevs)
    cur_sev_mono = float(sevs_mono[-1])

    coeffs_mono = np.polyfit(t_rel, sevs_mono, 1)
    slope_mono = float(coeffs_mono[0])
    intercept_mono = float(coeffs_mono[1])
    pred_mono = slope_mono * t_rel + intercept_mono
    ss_res_mono = float(np.sum((sevs_mono - pred_mono) ** 2))
    ss_tot_mono = float(np.sum((sevs_mono - np.mean(sevs_mono)) ** 2))
    r2_mono = float(max(0.0, min(1.0, 1.0 - (ss_res_mono / ss_tot_mono)))) if ss_tot_mono > 1e-12 else 0.0

    slope = max(1e-6, slope_mono)

    # Statistically significant degradation trend
    time_to_derate = 0.0 if cur_sev_mono >= derate_thresh else max(0.0, (derate_thresh - cur_sev_mono) / slope)
    delta_trip = max(0.0, trip_thresh - cur_sev_mono)

    if cur_sev_mono >= trip_thresh:
        time_to_trip = 0.0
        rul_h = 0.0
        rul_low_h = 0.0
        rul_up_h = 0.0
    else:
        time_to_trip = delta_trip / slope
        rul_h = time_to_trip / 3600.0

        # 95% Confidence / Prediction Interval on failure horizon
        n = len(t_rel)
        df = n - 2
        s_err = math.sqrt(ss_res_mono / max(1, df))
        s_xx = float(np.sum((t_rel - np.mean(t_rel)) ** 2))
        se_slope = s_err / math.sqrt(max(1e-12, s_xx))
        t_crit = float(student_t.ppf(0.975, df))

        slope_lower = max(1e-6, slope - t_crit * se_slope)
        slope_upper = slope + t_crit * se_slope

        rul_low_h = round((delta_trip / slope_upper) / 3600.0, 3)
        rul_up_h = round((delta_trip / slope_lower) / 3600.0, 3)

    return {
        "current_severity": round(cur_sev, 4),
        "slope_per_s": round(slope, 6),
        "time_to_derate_s": round(time_to_derate, 1) if time_to_derate is not None else None,
        "time_to_trip_s": round(time_to_trip, 1) if time_to_trip is not None else None,
        "trend": "increasing",
        "sample_count": sample_count,
        "status": "degrading",
        "method": "linear_trend",
        "r2": round(r2_mono, 4),
        "rul_hours": round(rul_h, 3),
        "rul_lower_hours": rul_low_h,
        "rul_upper_hours": rul_up_h,
    }

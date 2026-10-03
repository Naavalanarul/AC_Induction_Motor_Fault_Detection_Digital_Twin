import numpy as np

from app.diagnostics.prognosis import estimate_time_to_threshold
from app.diagnostics.rul_engine import RULEngine


def test_short_history_accumulates_data():
    """History with < 30 samples returns status='accumulating_data' and rul_hours=null."""
    history = [(float(t), 0.1 + 0.005 * t) for t in range(20)]  # 20 samples < 30
    res = estimate_time_to_threshold(history)
    assert res["status"] == "accumulating_data"
    assert res["rul_hours"] is None
    assert res["rul_lower_hours"] is None
    assert res["rul_upper_hours"] is None
    assert res["method"] == "linear_trend"
    assert res["sample_count"] == 20


def test_noisy_flat_signal_is_stable_with_null_rul():
    """Noisy flat signal (R2 < 0.5 or non-positive slope) returns status='stable' and rul_hours=null."""
    rng = np.random.default_rng(42)
    # 40 samples of mean 0.25 with zero slope + random noise
    times = [float(t) for t in range(40)]
    sevs = [0.25 + rng.normal(0, 0.01) for _ in range(40)]
    history = list(zip(times, sevs, strict=True))

    res = estimate_time_to_threshold(history)
    assert res["status"] == "stable"
    assert res["rul_hours"] is None
    assert res["rul_lower_hours"] is None
    assert res["rul_upper_hours"] is None
    assert res["method"] == "linear_trend"


def test_clear_degradation_trend_yields_accurate_rul_with_95_ci():
    """Clear degradation trend (slope > 0, R2 >= 0.5) produces status='degrading' and finite 95% CI."""
    # 50 samples with steady ramp: severity = 0.2 + 0.005 * t
    # at t=49, severity = 0.2 + 0.245 = 0.445
    # failure trip threshold (0.8): delta = 0.8 - 0.445 = 0.355
    # time to trip: 0.355 / 0.005 = 71.0 seconds
    times = [float(t) for t in range(50)]
    sevs = [0.2 + 0.005 * t for t in range(50)]
    history = list(zip(times, sevs, strict=True))

    res = estimate_time_to_threshold(history, trip_thresh=0.8)
    assert res["status"] == "degrading"
    assert res["trend"] == "increasing"
    assert res["method"] == "linear_trend"
    assert res["r2"] is not None and res["r2"] > 0.95

    # Nominal RUL
    assert res["rul_hours"] is not None
    expected_rul_hours = 71.0 / 3600.0
    assert abs(res["rul_hours"] - expected_rul_hours) < 0.005

    # 95% Confidence / Prediction bounds
    assert res["rul_lower_hours"] is not None
    assert res["rul_upper_hours"] is not None
    assert 0.0 < res["rul_lower_hours"] <= res["rul_hours"] <= res["rul_upper_hours"]


def test_monotonicity_filter_handles_fluctuations():
    """Fluctuating or decaying symptoms during load shedding are filtered monotonically."""
    # Severity ramps up, dips briefly due to derate, then continues
    history = [(float(t), 0.2 + 0.005 * t) for t in range(25)]
    # Dip at t=25..30
    history += [(float(t), 0.25) for t in range(25, 30)]
    # Continues up at t=30..45
    history += [(float(t), 0.30 + 0.005 * (t - 30)) for t in range(30, 45)]

    res = estimate_time_to_threshold(history)
    assert res["status"] == "degrading"
    assert res["rul_hours"] is not None
    assert res["rul_lower_hours"] is not None and res["rul_upper_hours"] is not None


def test_rul_engine_predict_trend_guards():
    """RULEngine.predict_rul_from_trend enforces 30 samples and R2 threshold."""
    engine = RULEngine()

    # Short history (< 30) -> returns (0.0, 0.0)
    short_hist = [(float(t), 95.0 - 0.5 * t) for t in range(15)]
    rul, conf = engine.predict_rul_from_trend(short_hist)
    assert rul == 0.0 and conf == 0.0

    # 40 samples degrading -> returns finite RUL and confidence
    long_hist = [(float(t), 95.0 - 0.5 * t) for t in range(40)]
    rul, conf = engine.predict_rul_from_trend(long_hist, threshold_health=20.0)
    assert rul > 0.0
    assert conf >= 0.5

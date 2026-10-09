"""app/api/routes/static.py — Static-value snapshot diagnosis endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.api.schemas import Page
from app.config import get_settings
from app.core.ratelimit import rate_limit
from app.db.models import Motor, StaticAnalysis
from app.db.session import get_db
from app.diagnostics.prognosis import estimate_time_to_threshold
from app.static_analysis.engine import StaticDiagnosticEngine
from app.static_analysis.schemas import StaticDiagnosisOut, StaticMeasurement

router = APIRouter(prefix="/static", tags=["static-analysis"])
engine = StaticDiagnosticEngine()

_static_rate_limit = rate_limit("static_diagnose", lambda: get_settings().fault_rate_per_min)


@router.post(
    "/diagnose",
    response_model=StaticDiagnosisOut,
    dependencies=[Depends(_static_rate_limit)],
    summary="Run static-value motor diagnosis on input snapshot",
)
def diagnose_static(
    measurement: StaticMeasurement,
    request: Request,
    response: Response,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    p: Principal = Depends(require("operator")),
    db: Session = Depends(get_db),
) -> StaticDiagnosisOut:
    """Executes steady-state physics residual and multi-channel diagnosis on measured scalars.

    Role requirement: operator or admin.
    """
    if idempotency_key:
        existing = db.scalar(
            select(StaticAnalysis).where(StaticAnalysis.request_id == idempotency_key)
        )
        if existing is not None:
            return StaticDiagnosisOut.model_validate(existing.result_json)

    # Validate motor exists if motor_id is passed
    if measurement.motor_id is not None:
        motor = db.get(Motor, measurement.motor_id)
        if motor is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Motor {measurement.motor_id} not found in database",
            )

    try:
        result = engine.diagnose(measurement, db=db)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    # Persist analysis
    row = StaticAnalysis(
        user=p.username,
        motor_id=measurement.motor_id,
        inputs_json=measurement.model_dump(mode="json"),
        result_json=result.model_dump(mode="json"),
        fault_type=result.fault_type,
        severity=result.severity,
        mhi=result.health_index,
        request_id=idempotency_key,
    )
    db.add(row)
    db.commit()

    return result


@router.get("/analyses", response_model=Page, summary="List past static analyses (paged)")
def list_analyses(
    motor_id: int | None = Query(None, description="Filter by motor ID"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: Principal = Depends(require("viewer")),
    db: Session = Depends(get_db),
) -> Page:
    """Returns paged historical static diagnostic analyses. Role requirement: viewer."""
    q = select(StaticAnalysis)
    if motor_id is not None:
        q = q.where(StaticAnalysis.motor_id == motor_id)

    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(
        q.order_by(StaticAnalysis.ts.desc(), StaticAnalysis.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    items = [
        {
            "id": r.id,
            "user": r.user,
            "ts": r.ts.isoformat(),
            "motor_id": r.motor_id,
            "fault_type": r.fault_type,
            "severity": r.severity,
            "mhi": r.mhi,
            "error_code": r.result_json.get("error_code") if r.result_json else None,
            "zone": r.result_json.get("zone") if r.result_json else None,
        }
        for r in rows
    ]
    return Page(total=total, limit=limit, offset=offset, items=items)


@router.get("/analyses/{analysis_id}", response_model=dict[str, Any], summary="Get full static analysis record")
def get_analysis(
    analysis_id: int,
    _: Principal = Depends(require("viewer")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieves full detail of a specific saved static analysis. Role requirement: viewer."""
    row = db.get(StaticAnalysis, analysis_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis record not found")

    return {
        "id": row.id,
        "user": row.user,
        "ts": row.ts.isoformat(),
        "motor_id": row.motor_id,
        "inputs": row.inputs_json,
        "result": row.result_json,
        "fault_type": row.fault_type,
        "severity": row.severity,
        "mhi": row.mhi,
    }


@router.get("/trend", summary="Prognosis trend from sparse manual static snapshots")
def static_trend(
    motor_id: int = Query(..., description="Target motor ID"),
    _: Principal = Depends(require("viewer")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Projects degradation trend / RUL from saved static analyses.

    Marked clearly as based on sparse manual snapshot readings.
    """
    rows = db.scalars(
        select(StaticAnalysis)
        .where(StaticAnalysis.motor_id == motor_id)
        .order_by(StaticAnalysis.ts.asc())
        .limit(100)
    ).all()

    if len(rows) < 3:
        return {
            "motor_id": motor_id,
            "data_points": len(rows),
            "status": "insufficient_history",
            "message": "At least 3 historical static snapshots are required to estimate a trend.",
            "is_sparse_snapshot": True,
        }

    t0 = rows[0].ts.timestamp()
    history: list[tuple[float, float]] = [
        (r.ts.timestamp() - t0, float(r.severity)) for r in rows
    ]

    fit = estimate_time_to_threshold(history, derate_thresh=0.5, trip_thresh=0.8)
    slope = float(fit.get("slope_per_s") or 0.0)

    return {
        "motor_id": motor_id,
        "data_points": len(rows),
        "status": fit.get("status", "computed"),
        "current_severity": rows[-1].severity,
        "rate_per_day": round(slope * 86400.0, 5),
        "time_to_derate_s": fit.get("time_to_derate_s"),
        "time_to_trip_s": fit.get("time_to_trip_s"),
        "rul_hours": fit.get("rul_hours"),
        "fit_quality_r2": fit.get("r2"),
        "is_sparse_snapshot": True,
        "advisory_notice": (
            "Prognosis projection is calculated from sparse manual snapshots. "
            "Use for long-term trending only; do not use as replacement for high-frequency vibration telemetry."
        ),
    }


from __future__ import annotations

import asyncio
import dataclasses
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Principal, require, runtime
from app.api.schemas import (
    AlertOut,
    DiagnosisOut,
    FaultIn,
    FaultOut,
    HistoryEvent,
    LoadPatch,
    MotorDetail,
    MotorIn,
    MotorOut,
    OverrideIn,
    Page,
    PrognosisOut,
    RecommendationOut,
    SensorOut,
    SensorPatch,
    SupervisoryOut,
)
from app.config import get_settings
from app.core.metrics import FAULT_INJECTIONS
from app.core.ratelimit import rate_limit
from app.db.models import (
    Alert,
    Diagnosis,
    FaultInjected,
    Motor,
    Sensor,
    SensorModeEnum,
    SensorTypeEnum,
    SupervisoryAction,
    utcnow,
)
from app.db.session import get_db
from app.diagnostics.schema import DiagFault
from app.simulation.params import DEFAULT_MOTOR
from app.supervisory.sada import SadaConfig

router = APIRouter(prefix="/motors", tags=["motors"])
_fault_limit = rate_limit("faults", lambda: get_settings().fault_rate_per_min)


def _motor(db: Session, motor_id: int) -> Motor:
    m = db.get(Motor, motor_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "motor not found")
    return m


def create_motor_row(db: Session, name: str, params: dict, base_load_nm: float) -> Motor:
    m = Motor(name=name, rated_power=params["rated_power"], rated_speed=params["rated_speed"],
              rated_torque=params["rated_torque"], base_load_nm=base_load_nm, params_json=params)
    m.sensors = [Sensor(type=t, mode=SensorModeEnum.simulated, config_json={}) for t in SensorTypeEnum]
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


@router.get("", response_model=list[MotorOut])
def list_motors(_: Principal = Depends(require("viewer")), db: Session = Depends(get_db)):
    return db.scalars(select(Motor).order_by(Motor.id)).all()


@router.post("", response_model=MotorOut, status_code=201)
async def create_motor(body: MotorIn, request: Request, _: Principal = Depends(require("admin")),
                       db: Session = Depends(get_db)):
    params = body.params.model_dump() if body.params else dataclasses.asdict(DEFAULT_MOTOR)
    try:
        m = await asyncio.to_thread(create_motor_row, db, body.name, params, body.base_load_nm)
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "motor name exists") from exc
    # the worker task must be created on the event loop, hence this handler is async
    rt = request.app.state.runtime
    if rt.settings.run_simulation:
        rt.manager.start(m.id)
    return m


@router.get("/{motor_id}", response_model=MotorDetail)
async def get_motor(motor_id: int, _: Principal = Depends(require("viewer")), db: Session = Depends(get_db),
                    rt=Depends(runtime)):
    m = _motor(db, motor_id)
    latest = await rt.broker.get_latest(motor_id)
    state = None
    if latest:
        state = {k: latest.get(k) for k in ("t", "diagnosis", "supervisory", "faults", "mechanics", "ml_backend")}
    detail = MotorDetail.model_validate(m)
    detail.state = state
    return detail


@router.patch("/{motor_id}/load", response_model=MotorOut)
async def set_load(motor_id: int, body: LoadPatch, p: Principal = Depends(require("operator")),
                   db: Session = Depends(get_db), rt=Depends(runtime)):
    m = _motor(db, motor_id)
    m.base_load_nm = body.base_load_nm
    db.commit()
    await rt.broker.publish(f"cmd:{motor_id}", {"cmd": "base_load", "value": body.base_load_nm, "actor": p.username})
    return m


# ---------------------------------------------------------------- faults
@router.post("/{motor_id}/faults", response_model=FaultOut, status_code=201, dependencies=[Depends(_fault_limit)])
async def inject_fault(motor_id: int, body: FaultIn, response: Response, p: Principal = Depends(require("operator")),
                       db: Session = Depends(get_db), rt=Depends(runtime),
                       idempotency_key: str | None = Header(default=None, max_length=64)):
    _motor(db, motor_id)
    if idempotency_key:
        existing = db.scalar(select(FaultInjected).where(FaultInjected.request_id == idempotency_key))
        if existing:
            if existing.motor_id != motor_id:
                raise HTTPException(status.HTTP_409_CONFLICT, "idempotency key reused for another motor")
            response.status_code = status.HTTP_200_OK
            return existing
    # Durably log the injection BEFORE it is applied to the simulation.
    row = FaultInjected(motor_id=motor_id, fault_type=body.fault_type.value, severity=body.severity,
                        params_json=body.params, request_id=idempotency_key, created_by=p.username)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:  # concurrent retry with the same key
        db.rollback()
        return db.scalar(select(FaultInjected).where(FaultInjected.request_id == idempotency_key))
    FAULT_INJECTIONS.labels(body.fault_type.value).inc()
    await rt.broker.publish(f"cmd:{motor_id}", {"cmd": "inject", "id": row.id, "fault_type": row.fault_type,
                                                "severity": row.severity, "params": row.params_json})
    return row


@router.get("/{motor_id}/faults", response_model=list[FaultOut])
def list_faults(motor_id: int, active: bool | None = None, _: Principal = Depends(require("viewer")),
                db: Session = Depends(get_db)):
    _motor(db, motor_id)
    q = select(FaultInjected).where(FaultInjected.motor_id == motor_id)
    if active is True:
        q = q.where(FaultInjected.end_ts.is_(None))
    elif active is False:
        q = q.where(FaultInjected.end_ts.is_not(None))
    return db.scalars(q.order_by(FaultInjected.start_ts.desc()).limit(500)).all()


@router.delete("/{motor_id}/faults/{fault_id}", response_model=FaultOut)
async def clear_fault(motor_id: int, fault_id: int, _: Principal = Depends(require("operator")),
                      db: Session = Depends(get_db), rt=Depends(runtime)):
    row = db.get(FaultInjected, fault_id)
    if row is None or row.motor_id != motor_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "fault not found")
    if row.end_ts is None:  # idempotent: clearing twice is a no-op
        row.end_ts = utcnow()
        db.commit()
        await rt.broker.publish(f"cmd:{motor_id}", {"cmd": "clear", "fault_id": fault_id})
    return row


# ---------------------------------------------------------------- sensors
@router.get("/{motor_id}/sensors", response_model=list[SensorOut])
def list_sensors(motor_id: int, _: Principal = Depends(require("viewer")), db: Session = Depends(get_db)):
    return _motor(db, motor_id).sensors


@router.patch("/{motor_id}/sensors/{sensor_id}", response_model=SensorOut)
async def patch_sensor(motor_id: int, sensor_id: int, body: SensorPatch, _: Principal = Depends(require("admin")),
                       db: Session = Depends(get_db), rt=Depends(runtime)):
    s = db.get(Sensor, sensor_id)
    if s is None or s.motor_id != motor_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sensor not found")
    s.mode = SensorModeEnum(body.mode)
    db.commit()
    await rt.broker.publish(f"cmd:{motor_id}", {"cmd": "sensor_mode", "sensor_type": s.type.value, "mode": body.mode})
    return s


# ---------------------------------------------------------------- history
@router.get("/{motor_id}/diagnoses", response_model=Page)
def list_diagnoses(motor_id: int, start: datetime | None = None, end: datetime | None = None,
                   fault_type: DiagFault | None = None,
                   limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
                   _: Principal = Depends(require("viewer")), db: Session = Depends(get_db)):
    _motor(db, motor_id)
    q = select(Diagnosis).where(Diagnosis.motor_id == motor_id)
    if start:
        q = q.where(Diagnosis.ts >= start)
    if end:
        q = q.where(Diagnosis.ts <= end)
    if fault_type:
        q = q.where(Diagnosis.fault_type == fault_type.value)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(Diagnosis.ts.desc(), Diagnosis.id.desc()).limit(limit).offset(offset)).all()
    return Page(total=total or 0, limit=limit, offset=offset, items=[DiagnosisOut.model_validate(r) for r in rows])


@router.get("/{motor_id}/history", response_model=list[HistoryEvent])
def history(motor_id: int, start: datetime | None = None, end: datetime | None = None,
            limit: int = Query(200, ge=1, le=2000), _: Principal = Depends(require("viewer")),
            db: Session = Depends(get_db)):
    _motor(db, motor_id)
    events: list[HistoryEvent] = []
    fq = select(FaultInjected).where(FaultInjected.motor_id == motor_id)
    sq = select(SupervisoryAction).where(SupervisoryAction.motor_id == motor_id)
    if start:
        sq = sq.where(SupervisoryAction.ts >= start)
    if end:
        sq = sq.where(SupervisoryAction.ts <= end)
    for f in db.scalars(fq.order_by(FaultInjected.start_ts.desc()).limit(limit)):
        data = FaultOut.model_validate(f).model_dump(mode="json")
        events.append(HistoryEvent(ts=f.start_ts, kind="fault_injected", data=data))
        if f.end_ts:
            events.append(HistoryEvent(ts=f.end_ts, kind="fault_cleared", data=data))
    for a in db.scalars(sq.order_by(SupervisoryAction.ts.desc()).limit(limit)):
        events.append(HistoryEvent(ts=a.ts, kind="supervisory",
                                   data=SupervisoryOut.model_validate(a).model_dump(mode="json")))
    events = [e for e in events if (not start or e.ts >= start) and (not end or e.ts <= end)]
    events.sort(key=lambda e: e.ts, reverse=True)
    return events[:limit]


@router.get("/{motor_id}/alerts", response_model=list[AlertOut])
def list_alerts(motor_id: int, unacknowledged: bool = False, limit: int = Query(100, ge=1, le=1000),
                _: Principal = Depends(require("viewer")), db: Session = Depends(get_db)):
    _motor(db, motor_id)
    q = select(Alert).where(Alert.motor_id == motor_id)
    if unacknowledged:
        q = q.where(Alert.acknowledged.is_(False))
    return db.scalars(q.order_by(Alert.ts.desc(), Alert.id.desc()).limit(limit)).all()


@router.post("/{motor_id}/alerts/{alert_id}/ack", response_model=AlertOut)
def ack_alert(motor_id: int, alert_id: int, _: Principal = Depends(require("operator")), db: Session = Depends(get_db)):
    a = db.get(Alert, alert_id)
    if a is None or a.motor_id != motor_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "alert not found")
    a.acknowledged = True
    db.commit()
    return a


# ---------------------------------------------------------------- supervisory
@router.post("/{motor_id}/supervisory/override", response_model=SupervisoryOut)
async def override(motor_id: int, body: OverrideIn, p: Principal = Depends(require("operator")),
                   db: Session = Depends(get_db), rt=Depends(runtime),
                   idempotency_key: str | None = Header(default=None, max_length=64)):
    _motor(db, motor_id)
    if idempotency_key:
        existing = db.scalar(select(SupervisoryAction).where(SupervisoryAction.request_id == idempotency_key))
        if existing:
            return existing
    latest = await rt.broker.get_latest(motor_id)
    sup = (latest or {}).get("supervisory") or {}
    if body.action == "reset" and sup.get("trip"):
        cfg = SadaConfig()
        if float(sup.get("smoothed_severity", 1.0)) >= cfg.trip - cfg.hysteresis:
            raise HTTPException(status.HTTP_409_CONFLICT, "cannot reset: fault severity still at trip level")
    load = body.load if body.action == "set_load" else float(sup.get("load_cmd", 1.0))
    # Durably log the operator action BEFORE it is applied.
    row = SupervisoryAction(motor_id=motor_id, state=str(sup.get("state", "UNKNOWN")), load_cmd=load,
                            reason_code=f"MANUAL_{body.action.upper()}", trip=bool(sup.get("trip", False)),
                            smoothed_severity=sup.get("smoothed_severity"), actor=p.username,
                            request_id=idempotency_key)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.scalar(select(SupervisoryAction).where(SupervisoryAction.request_id == idempotency_key))
    await rt.broker.publish(f"cmd:{motor_id}", {"cmd": "override", "action": body.action, "load": body.load,
                                                "actor": p.username})
    return row


# ---------------------------------------------------------------- prognosis & recommendation
@router.get("/{motor_id}/prognosis", response_model=PrognosisOut)
def get_motor_prognosis(
    motor_id: int,
    _: Principal = Depends(require("viewer")),
    db: Session = Depends(get_db),
    rt=Depends(runtime),
):
    _motor(db, motor_id)
    return rt.manager.get_prognosis(motor_id, db=db)


@router.get("/{motor_id}/recommendation", response_model=RecommendationOut)
def get_motor_recommendation(
    motor_id: int,
    _: Principal = Depends(require("viewer")),
    db: Session = Depends(get_db),
    rt=Depends(runtime),
):
    _motor(db, motor_id)
    return rt.manager.get_recommendation(motor_id, db=db)


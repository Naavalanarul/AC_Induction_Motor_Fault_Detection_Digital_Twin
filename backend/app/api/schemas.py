"""api/schemas.py — Pydantic request/response models (single source of truth for OpenAPI)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.simulation.faults import FaultType


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    role: str
    username: str


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=256)
    role: Literal["viewer", "operator", "admin"] = "viewer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    role: str
    is_active: bool


class MotorParamsIn(BaseModel):
    Rs: float = Field(gt=0)
    Rr: float = Field(gt=0)
    Ls: float = Field(gt=0)
    Lr: float = Field(gt=0)
    Lm: float = Field(gt=0)
    J: float = Field(gt=0)
    pole_pairs: int = Field(ge=1, le=12)
    rated_power: float = Field(gt=0)
    rated_voltage: float = Field(gt=0)
    rated_current: float = Field(gt=0)
    rated_speed: float = Field(gt=0)
    rated_torque: float = Field(gt=0)

    @model_validator(mode="after")
    def _physical(self):
        if self.Lm >= min(self.Ls, self.Lr):
            raise ValueError("Lm must be smaller than Ls and Lr (positive leakage)")
        return self


class MotorIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    params: MotorParamsIn | None = None  # default: the built-in 1.5 kW parameter set
    base_load_nm: float = Field(default=8.0, ge=0, le=50)


class SensorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    motor_id: int
    type: str
    mode: str
    config_json: dict


class SensorPatch(BaseModel):
    mode: Literal["simulated", "hardware"]


class MotorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    rated_power: float
    rated_speed: float
    rated_torque: float
    base_load_nm: float
    params_json: dict
    created_at: datetime


class MotorDetail(MotorOut):
    sensors: list[SensorOut]
    state: dict | None = None


class LoadPatch(BaseModel):
    base_load_nm: float = Field(ge=0, le=50)


class FaultIn(BaseModel):
    fault_type: FaultType
    severity: float = Field(ge=0.0, le=1.0)
    params: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_params(self):
        p = self.params
        allowed = {
            FaultType.BROKEN_ROTOR_BAR: {"count", "position"},
            FaultType.INTERTURN_SHORT: {"phase"},
            FaultType.ECCENTRICITY: {"type"},
            FaultType.VOLTAGE_ANOMALY: {"type"},
        }.get(self.fault_type, set())
        extra = set(p) - allowed
        if extra:
            raise ValueError(f"unexpected params for {self.fault_type.value}: {sorted(extra)}")
        if "phase" in p and p["phase"] not in ("a", "b", "c"):
            raise ValueError("phase must be a, b or c")
        if self.fault_type == FaultType.ECCENTRICITY and p.get("type", "dynamic") not in ("static", "dynamic"):
            raise ValueError("eccentricity type must be static or dynamic")
        if self.fault_type == FaultType.VOLTAGE_ANOMALY and p.get("type", "sag") not in ("sag", "imbalance", "harmonic"):
            raise ValueError("voltage anomaly type must be sag, imbalance or harmonic")
        if "count" in p and not (isinstance(p["count"], int) and 1 <= p["count"] <= 8):
            raise ValueError("count must be an integer in [1, 8]")
        return self


class FaultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    motor_id: int
    fault_type: str
    severity: float
    params_json: dict
    start_ts: datetime
    end_ts: datetime | None
    created_by: str | None


class DiagnosisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ts: datetime
    fault_type: str
    confidence: float
    severity_score: float
    per_sensor_scores_json: dict
    source: str


class Page(BaseModel):
    total: int
    limit: int
    offset: int
    items: list


class OverrideIn(BaseModel):
    action: Literal["ack", "reset", "set_load", "release_load"]
    load: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _load_required(self):
        if self.action == "set_load" and self.load is None:
            raise ValueError("load is required for set_load")
        return self


class SupervisoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ts: datetime
    state: str
    load_cmd: float
    reason_code: str
    trip: bool
    smoothed_severity: float | None
    actor: str


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ts: datetime
    severity: str
    message: str
    acknowledged: bool


class HistoryEvent(BaseModel):
    ts: datetime
    kind: Literal["fault_injected", "fault_cleared", "supervisory"]
    data: dict


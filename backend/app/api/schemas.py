"""api/schemas.py — Pydantic request/response models (single source of truth for OpenAPI)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.simulation.faults import FaultType
from app.simulation.params import MotorParams, validate_motor_params


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
    t_ambient: float = Field(default=25.0, ge=-20.0, le=80.0)
    insulation_class: Literal["B", "F", "H"] = "F"
    warn_c: float | None = Field(default=None, gt=0)
    trip_c: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _validate_params(self):
        p = MotorParams(
            Rs=self.Rs,
            Rr=self.Rr,
            Ls=self.Ls,
            Lr=self.Lr,
            Lm=self.Lm,
            J=self.J,
            pole_pairs=self.pole_pairs,
            rated_power=self.rated_power,
            rated_voltage=self.rated_voltage,
            rated_current=self.rated_current,
            rated_speed=self.rated_speed,
            rated_torque=self.rated_torque,
            t_ambient=self.t_ambient,
            insulation_class=self.insulation_class,
            warn_c=self.warn_c,
            trip_c=self.trip_c,
        )
        ok, err_msg = validate_motor_params(p)
        if not ok:
            raise ValueError(err_msg)
        return self


class MotorIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    params: MotorParamsIn | None = None  # default: the built-in 1.5 kW parameter set
    base_load_nm: float = Field(default=8.0, ge=0, le=2000.0)


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
    base_load_nm: float = Field(ge=0, le=2000.0)


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
    health_index: float | None = None
    error_code: str | None = None


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


class PrognosisOut(BaseModel):
    current_severity: float
    slope_per_s: float
    time_to_derate_s: float | None = None
    time_to_trip_s: float | None = None
    trend: str
    sample_count: int


class RecommendationOut(BaseModel):
    motor_id: int
    fault_type: str
    zone: str
    mhi: float
    urgency: str
    title: str
    action: str
    checklist: list[str]


class TransientSolveIn(BaseModel):
    duration_s: float = Field(default=0.8, ge=0.05, le=3.0)
    load_torque_nm: float = Field(default=8.0, ge=0.0, le=50.0)
    itsc_mu: float = Field(default=0.0, ge=0.0, le=0.5)
    itsc_rf: float = Field(default=20.0, ge=0.01)
    brb_delta: float = Field(default=0.0, ge=0.0, le=2.0)
    ecc_dynamic: float = Field(default=0.0, ge=0.0, le=0.9)
    method: Literal["RK45", "DOP853", "Radau"] = "RK45"


class TransientSolveOut(BaseModel):
    motor_id: int
    duration_s: float
    steady_state_rpm: float
    steady_state_torque: float
    slip: float
    t: list[float]
    rpm: list[float]
    te: list[float]
    load_torque: list[float]
    ia: list[float]
    ib: list[float]
    ic: list[float]
    id: list[float]
    iq: list[float]
    psi_rd: list[float]
    psi_rq: list[float]
    copper_loss_w: list[float]
    fault_heat_w: list[float]


class MCSAPeakOut(BaseModel):
    freq_hz: float
    magnitude_db: float
    label: str
    harmonic_k: int | None = None
    expected_freq_hz: float | None = None
    deviation_hz: float | None = None


class MCSAResultOut(BaseModel):
    status: str
    fundamental_freq: float = 50.0
    fundamental_mag_db: float = 0.0
    slip: float = 0.02
    rotor_freq_hz: float = 24.5
    brb_fault_detected: bool = False
    eccentricity_detected: bool = False
    worst_brb_sideband_db: float | None = None
    peaks: list[MCSAPeakOut] = []
    brb_peaks: list[MCSAPeakOut] = []
    ecc_peaks: list[MCSAPeakOut] = []
    freqs: list[float] = []
    psd_db: list[float] = []


class InsulationRULOut(BaseModel):
    winding_temp_c: float
    hotspot_temp_c: float
    aging_acceleration_factor: float
    nominal_life_hours: float
    rul_hours: float
    rul_years: float
    health_percent: float
    temp_margin_c: float


class BearingRULOut(BaseModel):
    bearing_temp_c: float
    shaft_speed_rpm: float
    l10h_hours: float
    adjusted_l10h_hours: float
    rul_hours: float
    rul_years: float
    health_percent: float
    vibration_rms_mms: float
    iso_zone: str


class RULResultOut(BaseModel):
    motor_id: int
    overall_rul_hours: float
    overall_rul_years: float
    overall_health_percent: float
    limiting_factor: str
    insulation: InsulationRULOut
    bearing_de: BearingRULOut
    bearing_nde: BearingRULOut




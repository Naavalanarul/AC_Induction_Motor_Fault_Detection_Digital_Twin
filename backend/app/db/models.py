"""db/models.py — SQLAlchemy 2.x ORM models (MySQL 8 target, SQLite for tests/dev)."""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Microsecond timestamps on MySQL; BIGINT ids that still autoincrement on SQLite.
TS = DateTime(timezone=False).with_variant(mysql.DATETIME(fsp=6), "mysql")
BIGID = BigInteger().with_variant(Integer, "sqlite")
BLOB = LargeBinary().with_variant(mysql.MEDIUMBLOB(), "mysql")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class SensorTypeEnum(str, enum.Enum):
    current = "current"
    vibration = "vibration"
    acoustic = "acoustic"
    temp = "temp"
    speed = "speed"
    voltage = "voltage"


class SensorModeEnum(str, enum.Enum):
    simulated = "simulated"
    hardware = "hardware"


class DiagSourceEnum(str, enum.Enum):
    electrical_residual = "electrical_residual"
    ml_classifier = "ml_classifier"
    thermal = "thermal"
    supply = "supply"
    fused = "fused"


class RoleEnum(str, enum.Enum):
    viewer = "viewer"
    operator = "operator"
    admin = "admin"


class Motor(Base):
    __tablename__ = "motors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    rated_power: Mapped[float] = mapped_column(Float)
    rated_speed: Mapped[float] = mapped_column(Float)
    rated_torque: Mapped[float] = mapped_column(Float)
    base_load_nm: Mapped[float] = mapped_column(Float, default=8.0)
    params_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    sensors: Mapped[list[Sensor]] = relationship(back_populates="motor", cascade="all, delete-orphan")


class Sensor(Base):
    __tablename__ = "sensors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    motor_id: Mapped[int] = mapped_column(ForeignKey("motors.id", ondelete="CASCADE"), index=True)
    type: Mapped[SensorTypeEnum] = mapped_column(Enum(SensorTypeEnum, name="sensor_type"))
    mode: Mapped[SensorModeEnum] = mapped_column(Enum(SensorModeEnum, name="sensor_mode"),
                                                 default=SensorModeEnum.simulated)
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    motor: Mapped[Motor] = relationship(back_populates="sensors")


class SensorReading(Base):
    """Extracted features per window, always. Raw waveforms only on anomaly/on demand (raw_ref)."""

    __tablename__ = "sensor_readings"
    id: Mapped[int] = mapped_column(BIGID, primary_key=True, autoincrement=True)
    sensor_id: Mapped[int] = mapped_column(ForeignKey("sensors.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    window_start: Mapped[float] = mapped_column(Float)
    window_end: Mapped[float] = mapped_column(Float)
    feature_vector_json: Mapped[dict] = mapped_column(JSON)
    raw_ref: Mapped[bytes | None] = mapped_column(BLOB, nullable=True)
    __table_args__ = (Index("ix_sensor_readings_sensor_ts", "sensor_id", "ts"),)


class Diagnosis(Base):
    __tablename__ = "diagnoses"
    id: Mapped[int] = mapped_column(BIGID, primary_key=True, autoincrement=True)
    motor_id: Mapped[int] = mapped_column(ForeignKey("motors.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    fault_type: Mapped[str] = mapped_column(String(40))
    confidence: Mapped[float] = mapped_column(Float)
    severity_score: Mapped[float] = mapped_column(Float)
    per_sensor_scores_json: Mapped[dict] = mapped_column(JSON)
    source: Mapped[DiagSourceEnum] = mapped_column(Enum(DiagSourceEnum, name="diag_source"),
                                                   default=DiagSourceEnum.fused)
    health_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(24), nullable=True)
    __table_args__ = (Index("ix_diagnoses_motor_ts", "motor_id", "ts"),)


class FaultInjected(Base):
    """Ground truth for simulation runs. Written *before* the fault is applied."""

    __tablename__ = "faults_injected"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    motor_id: Mapped[int] = mapped_column(ForeignKey("motors.id", ondelete="CASCADE"))
    fault_type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[float] = mapped_column(Float)
    params_json: Mapped[dict] = mapped_column(JSON, default=dict)
    start_ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    end_ts: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    __table_args__ = (Index("ix_faults_motor_ts", "motor_id", "start_ts"),)


class SupervisoryAction(Base):
    __tablename__ = "supervisory_actions"
    id: Mapped[int] = mapped_column(BIGID, primary_key=True, autoincrement=True)
    motor_id: Mapped[int] = mapped_column(ForeignKey("motors.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    state: Mapped[str] = mapped_column(String(16))
    load_cmd: Mapped[float] = mapped_column(Float)
    reason_code: Mapped[str] = mapped_column(String(64))
    trip: Mapped[bool] = mapped_column(Boolean, default=False)
    smoothed_severity: Mapped[float | None] = mapped_column(Float, nullable=True)
    actor: Mapped[str] = mapped_column(String(64), default="sada")
    request_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    __table_args__ = (Index("ix_supervisory_motor_ts", "motor_id", "ts"),)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(BIGID, primary_key=True, autoincrement=True)
    motor_id: Mapped[int] = mapped_column(ForeignKey("motors.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    severity: Mapped[str] = mapped_column(String(16))  # info | warning | critical
    message: Mapped[str] = mapped_column(String(255))
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (Index("ix_alerts_motor_ts", "motor_id", "ts"),)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[RoleEnum] = mapped_column(Enum(RoleEnum, name="user_role"), default=RoleEnum.viewer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

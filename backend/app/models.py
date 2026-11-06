from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    industry: Mapped[str] = mapped_column(String(80))
    demonstration: Mapped[bool] = mapped_column(Boolean, default=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("user_accounts.id"), nullable=True, index=True)

class UserAccount(Base):
    __tablename__ = "user_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class ESGRecord(Base):
    __tablename__ = "esg_records"
    __table_args__ = (UniqueConstraint("organization_id", "period", name="uq_org_period"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    period: Mapped[str] = mapped_column(String(7), index=True)
    source: Mapped[str] = mapped_column(String(255), default="Synthetic demonstration data")
    electricity_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    renewable_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    scope1_tco2e: Mapped[float | None] = mapped_column(Float, nullable=True)
    scope2_tco2e: Mapped[float | None] = mapped_column(Float, nullable=True)
    scope3_tco2e: Mapped[float | None] = mapped_column(Float, nullable=True)
    water_m3: Mapped[float | None] = mapped_column(Float, nullable=True)
    waste_tonnes: Mapped[float | None] = mapped_column(Float, nullable=True)
    recycled_tonnes: Mapped[float | None] = mapped_column(Float, nullable=True)
    employees: Mapped[float | None] = mapped_column(Float, nullable=True)
    female_employees: Mapped[float | None] = mapped_column(Float, nullable=True)
    male_employees: Mapped[float | None] = mapped_column(Float, nullable=True)
    employee_exits: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    safety_incidents: Mapped[float | None] = mapped_column(Float, nullable=True)
    board_members: Mapped[float | None] = mapped_column(Float, nullable=True)
    independent_directors: Mapped[float | None] = mapped_column(Float, nullable=True)
    compliance_incidents: Mapped[float | None] = mapped_column(Float, nullable=True)
    ethics_violations: Mapped[float | None] = mapped_column(Float, nullable=True)
    audit_findings: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolved_findings: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class UploadJob(Base):
    __tablename__ = "uploaded_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    cleaned_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    status: Mapped[str] = mapped_column(String(30), default="validated")
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, default=0)
    report_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class FlexibleDataset(Base):
    __tablename__ = "flexible_datasets"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    schema_json: Mapped[str] = mapped_column(Text)
    rows_json: Mapped[str] = mapped_column(Text)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class AnomalyEvent(Base):
    __tablename__ = "anomaly_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    period: Mapped[str] = mapped_column(String(7))
    metric: Mapped[str] = mapped_column(String(80))
    value: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(20))
    explanation: Mapped[str] = mapped_column(Text)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

"""Relational schema. Large payloads (raw uploads, normalised snapshots,
reports, model artefacts) live in the object store; tables hold metadata,
hashes and pointers.

Immutability: a DatasetVersion's snapshot file and hash never change after
creation. An AnalysisJob references exactly one DatasetVersion and stores
its full configuration and config hash, so a rerun always uses the same
inputs or creates a new, separately identified job.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


TS = DateTime(timezone=True)


class Organisation(Base):
    __tablename__ = "organisations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str | None] = mapped_column(String(300))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    organisation_id: Mapped[int | None] = mapped_column(ForeignKey("organisations.id"))
    external_subject: Mapped[str | None] = mapped_column(String(300), unique=True)  # OIDC 'sub' when federated
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class AuthToken(Base):
    """Sessions and API tokens. Only a SHA-256 of the token is stored."""

    __tablename__ = "auth_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(16))  # session | api
    label: Mapped[str | None] = mapped_column(String(100))
    csrf_token: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(TS)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    organisation_id: Mapped[int | None] = mapped_column(ForeignKey("organisations.id"))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
    members: Mapped[list[ProjectMember]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # owner | analyst | viewer
    project: Mapped[Project] = relationship(back_populates="members")


class UploadedFile(Base):
    __tablename__ = "uploaded_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(200))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    detected_format: Mapped[str | None] = mapped_column(String(32))
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(TS, default=now)
    retain_until: Mapped[datetime | None] = mapped_column(TS)
    origin: Mapped[str] = mapped_column(String(32), default="upload")  # upload | provider | synthetic


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
    versions: Mapped[list[DatasetVersion]] = relationship(back_populates="dataset", order_by="DatasetVersion.version")


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("dataset_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    file_id: Mapped[int] = mapped_column(ForeignKey("uploaded_files.id"))
    status: Mapped[str] = mapped_column(String(24))  # validated | needs_review | rejected | approved
    format: Mapped[str] = mapped_column(String(32))
    snapshot_key: Mapped[str] = mapped_column(String(200))  # normalised records JSON in object store
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    reference_time: Mapped[datetime] = mapped_column(TS)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
    dataset: Mapped[Dataset] = relationship(back_populates="versions")


class ObjectRecord(Base):
    """Index of normalised records for catalogue browsing; the snapshot file is authoritative."""

    __tablename__ = "object_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(ForeignKey("dataset_versions.id", ondelete="CASCADE"), index=True)
    object_id: Mapped[str] = mapped_column(String(64), index=True)
    object_name: Mapped[str | None] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(24))
    source_format: Mapped[str] = mapped_column(String(32))
    epoch: Mapped[datetime] = mapped_column(TS)
    frame: Mapped[str] = mapped_column(String(16))
    has_covariance: Mapped[bool] = mapped_column(Boolean, default=False)
    perigee_alt_km: Mapped[float | None] = mapped_column(Float)
    apogee_alt_km: Mapped[float | None] = mapped_column(Float)
    inclination_deg: Mapped[float | None] = mapped_column(Float)
    period_min: Mapped[float | None] = mapped_column(Float)
    source_ref: Mapped[str | None] = mapped_column(String(100))
    usable: Mapped[bool] = mapped_column(Boolean, default=True)


class ValidationFinding(Base):
    __tablename__ = "validation_findings"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(ForeignKey("dataset_versions.id", ondelete="CASCADE"), index=True)
    severity: Mapped[str] = mapped_column(String(10))
    code: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    record_ref: Mapped[str | None] = mapped_column(String(100))
    suggestion: Mapped[str | None] = mapped_column(Text)


class Transformation(Base):
    """Proposed or applied data transformation requiring explicit approval."""

    __tablename__ = "transformations"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(ForeignKey("dataset_versions.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(64))  # e.g. drop_duplicates, exclude_records
    description: Mapped[str] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="proposed")  # proposed | approved | rejected
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(TS)
    result_version_id: Mapped[int | None] = mapped_column(ForeignKey("dataset_versions.id"))


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"
    __table_args__ = (Index("ix_jobs_status_created", "status", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    dataset_version_id: Mapped[int] = mapped_column(ForeignKey("dataset_versions.id"))
    kind: Mapped[str] = mapped_column(String(24))  # screening | cdm_assessment
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|succeeded|failed|cancelled
    config: Mapped[dict] = mapped_column(JSON)
    config_sha256: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    progress_message: Mapped[str] = mapped_column(String(200), default="")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_category: Mapped[str | None] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    software: Mapped[dict] = mapped_column(JSON, default=dict)
    rerun_of: Mapped[int | None] = mapped_column(ForeignKey("analysis_jobs.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
    started_at: Mapped[datetime | None] = mapped_column(TS)
    finished_at: Mapped[datetime | None] = mapped_column(TS)
    worker_id: Mapped[str | None] = mapped_column(String(100))
    heartbeat_at: Mapped[datetime | None] = mapped_column(TS)


class Encounter(Base):
    __tablename__ = "encounters"
    __table_args__ = (Index("ix_enc_job_tca", "job_id", "tca"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True)
    primary_id: Mapped[str] = mapped_column(String(64), index=True)
    secondary_id: Mapped[str] = mapped_column(String(64), index=True)
    primary_name: Mapped[str | None] = mapped_column(String(200))
    secondary_name: Mapped[str | None] = mapped_column(String(200))
    tca: Mapped[datetime] = mapped_column(TS)
    tca_iso: Mapped[str] = mapped_column(String(40))
    miss_km: Mapped[float] = mapped_column(Float)
    rel_speed_km_s: Mapped[float] = mapped_column(Float)
    geometry: Mapped[dict] = mapped_column(JSON)
    frame: Mapped[str] = mapped_column(String(16))
    primary_state: Mapped[list] = mapped_column(JSON)
    secondary_state: Mapped[list] = mapped_column(JSON)
    refinement_status: Mapped[str] = mapped_column(String(32))
    flags: Mapped[list] = mapped_column(JSON, default=list)
    data_age_days: Mapped[dict] = mapped_column(JSON, default=dict)
    propagators: Mapped[dict] = mapped_column(JSON, default=dict)
    covariance_available: Mapped[str] = mapped_column(String(16))  # both | partial | none
    pc_status: Mapped[str] = mapped_column(String(32))
    pc_value: Mapped[float | None] = mapped_column(Float)
    ml_priority: Mapped[float | None] = mapped_column(Float)
    ml_model_version: Mapped[str | None] = mapped_column(String(64))


class ProbabilityCalculation(Base):
    __tablename__ = "probability_calculations"
    id: Mapped[int] = mapped_column(primary_key=True)
    encounter_id: Mapped[int] = mapped_column(ForeignKey("encounters.id", ondelete="CASCADE"), index=True)
    method: Mapped[str] = mapped_column(String(120))
    algorithm_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    value: Mapped[float | None] = mapped_column(Float)
    hbr_km: Mapped[float | None] = mapped_column(Float)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class CovarianceRecord(Base):
    __tablename__ = "covariance_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(ForeignKey("dataset_versions.id", ondelete="CASCADE"), index=True)
    object_id: Mapped[str] = mapped_column(String(64))
    epoch_iso: Mapped[str] = mapped_column(String(40))
    frame: Mapped[str] = mapped_column(String(16))
    matrix_km: Mapped[list] = mapped_column(JSON)
    valid: Mapped[bool] = mapped_column(Boolean)
    eigenvalues: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(200))


class MLModel(Base):
    __tablename__ = "ml_models"
    __table_args__ = (UniqueConstraint("name", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))  # experimental | active_experimental | retired
    artefact_key: Mapped[str] = mapped_column(String(200))
    artefact_sha256: Mapped[str] = mapped_column(String(64))
    training_data_sha256: Mapped[str] = mapped_column(String(64))
    training_data_origin: Mapped[str] = mapped_column(String(32))  # synthetic | authorised_labelled
    params: Mapped[dict] = mapped_column(JSON)
    metrics: Mapped[dict] = mapped_column(JSON)
    feature_schema: Mapped[dict] = mapped_column(JSON)
    seed: Mapped[int] = mapped_column(Integer)
    code_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class Scenario(Base):
    __tablename__ = "scenarios"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    encounter_id: Mapped[int] = mapped_column(ForeignKey("encounters.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    params: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    algorithm_version: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True)
    format: Mapped[str] = mapped_column(String(16))
    storage_key: Mapped[str] = mapped_column(String(200))
    sha256: Mapped[str] = mapped_column(String(64))
    generator_version: Mapped[str] = mapped_column(String(32))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class ProviderFetch(Base):
    __tablename__ = "provider_fetches"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    query: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(16))
    http_status: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(TS, default=now)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("uploaded_files.id"))
    message: Mapped[str | None] = mapped_column(Text)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_time", "occurred_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(TS, default=now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))
    project_id: Mapped[int | None] = mapped_column(Integer)
    target: Mapped[str | None] = mapped_column(String(200))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(40))
    ip: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(16), default="ok")


class SystemInfo(Base):
    __tablename__ = "system_info"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(TS, default=now)

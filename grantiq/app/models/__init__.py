"""Portable SQLAlchemy schema: source provenance and staff data stay separate."""
from datetime import date, datetime, timezone
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..database import Base

def utcnow():
    return datetime.now(timezone.utc)

class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class ResearchProspect(Base):
    __tablename__ = "research_prospects"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    original: Mapped[dict] = mapped_column(JSON)
    disposition: Mapped[str] = mapped_column(String(40))
    review_on: Mapped[date | None] = mapped_column(Date)
    team_notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

class SearchCursor(Base):
    __tablename__ = "search_cursor"
    id: Mapped[int] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

class ResearchImport(Base):
    __tablename__ = "research_imports"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class Grant(Base):
    __tablename__ = "grants"
    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    grant_title: Mapped[str] = mapped_column(Text)
    funder_name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    eligibility_text: Mapped[str] = mapped_column(Text, default="")
    award_min: Mapped[float | None] = mapped_column(Float)
    award_max: Mapped[float | None] = mapped_column(Float)
    estimated_award: Mapped[float | None] = mapped_column(Float)
    open_date: Mapped[date | None] = mapped_column(Date)
    deadline: Mapped[date | None] = mapped_column(Date, index=True)
    grant_status: Mapped[str] = mapped_column(String(20), index=True)
    date_discovered: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_checked: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Portable JSON stores variable-length source facts; indexed facts above remain relational.
    details: Mapped[dict] = mapped_column(JSON)
    sources: Mapped[list["SourceRecord"]] = relationship(back_populates="grant", cascade="all, delete-orphan")
    assessment: Mapped["GrantAssessment"] = relationship(back_populates="grant", cascade="all, delete-orphan", uselist=False)
    pipeline: Mapped["PipelineEntry | None"] = relationship(back_populates="grant", cascade="all, delete-orphan", uselist=False)
    reviews: Mapped[list["GrantReview"]] = relationship(back_populates="grant", cascade="all, delete-orphan", order_by="GrantReview.id.desc()")

class SourceRecord(Base):
    __tablename__ = "source_records"
    __table_args__ = (UniqueConstraint("source", "source_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    grant_id: Mapped[int] = mapped_column(ForeignKey("grants.id"), index=True)
    source: Mapped[str] = mapped_column(String(200))
    source_id: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str] = mapped_column(Text, index=True)
    last_checked: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw_text: Mapped[str] = mapped_column(Text)
    grant: Mapped[Grant] = relationship(back_populates="sources")

class GrantAssessment(Base):
    __tablename__ = "grant_assessments"
    grant_id: Mapped[int] = mapped_column(ForeignKey("grants.id"), primary_key=True)
    fit_score: Mapped[float] = mapped_column(Float, index=True)
    confidence_score: Mapped[float] = mapped_column(Float)
    eligibility_status: Mapped[str] = mapped_column(String(32), index=True)
    result: Mapped[dict] = mapped_column(JSON)
    grant: Mapped[Grant] = relationship(back_populates="assessment")

PIPELINE_STATUSES = ["Discovered", "Reviewing", "Interested", "Applying", "Submitted", "Awarded", "Rejected", "Skipped"]

class PipelineEntry(Base):
    __tablename__ = "pipeline_entries"
    grant_id: Mapped[int] = mapped_column(ForeignKey("grants.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default="Interested", index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    assigned_to: Mapped[str] = mapped_column(String(200), default="")
    requested_amount: Mapped[float | None] = mapped_column(Float)
    application_deadline: Mapped[date | None] = mapped_column(Date)
    submission_date: Mapped[date | None] = mapped_column(Date)
    final_result: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    grant: Mapped[Grant] = relationship(back_populates="pipeline")

class RefreshRun(Base):
    __tablename__ = "refresh_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(255), default="Grants.gov + approved sources")
    status: Mapped[str] = mapped_column(String(32), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    found: Mapped[int] = mapped_column(Integer, default=0)
    added: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    expired: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    source_stats: Mapped[dict] = mapped_column(JSON, default=dict)

class ApprovedSource(Base):
    __tablename__ = "approved_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(Text, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    terms_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by: Mapped[str] = mapped_column(String(200), default="")
    terms_reference: Mapped[str] = mapped_column(Text, default="")
    selectors: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

class SearchSchedule(Base):
    __tablename__ = "search_schedule"
    id: Mapped[int] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_hours: Mapped[int] = mapped_column(Integer, default=6)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str] = mapped_column(String(32), default="waiting")
    last_error: Mapped[str] = mapped_column(Text, default="")

class GrantReview(Base):
    """Append-only staff verification; scored values never replace original facts."""
    __tablename__ = "grant_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    grant_id: Mapped[int] = mapped_column(ForeignKey("grants.id"), index=True)
    facts: Mapped[dict] = mapped_column(JSON)
    source_revision: Mapped[str] = mapped_column(String(64))
    evidence_url: Mapped[str] = mapped_column(Text)
    evidence_note: Mapped[str] = mapped_column(Text)
    reviewed_by: Mapped[str] = mapped_column(String(200))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    valid_until: Mapped[date] = mapped_column(Date)
    action: Mapped[str] = mapped_column(String(20), default="verified")
    grant: Mapped[Grant] = relationship(back_populates="reviews")

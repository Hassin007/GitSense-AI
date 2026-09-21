from sqlalchemy import Integer, String, Float, Boolean, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base
import datetime


class Report(Base):
    __tablename__ = "reports"

    id:                    Mapped[int]   = mapped_column(Integer, primary_key=True)
    commit_id:              Mapped[int]   = mapped_column(Integer, ForeignKey("commits.id"), unique=True)

    summary:                Mapped[str]   = mapped_column(String, nullable=False)
    change_type:             Mapped[str]   = mapped_column(String, nullable=False)
    risk_score:               Mapped[float] = mapped_column(Float, nullable=False)
    issues:                   Mapped[list]  = mapped_column(JSON, default=list)          # list[DetectedIssue] as dicts
    recommendations:          Mapped[list]  = mapped_column(JSON, default=list)
    documentation_needed:      Mapped[bool]  = mapped_column(Boolean, default=False)
    documentation_reason:      Mapped[str | None] = mapped_column(String, nullable=True)
    documentation_suggestion:  Mapped[str | None] = mapped_column(String, nullable=True)

    analysis_tier:             Mapped[str]   = mapped_column(String, default="full")     # full | lightweight | multi_agent
    created_at:                Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    # Phase 3: multi-agent graph & caching fields
    analysis_gaps:             Mapped[list]  = mapped_column(JSON, default=list)
    whole_diff_skipped:        Mapped[bool]  = mapped_column(Boolean, default=False)
    scope_metrics:             Mapped[dict]  = mapped_column(JSON, default=dict)
    blast_radius_mermaid:      Mapped[str | None] = mapped_column(String, nullable=True)
    diff_hash:                 Mapped[str | None] = mapped_column(String, index=True, nullable=True)

    commit: Mapped["Commit"] = relationship("Commit", back_populates="report")

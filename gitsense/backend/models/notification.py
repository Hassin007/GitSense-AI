from sqlalchemy import Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from backend.database import Base
import datetime


class Notification(Base):
    __tablename__ = "notifications"

    id:          Mapped[int]  = mapped_column(Integer, primary_key=True)
    commit_id:    Mapped[int]  = mapped_column(Integer, ForeignKey("commits.id"))
    kind:         Mapped[str]  = mapped_column(String, nullable=False)
    # kind values: high_risk_commit | critical_security | breaking_change | diff_too_large | analysis_failed | analysis_gap
    message:      Mapped[str]  = mapped_column(String, nullable=False)
    created_at:   Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

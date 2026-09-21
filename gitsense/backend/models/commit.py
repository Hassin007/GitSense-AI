from sqlalchemy import Integer, String, DateTime, ForeignKey, func, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base
import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.models.report import Report
    from backend.models.repo import ConnectedRepo


class Commit(Base):
    __tablename__ = "commits"

    id:            Mapped[int]         = mapped_column(Integer, primary_key=True)
    repo_id:        Mapped[int]         = mapped_column(Integer, ForeignKey("connected_repos.id"))
    sha:            Mapped[str]         = mapped_column(String, nullable=False)
    message:        Mapped[str]         = mapped_column(String, nullable=False)
    author:         Mapped[str]         = mapped_column(String, nullable=False)
    timestamp:      Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)

    # status values: pending | analyzing | retrying | completed | skipped | failed
    status:          Mapped[str]         = mapped_column(String, default="pending")
    status_detail:    Mapped[str|None]    = mapped_column(String, nullable=True)   # e.g. "retrying: rate limited"
    skip_reason:       Mapped[str|None]    = mapped_column(String, nullable=True)

    risk_score:         Mapped[float|None]  = mapped_column(Float, nullable=True)   # denormalized for fast dashboard queries
    created_at:           Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at:           Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    repo:   Mapped["ConnectedRepo"] = relationship("ConnectedRepo", back_populates="commits")
    report: Mapped["Report | None"] = relationship("Report", back_populates="commit", uselist=False)

from sqlalchemy import Integer, String, DateTime, ForeignKey, func, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base
import datetime

class Commit(Base):
    __tablename__ = "commits"

    # NOTE: Raw diff is NEVER stored here. It lives on GitHub permanently
    # and is re-fetched on demand using the commit sha.

    id:           Mapped[int]         = mapped_column(Integer, primary_key=True)
    repo_id:      Mapped[int]         = mapped_column(Integer, ForeignKey("connected_repos.id"))
    sha:          Mapped[str]         = mapped_column(String, nullable=False)
    message:      Mapped[str]         = mapped_column(String, nullable=False)
    author:       Mapped[str]         = mapped_column(String, nullable=False)
    timestamp:    Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    status:       Mapped[str]         = mapped_column(String, default="pending")
    # status values: pending | completed | skipped | failed
    skip_reason:  Mapped[str|None]    = mapped_column(String, nullable=True)
    # populated after analysis:
    risk_score:   Mapped[float|None]  = mapped_column(Float, nullable=True)
    created_at:   Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    repo: Mapped["ConnectedRepo"] = relationship("ConnectedRepo", back_populates="commits")

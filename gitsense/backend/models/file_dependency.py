from sqlalchemy import Integer, String, ForeignKey, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from backend.database import Base
import datetime


class FileDependency(Base):
    """
    One row per known "importer -> imported" edge, discovered
    incrementally as files get analyzed. Fully synced (stale edges
    deleted, current edges upserted) every time the importer file is
    analyzed — not just appended to.
    """
    __tablename__ = "file_dependencies"

    id:                    Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id:                 Mapped[int] = mapped_column(Integer, ForeignKey("connected_repos.id"))
    importer_filepath:          Mapped[str] = mapped_column(String, nullable=False)
    imported_filepath:             Mapped[str] = mapped_column(String, nullable=False)
    last_seen_commit_sha:             Mapped[str] = mapped_column(String, nullable=False)
    updated_at:                          Mapped[datetime.datetime] = mapped_column(
                                              DateTime, server_default=func.now(), onupdate=func.now())

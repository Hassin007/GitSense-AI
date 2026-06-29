from sqlalchemy import Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base
import datetime

class ConnectedRepo(Base):
    __tablename__ = "connected_repos"

    id:               Mapped[int]      = mapped_column(Integer, primary_key=True)
    user_id:          Mapped[int]      = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    repo_full_name:   Mapped[str]      = mapped_column(String, nullable=False)   # e.g. "username/project"
    branch:           Mapped[str]      = mapped_column(String, default="main")
    github_pat:       Mapped[str]      = mapped_column(String, nullable=False)   # Personal Access Token
    webhook_id:       Mapped[int|None] = mapped_column(Integer, nullable=True)   # GitHub webhook ID (set after registration)
    webhook_active:   Mapped[bool]     = mapped_column(default=False)
    created_at:       Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    user:    Mapped["User"]           = relationship("User", back_populates="repos")
    commits: Mapped[list["Commit"]]   = relationship("Commit", back_populates="repo")

from sqlalchemy import Integer, String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base
import datetime

class User(Base):
    __tablename__ = "users"

    id:              Mapped[int]      = mapped_column(Integer, primary_key=True)
    github_id:       Mapped[int]      = mapped_column(Integer, unique=True, nullable=False)
    github_username: Mapped[str]      = mapped_column(String, nullable=False)
    github_email:    Mapped[str|None] = mapped_column(String, nullable=True)
    avatar_url:      Mapped[str|None] = mapped_column(String, nullable=True)
    created_at:      Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    repos: Mapped[list["ConnectedRepo"]] = relationship("ConnectedRepo", back_populates="user")

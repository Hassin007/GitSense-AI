from sqlalchemy import Integer, String, ForeignKey, DateTime, JSON, func
from sqlalchemy.orm import Mapped, mapped_column
from backend.database import Base
import datetime


class FileInterface(Base):
    """
    Caches the last-known public interface (function/class signatures)
    for a file, per repo. Used to deterministically compute what
    changed in a file's interface between commits, instead of asking
    the LLM to infer it purely from diff text.
    """
    __tablename__ = "file_interfaces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(Integer, ForeignKey("connected_repos.id"), nullable=False)
    filepath: Mapped[str] = mapped_column(String, nullable=False)
    signatures: Mapped[list] = mapped_column(JSON, default=list)
    # signatures: list of {"name": str, "params": [str], "kind": "function"|"class",
    #                       "raw_signature": str}
    exported_symbols: Mapped[list] = mapped_column(JSON, default=list)
    # exported_symbols: list of {
    #   "exported_name": str, "defined_name": str, "kind": str,
    #   "export_type": str, "is_reexport": bool, "reexport_source": str|None
    # }
    last_commit_sha: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

# backend/schemas/repo.py
from pydantic import BaseModel
from datetime import datetime


class ConnectRepoRequest(BaseModel):
    github_pat: str
    repo_full_name: str
    branch: str = "main"


class RepoResponse(BaseModel):
    id: int
    repo_full_name: str
    branch: str
    webhook_active: bool
    created_at: str

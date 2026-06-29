# backend/schemas/user.py
from pydantic import BaseModel
from datetime import datetime


class UserResponse(BaseModel):
    id: int
    username: str
    avatar_url: str | None
    email: str | None

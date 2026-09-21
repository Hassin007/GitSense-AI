# backend/config.py
from pathlib import Path
from pydantic_settings import BaseSettings

env_file_path = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    app_secret_key: str
    frontend_url: str = "http://localhost:8501"
    backend_url: str = "http://localhost:8000" 

    database_url: str
    redis_url: str = "redis://localhost:6379/0"

    github_client_id: str
    github_client_secret: str

    webhook_base_url: str
    github_webhook_secret: str

    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days

    groq_api_key: str
    google_api_key: str
    google_api_key_2: str | None = None
    nvidia_api_key: str

    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    class Config:
        env_file = str(env_file_path) if env_file_path.exists() else ".env"
        extra = "ignore"


settings = Settings()

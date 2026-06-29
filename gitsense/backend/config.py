# backend/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_secret_key: str
    frontend_url: str = "http://localhost:8501"
    backend_url: str = "http://localhost:8000" 

    database_url: str

    github_client_id: str
    github_client_secret: str

    webhook_base_url: str
    github_webhook_secret: str

    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days

    class Config:
        env_file = ".env"

settings = Settings()

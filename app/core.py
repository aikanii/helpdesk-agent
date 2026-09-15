from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class Settings(BaseModel):
    app_name: str = "Relay Helpdesk"
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./helpdesk.db")
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    jwt_secret: str = os.getenv("JWT_SECRET", "replace-me-before-production")
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    access_token_minutes: int = int(os.getenv("ACCESS_TOKEN_MINUTES", "480"))
    admin_email: str = os.getenv("ADMIN_EMAIL", "admin@acme.co")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "relay-demo-2026")
    admin_name: str = os.getenv("ADMIN_NAME", "Acme Administrator")
    cors_origins: str = os.getenv("CORS_ORIGINS", "*")
    base_dir: Path = Path(__file__).resolve().parent


settings = Settings()

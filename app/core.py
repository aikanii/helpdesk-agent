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
    cors_origins: str = os.getenv("CORS_ORIGINS", "*")
    base_dir: Path = Path(__file__).resolve().parent


settings = Settings()

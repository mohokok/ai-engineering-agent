"""Application settings loaded from environment variables or local .env."""

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Runtime configuration for the local engineering agent backend."""

    app_env: str = "development"
    app_name: str = "Local AI Engineering Agent"
    app_version: str = "0.1.0"
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    workspaces_dir: Path = REPO_ROOT / "workspaces"
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("workspaces_dir", mode="before")
    @classmethod
    def resolve_workspaces_dir(cls, value: Any) -> Path:
        """Resolve blank or relative workspaces_dir paths against REPO_ROOT."""
        if value is None or (isinstance(value, str) and not value.strip()):
            return REPO_ROOT / "workspaces"
        path = Path(value)
        if not path.is_absolute():
            return (REPO_ROOT / path).resolve()
        return path

    def cors_origin_list(self) -> list[str]:
        """Return configured CORS origins as a stripped list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()

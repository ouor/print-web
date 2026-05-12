from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    port: int = 8000

    admin_password_hash: str = ""
    secret_key: str = ""

    printer_name: str = ""

    retention_days: int = 7
    upload_max_mb: int = 15

    database_url: str = "sqlite:///./data.db"
    upload_dir: Path = Path("./uploads")

    session_cookie_name: str = "print_web_session"
    session_max_age_seconds: int = 24 * 3600
    session_secure: bool = False

    @property
    def upload_max_bytes(self) -> int:
        return self.upload_max_mb * 1024 * 1024


settings = Settings()

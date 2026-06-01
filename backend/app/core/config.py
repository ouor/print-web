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

    # Comma-separated list of printer names. Single printer is the common
    # case ("Samsung CLX-8380 Series PS"); for multiple printers, list them
    # all ("Samsung CLX-8380 Series PS,HP Business Inkjet 3000 PS"). The
    # worker spawns one task per printer and routes APPROVED jobs to
    # whichever printer is idle.
    printer_name: str = ""

    # Photo paper layout in mm — used by the startup calibration to push an
    # oversized DEVMODE whose printable area equals the real paper, so
    # prints fill the sheet edge-to-edge. Defaults to 4x6 (152.4 x 101.6 mm).
    print_paper_long_mm: float = 152.4
    print_paper_short_mm: float = 101.6

    # How long the worker waits for the Windows spooler to report a job as
    # PRINTED before giving up and marking it FAILED. Real-world prints on
    # warm-up / older USB printers regularly exceed 60s, so the default is
    # generous; tune per site if a printer is reliably faster or slower.
    print_spool_timeout_seconds: float = 120.0

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

    @property
    def printer_names(self) -> list[str]:
        """Parsed PRINTER_NAME as a list. Empty list when the env var is unset,
        in which case the main module falls back to an interactive prompt
        (or the Windows default printer if no TTY)."""
        return [n.strip() for n in self.printer_name.split(",") if n.strip()]


settings = Settings()

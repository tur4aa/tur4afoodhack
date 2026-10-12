"""Configuration from environment variables (and an optional local .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path) -> None:
    """Minimal .env reader: KEY=VALUE lines, '#' comments. Real env vars win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


@dataclass(frozen=True)
class Config:
    bot_token: str
    owner_id: int | None
    db_path: Path
    backup_dir: Path
    backup_keep: int
    log_dir: Path
    timezone: str
    webapp_url: str = ""
    webapp_max_url: int = 6000


def _path(value: str) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else BASE_DIR / p


def load_config() -> Config:
    load_dotenv(BASE_DIR / ".env")
    token = os.environ.get("BOT_TOKEN", "").strip()
    owner = os.environ.get("OWNER_ID", "").strip()
    return Config(
        bot_token=token,
        owner_id=int(owner) if owner.lstrip("-").isdigit() else None,
        db_path=_path(os.environ.get("DB_PATH", "data/personal_os.db")),
        backup_dir=_path(os.environ.get("BACKUP_DIR", "data/backups")),
        backup_keep=int(os.environ.get("BACKUP_KEEP", "14")),
        log_dir=_path(os.environ.get("LOG_DIR", "logs")),
        timezone=os.environ.get("DEFAULT_TIMEZONE", "Asia/Dubai"),
        webapp_url=os.environ.get("WEBAPP_URL", "").strip(),
        webapp_max_url=int(os.environ.get("WEBAPP_MAX_URL", "6000")),
    )

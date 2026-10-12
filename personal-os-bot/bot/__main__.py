"""Entry point: python -m bot"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from .config import load_config
from .db import DB
from .service import Service


def setup_logging(log_dir) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(log_dir / "bot.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


def main() -> int:
    cfg = load_config()
    setup_logging(cfg.log_dir)
    log = logging.getLogger("bot")
    if not cfg.bot_token:
        log.error("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")
        return 1
    db = DB(cfg.db_path)
    from . import ai

    ai_cfg = ai.config_from_env(dict(os.environ))
    client = ai.AIClient(ai_cfg) if ai_cfg else None
    log.info("AI: %s", f"{ai_cfg.provider} / {ai_cfg.model}" if ai_cfg else "off (rules only)")
    service = Service(db, default_tz=cfg.timezone, ai=client)
    log.info("starting Personal OS, db=%s, owner=%s", cfg.db_path, cfg.owner_id)
    from .telegram_app import run

    try:
        asyncio.run(run(cfg, service))
    except KeyboardInterrupt:
        pass
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

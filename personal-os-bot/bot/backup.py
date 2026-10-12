"""Consistent SQLite backups (safe while the bot is running) with rotation.

Usage:  python -m bot.backup            # one backup into BACKUP_DIR
        python -m bot.backup --restore data/backups/personal_os-20261012-030000.db
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def make_backup(db_path: Path, backup_dir: Path, keep: int = 14) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"personal_os-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)  # online backup API: consistent snapshot even during writes
    finally:
        dst.close()
        src.close()
    check = sqlite3.connect(str(target))
    try:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError(f"backup {target} failed integrity check")
    finally:
        check.close()
    prune(backup_dir, keep)
    return target


def prune(backup_dir: Path, keep: int) -> None:
    files = sorted(backup_dir.glob("personal_os-*.db"))
    for old in files[:-keep] if keep > 0 else []:
        old.unlink(missing_ok=True)


def restore(backup_file: Path, db_path: Path) -> None:
    """Replace the live DB with a backup. Stop the bot first!"""
    if db_path.exists():
        safety = db_path.with_suffix(f".before-restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db")
        shutil.copy2(db_path, safety)
        print(f"Current DB saved as {safety}")
    for suffix in ("-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)
    shutil.copy2(backup_file, db_path)
    print(f"Restored {backup_file} -> {db_path}")


def main(argv: list[str] | None = None) -> int:
    from .config import load_config

    cfg = load_config()
    ap = argparse.ArgumentParser(description="Personal OS database backup")
    ap.add_argument("--restore", type=Path, help="restore DB from this backup file (stop the bot first)")
    args = ap.parse_args(argv)
    if args.restore:
        restore(args.restore, cfg.db_path)
        return 0
    if not cfg.db_path.exists():
        print(f"No database at {cfg.db_path}", file=sys.stderr)
        return 1
    print(make_backup(cfg.db_path, cfg.backup_dir, cfg.backup_keep))
    return 0


if __name__ == "__main__":
    sys.exit(main())

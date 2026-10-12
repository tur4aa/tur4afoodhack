from datetime import datetime, timedelta

import pytest

from bot.db import DB
from bot.service import Service


class Clock:
    """Controllable UTC clock. Default: Mon 12 Oct 2026, 10:00 UTC = 14:00 Dubai."""

    def __init__(self, now: datetime = datetime(2026, 10, 12, 10, 0)):
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> None:
        self.now += timedelta(**kw)

    def set_local(self, local: datetime) -> None:  # Dubai is UTC+4, no DST
        self.now = local - timedelta(hours=4)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def db(tmp_path):
    d = DB(tmp_path / "test.db")
    yield d
    d.close()


@pytest.fixture
def svc(db, clock):
    return Service(db, clock=clock)


class Msg:
    """Sequential Telegram message ids."""

    def __init__(self):
        self.n = 100

    def __call__(self) -> int:
        self.n += 1
        return self.n


@pytest.fixture
def mid():
    return Msg()

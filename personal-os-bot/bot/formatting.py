"""Small text-formatting helpers (Russian UI)."""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal

WD_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MONTHS_GEN = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
MONTHS_SHORT = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
MONTHS_DAT = ["январю", "февралю", "марту", "апрелю", "маю", "июню", "июлю", "августу", "сентябрю", "октябрю",
              "ноябрю", "декабрю"]
MONTHS_NOM = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь",
              "октябрь", "ноябрь", "декабрь"]

STATUS_LABEL = {
    "new": "Новая", "in_progress": "В процессе", "waiting": "Ожидает", "done": "Выполнена",
    "cancelled": "Отменена",
}
STATUS_ICON = {"new": "▫️", "in_progress": "▶️", "waiting": "⏸", "done": "✅", "cancelled": "✖️"}


def to_minor(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money(minor: int, currency: str = "", sign: str = "") -> str:
    neg = minor < 0
    minor = abs(minor)
    whole, frac = divmod(minor, 100)
    s = f"{whole:,}".replace(",", " ")
    if frac:
        s += f".{frac:02d}"
    if neg:
        sign = "−"
    out = f"{sign}{s}"
    return f"{out} {currency}" if currency else out


def parse_amount_str(s: str) -> Decimal:
    return Decimal(s.replace(",", ".").replace(" ", ""))


def day(d: date, today: date | None = None) -> str:
    if today is not None:
        delta = (d - today).days
        if delta == 0:
            return "сегодня"
        if delta == 1:
            return "завтра"
        if delta == -1:
            return "вчера"
    s = f"{WD_SHORT[d.weekday()]} {d.day} {MONTHS_GEN[d.month - 1]}"
    if today is not None and d.year != today.year:
        s += f" {d.year}"
    return s


def hm(t: time | datetime) -> str:
    return t.strftime("%H:%M")


def when(d: date | None, t: time | None, today: date) -> str:
    if d is None:
        return ""
    s = day(d, today)
    if t is not None:
        s += f" {hm(t)}"
    return s


def short(text: str, n: int = 32) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def plural_days(n: int) -> str:
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} день"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} дня"
    return f"{n} дней"

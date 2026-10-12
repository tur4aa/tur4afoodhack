"""Extraction of dates, times and recurrence from Russian/English free text.

Pure functions, no I/O. Everything works on *local* naive datetimes
(the caller converts to/from the user's time zone).
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

# ---------------------------------------------------------------- vocab

WEEKDAYS_RU = [
    r"понедельник\w*",
    r"вторник\w*",
    r"сред(?:а|у|ы|е|ам)",
    r"четверг\w*",
    r"пятниц\w*",
    r"суббот\w*",
    r"воскресень\w*",
]
WEEKDAYS_EN = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAY_ALT = "|".join(f"(?P<wd{i}>{ru}|{en}s?)" for i, (ru, en) in enumerate(zip(WEEKDAYS_RU, WEEKDAYS_EN)))

MONTHS = [
    (r"январ\w*", r"january|jan"),
    (r"феврал\w*", r"february|feb"),
    (r"март\w*", r"march|mar"),
    (r"апрел\w*", r"april|apr"),
    (r"ма[йяю]", r"may"),
    (r"июн\w*", r"june|jun"),
    (r"июл\w*", r"july|jul"),
    (r"август\w*", r"august|aug"),
    (r"сентябр\w*", r"september|sept|sep"),
    (r"октябр\w*", r"october|oct"),
    (r"ноябр\w*", r"november|nov"),
    (r"декабр\w*", r"december|dec"),
]
MONTH_RU_ALT = "|".join(f"(?P<m{i}>{ru})" for i, (ru, _) in enumerate(MONTHS))
MONTH_EN_ALT = "|".join(f"(?P<m{i}>{en})" for i, (_, en) in enumerate(MONTHS))

_ORD_UNITS = ["первого", "второго", "третьего", "четвертого", "пятого", "шестого",
              "седьмого", "восьмого", "девятого"]
_ORD_TEENS = ["десятого", "одиннадцатого", "двенадцатого", "тринадцатого", "четырнадцатого",
              "пятнадцатого", "шестнадцатого", "семнадцатого", "восемнадцатого", "девятнадцатого"]
ORDINALS: dict[str, int] = {}
for _i, _w in enumerate(_ORD_UNITS, start=1):
    ORDINALS[_w] = _i
for _i, _w in enumerate(_ORD_TEENS, start=10):
    ORDINALS[_w] = _i
ORDINALS["двадцатого"] = 20
for _i, _w in enumerate(_ORD_UNITS, start=21):
    ORDINALS[f"двадцать {_w}"] = _i
ORDINALS["тридцатого"] = 30
ORDINALS["тридцать первого"] = 31
ORD_ALT = "|".join(sorted((re.escape(k) for k in ORDINALS), key=len, reverse=True))

DEADLINE_PREFIXES = {"до", "к", "by", "until", "before", "till"}

F = re.IGNORECASE | re.UNICODE


@dataclass
class TimeInfo:
    """Result of parsing. ``date``/``time`` are already resolved to concrete values."""

    remaining: str = ""
    found: bool = False
    date: date | None = None
    time: time | None = None
    end_time: time | None = None
    end_date: date | None = None
    recurrence: str | None = None  # 'daily' | 'weekly' | 'monthly'
    rec_weekday: int | None = None
    rec_day: int | None = None
    day_of_month_form: bool = False  # "первого числа", "15 числа"
    deadline: bool = False
    after_payday: bool = False
    # When the date is ambiguous (e.g. "завтра" written at 01:30) - candidates to ask about.
    ambiguous: list[date] = field(default_factory=list)

    @property
    def has_when(self) -> bool:
        return self.date is not None or self.time is not None or self.recurrence is not None

    def start_dt(self) -> datetime | None:
        if self.date is None or self.time is None:
            return None
        return datetime.combine(self.date, self.time)

    def end_dt(self) -> datetime | None:
        if self.end_time is None or self.date is None:
            return None
        return datetime.combine(self.end_date or self.date, self.end_time)


def normalize(text: str) -> str:
    return text.replace("ё", "е").replace("Ё", "Е")


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"(^|\s)[,.;:\-–—]+(?=\s|$)", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" ,.;:-–—")


def _hour(h: int, minute_str: str | None, qualifier: str | None, raw: str) -> int | None:
    q = (qualifier or "").lower().replace(".", "")
    if h > 23:
        return None
    if q in ("am",):
        return 0 if h == 12 else h
    if q in ("pm",):
        return h if h == 12 else h + 12 if h < 12 else h
    if q == "утра":
        return h
    if q in ("дня", "вечера"):
        return h + 12 if h < 12 else h
    if q == "ночи":
        if h == 12:
            return 0
        return h if h <= 5 else (h + 12 if h < 12 else h)
    # No qualifier: "в 3" almost always means 15:00 in everyday speech.
    # A leading zero ("в 03:00") means the user wrote 24h time explicitly.
    if 1 <= h <= 6 and not raw.startswith("0"):
        return h + 12
    return h


def _weekday_from_match(m: re.Match) -> int:
    for i in range(7):
        if m.group(f"wd{i}"):
            return i
    raise ValueError("no weekday")


def _month_from_match(m: re.Match) -> int:
    for i in range(12):
        if m.group(f"m{i}"):
            return i + 1
    raise ValueError("no month")


def clamp_day(year: int, month: int, day: int) -> date:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last))


def add_months(d: date, months: int, day: int | None = None) -> date:
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    return clamp_day(y, m, day or d.day)


def next_month_day(today: date, day: int, allow_today: bool = True) -> date:
    cand = clamp_day(today.year, today.month, day)
    if cand < today or (cand == today and not allow_today):
        cand = add_months(today.replace(day=1), 1, day)
    return cand


class _Parser:
    def __init__(self, text: str, now: datetime, prefer_future: bool, tomorrow_date: date | None):
        self.text = normalize(text)
        self.now = now
        self.today = now.date()
        self.prefer_future = prefer_future
        self.tomorrow_date = tomorrow_date
        self.info = TimeInfo()
        self.day_offset: int | None = None
        self.weekday: int | None = None
        self.explicit_date: date | None = None
        self.month_day: int | None = None
        self.relative: timedelta | None = None
        self.relative_months = 0
        self.explicit_tomorrow = False
        self.raw_time: time | None = None
        self.raw_end: time | None = None

    # -- helpers
    def sub(self, pattern: str, fn) -> None:
        def repl(m: re.Match) -> str:
            ok = fn(m)
            if ok is False:
                return m.group(0)
            self.info.found = True
            return " "

        self.text = re.sub(pattern, repl, self.text, flags=F)

    def _prefix_deadline(self, prefix: str | None) -> None:
        if prefix and prefix.lower().split()[0] in DEADLINE_PREFIXES:
            self.info.deadline = True

    # -- recognisers
    def parse(self) -> TimeInfo:
        info = self.info

        def rec_daily(m):
            info.recurrence = "daily"

        def rec_weekly_wd(m):
            info.recurrence = "weekly"
            info.rec_weekday = _weekday_from_match(m)
            self.weekday = info.rec_weekday

        def rec_weekly(m):
            info.recurrence = "weekly"

        def rec_monthly(m):
            info.recurrence = "monthly"

        def rec_monthly_day(m):
            info.recurrence = "monthly"
            info.rec_day = int(m.group(1))
            self.month_day = info.rec_day
            info.day_of_month_form = True

        self.sub(r"\b(?:каждый\s+день|ежедневно|every\s*day|daily)\b", rec_daily)
        self.sub(rf"\b(?:кажд\w*|every)\s+(?:{WEEKDAY_ALT})\b", rec_weekly_wd)
        self.sub(r"\bпо\s+(?:(?P<wd0>понедельникам)|(?P<wd1>вторникам)|(?P<wd2>средам)|(?P<wd3>четвергам)"
                 r"|(?P<wd4>пятницам)|(?P<wd5>субботам)|(?P<wd6>воскресеньям))\b", rec_weekly_wd)
        self.sub(r"\bon\s+(?:(?P<wd0>mondays)|(?P<wd1>tuesdays)|(?P<wd2>wednesdays)|(?P<wd3>thursdays)"
                 r"|(?P<wd4>fridays)|(?P<wd5>saturdays)|(?P<wd6>sundays))\b", rec_weekly_wd)
        self.sub(r"\b(?:каждую\s+неделю|еженедельно|every\s+week|weekly)\b", rec_weekly)
        self.sub(r"\bкажд\w*\s+(\d{1,2})(?:-?го|-?е)?\s+числ\w*(?:\s+(?:каждого\s+)?месяца)?", rec_monthly_day)
        self.sub(r"\b(?:каждый\s+месяц|ежемесячно|every\s+month|monthly|каждого\s+месяца|of\s+every\s+month"
                 r"|of\s+each\s+month)\b", rec_monthly)

        # after payday
        def payday(m):
            info.after_payday = True

        self.sub(r"\b(?:после|с)\s+зарплат\w*|\bafter\s+(?:the\s+|my\s+)?(?:payday|salary|paycheck)\b", payday)

        # -- dates with month names
        def d_month(m):
            day = int(m.group("day"))
            month = _month_from_match(m)
            year = int(m.group("year")) if m.group("year") else None
            if not self._set_date(day, month, year):
                return False
            self._prefix_deadline(m.group("pre"))

        pre = r"(?:(?P<pre>до|к|на|by|on|until|before|till)\s+)?"
        self.sub(rf"\b{pre}(?P<day>\d{{1,2}})(?:-?го|-?е)?\s+(?:{MONTH_RU_ALT})\b(?:\s+(?P<year>\d{{4}}))?", d_month)
        self.sub(rf"\b{pre}(?:the\s+)?(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{MONTH_EN_ALT})\b"
                 rf"(?:,?\s+(?P<year>\d{{4}}))?", d_month)
        self.sub(rf"\b{pre}(?:{MONTH_EN_ALT})\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(?P<year>\d{{4}}))?",
                 d_month)

        # -- numeric dates: only with a prefix or a year (otherwise "такси 25.5" is a price)
        def d_num(m):
            day, month = int(m.group("day")), int(m.group("mon"))
            year = m.group("year")
            if not m.group("pre") and not year:
                return False
            y = None
            if year:
                y = int(year)
                if y < 100:
                    y += 2000
            if not self._set_date(day, month, y):
                return False
            self._prefix_deadline(m.group("pre"))

        self.sub(r"(?<![\d.,])(?:(?P<pre>до|к|на|by|on|until|before|till)\s+)?(?P<day>\d{1,2})[./](?P<mon>\d{1,2})"
                 r"(?:[./](?P<year>\d{4}|\d{2}))?(?![\d.,]*\d)", d_num)

        # -- day of month ("первого числа", "15 числа", "the 1st")
        def dom(m):
            raw = m.group("num")
            day = int(raw) if raw.isdigit() else ORDINALS[raw.lower()]
            if not 1 <= day <= 31:
                return False
            self.month_day = day
            info.day_of_month_form = True
            self._prefix_deadline(m.group("pre"))

        self.sub(rf"\b(?:(?P<pre>до|к|на)\s+)?(?P<num>\d{{1,2}}|{ORD_ALT})(?:-?го|-?е)?\s+числа\b", dom)
        self.sub(r"\b(?:(?P<pre>by|on|until|before)\s+)?the\s+(?P<num>\d{1,2})(?:st|nd|rd|th)\b", dom)

        # -- day words
        def day_word(offset, tomorrow=False):
            def fn(m):
                self.day_offset = offset
                self.explicit_tomorrow = tomorrow
                self._prefix_deadline(m.group("pre"))
            return fn

        pre_d = r"(?:(?P<pre>до|к|by|until|before|till)\s+)?"
        self.sub(rf"\b{pre_d}(?:послезавтра|(?:the\s+)?day\s+after\s+tomorrow)\b", day_word(2))
        self.sub(rf"\b{pre_d}(?:завтра|tomorrow)\b", day_word(1, True))
        self.sub(rf"\b{pre_d}позавчера\b", day_word(-2))
        self.sub(rf"\b{pre_d}(?:вчера|yesterday)\b", day_word(-1))
        self.sub(rf"\b{pre_d}(?:сегодня|today|tonight)\b", day_word(0))

        # -- weekdays
        def weekday(m):
            self.weekday = _weekday_from_match(m)
            self._prefix_deadline(m.group("pre"))

        self.sub(rf"\b(?:(?P<pre>в|во|до|к|by|on|until|before|this|next)\s+)?(?:(?:в\s+)?(?:следующ|эт)\w*\s+)?"
                 rf"(?:{WEEKDAY_ALT})\b", weekday)

        # -- relative
        def rel(m):
            n = m.group("n")
            n = 1 if not n or n.lower() in ("a", "an", "one") else int(n)
            unit = m.group("unit").lower()
            if unit.startswith(("мин", "min")):
                self.relative = timedelta(minutes=n)
            elif unit.startswith(("час", "hour", "hr")) or unit in ("ч", "h"):
                self.relative = timedelta(hours=n)
            elif unit.startswith(("дн", "ден", "day")):
                self.day_offset = n
            elif unit.startswith(("недел", "week")):
                self.day_offset = 7 * n
            elif unit.startswith(("месяц", "month")):
                self.relative_months = n
            else:
                return False

        self.sub(r"\bчерез\s+(?:пол\s*часа|полчаса)\b", lambda m: setattr(self, "relative", timedelta(minutes=30)))
        self.sub(r"\b(?:через|in)\s+(?P<n>\d{1,3}|an?|one)?\s*(?P<unit>минут\w*|мин\b|часа|часов|час|ч\b|дн\w*"
                 r"|день|недел\w*|месяц\w*|minutes?|mins?|hours?|hrs?|h\b|days?|weeks?|months?)", rel)

        # -- time ranges
        def t_range(m):
            g = m.groupdict()
            h1, h2 = int(g["h1"]), int(g["h2"])
            m1, m2 = int(g["m1"] or 0), int(g["m2"] or 0)
            if m1 > 59 or m2 > 59:
                return False
            s = _hour(h1, g["m1"], g.get("q1"), g["h1"])
            e_raw = h2
            q2 = g.get("q2")
            if s is None or e_raw > 23:
                return False
            if q2:
                e = _hour(h2, g["m2"], q2, g["h2"])
            else:
                e = e_raw
                # "с 2 до 4" -> 14:00-16:00; "с 22 до 6" -> overnight
                if e < s and e + 12 > s and e + 12 <= 23 and s >= 12:
                    e += 12
            if e is None:
                return False
            self.raw_time = time(s, m1)
            self.raw_end = time(e, m2)

        q_ru = r"(?:утра|дня|вечера|ночи)"
        self.sub(rf"\b(?:с|со)\s+(?P<h1>\d{{1,2}})(?:[:.](?P<m1>\d{{2}}))?\s*(?P<q1>{q_ru})?\s+до\s+"
                 rf"(?P<h2>\d{{1,2}})(?:[:.](?P<m2>\d{{2}}))?\s*(?P<q2>{q_ru})?(?!\d)", t_range)
        self.sub(r"\bfrom\s+(?P<h1>\d{1,2})(?::(?P<m1>\d{2}))?\s*(?P<q1>am|pm)?\s+(?:to|till|until)\s+"
                 r"(?P<h2>\d{1,2})(?::(?P<m2>\d{2}))?\s*(?P<q2>am|pm)?\b", t_range)
        self.sub(r"(?<![\d.])(?P<h1>\d{1,2}):(?P<m1>\d{2})\s*[-–—]\s*(?P<h2>\d{1,2}):(?P<m2>\d{2})(?!\d)", t_range)

        # -- single times
        def t_single(m):
            g = m.groupdict()
            h = int(g["h"])
            minute = int(g.get("m") or 0)
            if minute > 59:
                return False
            hh = _hour(h, g.get("m"), g.get("q"), g["h"])
            if hh is None:
                return False
            self.raw_time = time(hh, minute)
            if g.get("pre") and g["pre"].lower() in ("к", "by"):
                info.deadline = True

        self.sub(r"\b(?:в|at)\s+(?:полдень|noon)\b|\bnoon\b|\bв\s+полдень\b", lambda m: setattr(self, "raw_time", time(12, 0)))
        self.sub(r"\b(?:в\s+)?(?:полночь|midnight)\b", lambda m: setattr(self, "raw_time", time(0, 0)))
        self.sub(r"\b(?P<pre>в|во|at|к|by)\s+(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?"
                 r"(?:\s*(?P<q>утра|дня|вечера|ночи|a\.?m\.?|p\.?m\.?)(?!\w))?(?:\s*час\w*)?"
                 r"(?![\d.,]|\s*(?:числа|-?го\b|%|aed|dhs|дирх|руб|\$|usd|eur))", t_single)
        self.sub(r"(?<![\d.,])(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<q>a\.?m\.?|p\.?m\.?)(?!\w)", t_single)
        self.sub(r"(?<![\d.,])(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s+(?P<q>утра|вечера|ночи)\b", t_single)
        self.sub(r"(?<![\d.,:])(?P<h>\d{1,2}):(?P<m>\d{2})(?![\d:])", t_single)

        info.remaining = _clean(self.text)
        self._resolve()
        return info

    def _set_date(self, day: int, month: int, year: int | None) -> bool:
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return False
        y = year or self.today.year
        try:
            d = date(y, month, day)
        except ValueError:
            return False
        if year is None:
            if self.prefer_future and d < self.today:
                d = date(y + 1, month, min(day, calendar.monthrange(y + 1, month)[1]))
            elif not self.prefer_future and d > self.today + timedelta(days=31):
                d = date(y - 1, month, min(day, calendar.monthrange(y - 1, month)[1]))
        self.explicit_date = d
        return True

    def _resolve(self) -> None:
        info, today, now = self.info, self.today, self.now
        d: date | None = None
        t = self.raw_time

        if self.relative is not None:
            dt = now + self.relative
            dt = dt.replace(second=0, microsecond=0)
            info.date, info.time = dt.date(), dt.time()
            return
        if self.explicit_date:
            d = self.explicit_date
        elif self.day_offset is not None:
            d = today + timedelta(days=self.day_offset)
            if self.explicit_tomorrow:
                if self.tomorrow_date is not None:
                    d = self.tomorrow_date
                elif now.hour < 4:
                    # 01:30, "завтра" - the user may mean the day that already started.
                    info.ambiguous = [today, today + timedelta(days=1)]
        elif self.weekday is not None and info.recurrence != "weekly":
            ahead = (self.weekday - today.weekday()) % 7 or 7
            d = today + timedelta(days=ahead)
        elif self.weekday is not None:  # weekly recurrence on a given weekday: next occurrence (today allowed)
            ahead = (self.weekday - today.weekday()) % 7
            d = today + timedelta(days=ahead)
            if ahead == 0 and t is not None and datetime.combine(d, t) <= now:
                d += timedelta(days=7)
        elif self.month_day is not None:
            d = next_month_day(today, self.month_day)
            if d == today and t is not None and datetime.combine(d, t) <= now:
                d = next_month_day(today, self.month_day, allow_today=False)
        elif self.relative_months:
            d = add_months(today, self.relative_months)
        elif t is not None:
            d = today
            if self.prefer_future and datetime.combine(d, t) <= now:
                d += timedelta(days=1)
        elif info.recurrence == "daily":
            d = today
        elif info.recurrence == "weekly":
            d = today
        elif info.recurrence == "monthly":
            d = today

        if info.recurrence == "monthly" and info.rec_day is None and d is not None:
            info.rec_day = self.month_day or d.day
        if info.recurrence == "weekly" and info.rec_weekday is None and d is not None:
            info.rec_weekday = d.weekday()

        info.date = d
        info.time = t
        if self.raw_end is not None and d is not None and t is not None:
            info.end_time = self.raw_end
            info.end_date = d + timedelta(days=1) if self.raw_end <= t else d


def parse(text: str, now: datetime, *, prefer_future: bool = True, tomorrow_date: date | None = None) -> TimeInfo:
    """Parse ``text`` relative to local naive ``now``."""
    return _Parser(text, now, prefer_future, tomorrow_date).parse()


def next_occurrence(current: datetime, recurrence: str, rec_day: int | None = None) -> datetime:
    """Next datetime strictly after ``current`` for a recurrence rule."""
    if recurrence == "daily":
        return current + timedelta(days=1)
    if recurrence == "weekly":
        return current + timedelta(days=7)
    if recurrence == "monthly":
        d = add_months(current.date().replace(day=1), 1, rec_day or current.day)
        return datetime.combine(d, current.time())
    raise ValueError(recurrence)

from datetime import date, datetime, time

import pytest

from bot.timeparse import next_occurrence, parse

NOW = datetime(2026, 10, 12, 14, 0)  # Monday


@pytest.mark.parametrize("text,d,t,rest", [
    ("Завтра в 11 позвонить преподавателю", date(2026, 10, 13), time(11, 0), "позвонить преподавателю"),
    ("В четверг пара в 8:30", date(2026, 10, 15), time(8, 30), "пара"),
    ("До пятницы закончить презентацию", date(2026, 10, 16), None, "закончить презентацию"),
    ("В субботу проверить документы", date(2026, 10, 17), None, "проверить документы"),
    ("послезавтра в 7 вечера кино", date(2026, 10, 14), time(19, 0), "кино"),
    ("в 3 встреча", date(2026, 10, 12), time(15, 0), "встреча"),
    ("в 03:00 будильник", date(2026, 10, 13), time(3, 0), "будильник"),
    ("в 9 утра зарядка", date(2026, 10, 13), time(9, 0), "зарядка"),
    ("через 2 часа выключить духовку", date(2026, 10, 12), time(16, 0), "выключить духовку"),
    ("через полчаса выйти", date(2026, 10, 12), time(14, 30), "выйти"),
    ("12 октября 2026 день рождения", date(2026, 10, 12), None, "день рождения"),
    ("до 15.10 сдать отчет", date(2026, 10, 15), None, "сдать отчет"),
    ("tomorrow at 5pm call mom", date(2026, 10, 13), time(17, 0), "call mom"),
    ("on friday at 10:30 dentist", date(2026, 10, 16), time(10, 30), "dentist"),
    ("1 ноября заплатить налог", date(2026, 11, 1), None, "заплатить налог"),
    ("первого числа оплатить интернет", date(2026, 11, 1), None, "оплатить интернет"),
])
def test_dates(text, d, t, rest):
    info = parse(text, NOW)
    assert info.date == d
    assert info.time == t
    assert info.remaining.lower() == rest.lower()


def test_prices_are_not_dates_or_times():
    for text in ["Такси 25.5", "Кофе 18", "кофе 12.10", "продукты 120,50"]:
        info = parse(text, NOW)
        assert info.date is None and info.time is None, text


def test_deadline_flag():
    assert parse("до пятницы отчёт", NOW).deadline
    assert not parse("в пятницу отчёт", NOW).deadline


def test_time_without_date_rolls_to_tomorrow_if_passed():
    info = parse("в 10 созвон", NOW)
    assert info.date == date(2026, 10, 13) and info.time == time(10, 0)


def test_night_shift_crosses_midnight():
    info = parse("смена с 22 до 6 в пятницу", NOW)
    assert info.start_dt() == datetime(2026, 10, 16, 22, 0)
    assert info.end_dt() == datetime(2026, 10, 17, 6, 0)


def test_afternoon_range():
    info = parse("встреча с 2 до 4 завтра", NOW)
    assert info.time == time(14, 0) and info.end_time == time(16, 0) and info.end_date == date(2026, 10, 13)


def test_tomorrow_after_midnight_is_ambiguous():
    info = parse("завтра в 11 встреча", datetime(2026, 10, 13, 1, 30))
    assert info.ambiguous == [date(2026, 10, 13), date(2026, 10, 14)]
    resolved = parse("завтра в 11 встреча", datetime(2026, 10, 13, 1, 30), tomorrow_date=date(2026, 10, 13))
    assert resolved.ambiguous == [] and resolved.date == date(2026, 10, 13)


def test_recurrence():
    assert parse("каждый день в 9 таблетки", NOW).recurrence == "daily"
    w = parse("каждую пятницу в 18 уборка", NOW)
    assert w.recurrence == "weekly" and w.date == date(2026, 10, 16)
    m = parse("каждое 5 число аренда", NOW)
    assert m.recurrence == "monthly" and m.rec_day == 5 and m.date == date(2026, 11, 5)


def test_past_dates_for_money():
    assert parse("вчера такси 30", NOW, prefer_future=False).date == date(2026, 10, 11)
    assert parse("на 10.10 обед 40", NOW, prefer_future=False).date == date(2026, 10, 10)


def test_next_occurrence_monthly_clamps_short_months():
    assert next_occurrence(datetime(2026, 1, 31, 9), "monthly", 31) == datetime(2026, 2, 28, 9)
    assert next_occurrence(datetime(2026, 2, 28, 9), "monthly", 31) == datetime(2026, 3, 31, 9)

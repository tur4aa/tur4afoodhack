from datetime import date, datetime
from decimal import Decimal

import pytest

from bot.nlp import classify, find_amounts

NOW = datetime(2026, 10, 12, 14, 0)


def money(text):
    i = classify(text, NOW)
    assert i.kind == "money", (text, i.kind)
    return i.items


@pytest.mark.parametrize("text,amount,cat,typ", [
    ("Кофе 18", "18", "Кафе и рестораны", "expense"),
    ("Такси 25.5", "25.5", "Транспорт", "expense"),
    ("такси 25,5", "25.5", "Транспорт", "expense"),
    ("Купил продукты за 120 дирхам", "120", "Продукты", "expense"),
    ("Получил зарплату 6500", "6500", "Работа", "income"),
    ("зарплата 6 500", "6500", "Работа", "income"),
    ("возврат за кроссовки 200", "200", "Покупки", "refund"),
    ("перевел 500 на сберегательный", "500", "Переводы", "transfer"),
    ("перевел маме 300", "300", "Переводы", "expense"),
    ("Netflix 39", "39", "Подписки", "expense"),
    ("аптека 64.50", "64.5", "Здоровье", "expense"),
    ("шаверма 22", "22", "Кафе и рестораны", "expense"),
    ("что-то непонятное 15", "15", "Прочее", "expense"),
])
def test_single_money(text, amount, cat, typ):
    [item] = money(text)
    assert item.amount == Decimal(amount)
    assert item.category == cat
    assert item.type == typ
    assert item.currency == "AED"


def test_currency_detection():
    assert money("обед 20 usd")[0].currency == "USD"
    assert money("кофе 3€")[0].currency == "EUR"
    assert money("такси 300 руб")[0].currency == "RUB"


def test_multiple_operations():
    items = money("Такси 25, продукты 60, кофе 15")
    assert [(str(i.amount), i.category) for i in items] == [
        ("25", "Транспорт"), ("60", "Продукты"), ("15", "Кафе и рестораны")]


def test_past_date_money():
    [item] = money("вчера такси 30")
    assert item.occurred_on == date(2026, 10, 11)


def test_ambiguous_amount_asks():
    i = classify("кофе 18 20", NOW)
    assert i.kind == "ask_amount" and i.candidates == [Decimal(18), Decimal(20)]


@pytest.mark.parametrize("text,title", [
    ("Написать преподавателю", "Написать преподавателю"),
    ("Завтра купить продукты", "купить продукты"),
    ("Завтра в 11 позвонить преподавателю", "позвонить преподавателю"),
    ("Позвонить 3 клиентам", "Позвонить 3 клиентам"),
    ("Купить 2 батарейки", "Купить 2 батарейки"),
    ("После зарплаты оплатить интернет", "оплатить интернет"),
])
def test_tasks(text, title):
    i = classify(text, NOW)
    assert i.kind == "task", (text, i.kind)
    assert i.title == title


def test_task_with_time_has_datetime():
    i = classify("Завтра в 11 позвонить преподавателю", NOW)
    assert i.time.start_dt() == datetime(2026, 10, 13, 11, 0)


def test_after_payday_flag():
    assert classify("После зарплаты оплатить интернет", NOW).time.after_payday


def test_event():
    i = classify("В четверг пара в 8:30", NOW)
    assert i.kind == "event" and i.title == "пара"


def test_reminder_monthly_for_bills():
    i = classify("Напомни оплатить интернет первого числа", NOW)
    assert i.kind == "reminder" and i.time.recurrence == "monthly" and i.time.rec_day == 1


def test_reminder_without_time_asks():
    assert classify("напомни купить хлеб", NOW).kind == "ask_when"


def test_done_and_unknown_and_note():
    assert classify("Купил продукты", NOW).kind == "done"
    assert classify("готово", NOW).kind == "done"
    assert classify("привет как дела", NOW).kind == "unknown"
    n = classify("Заметка: идея подарка", NOW)
    assert n.kind == "note" and n.title == "идея подарка"


def test_correction():
    i = classify("не 18, а 20", NOW)
    assert i.kind == "correction" and i.amount == Decimal(20)


def test_find_amounts_variants():
    assert [a.value for a in find_amounts("6.5k")] == [Decimal("6500")]
    assert [a.value for a in find_amounts("1 250 и 30")] == [Decimal(1250), Decimal(30)]
    assert find_amounts("в 8:30") == []

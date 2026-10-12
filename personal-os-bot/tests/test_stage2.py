"""Stage 2: recurring reminders/payments, calendar, inbox, digests, payday budget, access control."""
import asyncio
from datetime import datetime
from types import SimpleNamespace


def bells(svc):
    return [n for n in svc.collect_due() if n.reply.text.startswith("🔔")]


def test_monthly_reminder_for_bills(svc, mid, clock):
    r = svc.process_text("Напомни оплатить интернет первого числа", mid())
    assert "каждый месяц 1-го в 09:00" in r.text
    rem = svc.db.one("SELECT * FROM reminders")
    assert rem["recurrence"] == "monthly" and rem["remind_at"] == "2026-11-01 05:00:00"
    clock.set_local(datetime(2026, 11, 1, 9, 0, 30))
    [n] = bells(svc)
    n.on_sent()
    rem = svc.db.one("SELECT * FROM reminders")
    assert rem["status"] == "active" and rem["remind_at"] == "2026-12-01 05:00:00" and rem["pending_ack"] == 1
    assert "Ждут ответа" in svc.view_today().text
    svc.handle_callback(f"r:d:{rem['id']}")
    assert svc.db.scalar("SELECT pending_ack FROM reminders") == 0


def test_weekly_and_daily_reminders(svc, mid, clock):
    r = svc.process_text("каждую пятницу в 18 уборка", mid())
    assert "каждую пятницу в 18:00" in r.text
    r = svc.process_text("напомни каждый день в 9 утра таблетки", mid())
    assert "каждый день в 09:00" in r.text
    assert svc.db.scalar("SELECT remind_at FROM reminders WHERE recurrence='daily'") == "2026-10-13 05:00:00"


def test_reminder_asks_when_without_time(svc, mid):
    r = svc.process_text("напомни купить хлеб", mid())
    assert r.text.startswith("Когда напомнить «Купить хлеб»?")
    r = svc.process_text("в 18", mid())
    assert "Купить хлеб" in r.text and "18:00" in r.text
    assert svc.db.scalar("SELECT COUNT(*) FROM reminders") == 1


def test_reminder_quick_choice(svc, mid):
    r = svc.process_text("напомни купить хлеб", mid())
    cb = next(d for row in r.buttons for t, d in row if t == "Завтра 09:00")
    svc.handle_callback(cb)
    assert svc.db.scalar("SELECT remind_at FROM reminders") == "2026-10-13 05:00:00"


def test_event_and_calendar(svc, mid):
    r = svc.process_text("В четверг пара в 8:30", mid())
    assert r.text == "📅 Пара · чт 15 окт 08:30"
    assert svc.db.scalar("SELECT COUNT(*) FROM reminders WHERE event_id IS NOT NULL") == 1
    cal = svc.view_calendar().text
    assert "08:30 Пара" in cal
    assert svc.process_text("В четверг пара в 8:30", mid()).text.startswith("Такое событие уже есть")


def test_night_shift_event(svc, mid):
    r = svc.process_text("смена с 22 до 6 в пятницу", mid())
    assert r.text == "📅 Смена · пт 16 окт 22:00–06:00 (сб 17 окт)"
    ev = svc.db.one("SELECT * FROM events")
    assert ev["start_at"] == "2026-10-16 18:00:00" and ev["end_at"] == "2026-10-17 02:00:00"


def test_tomorrow_after_midnight_is_clarified(svc, mid, clock):
    clock.set_local(datetime(2026, 10, 13, 1, 30))
    r = svc.process_text("завтра в 11 позвонить врачу", mid())
    assert "за полночь" in r.text and svc.db.scalar("SELECT COUNT(*) FROM tasks") == 0
    svc.handle_callback(r.buttons[0][0][1])  # Tue 13 (the day that already started)
    assert svc.db.scalar("SELECT due_date FROM tasks") == "2026-10-13"


def test_inbox_list_and_conversions(svc, mid):
    svc.process_text("asdf qwerty", mid())
    svc.process_text("подарок маме 150", mid())  # money signal -> expense directly
    svc.process_text("непонятная штука", mid())
    v = svc.view_inbox()
    assert v.text.startswith("📥 Inbox (2)")
    first, second = [r["id"] for r in svc.db.all("SELECT id FROM inbox ORDER BY id")]
    r = svc.handle_callback(f"ib:{first}:x")
    assert "непонятная штука" in r.text  # shows the next item
    r = svc.handle_callback(f"ib:{second}:m")
    assert "Какая сумма" in r.text
    r = svc.process_text("45", mid())
    assert "−45 AED" in r.text
    assert svc.view_inbox().text == "📥 Inbox пуст."


def test_inbox_to_task(svc, mid):
    svc.process_text("документы для визы", mid())
    iid = svc.db.scalar("SELECT id FROM inbox")
    r = svc.handle_callback(f"ib:{iid}:t")
    assert r.text.startswith("Задача: Документы для визы")


def test_morning_and_evening_digests(svc, mid, clock):
    clock.set_local(datetime(2026, 10, 12, 7, 0))
    svc.process_text("Сегодня купить продукты", mid())
    svc.process_text("В 12 встреча с куратором", mid())
    assert svc.collect_due() == []
    clock.set_local(datetime(2026, 10, 12, 8, 0, 20))
    [n] = svc.collect_due()
    assert n.reply.text.startswith("☀️ Доброе утро!")
    assert "Купить продукты" in n.reply.text and "12:00 Встреча с куратором" in n.reply.text
    n.on_sent()
    assert svc.collect_due() == []  # once per day
    clock.set_local(datetime(2026, 10, 12, 21, 30, 10))
    [ev] = [n for n in svc.collect_due() if n.reply.text.startswith("🌙")]
    assert "Расходов сегодня не записано" in ev.reply.text  # does not assume zero spending
    assert "Не сделано: 1" in ev.reply.text
    cb = ev.reply.buttons[0][0][1]
    svc.handle_callback(cb)
    assert svc.db.scalar("SELECT due_date FROM tasks") == "2026-10-13"


def test_digest_can_be_disabled(svc, clock):
    svc.handle_callback("set:tog:morning_enabled")
    clock.set_local(datetime(2026, 10, 12, 8, 1))
    assert svc.collect_due() == []


def test_missed_digest_is_not_sent_late(svc, clock):
    clock.set_local(datetime(2026, 10, 12, 15, 0))  # laptop was asleep all morning
    assert not [n for n in svc.collect_due() if n.reply.text.startswith("☀️")]


def test_payday_budget(svc, mid):
    svc.process_text("остаток 2000", mid())
    svc.process_text("день зарплаты 25", mid())
    svc.process_text("платёж интернет 300 20", mid())
    svc.process_text("резерв отпуск 500", mid())
    svc.process_text("кофе 100", mid())
    block = "\n".join(svc.payday_block())
    assert "Зарплата: вс 25 окт, через 13 дней" in block
    assert "Введённый остаток: 2 000 AED" in block
    assert "Расчётный остаток: 1 900 AED" in block
    assert "Обязательные платежи до зарплаты: −300 AED" in block
    assert "Резервы: −500 AED" in block
    # (1900 - 300 - 500) / 13 days = 84.61
    assert "Свободно: 1 100 AED → можно 84.61 AED/день" in block
    # paying the bill marks it paid and removes it from upcoming payments
    svc.process_text("интернет 300", mid())
    block = "\n".join(svc.payday_block())
    assert "Обязательные платежи" not in block
    assert "Расчётный остаток: 1 600 AED" in block


def test_payday_task(svc, mid):
    svc.process_text("день зарплаты 25", mid())
    r = svc.process_text("После зарплаты оплатить интернет", mid())
    assert "после зарплаты" in r.text
    assert svc.db.scalar("SELECT due_date FROM tasks") == "2026-10-25"


def test_settings_change_and_delete(svc, mid):
    svc.handle_callback("set:ask:monthly_budget")
    r = svc.process_text("3000", mid())
    assert r.text.startswith("Сохранено")
    assert svc.db.get_setting("monthly_budget") == "300000"
    svc.handle_callback("set:ask:monthly_budget")
    svc.process_text("-", mid())
    assert svc.db.get_setting("monthly_budget") is None
    svc.handle_callback("set:ask:morning_time")
    svc.process_text("7:15", mid())
    assert svc.db.get_setting("morning_time") == "07:15"


def test_pending_input_does_not_swallow_normal_messages(svc, mid):
    svc.process_text("Кофе 18", mid())
    tx_id = svc.db.scalar("SELECT id FROM transactions")
    svc.handle_callback(f"tx:a:{tx_id}")
    svc.process_text("Завтра купить продукты", mid())  # not an amount -> processed normally
    assert svc.db.scalar("SELECT COUNT(*) FROM tasks") == 1
    assert svc.db.scalar("SELECT amount_minor FROM transactions") == 1800


def test_owner_only_middleware():
    from bot.telegram_app import OwnerOnly

    mw = OwnerOnly(42)
    calls = []

    async def handler(event, data):
        calls.append(event)
        return "ok"

    assert asyncio.run(mw(handler, "e1", {"event_from_user": SimpleNamespace(id=7)})) is None
    assert asyncio.run(mw(handler, "e2", {"event_from_user": None})) is None
    assert asyncio.run(mw(handler, "e3", {"event_from_user": SimpleNamespace(id=42)})) == "ok"
    assert calls == ["e3"]


def test_backup_roundtrip(tmp_path, svc, mid):
    from bot.backup import make_backup
    import sqlite3
    svc.process_text("Кофе 18", mid())
    for _ in range(3):
        path = make_backup(__import__("pathlib").Path(svc.db.path), tmp_path / "b", keep=2)
    assert len(list((tmp_path / "b").glob("*.db"))) <= 2
    assert sqlite3.connect(path).execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1

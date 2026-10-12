"""Stage 1: money, tasks, reminders, /today, /money, undo, reliability."""
from datetime import datetime, timedelta

from bot.service import Service
from tests.conftest import plain


def tx_count(svc):
    return svc.db.scalar("SELECT COUNT(*) FROM transactions")


def test_expense_short_confirmation(svc, mid):
    r = svc.process_text("Кофе 18", mid())
    assert r.text == "Записал: −18 AED · Кафе и рестораны · Кофе"
    labels = [b[0] for row in r.buttons for b in row]
    assert labels[:2] == ["Отменить", "Изменить"]
    tx = svc.db.one("SELECT * FROM transactions")
    assert tx["amount_minor"] == 1800 and tx["currency"] == "AED" and tx["occurred_on"] == "2026-10-12"


def test_multiple_expenses_create_multiple_records(svc, mid):
    r = svc.process_text("Такси 25, продукты 60, кофе 15", mid())
    assert tx_count(svc) == 3
    assert r.text.startswith("Записал 3:")


def test_income(svc, mid):
    r = svc.process_text("Получил зарплату 6500", mid())
    assert "+6 500 AED · Работа" in r.text


def test_transfer_not_counted(svc, mid):
    svc.process_text("перевел 500 на сберегательный", mid())
    svc.process_text("кофе 20", mid())
    money = plain(svc.view_money().text)
    assert "Месяц 20 AED" in money and "Доходы за месяц +0 AED" in money


def test_refund_reduces_expenses(svc, mid):
    svc.process_text("кроссовки 300", mid())
    svc.process_text("возврат за кроссовки 100", mid())
    assert "Сегодня 200 AED" in plain(svc.view_money().text)


def test_undo_button_and_command(svc, mid):
    r = svc.process_text("Кофе 18", mid())
    undo_cb = r.buttons[0][0][1]
    assert svc.handle_callback(undo_cb).text.startswith("↩️ Отменено")
    assert tx_count(svc) == 0
    assert svc.handle_callback(undo_cb).text == "Уже отменено."
    svc.process_text("Такси 30", mid())
    svc.undo()
    assert tx_count(svc) == 0
    assert svc.undo().text == "Нечего отменять."


def test_ambiguous_amount_asks_and_saves_choice(svc, mid):
    r = svc.process_text("кофе 18 20", mid())
    assert r.text == "Какое число — сумма?" and tx_count(svc) == 0
    cb = r.buttons[0][1][1]  # "20"
    svc.handle_callback(cb)
    assert svc.db.scalar("SELECT amount_minor FROM transactions") == 2000


def test_edit_amount_and_category(svc, mid):
    r = svc.process_text("Кофе 18", mid())
    tx_id = svc.db.scalar("SELECT id FROM transactions")
    svc.handle_callback(f"tx:a:{tx_id}")
    r = svc.process_text("22.5", mid())
    assert "−22.50 AED" in r.text
    cats = svc.handle_callback(f"tx:c:{tx_id}")
    target = next(d for row in cats.buttons for t, d in row if t == "Продукты")
    svc.handle_callback(target)
    assert svc.db.scalar("SELECT category FROM transactions") == "Продукты"
    # the bot remembers the word for next time
    r = svc.process_text("кофе 10", mid())
    assert "Продукты" in r.text


def test_text_correction(svc, mid):
    svc.process_text("Кофе 18", mid())
    svc.process_text("не 18, а 20", mid())
    assert svc.db.scalar("SELECT amount_minor FROM transactions") == 2000
    svc.undo()
    assert svc.db.scalar("SELECT amount_minor FROM transactions") == 1800


def test_repeated_telegram_message_is_ignored(svc):
    assert svc.process_text("Кофе 18", 555) is not None
    assert svc.process_text("Кофе 18", 555) is None
    assert tx_count(svc) == 1


def test_duplicate_content_asks(svc, mid):
    svc.process_text("Кофе 18", mid())
    r = svc.process_text("Кофе 18", mid())
    assert "повтор" in r.text and tx_count(svc) == 1
    svc.handle_callback(r.buttons[0][0][1])  # "Записать"
    assert tx_count(svc) == 2


def test_task_with_reminder(svc, mid, clock):
    r = svc.process_text("Завтра в 11 позвонить преподавателю", mid())
    assert r.text == "Задача: Позвонить преподавателю — завтра 11:00 🔔"
    rem = svc.db.one("SELECT * FROM reminders")
    assert rem["remind_at"] == "2026-10-13 07:00:00"  # 11:00 Dubai = 07:00 UTC
    clock.set_local(datetime(2026, 10, 13, 11, 0, 30))
    due = [n for n in svc.collect_due() if n.reply.text.startswith("🔔")]
    assert len(due) == 1 and due[0].reply.text == "🔔 Позвонить преподавателю"
    due[0].on_sent()
    assert not [n for n in svc.collect_due() if n.reply.text.startswith("🔔")]


def test_reminder_not_lost_if_send_failed(svc, mid, clock):
    svc.process_text("Завтра в 11 позвонить преподавателю", mid())
    clock.set_local(datetime(2026, 10, 13, 11, 1))
    assert len([n for n in svc.collect_due() if n.reply.text.startswith("🔔")]) == 1  # not marked: send failed
    assert len([n for n in svc.collect_due() if n.reply.text.startswith("🔔")]) == 1


def test_task_without_deadline_gets_no_date(svc, mid):
    svc.process_text("Написать преподавателю", mid())
    t = svc.db.one("SELECT * FROM tasks")
    assert t["due_date"] is None and t["due_at"] is None


def test_task_no_duplicates_and_reschedule(svc, mid):
    svc.process_text("Завтра купить продукты", mid())
    r = svc.process_text("Завтра купить продукты", mid())
    assert r.text.startswith("Такая задача уже есть")
    r = svc.process_text("В субботу купить продукты", mid())
    assert "обновил срок" in r.text
    assert svc.db.scalar("SELECT COUNT(*) FROM tasks") == 1
    assert svc.db.scalar("SELECT due_date FROM tasks") == "2026-10-17"


def test_done_message_closes_matching_task(svc, mid):
    svc.process_text("Завтра купить продукты", mid())
    svc.process_text("Написать преподавателю", mid())
    r = svc.process_text("Купил продукты", mid())
    assert r.text.startswith("✅ Выполнена: Купить продукты")
    assert svc.db.scalar("SELECT status FROM tasks WHERE title = 'Купить продукты'") == "done"


def test_done_ambiguous_asks(svc, mid):
    svc.process_text("Купить продукты в Lulu", mid())
    svc.process_text("Купить продукты для мамы", mid())
    r = svc.process_text("купил продукты", mid())
    assert r.text == "Какую задачу отметить выполненной?" and len(r.buttons) == 2


def test_completing_task_disables_reminder(svc, mid, clock):
    svc.process_text("Завтра в 11 позвонить преподавателю", mid())
    svc.process_text("позвонил преподавателю", mid())
    assert svc.db.scalar("SELECT status FROM reminders") == "done"
    clock.set_local(datetime(2026, 10, 13, 11, 5))
    assert not [n for n in svc.collect_due() if n.reply.text.startswith("🔔")]


def test_task_card_status_reschedule_delete(svc, mid):
    svc.process_text("Завтра в 11 позвонить преподавателю", mid())
    tid = svc.db.scalar("SELECT id FROM tasks")
    assert "Статус: Новая" in svc.handle_callback(f"t:o:{tid}").text
    svc.handle_callback(f"t:s:{tid}:p")
    assert svc.db.scalar("SELECT status FROM tasks") == "in_progress"
    svc.handle_callback(f"t:rd:{tid}:7")
    t = svc.db.one("SELECT * FROM tasks")
    assert t["due_date"] == "2026-10-19" and t["due_at"] == "2026-10-19 07:00:00"
    assert svc.db.scalar("SELECT COUNT(*) FROM reminders WHERE status = 'active'") == 1
    r = svc.handle_callback(f"t:x:{tid}")
    assert svc.db.scalar("SELECT COUNT(*) FROM tasks") == 0
    svc.handle_callback(r.buttons[0][0][1])  # undo delete
    assert svc.db.scalar("SELECT COUNT(*) FROM tasks") == 1
    assert svc.db.scalar("SELECT COUNT(*) FROM reminders") >= 1


def test_reschedule_by_text(svc, mid):
    svc.process_text("Написать преподавателю", mid())
    tid = svc.db.scalar("SELECT id FROM tasks")
    svc.handle_callback(f"t:rd:{tid}:ask")
    r = svc.process_text("в пятницу в 15:00", mid())
    assert r.text.startswith("Перенёс")
    assert svc.db.scalar("SELECT due_date FROM tasks") == "2026-10-16"


def test_reminder_snooze_and_done(svc, mid, clock):
    svc.process_text("через 1 час выключить духовку", mid())
    clock.advance(hours=1, minutes=1)
    [n] = [n for n in svc.collect_due() if n.reply.text.startswith("🔔")]
    n.on_sent()
    rid = svc.db.scalar("SELECT id FROM reminders")
    r = svc.handle_callback(f"r:z:{rid}:60")
    assert r.text.startswith("⏰ Напомню")
    clock.advance(minutes=61)
    [n] = [n for n in svc.collect_due() if n.reply.text.startswith("🔔")]
    n.on_sent()
    svc.handle_callback(f"r:d:{rid}")
    assert svc.db.scalar("SELECT status FROM tasks") == "done"


def test_several_due_reminders_are_grouped(svc, mid, clock):
    svc.process_text("сегодня в 18 купить хлеб", mid())
    svc.process_text("сегодня в 18:05 позвонить маме", mid())
    clock.set_local(datetime(2026, 10, 12, 19, 0))
    rem = [n for n in svc.collect_due() if n.reply.text.startswith("🔔")]
    assert len(rem) == 1 and rem[0].reply.text.startswith("🔔 Напоминания:")


def test_today_view(svc, mid):
    svc.process_text("Сегодня купить продукты", mid())
    svc.process_text("Кофе 18", mid())
    t = svc.view_today().text
    assert "Купить продукты" in t and "Расходы сегодня: 18 AED" in t


def test_overdue_shown(svc, mid, clock):
    svc.process_text("Сегодня купить продукты", mid())
    clock.advance(days=2)
    assert "Просрочено" in svc.view_today().text


def test_money_summary(svc, mid, clock):
    svc.process_text("вчера такси 30", mid())  # Sunday 11 Oct - previous ISO week
    svc.process_text("Кофе 18", mid())
    svc.process_text("Получил зарплату 6500", mid())
    m = plain(svc.view_money().text)
    assert "Сегодня 18 AED" in m
    assert "Неделя 18 AED" in m
    assert "Месяц 48 AED" in m
    assert "Доходы за месяц +6 500 AED" in m
    assert "Транспорт — 30 (62%)" in m


def test_budget_and_limit_warnings(svc, mid):
    svc.process_text("бюджет 100", mid())
    svc.process_text("лимит кафе 50", mid())
    r = svc.process_text("обед 60", mid())
    assert "лимит превышен" in r.text
    r = svc.process_text("такси 35", mid())
    assert "Бюджет месяца" in r.text
    assert "из 100 AED" in plain(svc.view_money().text)


def test_unknown_goes_to_inbox_and_can_be_converted(svc, mid):
    r = svc.process_text("привет как дела", mid())
    assert "Inbox" in r.text
    iid = svc.db.scalar("SELECT id FROM inbox")
    svc.handle_callback(f"ib:{iid}:n")
    assert svc.db.scalar("SELECT COUNT(*) FROM notes") == 1
    assert svc.db.scalar("SELECT status FROM inbox") == "processed"


def test_processing_error_saves_message(svc, mid, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bug")
    monkeypatch.setattr(svc, "_process", boom)
    r = svc.process_text("Кофе 18", mid())
    assert "сохранил в Inbox" in r.text
    assert svc.db.scalar("SELECT text FROM inbox") == "Кофе 18"


def test_failed_save_never_reports_success(svc, mid, monkeypatch):
    real_insert = svc.db.insert

    def failing_insert(table, values):
        if table == "transactions":
            raise RuntimeError("disk full")
        return real_insert(table, values)
    monkeypatch.setattr(svc.db, "insert", failing_insert)
    r = svc.process_text("Кофе 18", mid())
    assert "Записал" not in r.text
    assert tx_count(svc) == 0


def test_edited_message_replaces_record(svc):
    svc.process_text("Кофе 18", 900)
    r = svc.process_edit("Кофе 28", 900)
    assert r.text.startswith("✏️ Исправил.")
    assert tx_count(svc) == 1 and svc.db.scalar("SELECT amount_minor FROM transactions") == 2800


def test_data_survives_restart(tmp_path, clock):
    from bot.db import DB
    db = DB(tmp_path / "p.db")
    Service(db, clock=clock).process_text("Кофе 18", 1)
    db.close()
    db2 = DB(tmp_path / "p.db")
    assert db2.scalar("SELECT COUNT(*) FROM transactions") == 1
    assert Service(db2, clock=clock).process_text("Кофе 18", 1) is None  # still knows message 1
    db2.close()


def test_timezone_setting(svc, mid):
    svc.handle_callback("set:ask:timezone")
    svc.process_text("Europe/Moscow", mid())  # UTC+3
    svc.process_text("Завтра в 11 позвонить", mid())
    assert svc.db.scalar("SELECT remind_at FROM reminders") == "2026-10-13 08:00:00"


def test_export_zip(svc, mid):
    import io
    import zipfile
    svc.process_text("Кофе 18", mid())
    r = svc.export()
    zf = zipfile.ZipFile(io.BytesIO(r.document[1]))
    assert "transactions.csv" in zf.namelist()
    assert "Кофе" in zf.read("transactions.csv").decode("utf-8-sig")

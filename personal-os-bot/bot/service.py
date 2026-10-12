"""Business logic of Personal OS. Telegram-independent: every method returns ``Reply`` objects.

All database changes that the user can see are recorded in ``actions`` so they can be undone.
"""
from __future__ import annotations

import csv
import html
import io
import json
import logging
import re
import secrets
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import formatting as fmt
from . import capital, nlp, timeparse
from .capital_service import CAPITAL_HELP, CapitalMixin
from .db import DB, fmt_utc, new_uid, parse_utc, utcnow
from .nlp import CATEGORIES, Intent, MoneyItem
from .timeparse import TimeInfo, add_months, next_month_day

log = logging.getLogger(__name__)

Buttons = list[list[tuple[str, str]]]

DEFAULTS = {
    "currency": "AED",
    "timezone": "Asia/Dubai",
    "morning_enabled": "1",
    "morning_time": "08:00",
    "evening_enabled": "1",
    "evening_time": "21:30",
    "default_remind_time": "09:00",
    "event_remind_min": "30",
    "ai_enabled": "1",
    "monthly_report": "1",
}

OPEN_STATUSES = ("new", "in_progress", "waiting")
DUP_WINDOW = timedelta(minutes=3)
CHOICE_TTL = timedelta(days=3)
PENDING_TTL = timedelta(minutes=15)
CANCEL_WORDS = {"отмена", "cancel", "стоп", "stop", "/cancel"}

AMOUNT_ONLY_RE = re.compile(r"^\s*(\d+(?:[.,]\d{1,2})?)\s*(?:[a-zA-Zа-яА-Я$€£₽.]{0,8})\s*$")


@dataclass
class Reply:
    text: str
    buttons: Buttons = field(default_factory=list)
    edit: bool = False  # for callbacks: replace the original message
    document: tuple[str, bytes] | None = None
    photo: tuple[str, bytes] | None = None
    html: bool = False      # text uses Telegram HTML (<b>, <i>); user content must be escaped
    toast: str | None = None
    show_menu: bool = False


@dataclass
class Notification:
    reply: Reply
    on_sent: Callable[[], None]


class Service(CapitalMixin):
    def __init__(self, db: DB, clock: Callable[[], datetime] = utcnow, default_tz: str | None = None,
                 ai=None, fetch=None):
        from .market import Market, http_get

        self.db = db
        self.clock = clock  # naive UTC
        self.ai = ai        # optional ai.AIClient; None = rules only
        self.market = Market(db, fetch or http_get)
        self._fx_missing: set[str] = set()
        with db.tx():
            for k, v in DEFAULTS.items():
                if k == "timezone" and default_tz:
                    v = default_tz
                if db.get_setting(k) is None:
                    db.set_setting(k, v)

    # ------------------------------------------------------------ time helpers
    @property
    def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.db.get_setting("timezone", "Asia/Dubai"))
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo("Asia/Dubai")

    def now_utc(self) -> datetime:
        return self.clock().replace(microsecond=0)

    def now_local(self) -> datetime:
        return self.to_local(self.now_utc())

    def today(self) -> date:
        return self.now_local().date()

    def to_local(self, utc_naive: datetime) -> datetime:
        return utc_naive.replace(tzinfo=timezone.utc).astimezone(self.tz).replace(tzinfo=None)

    def to_utc(self, local_naive: datetime) -> datetime:
        return local_naive.replace(tzinfo=self.tz).astimezone(timezone.utc).replace(tzinfo=None)

    def local_of(self, utc_str: str | None) -> datetime | None:
        return self.to_local(parse_utc(utc_str).replace(tzinfo=None)) if utc_str else None

    @property
    def currency(self) -> str:
        return self.db.get_setting("currency", "AED")

    def _setting_time(self, key: str) -> time:
        v = self.db.get_setting(key, DEFAULTS.get(key, "09:00"))
        h, m = v.split(":")
        return time(int(h), int(m))

    # ------------------------------------------------------------ actions / undo
    def _action(self, description: str, created=(), updated=(), deleted=(), msg_id: int | None = None) -> int:
        payload = {
            "created": [list(x) for x in created],
            "updated": [[t, i, old] for t, i, old in updated],
            "deleted": [[t, row] for t, row in deleted],
        }
        cur = self.db.execute(
            "INSERT INTO actions(created_at, description, payload, source_msg_id) VALUES (?, ?, ?, ?)",
            (fmt_utc(self.now_utc()), description, json.dumps(payload, ensure_ascii=False), msg_id))
        return int(cur.lastrowid)

    def _update(self, table: str, row_id: int, values: dict) -> tuple[str, int, dict]:
        """Update a row and return the (table, id, old_values) triple for the action log."""
        row = self.db.get(table, row_id)
        old = {k: row[k] for k in values}
        self.db.update(table, row_id, values)
        return table, row_id, old

    def undo(self, action_id: int | None = None) -> Reply:
        with self.db.tx():
            if action_id is None:
                row = self.db.one("SELECT * FROM actions WHERE undone = 0 ORDER BY id DESC LIMIT 1")
            else:
                row = self.db.one("SELECT * FROM actions WHERE id = ?", (action_id,))
            if row is None:
                return Reply("Нечего отменять.")
            if row["undone"]:
                return Reply("Уже отменено.", toast="Уже отменено")
            p = json.loads(row["payload"])
            for table, row_id in reversed(p["created"]):
                self._check_table(table)
                self.db.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
            for table, row_id, old in reversed(p["updated"]):
                self._check_table(table)
                if self.db.get(table, row_id) is not None:
                    self.db.update(table, row_id, old)
            for table, data in reversed(p["deleted"]):
                self._check_table(table)
                if self.db.get(table, data["id"]) is None:
                    self.db.insert(table, data)
            self.db.execute("UPDATE actions SET undone = 1 WHERE id = ?", (row["id"],))
        return Reply(f"↩️ Отменено: {row['description']}", toast="Отменено")

    @staticmethod
    def _check_table(table: str) -> None:
        from .db import ALLOWED_TABLES
        if table not in ALLOWED_TABLES:
            raise ValueError(table)

    # ------------------------------------------------------------ choices & pending input
    def _choice(self, payload: dict) -> str:
        key = secrets.token_hex(4)
        self.db.kv_set(f"ch:{key}", payload, self.now_utc() + CHOICE_TTL)
        return key

    def _set_pending(self, kind: str, **data) -> None:
        self.db.kv_set("pending", {"kind": kind, **data}, self.now_utc() + PENDING_TTL)

    def _clear_pending(self) -> None:
        self.db.kv_del("pending")

    # ------------------------------------------------------------ entry points
    def process_text(self, text: str, msg_id: int | None = None) -> Reply | None:
        if msg_id is not None and self.db.scalar(
                "SELECT 1 FROM processed_messages WHERE message_id = ?", (msg_id,)):
            log.info("message %s already processed, skipping", msg_id)
            return None
        try:
            reply = self._handle_pending(text, msg_id)
            if reply is None:
                reply = self._process(text, msg_id)
        except Exception as exc:  # never lose the message
            log.exception("failed to process message %r", text)
            reply = self._save_failed(text, msg_id, exc)
        if msg_id is not None:
            try:
                self.db.execute("INSERT OR IGNORE INTO processed_messages(message_id, created_at) VALUES (?, ?)",
                                (msg_id, fmt_utc(self.now_utc())))
            except Exception:
                log.exception("could not mark message %s processed", msg_id)
        return reply

    def process_edit(self, text: str, msg_id: int) -> Reply | None:
        """User edited a message he already sent: replace what it created."""
        row = self.db.one("SELECT id FROM actions WHERE source_msg_id = ? AND undone = 0 ORDER BY id DESC LIMIT 1",
                          (msg_id,))
        if row is None:
            return None
        try:
            with self.db.tx():
                self.undo(row["id"])
                reply = self._process(text, msg_id, skip_dup=True)
        except Exception as exc:
            log.exception("failed to process edit %r", text)
            return self._save_failed(text, msg_id, exc)
        reply.text = "✏️ Исправил. " + reply.text
        return reply

    def _save_failed(self, text: str, msg_id: int | None, exc: Exception) -> Reply:
        try:
            with self.db.tx():
                self.db.insert("inbox", {"uid": new_uid(), "text": text, "status": "new",
                                         "error": f"{type(exc).__name__}: {exc}"[:500],
                                         "created_at": fmt_utc(self.now_utc()), "source_msg_id": msg_id})
            return Reply("⚠️ Не смог обработать — сохранил в Inbox, ничего не потеряно.")
        except Exception:
            log.exception("could not save to inbox either")
            return Reply("⚠️ Ошибка: сообщение НЕ сохранено. Попробуйте отправить ещё раз.")

    def _memory(self) -> dict[str, str]:
        return {r["keyword"]: r["category"] for r in self.db.all("SELECT keyword, category FROM category_memory")}

    def _process(self, text: str, msg_id: int | None, *, skip_dup: bool = False,
                 tomorrow_date: date | None = None) -> Reply:
        if text.strip().startswith("/"):
            return Reply("Неизвестная команда. Список — /help")
        setting_reply = self._setting_command(text, msg_id)
        if setting_reply is not None:
            return setting_reply
        low = text.strip().lower().rstrip("!.?")
        if low in ("капитал", "инвестиции", "сбережения", "capital", "portfolio", "портфель"):
            return self.view_capital()
        if low in ("курс", "курсы", "курсы валют", "rates"):
            return self.view_rates()
        ci = capital.parse(text, self.currency, [a["name"] for a in self._accounts()])
        if ci is not None:
            return self._h_capital(ci, msg_id)
        intent = nlp.classify(text, self.now_local(), self.currency, self._memory(), tomorrow_date)
        if intent.ambiguous_dates:
            return self._ask_date(text, intent.ambiguous_dates, msg_id)
        ai_note = ""
        if intent.kind == "complex":
            ai_reply, ai_note = self._try_ai(text, msg_id)
            if ai_reply is not None:
                return ai_reply
            return self._to_inbox(text, msg_id, prefix=(ai_note + " " if ai_note else "") +
                                  "Тут несколько разных дел — отправьте их отдельными сообщениями или разберите:")
        if intent.kind == "money" and intent.low_confidence and self.ai_active:
            ai_reply, _ = self._try_ai(text, msg_id)   # e.g. a forwarded bank SMS; rules stay the fallback
            if ai_reply is not None:
                return ai_reply
        if intent.kind == "unknown" or (intent.kind == "ask_amount" and intent.candidates):
            # the rules gave up - let the (optional) AI try before asking / filing to Inbox
            ai_reply, ai_note = self._try_ai(text, msg_id)
            if ai_reply is not None:
                return ai_reply
            if intent.kind == "unknown":
                return self._to_inbox(text, msg_id, prefix=ai_note)
        handler = {
            "money": self._h_money,
            "ask_amount": self._h_ask_amount,
            "task": self._h_task,
            "reminder": self._h_reminder,
            "ask_when": self._h_ask_when,
            "event": self._h_event,
            "done": self._h_done,
            "note": self._h_note,
            "correction": self._h_correction,
        }.get(intent.kind, self._h_unknown)
        return handler(intent, msg_id, skip_dup=skip_dup)

    # ------------------------------------------------------------ AI (optional)
    @property
    def ai_active(self) -> bool:
        return self.ai is not None and self.db.get_setting("ai_enabled", "1") == "1"

    def _ai_ctx(self) -> dict:
        return {"now": self.now_local(), "tz": self.tz.key, "currency": self.currency, "categories": CATEGORIES}

    def _try_ai(self, text: str, msg_id: int | None, image: bytes | None = None) -> tuple[Reply | None, str]:
        """Ask the AI. Returns (reply, note). reply is None when nothing was saved."""
        from .ai import AIError, validate

        if not self.ai_active:
            return None, ""
        try:
            data = self.ai.parse_image(image, text, self._ai_ctx()) if image is not None \
                else self.ai.parse_text(text, self._ai_ctx())
        except AIError as e:
            log.warning("AI failed: %s", e)
            return None, f"🤖 AI недоступен ({e})."
        except Exception:
            log.exception("AI crashed")
            return None, "🤖 AI недоступен."
        items, question = validate(data, self.today(), CATEGORIES)
        if not items:
            return None, (f"🤖 {question}" if question else "🤖 AI тоже не понял.")
        try:
            return self._apply_ai(items, msg_id), ""
        except Exception as exc:  # nothing partial is kept: the whole batch is one transaction
            log.exception("could not apply AI result")
            return None, f"🤖 Не смог сохранить разбор AI ({type(exc).__name__})."

    def _apply_ai(self, items, msg_id: int | None) -> Reply:
        replies: list[Reply] = []
        with self.db.tx():
            before = self.db.scalar("SELECT COALESCE(MAX(id), 0) FROM actions")
            money = []
            for it in items:
                if it.type in ("expense", "income", "refund", "transfer"):
                    desc = it.description or it.title
                    cat = it.category or nlp.guess_category(desc, self._memory())[0]
                    if it.type == "transfer":
                        cat = "Переводы"
                    d = it.date if it.date and it.date <= self.today() + timedelta(days=1) else self.today()
                    money.append(MoneyItem(it.type, Decimal(str(round(it.amount, 2))), it.currency or self.currency,
                                           cat, desc, d))
            if money:
                replies.append(self._save_money(money, msg_id, skip_dup=True))
            for it in items:
                if it.type in ("expense", "income", "refund", "transfer"):
                    continue
                title = fmt.cap(it.title)
                t = time(*it.time) if it.time else None
                if it.type == "note":
                    replies.append(self._h_note(Intent("note", title=title), msg_id))
                elif it.recurrence:
                    ti = TimeInfo(date=it.date, time=t, recurrence=it.recurrence,
                                  rec_day=it.date.day if it.date and it.recurrence == "monthly" else None)
                    replies.append(self._create_recurring_reminder(title, ti, msg_id))
                elif it.type == "event" and it.date is not None:
                    ti = TimeInfo(date=it.date, time=t, found=True)
                    if t is not None and it.end_time:
                        ti.end_time = time(*it.end_time)
                        ti.end_date = it.end_date or (it.date + timedelta(days=1) if ti.end_time <= t else it.date)
                    replies.append(self._h_event(Intent("event", title=title, time=ti), msg_id))
                else:
                    d = it.date
                    if d is None and t is not None:
                        now = self.now_local()
                        d = now.date() if datetime.combine(now.date(), t) > now else now.date() + timedelta(days=1)
                    if it.type == "reminder" and d is not None and t is None:
                        t = self._setting_time("default_remind_time")
                    local = datetime.combine(d, t) if d and t else None
                    replies.append(self._create_task(title, d, local, it.deadline, msg_id))
            ids = [r["id"] for r in self.db.all("SELECT id FROM actions WHERE id > ? ORDER BY id", (before,))]
            aid = self._merge_actions(ids, "разбор AI")
        lines = [r.text for r in replies]
        buttons: Buttons = []
        if aid:
            buttons.append([("Отменить всё", f"u:{aid}")])
        tx_buttons = [b for r in replies for row in r.buttons for b in row if b[1].startswith("tx:e:")]
        if len(tx_buttons) == 1:
            buttons[0].append(("Изменить", tx_buttons[0][1]))
        elif tx_buttons:
            buttons.append(tx_buttons[:8])
        return Reply("🤖 " + "\n".join(lines), buttons)

    def _merge_actions(self, ids: list[int], description: str) -> int | None:
        """Fold several actions into one, so a single "Отменить" reverts them all."""
        if not ids:
            return None
        if len(ids) == 1:
            return ids[0]
        merged = {"created": [], "updated": [], "deleted": []}
        for aid in ids:
            p = json.loads(self.db.scalar("SELECT payload FROM actions WHERE id = ?", (aid,)))
            for k in merged:
                merged[k] += p[k]
        self.db.execute("UPDATE actions SET payload = ?, description = ? WHERE id = ?",
                        (json.dumps(merged, ensure_ascii=False), description, ids[0]))
        self.db.execute(f"DELETE FROM actions WHERE id IN ({','.join('?' * (len(ids) - 1))})", ids[1:])
        return ids[0]

    def process_photo(self, image: bytes, caption: str, msg_id: int | None) -> Reply | None:
        if msg_id is not None and self.db.scalar("SELECT 1 FROM processed_messages WHERE message_id = ?", (msg_id,)):
            return None
        if not self.ai_active:
            reply = Reply("Фото (чеки, SMS, скриншоты) я понимаю только с подключённым AI — "
                          "это бесплатно, см. README → «Бесплатный AI»." if self.ai is None else
                          "AI выключен в /settings — включите, чтобы я разбирал фото.")
        else:
            reply, note = self._try_ai(caption or "", msg_id, image=image)
            if reply is None:
                reply = Reply(f"{note}\nНе смог разобрать фото. Напишите текстом, например «Carrefour 120».")
        if msg_id is not None:
            self.db.execute("INSERT OR IGNORE INTO processed_messages(message_id, created_at) VALUES (?, ?)",
                            (msg_id, fmt_utc(self.now_utc())))
        return reply

    # ------------------------------------------------------------ money
    def _insert_tx(self, item: MoneyItem, msg_id: int | None) -> int:
        return self.db.insert("transactions", {
            "uid": new_uid(), "type": item.type, "amount_minor": fmt.to_minor(item.amount),
            "currency": item.currency, "category": item.category, "description": item.description,
            "occurred_on": item.occurred_on.isoformat(), "created_at": fmt_utc(self.now_utc()),
            "source_msg_id": msg_id,
        })

    def _tx_line(self, tx: dict, show_date: bool = True) -> str:
        amount = tx["amount_minor"]
        cur = tx["currency"]
        desc = f" · {tx['description']}" if tx["description"] and tx["description"].lower() not in \
            tx["category"].lower() else ""
        d = date.fromisoformat(tx["occurred_on"])
        when = "" if d == self.today() or not show_date else f" · {fmt.day(d, self.today())}"
        if tx["type"] == "expense":
            return f"{fmt.money(-amount, cur)} · {tx['category']}{desc}{when}"
        if tx["type"] == "income":
            return f"{fmt.money(amount, cur, '+')} · {tx['category']}{desc}{when}"
        if tx["type"] == "refund":
            return f"↩ {fmt.money(amount, cur, '+')} · возврат · {tx['category']}{desc}{when}"
        return f"↔ {fmt.money(amount, cur)} · перевод между своими счетами{desc}{when}"

    def _find_dup_tx(self, item: MoneyItem, msg_id: int | None) -> dict | None:
        since = fmt_utc(self.now_utc() - DUP_WINDOW)
        row = self.db.one(
            "SELECT * FROM transactions WHERE type = ? AND amount_minor = ? AND currency = ? "
            "AND lower(description) = lower(?) AND created_at >= ? AND (source_msg_id IS NULL OR "
            "source_msg_id IS NOT ?) ORDER BY id DESC LIMIT 1",
            (item.type, fmt.to_minor(item.amount), item.currency, item.description, since, msg_id))
        return dict(row) if row else None

    def _h_money(self, intent: Intent, msg_id, skip_dup=False) -> Reply:
        return self._save_money(intent.items, msg_id, skip_dup=skip_dup)

    def _save_money(self, items: list[MoneyItem], msg_id: int | None, *, skip_dup: bool = False) -> Reply:
        if not skip_dup:
            dups = [d for d in (self._find_dup_tx(i, msg_id) for i in items) if d]
            if dups:
                key = self._choice({"kind": "save_money", "items": [i.to_json() for i in items], "msg": msg_id})
                lines = "\n".join(self._tx_line(d) for d in dups)
                return Reply(f"Похоже на повтор — такое уже записано пару минут назад:\n{lines}\nЗаписать ещё раз?",
                             [[("Записать", f"ch:{key}:1"), ("Не надо", f"ch:{key}:0")]])
        with self.db.tx():
            ids = [self._insert_tx(i, msg_id) for i in items]
            desc = "запись " + ", ".join(f"{fmt.money(fmt.to_minor(i.amount), i.currency)} {i.category}"
                                         for i in items)
            aid = self._action(desc, created=[("transactions", i) for i in ids], msg_id=msg_id)
            for i, tx_id in zip(items, ids):
                if i.type == "expense":
                    self._auto_mark_payment(i)
        txs = [self.db.get("transactions", i) for i in ids]
        if len(txs) == 1:
            text = f"Записал: {self._tx_line(txs[0])}"
            buttons: Buttons = [[("Отменить", f"u:{aid}"), ("Изменить", f"tx:e:{ids[0]}")]]
        else:
            text = f"Записал {len(txs)}:\n" + "\n".join(self._tx_line(t) for t in txs)
            buttons = [[("Отменить всё", f"u:{aid}")],
                       [(f"✏️ {n}", f"tx:e:{t['id']}") for n, t in enumerate(txs, 1)][:8]]
        warnings = self._budget_warnings(items)
        if warnings:
            text += "\n" + "\n".join(warnings)
        if len(items) == 1 and items[0].type == "expense" and items[0].description:
            task = self._best_task_match(items[0].description, threshold=0.6, unique=True)
            if task:
                buttons.append([(f"✅ Закрыть задачу «{fmt.short(task['title'], 24)}»", f"t:s:{task['id']}:d")])
        return Reply(text, buttons)

    def _budget_warnings(self, items: list[MoneyItem]) -> list[str]:
        out = []
        today = self.today()
        start = today.replace(day=1)
        cur = self.currency
        cats = {i.category for i in items if i.type == "expense" and i.currency == cur}
        for cat in cats:
            limit = self.db.scalar("SELECT amount_minor FROM category_limits WHERE category = ?", (cat,))
            if limit:
                spent = self._net_expense(start, today, cur, cat)
                if spent > limit:
                    out.append(f"⚠️ {cat}: {fmt.money(spent)} из {fmt.money(limit, cur)} — лимит превышен")
                elif spent >= limit * 0.9:
                    out.append(f"⚠️ {cat}: {fmt.money(spent)} из {fmt.money(limit, cur)} (≥90%)")
        budget = self.db.get_setting("monthly_budget")
        if budget and cats:
            budget = int(budget)
            spent = self._net_expense(start, today, cur)
            if spent > budget:
                out.append(f"⚠️ Бюджет месяца превышен: {fmt.money(spent)} из {fmt.money(budget, cur)}")
            elif spent >= budget * 0.9:
                out.append(f"⚠️ Бюджет месяца: {fmt.money(spent)} из {fmt.money(budget, cur)}")
        return out

    def _h_ask_amount(self, intent: Intent, msg_id, skip_dup=False) -> Reply:
        if intent.candidates:
            key = self._choice({"kind": "amount", "text": intent.text, "msg": msg_id,
                                "candidates": [str(c) for c in intent.candidates]})
            row = [(fmt.money(fmt.to_minor(c)), f"ch:{key}:{n}") for n, c in enumerate(intent.candidates)][:6]
            return Reply("Какое число — сумма?", [row, [("Отмена", f"ch:{key}:x")]])
        self._set_pending("text_amount", text=intent.text, msg=msg_id)
        return Reply("Какая сумма? Напишите числом.")

    def _h_correction(self, intent: Intent, msg_id, skip_dup=False) -> Reply:
        row = self.db.one("SELECT * FROM transactions ORDER BY id DESC LIMIT 1")
        if row is None or intent.amount is None or intent.amount <= 0:
            return Reply("Не нашёл, что исправлять.")
        return self._set_tx_amount(row["id"], intent.amount, msg_id)

    def _set_tx_amount(self, tx_id: int, amount: Decimal, msg_id: int | None = None) -> Reply:
        with self.db.tx():
            if self.db.get("transactions", tx_id) is None:
                return Reply("Запись не найдена (возможно, удалена).")
            upd = self._update("transactions", tx_id, {"amount_minor": fmt.to_minor(amount)})
            aid = self._action(f"исправление суммы на {fmt.money(fmt.to_minor(amount))}", updated=[upd],
                               msg_id=msg_id)
        tx = self.db.get("transactions", tx_id)
        return Reply(f"Исправил: {self._tx_line(tx)}", [[("Отменить", f"u:{aid}"), ("Изменить", f"tx:e:{tx_id}")]])

    def _set_tx_category(self, tx_id: int, category: str) -> Reply:
        with self.db.tx():
            tx = self.db.get("transactions", tx_id)
            if tx is None:
                return Reply("Запись не найдена (возможно, удалена).", edit=True)
            upd = self._update("transactions", tx_id, {"category": category})
            aid = self._action(f"категория → {category}", updated=[upd])
            # remember: next time the same word goes to this category
            words = [w for w in re.findall(r"\w+", timeparse.normalize(tx["description"].lower()))
                     if w not in nlp.STOPWORDS and not w.isdigit()]
            if words:
                self.db.execute(
                    "INSERT INTO category_memory(keyword, category, hits) VALUES (?, ?, 1) "
                    "ON CONFLICT(keyword) DO UPDATE SET category = excluded.category, hits = hits + 1",
                    (words[0], category))
        tx = self.db.get("transactions", tx_id)
        return Reply(f"Исправил: {self._tx_line(tx)}", [[("Отменить", f"u:{aid}"), ("Изменить", f"tx:e:{tx_id}")]],
                     edit=True)

    def _categories_ordered(self) -> list[str]:
        usage = {r["category"]: r["n"] for r in self.db.all(
            "SELECT category, COUNT(*) AS n FROM transactions WHERE created_at >= ? GROUP BY category",
            (fmt_utc(self.now_utc() - timedelta(days=90)),))}
        return sorted(CATEGORIES, key=lambda c: (-usage.get(c, 0), CATEGORIES.index(c)))

    # ------------------------------------------------------------ tasks
    def _open_tasks(self) -> list[dict]:
        return [dict(r) for r in self.db.all(
            f"SELECT * FROM tasks WHERE status IN {OPEN_STATUSES} ORDER BY "
            "CASE WHEN due_date IS NULL THEN 1 ELSE 0 END, due_date, due_at, id")]

    def _best_task_match(self, query: str, threshold: float = 0.5, unique: bool = False):
        """Return the best matching open task, a list of equally good ones, or None."""
        words = query.split()
        nouns = " ".join(words[1:]) if len(words) > 1 and nlp.DONE_RE.match(query) else query
        noun_stems = nlp.stems(nouns)
        scored = []
        for t in self._open_tasks():
            if noun_stems and not (noun_stems & nlp.stems(t["title"])):
                continue
            s = nlp.match_score(query, t["title"])
            if s >= threshold:
                scored.append((s, t))
        if not scored:
            return None
        best = max(s for s, _ in scored)
        top = [t for s, t in scored if s == best]
        if len(top) == 1:
            return top[0]
        return None if unique else top

    def _task_when(self, task: dict) -> str:
        today = self.today()
        if task["due_at"]:
            loc = self.local_of(task["due_at"])
            return fmt.when(loc.date(), loc.time(), today)
        if task["due_date"]:
            s = fmt.day(date.fromisoformat(task["due_date"]), today)
            return f"до {s}" if task["is_deadline"] else s
        return ""

    def _task_line(self, task: dict, with_status: bool = False) -> str:
        w = self._task_when(task)
        icon = fmt.STATUS_ICON.get(task["status"], "") + " " if with_status else ""
        overdue = ""
        if task["status"] in OPEN_STATUSES and task["due_date"] and date.fromisoformat(task["due_date"]) < self.today():
            overdue = " ⚠️"
        has_rem = self.db.scalar("SELECT 1 FROM reminders WHERE task_id = ? AND status = 'active'", (task["id"],))
        return f"{icon}{task['title']}" + (f" — {w}" if w else "") + (" 🔔" if has_rem else "") + overdue

    def _payday_date(self) -> date | None:
        day = self.db.get_setting("payday_day")
        if not day:
            return None
        return next_month_day(self.today(), int(day))

    def _h_task(self, intent: Intent, msg_id, skip_dup=False) -> Reply:
        ti = intent.time or TimeInfo()
        if ti.recurrence:
            return self._create_recurring_reminder(intent.title, ti, msg_id)
        title = fmt.cap(intent.title.strip())
        due_date = ti.date
        note = ""
        if ti.after_payday:
            pd = self._payday_date()
            if pd:
                due_date = pd
                note = " (после зарплаты)"
            else:
                note = " · срок «после зарплаты» — укажите день зарплаты: «день зарплаты 25»"
        due_local = ti.start_dt()
        return self._create_task(title, due_date, due_local, ti.deadline, msg_id, note=note)

    def _create_task(self, title: str, due_date: date | None, due_local: datetime | None, deadline: bool,
                     msg_id: int | None, note: str = "", remind: bool = True) -> Reply:
        norm = nlp.norm_title(title)
        existing = self.db.one(f"SELECT * FROM tasks WHERE norm_title = ? AND status IN {OPEN_STATUSES}", (norm,))
        if existing:
            existing = dict(existing)
            new_due_at = fmt_utc(self.to_utc(due_local)) if due_local else None
            new_due_date = due_date.isoformat() if due_date else None
            if (new_due_date and new_due_date != existing["due_date"]) or (new_due_at and new_due_at != existing["due_at"]):
                return self._reschedule_task(existing["id"], due_date, due_local.time() if due_local else None,
                                             msg_id, prefix="Такая задача уже есть — обновил срок")
            return Reply(f"Такая задача уже есть: {self._task_line(existing)}",
                         [[("Открыть", f"t:o:{existing['id']}")]])
        now = fmt_utc(self.now_utc())
        with self.db.tx():
            tid = self.db.insert("tasks", {
                "uid": new_uid(), "title": title, "norm_title": norm, "status": "new",
                "due_date": due_date.isoformat() if due_date else None,
                "due_at": fmt_utc(self.to_utc(due_local)) if due_local else None,
                "is_deadline": int(deadline), "created_at": now, "updated_at": now, "source_msg_id": msg_id,
            })
            created = [("tasks", tid)]
            if remind and due_local and self.to_utc(due_local) > self.now_utc():
                rid = self._insert_reminder(title, self.to_utc(due_local), task_id=tid)
                created.append(("reminders", rid))
            aid = self._action(f"задача «{title}»", created=created, msg_id=msg_id)
        task = self.db.get("tasks", tid)
        past = ""
        if due_local and self.to_utc(due_local) <= self.now_utc():
            past = "\n(время уже прошло — напоминание не ставлю)"
        return Reply(f"Задача: {self._task_line(task)}{note}{past}",
                     [[("Отменить", f"u:{aid}"), ("Изменить", f"t:o:{tid}")]])

    def _reschedule_task(self, tid: int, new_date: date | None, new_time: time | None,
                         msg_id: int | None = None, prefix: str = "Перенёс") -> Reply:
        with self.db.tx():
            task = self.db.get("tasks", tid)
            if task is None:
                return Reply("Задача не найдена.")
            due_local = datetime.combine(new_date, new_time) if new_date and new_time else None
            updated = [self._update("tasks", tid, {
                "due_date": new_date.isoformat() if new_date else None,
                "due_at": fmt_utc(self.to_utc(due_local)) if due_local else None,
                "updated_at": fmt_utc(self.now_utc()),
            })]
            created = []
            for r in self.db.all("SELECT id FROM reminders WHERE task_id = ? AND status IN ('active','fired')", (tid,)):
                updated.append(self._update("reminders", r["id"], {"status": "cancelled"}))
            if due_local and self.to_utc(due_local) > self.now_utc():
                created.append(("reminders", self._insert_reminder(task["title"], self.to_utc(due_local), task_id=tid)))
            aid = self._action(f"перенос «{task['title']}»", created=created, updated=updated, msg_id=msg_id)
        task = self.db.get("tasks", tid)
        return Reply(f"{prefix}: {self._task_line(task)}", [[("Отменить", f"u:{aid}"), ("Изменить", f"t:o:{tid}")]])

    def _set_task_status(self, tid: int, status: str, msg_id: int | None = None) -> Reply:
        with self.db.tx():
            task = self.db.get("tasks", tid)
            if task is None:
                return Reply("Задача не найдена.", edit=True)
            if task["status"] == status:
                return Reply(f"Уже: {fmt.STATUS_LABEL[status].lower()} — {task['title']}", toast="Без изменений")
            values = {"status": status, "updated_at": fmt_utc(self.now_utc())}
            if status == "done":
                values["done_at"] = fmt_utc(self.now_utc())
            updated = [self._update("tasks", tid, values)]
            if status in ("done", "cancelled"):
                for r in self.db.all("SELECT id FROM reminders WHERE task_id = ? AND status IN ('active','fired')",
                                     (tid,)):
                    updated.append(self._update("reminders", r["id"], {"status": "done"}))
            aid = self._action(f"«{task['title']}» → {fmt.STATUS_LABEL[status].lower()}", updated=updated,
                               msg_id=msg_id)
        icon = fmt.STATUS_ICON[status]
        return Reply(f"{icon} {fmt.STATUS_LABEL[status]}: {task['title']}", [[("Отменить", f"u:{aid}")]])

    def _delete_task(self, tid: int) -> Reply:
        with self.db.tx():
            task = self.db.get("tasks", tid)
            if task is None:
                return Reply("Задача не найдена.", edit=True)
            rems = [dict(r) for r in self.db.all("SELECT * FROM reminders WHERE task_id = ?", (tid,))]
            self.db.execute("DELETE FROM reminders WHERE task_id = ?", (tid,))
            self.db.execute("DELETE FROM tasks WHERE id = ?", (tid,))
            aid = self._action(f"удаление «{task['title']}»",
                               deleted=[("tasks", task)] + [("reminders", r) for r in rems])
        return Reply(f"🗑 Удалено: {task['title']}", [[("Отменить", f"u:{aid}")]], edit=True)

    def _h_done(self, intent: Intent, msg_id, skip_dup=False) -> Reply:
        query = intent.title
        if len(query.split()) == 1:  # just "готово" / "done"
            tasks = self._today_open_tasks()[:8] or self._open_tasks()[:8]
            if not tasks:
                return Reply("Открытых задач нет 👌")
            return Reply("Какая задача выполнена?",
                         [[(fmt.short(t["title"], 40), f"t:s:{t['id']}:d")] for t in tasks])
        match = self._best_task_match(query)
        if match is None:
            return self._to_inbox(intent.text, msg_id, prefix=f"Не нашёл открытую задачу «{query}».")
        if isinstance(match, list):
            return Reply("Какую задачу отметить выполненной?",
                         [[(fmt.short(t["title"], 40), f"t:s:{t['id']}:d")] for t in match[:8]])
        return self._set_task_status(match["id"], "done", msg_id)

    def _today_open_tasks(self) -> list[dict]:
        today = self.today().isoformat()
        return [t for t in self._open_tasks() if t["due_date"] and t["due_date"] <= today]

    # ------------------------------------------------------------ reminders
    def _insert_reminder(self, text: str, remind_at_utc: datetime, task_id: int | None = None,
                         event_id: int | None = None, recurrence: str | None = None,
                         rec_day: int | None = None, local_time: str | None = None) -> int:
        return self.db.insert("reminders", {
            "uid": new_uid(), "task_id": task_id, "event_id": event_id, "text": text,
            "remind_at": fmt_utc(remind_at_utc), "recurrence": recurrence, "rec_day": rec_day,
            "local_time": local_time, "status": "active", "created_at": fmt_utc(self.now_utc()),
        })

    def _rec_label(self, rec: str, rec_day: int | None, local_dt: datetime) -> str:
        t = fmt.hm(local_dt)
        if rec == "daily":
            return f"каждый день в {t}"
        if rec == "weekly":
            names = ["каждый понедельник", "каждый вторник", "каждую среду", "каждый четверг", "каждую пятницу",
                     "каждую субботу", "каждое воскресенье"]
            return f"{names[local_dt.weekday()]} в {t}"
        return f"каждый месяц {rec_day or local_dt.day}-го в {t}"

    def _create_recurring_reminder(self, title: str, ti: TimeInfo, msg_id: int | None) -> Reply:
        title = fmt.cap(title.strip()) or "Напоминание"
        t = ti.time or self._setting_time("default_remind_time")
        d = ti.date or self.today()
        local = datetime.combine(d, t)
        if ti.recurrence == "monthly":
            local = datetime.combine(next_month_day(self.today(), ti.rec_day or d.day), t)
        while self.to_utc(local) <= self.now_utc():
            local = timeparse.next_occurrence(local, ti.recurrence, ti.rec_day)
        dup = self.db.one("SELECT id FROM reminders WHERE lower(text) = lower(?) AND recurrence = ? AND "
                          "status = 'active'", (title, ti.recurrence))
        if dup:
            return Reply(f"Такое напоминание уже есть: {title}")
        with self.db.tx():
            rid = self._insert_reminder(title, self.to_utc(local), recurrence=ti.recurrence, rec_day=ti.rec_day,
                                        local_time=fmt.hm(t))
            aid = self._action(f"напоминание «{title}»", created=[("reminders", rid)], msg_id=msg_id)
        label = self._rec_label(ti.recurrence, ti.rec_day, local)
        return Reply(f"🔁 Напоминание: {title} · {label}\nБлижайшее: {fmt.when(local.date(), local.time(), self.today())}",
                     [[("Отменить", f"u:{aid}")]])

    def _h_reminder(self, intent: Intent, msg_id, skip_dup=False) -> Reply:
        ti = intent.time
        if ti.recurrence:
            return self._create_recurring_reminder(intent.title, ti, msg_id)
        t = ti.time or self._setting_time("default_remind_time")
        local = datetime.combine(ti.date, t)
        if self.to_utc(local) <= self.now_utc():
            return self._h_ask_when(intent, msg_id, prefix="Это время уже прошло. ")
        return self._create_task(fmt.cap(intent.title), ti.date, local, False, msg_id)

    def _h_ask_when(self, intent: Intent, msg_id, skip_dup=False, prefix: str = "") -> Reply:
        title = fmt.cap(intent.title)
        key = self._choice({"kind": "when", "title": title, "msg": msg_id})
        now = self.now_local()
        row1 = [("Через 1 час", f"ch:{key}:h1")]
        if now.hour < 19:
            row1.append(("Сегодня 20:00", f"ch:{key}:t20"))
        row1.append(("Завтра 09:00", f"ch:{key}:m9"))
        self._set_pending("remind_time", title=title, msg=msg_id)
        return Reply(f"{prefix}Когда напомнить «{title}»? Выберите или напишите, например «в пятницу в 18».",
                     [row1, [("Без напоминания — просто задача", f"ch:{key}:task")]])

    def _remind_from_choice(self, title: str, code: str, msg_id: int | None) -> Reply:
        now = self.now_local().replace(second=0)
        if code == "h1":
            local = now + timedelta(hours=1)
        elif code == "t20":
            local = datetime.combine(now.date(), time(20, 0))
        elif code == "m9":
            local = datetime.combine(now.date() + timedelta(days=1), time(9, 0))
        else:
            return self._create_task(title, None, None, False, msg_id)
        return self._create_task(title, local.date(), local, False, msg_id)

    def _reminder_done(self, rid: int) -> Reply:
        with self.db.tx():
            r = self.db.get("reminders", rid)
            if r is None:
                return Reply("Напоминание не найдено.", edit=True)
            if r["task_id"] and self.db.get("tasks", r["task_id"]):
                return self._set_task_status(r["task_id"], "done")
            if r["recurrence"]:
                upd = self._update("reminders", rid, {"pending_ack": 0})
                nxt = self.local_of(r["remind_at"])
                aid = self._action(f"«{r['text']}» отмечено", updated=[upd])
                return Reply(f"✅ {r['text']} — отмечено. Следующее: {fmt.when(nxt.date(), nxt.time(), self.today())}",
                             [[("Отменить", f"u:{aid}")]])
            upd = self._update("reminders", rid, {"status": "done", "pending_ack": 0})
            aid = self._action(f"«{r['text']}» выполнено", updated=[upd])
        return Reply(f"✅ {r['text']}", [[("Отменить", f"u:{aid}")]])

    def _reminder_snooze(self, rid: int, code: str) -> Reply:
        now = self.now_local().replace(second=0)
        if code == "tm":
            local = datetime.combine(now.date() + timedelta(days=1), self._setting_time("default_remind_time"))
        else:
            local = now + timedelta(minutes=int(code))
        with self.db.tx():
            r = self.db.get("reminders", rid)
            if r is None:
                return Reply("Напоминание не найдено.")
            if r["recurrence"]:
                # keep the schedule, add a one-off copy
                upd = [self._update("reminders", rid, {"pending_ack": 0})]
                new_id = self._insert_reminder(r["text"], self.to_utc(local), task_id=r["task_id"])
                aid = self._action(f"отложено «{r['text']}»", created=[("reminders", new_id)], updated=upd)
            else:
                upd = [self._update("reminders", rid, {"remind_at": fmt_utc(self.to_utc(local)), "status": "active",
                                                       "pending_ack": 0})]
                if r["task_id"] and self.db.get("tasks", r["task_id"]):
                    upd.append(self._update("tasks", r["task_id"], {
                        "due_date": local.date().isoformat(), "due_at": fmt_utc(self.to_utc(local))}))
                aid = self._action(f"отложено «{r['text']}»", updated=upd)
        return Reply(f"⏰ Напомню {fmt.when(local.date(), local.time(), self.today())}: {r['text']}",
                     [[("Отменить", f"u:{aid}")]])

    # ------------------------------------------------------------ events / calendar
    def _h_event(self, intent: Intent, msg_id, skip_dup=False) -> Reply:
        ti = intent.time
        title = fmt.cap(intent.title)
        all_day = ti.time is None
        start_local = datetime.combine(ti.date, ti.time or time(0, 0))
        end_local = ti.end_dt()
        start_utc = self.to_utc(start_local)
        dup = self.db.one("SELECT id FROM events WHERE lower(title) = lower(?) AND start_at = ?",
                          (title, fmt_utc(start_utc)))
        if dup:
            return Reply(f"Такое событие уже есть: {title} · {self._event_when(self.db.get('events', dup['id']))}")
        with self.db.tx():
            eid = self.db.insert("events", {
                "uid": new_uid(), "title": title, "start_at": fmt_utc(start_utc),
                "end_at": fmt_utc(self.to_utc(end_local)) if end_local else None,
                "all_day": int(all_day), "created_at": fmt_utc(self.now_utc()), "source_msg_id": msg_id,
            })
            created = [("events", eid)]
            before = int(self.db.get_setting("event_remind_min", "30"))
            if not all_day and before > 0:
                rem_utc = start_utc - timedelta(minutes=before)
                if rem_utc > self.now_utc():
                    created.append(("reminders", self._insert_reminder(
                        f"{title} в {fmt.hm(start_local)}", rem_utc, event_id=eid)))
            aid = self._action(f"событие «{title}»", created=created, msg_id=msg_id)
        ev = self.db.get("events", eid)
        return Reply(f"📅 {title} · {self._event_when(ev)}", [[("Отменить", f"u:{aid}"), ("Удалить", f"ev:x:{eid}")]])

    def _event_when(self, ev: dict, with_date: bool = True) -> str:
        start = self.local_of(ev["start_at"])
        today = self.today()
        s = fmt.day(start.date(), today) if with_date else ""
        if ev["all_day"]:
            return s or "весь день"
        s = f"{s} {fmt.hm(start)}".strip()
        if ev["end_at"]:
            end = self.local_of(ev["end_at"])
            s += f"–{fmt.hm(end)}"
            if end.date() != start.date():
                s += f" ({fmt.day(end.date(), today)})"
        return s

    def _events_between(self, start_d: date, end_d: date) -> list[dict]:
        """Events overlapping local dates [start_d, end_d] (inclusive)."""
        a = fmt_utc(self.to_utc(datetime.combine(start_d, time(0, 0))))
        b = fmt_utc(self.to_utc(datetime.combine(end_d + timedelta(days=1), time(0, 0))))
        return [dict(r) for r in self.db.all(
            "SELECT * FROM events WHERE start_at < ? AND COALESCE(end_at, start_at) >= ? ORDER BY start_at",
            (b, a))]

    def _delete_event(self, eid: int) -> Reply:
        with self.db.tx():
            ev = self.db.get("events", eid)
            if ev is None:
                return Reply("Событие не найдено.", edit=True)
            rems = [dict(r) for r in self.db.all("SELECT * FROM reminders WHERE event_id = ?", (eid,))]
            self.db.execute("DELETE FROM reminders WHERE event_id = ?", (eid,))
            self.db.execute("DELETE FROM events WHERE id = ?", (eid,))
            aid = self._action(f"удаление события «{ev['title']}»",
                               deleted=[("events", ev)] + [("reminders", r) for r in rems])
        return Reply(f"🗑 Удалено событие: {ev['title']}", [[("Отменить", f"u:{aid}")]], edit=True)

    # ------------------------------------------------------------ notes / inbox
    def _h_note(self, intent: Intent, msg_id, skip_dup=False) -> Reply:
        with self.db.tx():
            nid = self.db.insert("notes", {"uid": new_uid(), "text": intent.title,
                                           "created_at": fmt_utc(self.now_utc())})
            aid = self._action("заметка", created=[("notes", nid)], msg_id=msg_id)
        return Reply("📝 Заметка сохранена.", [[("Отменить", f"u:{aid}")]])

    def _h_unknown(self, intent: Intent, msg_id, skip_dup=False) -> Reply:
        return self._to_inbox(intent.text, msg_id)

    def _to_inbox(self, text: str, msg_id: int | None, prefix: str = "") -> Reply:
        with self.db.tx():
            iid = self.db.insert("inbox", {"uid": new_uid(), "text": text, "status": "new",
                                           "created_at": fmt_utc(self.now_utc()), "source_msg_id": msg_id})
            self._action("в Inbox", created=[("inbox", iid)], msg_id=msg_id)
        head = (prefix + " " if prefix else "") + "📥 Сохранил в Inbox. Что это?"
        return Reply(head, self._inbox_buttons(iid))

    def _inbox_buttons(self, iid: int) -> Buttons:
        rows = [[("Задача", f"ib:{iid}:t"), ("Расход", f"ib:{iid}:m"), ("Напоминание", f"ib:{iid}:r")],
                [("Заметка", f"ib:{iid}:n"), ("Удалить", f"ib:{iid}:x")]]
        if self.ai_active:
            rows[1].insert(0, ("🤖 Разобрать", f"ib:{iid}:ai"))
        return rows

    def _inbox_convert(self, iid: int, kind: str) -> Reply:
        item = self.db.get("inbox", iid)
        if item is None or item["status"] != "new":
            return Reply("Эта запись уже разобрана.", edit=True)
        text = item["text"]

        def done(reply: Reply) -> Reply:
            self.db.update("inbox", iid, {"status": "processed"})
            nxt = self._next_inbox_hint()
            if nxt:
                reply.text += "\n\n" + nxt.text
                reply.buttons = reply.buttons + nxt.buttons
            return reply

        if kind == "ai":
            reply, note = self._try_ai(text, item["source_msg_id"])
            if reply is None:
                return Reply(f"{note}\nОставил в Inbox.", self._inbox_buttons(iid))
            return done(reply)
        if kind == "x":
            with self.db.tx():
                upd = self._update("inbox", iid, {"status": "deleted"})
                aid = self._action("удаление из Inbox", updated=[upd])
            reply = Reply(f"🗑 Удалено: {fmt.short(text, 60)}", [[("Отменить", f"u:{aid}")]])
            nxt = self._next_inbox_hint()
            if nxt:
                reply.text += "\n\n" + nxt.text
                reply.buttons += nxt.buttons
            return reply
        if kind == "n":
            with self.db.tx():
                nid = self.db.insert("notes", {"uid": new_uid(), "text": text, "created_at": fmt_utc(self.now_utc())})
                self._action("заметка из Inbox", created=[("notes", nid)])
                return done(Reply("📝 Сохранил как заметку."))
        if kind == "t":
            ti = timeparse.parse(text, self.now_local())
            title = fmt.cap(ti.remaining or text)
            with self.db.tx():
                return done(self._create_task(title, ti.date, ti.start_dt(), ti.deadline, item["source_msg_id"]))
        if kind == "m":
            ti = timeparse.parse(text, self.now_local(), prefer_future=False)
            amounts = nlp.find_amounts(ti.remaining)
            if len(amounts) == 1:
                money_item = nlp.build_money_item(ti.remaining, amounts[0], ti, self.currency, self.today(),
                                                  self._memory())
                money_item.type = "expense" if money_item.type == "transfer" else money_item.type
                with self.db.tx():
                    return done(self._save_money([money_item], item["source_msg_id"], skip_dup=True))
            self._set_pending("inbox_amount", inbox_id=iid)
            return Reply(f"Какая сумма для «{fmt.short(text, 40)}»? Напишите числом.")
        if kind == "r":
            ti = timeparse.parse(text, self.now_local())
            if ti.date and self.to_utc(datetime.combine(ti.date, ti.time or self._setting_time(
                    "default_remind_time"))) > self.now_utc():
                local = datetime.combine(ti.date, ti.time or self._setting_time("default_remind_time"))
                with self.db.tx():
                    return done(self._create_task(fmt.cap(ti.remaining or text), ti.date, local, False,
                                                  item["source_msg_id"]))
            self.db.update("inbox", iid, {"status": "processed"})
            return self._h_ask_when(Intent("ask_when", text, title=ti.remaining or text), item["source_msg_id"])
        return Reply("?")

    def _next_inbox_hint(self) -> Reply | None:
        row = self.db.one("SELECT * FROM inbox WHERE status = 'new' ORDER BY id LIMIT 1")
        if not row:
            return None
        n = self.db.scalar("SELECT COUNT(*) FROM inbox WHERE status = 'new'")
        return Reply(f"📥 Inbox ({n}): «{row['text']}»", self._inbox_buttons(row["id"]))

    # ------------------------------------------------------------ date ambiguity
    def _ask_date(self, text: str, candidates: list[date], msg_id: int | None) -> Reply:
        key = self._choice({"kind": "date", "text": text, "msg": msg_id,
                            "dates": [d.isoformat() for d in candidates]})
        today = self.today()
        row = [(fmt.day(d) + (" (сегодня)" if d == today else ""), f"ch:{key}:{n}")
               for n, d in enumerate(candidates)]
        return Reply("Уже за полночь — «завтра» это какой день?", [row])

    # ------------------------------------------------------------ pending input
    def _handle_pending(self, text: str, msg_id: int | None) -> Reply | None:
        p = self.db.kv_get("pending", self.now_utc())
        if not p:
            return None
        if text.strip().lower() in CANCEL_WORDS:
            self._clear_pending()
            return Reply("Ок, отменил ввод.")
        kind = p["kind"]
        amount_m = AMOUNT_ONLY_RE.match(text)
        reply: Reply | None = None
        if kind == "tx_amount" and amount_m:
            reply = self._set_tx_amount(p["id"], fmt.parse_amount_str(amount_m.group(1)), msg_id)
        elif kind == "text_amount" and amount_m:
            item = nlp.money_item_with_amount(p["text"], fmt.parse_amount_str(amount_m.group(1)), self.now_local(),
                                              self.currency, self._memory())
            reply = self._save_money([item], p.get("msg"), skip_dup=True)
        elif kind == "inbox_amount" and amount_m:
            inbox = self.db.get("inbox", p["inbox_id"])
            if inbox:
                item = nlp.money_item_with_amount(inbox["text"], fmt.parse_amount_str(amount_m.group(1)),
                                                  self.now_local(), self.currency, self._memory())
                if item.type == "transfer":
                    item.type = "expense"
                with self.db.tx():
                    reply = self._save_money([item], inbox["source_msg_id"], skip_dup=True)
                    self.db.update("inbox", inbox["id"], {"status": "processed"})
        elif kind == "task_title":
            title = fmt.cap(text.strip())
            with self.db.tx():
                upd = self._update("tasks", p["id"], {"title": title, "norm_title": nlp.norm_title(title),
                                                      "updated_at": fmt_utc(self.now_utc())})
                aid = self._action("переименование задачи", updated=[upd], msg_id=msg_id)
            reply = Reply(f"Переименовал: {title}", [[("Отменить", f"u:{aid}"), ("Открыть", f"t:o:{p['id']}")]])
        elif kind in ("task_due", "remind_time"):
            ti = timeparse.parse(text, self.now_local())
            if kind == "task_due" and re.fullmatch(r"\s*(?:без\s+срока|нет|none|no)\s*", text, re.I):
                reply = self._reschedule_task(p["id"], None, None, msg_id)
            elif ti.date is not None:
                if kind == "task_due":
                    reply = self._reschedule_task(p["id"], ti.date, ti.time, msg_id)
                else:
                    local = datetime.combine(ti.date, ti.time or self._setting_time("default_remind_time"))
                    if self.to_utc(local) <= self.now_utc():
                        return Reply("Это время уже прошло — напишите другое.")
                    reply = self._create_task(p["title"], ti.date, local, False, p.get("msg") or msg_id)
        elif kind == "setting":
            reply = self._apply_setting(p["key"], text.strip())
        if reply is not None or kind != "setting":
            self._clear_pending()
        return reply

    # ------------------------------------------------------------ settings & money config
    SETTING_PROMPTS = {
        "morning_time": "Во сколько присылать утренний план? Например 08:00",
        "evening_time": "Во сколько присылать вечернюю сверку? Например 21:30",
        "currency": "Валюта по умолчанию (код из 3 букв), например AED",
        "timezone": "Часовой пояс, например Asia/Dubai или Europe/Moscow",
        "monthly_budget": "Месячный бюджет расходов числом (или «-», чтобы удалить)",
        "payday_day": "День зарплаты (число месяца 1–31, или «-», чтобы удалить)",
        "salary_amount": "Ожидаемая сумма зарплаты (или «-», чтобы удалить)",
        "balance": "Текущий доступный остаток (сколько денег сейчас), или «-»",
        "default_remind_time": "Время напоминания по умолчанию, например 09:00",
        "event_remind_min": "За сколько минут напоминать о событиях (0 — не напоминать)",
    }

    def _apply_setting(self, key: str, value: str) -> Reply:
        v = value.strip()
        deleting = v.lower() in ("-", "удалить", "сбросить", "нет", "delete", "reset", "none")
        try:
            with self.db.tx():
                if deleting:
                    if key in DEFAULTS:
                        self.db.set_setting(key, DEFAULTS[key])
                        return Reply(f"Сбросил «{key}» на значение по умолчанию: {DEFAULTS[key]}")
                    if key == "balance":
                        for k in ("balance_minor", "balance_set_at", "balance_after_tx", "balances"):
                            self.db.del_setting(k)
                    else:
                        self.db.del_setting(key)
                    return Reply("Удалено.")
                if key in ("morning_time", "evening_time", "default_remind_time"):
                    m = re.fullmatch(r"(\d{1,2})(?:[:.](\d{2}))?", v)
                    if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
                        return Reply("Нужно время в формате ЧЧ:ММ, например 08:00")
                    self.db.set_setting(key, f"{int(m.group(1)):02d}:{int(m.group(2) or 0):02d}")
                elif key == "currency":
                    if not re.fullmatch(r"[A-Za-z]{3}", v):
                        return Reply("Нужен код из 3 букв, например AED, USD, EUR")
                    self.db.set_setting(key, v.upper())
                elif key == "timezone":
                    try:
                        ZoneInfo(v)
                    except (ZoneInfoNotFoundError, ValueError):
                        return Reply("Не знаю такой часовой пояс. Пример: Asia/Dubai")
                    self.db.set_setting(key, v)
                elif key in ("monthly_budget", "salary_amount"):
                    self.db.set_setting(key, fmt.to_minor(fmt.parse_amount_str(self._num(v))))
                elif key == "balance":
                    cur = nlp.find_currency(v)[0] or self.currency
                    self._set_balance(cur, fmt.to_minor(fmt.parse_amount_str(self._num(v))))
                elif key == "payday_day":
                    d = int(self._num(v))
                    if not 1 <= d <= 31:
                        return Reply("День должен быть от 1 до 31")
                    self.db.set_setting(key, d)
                elif key == "event_remind_min":
                    self.db.set_setting(key, int(self._num(v)))
                else:
                    return Reply("Неизвестная настройка.")
        except (ValueError, ArithmeticError):
            return Reply("Не понял значение. Попробуйте ещё раз или напишите «отмена».")
        return Reply(f"Сохранено ✅\n\n{self.settings_text()}", self.settings_buttons())

    @staticmethod
    def _num(v: str) -> str:
        m = re.search(r"-?\d+(?:[.,]\d{1,2})?", v.replace(" ", ""))
        if not m:
            raise ValueError(v)
        return m.group(0)

    def _setting_command(self, text: str, msg_id: int | None) -> Reply | None:
        t = timeparse.normalize(text.strip())
        num = r"(\d[\d\s]*(?:[.,]\d{1,2})?)\s*(?:k|к)?"
        m = re.fullmatch(rf"(?:месячный\s+)?(?:бюджет|budget)\s+{num}", t, re.I)
        if m:
            return self._apply_setting("monthly_budget", m.group(1))
        m = re.fullmatch(rf"(?:лимит|limit)\s+(.+?)\s+{num}", t, re.I)
        if m:
            cat = self._category_by_name(m.group(1))
            if not cat:
                return Reply("Не нашёл категорию. Категории: " + ", ".join(CATEGORIES))
            amount = fmt.to_minor(fmt.parse_amount_str(self._num(m.group(2))))
            with self.db.tx():
                if amount == 0:
                    self.db.execute("DELETE FROM category_limits WHERE category = ?", (cat,))
                    return Reply(f"Лимит для «{cat}» удалён.")
                self.db.execute("INSERT INTO category_limits(category, amount_minor) VALUES (?, ?) "
                                "ON CONFLICT(category) DO UPDATE SET amount_minor = excluded.amount_minor", (cat, amount))
            return Reply(f"Лимит: {cat} — {fmt.money(amount, self.currency)} в месяц")
        m = re.fullmatch(rf"(?:остаток|баланс|balance)\s+{num}\s*(?P<cur>\S+)?", t, re.I)
        if m:
            cur = nlp.find_currency(m.group("cur"))[0] if m.group("cur") else self.currency
            if cur is None:
                return Reply("Не понял валюту. Пример: «остаток 150000 тенге».")
            minor = fmt.to_minor(fmt.parse_amount_str(self._num(m.group(1))))
            with self.db.tx():
                self._set_balance(cur, minor)
            others = [fmt.money(v[1], c) for c, v in self._pockets().items() if c != cur]
            return Reply(f"Остаток записан: {fmt.money(minor, cur)}" + (f" (ещё: {', '.join(others)})" if others else "")
                         + ".\nДальше считаю расчётный остаток по записанным операциям.")
        m = re.fullmatch(r"(?:день\s+зарплаты|зарплата|зп|payday)\s+(\d{1,2})(?:-?го|-?е)?(?:\s+числа)?", t, re.I)
        if m:
            r = self._apply_setting("payday_day", m.group(1))
            if r.text.startswith("Сохранено"):
                return Reply(f"День зарплаты: {int(m.group(1))}-е число. Ближайшая: "
                             f"{fmt.day(self._payday_date(), self.today())}")
            return r
        m = re.fullmatch(rf"(?:сумма\s+зарплаты|ожидаемая\s+зарплата|salary\s+amount|expected\s+salary)\s+{num}",
                         t, re.I)
        if m:
            self._apply_setting("salary_amount", m.group(1))
            return Reply(f"Ожидаемая зарплата: {fmt.money(int(self.db.get_setting('salary_amount')), self.currency)}")
        m = re.fullmatch(rf"(?:обязательный\s+)?(?:плат[её]ж|payment)\s+(.+?)\s+{num}\s+(\d{{1,2}})(?:-?го|-?е)?"
                         r"(?:\s+числа)?", t, re.I)
        if m:
            return self._add_payment(m.group(1), m.group(2), int(m.group(3)), msg_id)
        m = re.fullmatch(rf"(?:резерв|отложить|reserve)\s+(.+?)\s+{num}", t, re.I)
        if m:
            return self._set_reserve(m.group(1), m.group(2), msg_id)
        return None

    def _category_by_name(self, name: str) -> str | None:
        n = timeparse.normalize(name.lower().strip())
        for c in CATEGORIES:
            cn = timeparse.normalize(c.lower())
            if cn == n or cn.startswith(n[:4]):
                return c
        cat, matched = nlp.guess_category(n)
        return cat if matched else None

    def _add_payment(self, name: str, amount: str, day: int, msg_id: int | None) -> Reply:
        if not 1 <= day <= 31:
            return Reply("День платежа должен быть от 1 до 31.")
        name = fmt.cap(name.strip())
        minor = fmt.to_minor(fmt.parse_amount_str(self._num(amount)))
        cat, _ = nlp.guess_category(name)
        with self.db.tx():
            existing = self.db.one("SELECT id FROM payments WHERE lower(name) = lower(?)", (name,))
            if existing:
                upd = self._update("payments", existing["id"], {"amount_minor": minor, "day_of_month": day})
                aid = self._action(f"платёж «{name}» изменён", updated=[upd], msg_id=msg_id)
            else:
                pid = self.db.insert("payments", {
                    "uid": new_uid(), "name": name, "amount_minor": minor, "currency": self.currency,
                    "day_of_month": day, "category": cat, "created_at": fmt_utc(self.now_utc())})
                aid = self._action(f"платёж «{name}»", created=[("payments", pid)], msg_id=msg_id)
        nxt = next_month_day(self.today(), day)
        return Reply(f"💳 Обязательный платёж: {name} — {fmt.money(minor, self.currency)}, {day}-го числа.\n"
                     f"Ближайший: {fmt.day(nxt, self.today())}. Учитываю в бюджете до зарплаты.",
                     [[("Отменить", f"u:{aid}")]])

    def _set_reserve(self, name: str, amount: str, msg_id: int | None) -> Reply:
        name = fmt.cap(name.strip())
        minor = fmt.to_minor(fmt.parse_amount_str(self._num(amount)))
        with self.db.tx():
            existing = self.db.one("SELECT * FROM reserves WHERE lower(name) = lower(?)", (name,))
            if minor == 0:
                if not existing:
                    return Reply("Такого резерва нет.")
                self.db.execute("DELETE FROM reserves WHERE id = ?", (existing["id"],))
                aid = self._action(f"резерв «{name}» удалён", deleted=[("reserves", dict(existing))], msg_id=msg_id)
                return Reply(f"Резерв «{name}» удалён.", [[("Отменить", f"u:{aid}")]])
            if existing:
                upd = self._update("reserves", existing["id"], {"amount_minor": minor})
                aid = self._action(f"резерв «{name}»", updated=[upd], msg_id=msg_id)
            else:
                rid = self.db.insert("reserves", {"uid": new_uid(), "name": name, "amount_minor": minor,
                                                  "created_at": fmt_utc(self.now_utc())})
                aid = self._action(f"резерв «{name}»", created=[("reserves", rid)], msg_id=msg_id)
        return Reply(f"🔒 Резерв: {name} — {fmt.money(minor, self.currency)}. Не учитываю его в доступных деньгах.",
                     [[("Отменить", f"u:{aid}")]])

    def _payment_due(self, p: dict, today: date) -> date:
        """Next due date of a payment that is not yet paid."""
        d = next_month_day(today, p["day_of_month"])
        if p["last_paid_month"] == d.strftime("%Y-%m"):
            d = add_months(d.replace(day=1), 1, p["day_of_month"])
        return d

    def _auto_mark_payment(self, item: MoneyItem) -> None:
        """An expense like "интернет 300" pays the matching mandatory payment."""
        today = self.today()
        for p in self.db.all("SELECT * FROM payments"):
            p = dict(p)
            if nlp.match_score(p["name"], item.description) < 0.5:
                continue
            due = self._payment_due(p, today - timedelta(days=10))
            if abs((due - today).days) <= 10:
                self.db.update("payments", p["id"], {"last_paid_month": due.strftime("%Y-%m")})

    def _pay_payment(self, pid: int) -> Reply:
        with self.db.tx():
            p = self.db.get("payments", pid)
            if p is None:
                return Reply("Платёж не найден.")
            due = self._payment_due(p, self.today() - timedelta(days=10))
            month = due.strftime("%Y-%m")
            if p["last_paid_month"] == month:
                return Reply(f"Уже отмечено: {p['name']} за {month}.")
            tx_id = self.db.insert("transactions", {
                "uid": new_uid(), "type": "expense", "amount_minor": p["amount_minor"], "currency": p["currency"],
                "category": p["category"], "description": p["name"], "occurred_on": self.today().isoformat(),
                "created_at": fmt_utc(self.now_utc()), "source_msg_id": None})
            upd = self._update("payments", pid, {"last_paid_month": month})
            aid = self._action(f"оплата «{p['name']}»", created=[("transactions", tx_id)], updated=[upd])
        return Reply(f"💳 Оплачено: {self._tx_line(self.db.get('transactions', tx_id))}", [[("Отменить", f"u:{aid}")]])

    # ------------------------------------------------------------ money queries (multi-currency)
    @property
    def report_currency(self) -> str:
        return self.db.get_setting("report_currency") or self.currency

    @property
    def tracked_currencies(self) -> list[str]:
        return [c.strip().upper() for c in self.db.get_setting("currencies", "AED,USD,KZT").split(",") if c.strip()]

    def _conv(self, minor: int, frm: str, to: str, day: date | None = None) -> int | None:
        v = self.market.convert(minor, frm, to, day or self.today())
        if v is None:
            self._fx_missing.add(frm.upper() if self.market.per_usd(frm, day or self.today()) is None else to.upper())
        return v

    def _tx_rows(self, types: tuple[str, ...], start: date, end: date, category: str | None = None) -> list:
        q = (f"SELECT * FROM transactions WHERE type IN ({','.join('?' * len(types))}) "
             "AND occurred_on BETWEEN ? AND ?")
        params: list = [*types, start.isoformat(), end.isoformat()]
        if category:
            q += " AND category = ?"
            params.append(category)
        return self.db.all(q, params)

    def _sum(self, types: tuple[str, ...], start: date, end: date, currency: str, category: str | None = None) -> int:
        """Sum in ``currency``; each operation converted at the rate of its own date."""
        total = 0
        for r in self._tx_rows(types, start, end, category):
            v = self._conv(r["amount_minor"], r["currency"], currency, date.fromisoformat(r["occurred_on"]))
            total += v or 0
        return total

    def _net_expense(self, start: date, end: date, currency: str, category: str | None = None) -> int:
        return self._sum(("expense",), start, end, currency, category) - \
            self._sum(("refund",), start, end, currency, category)

    def _by_category(self, start: date, end: date, currency: str) -> list[tuple[str, int]]:
        acc: dict[str, int] = {}
        for r in self._tx_rows(("expense", "refund"), start, end):
            v = self._conv(r["amount_minor"], r["currency"], currency, date.fromisoformat(r["occurred_on"])) or 0
            acc[r["category"]] = acc.get(r["category"], 0) + (v if r["type"] == "expense" else -v)
        return sorted(((c, v) for c, v in acc.items() if v > 0), key=lambda x: -x[1])

    def _fx_warning(self) -> str:
        if not self._fx_missing:
            return ""
        codes = ", ".join(sorted(self._fx_missing))
        self._fx_missing.clear()
        return (f"⚠️ Нет курса для {codes} — эти суммы не пересчитаны и не учтены. "
                f"Курсы обновятся сами при доступе в интернет, или напишите «курс доллара 512 тенге».")

    # wallet: separate balances per currency ("остаток 2400", "остаток 150000 тенге")
    def _balances(self) -> dict[str, dict]:
        raw = self.db.get_setting("balances")
        if raw:
            return json.loads(raw)
        if self.db.get_setting("balance_minor") is not None:  # migrate the single-currency balance
            return {self.currency: {"minor": int(self.db.get_setting("balance_minor")),
                                    "after_tx": int(self.db.get_setting("balance_after_tx", "0")),
                                    "after_move": 0, "set_at": self.db.get_setting("balance_set_at")}}
        return {}

    def _set_balance(self, currency: str, minor: int | None) -> None:
        bal = self._balances()
        if minor is None:
            bal.pop(currency, None)
        else:
            bal[currency] = {"minor": minor,
                             "after_tx": int(self.db.scalar("SELECT COALESCE(MAX(id), 0) FROM transactions")),
                             "after_move": int(self.db.scalar("SELECT COALESCE(MAX(id), 0) FROM moves")),
                             "set_at": fmt_utc(self.now_utc())}
        self.db.set_setting("balances", json.dumps(bal))
        for k in ("balance_minor", "balance_set_at", "balance_after_tx"):
            self.db.del_setting(k)

    def _pockets(self) -> dict[str, tuple[int, int, datetime]]:
        """{currency: (entered, calculated, set_at)} - calculated = entered ± everything recorded after it."""
        out = {}
        for cur, b in self._balances().items():
            delta = int(self.db.scalar(
                "SELECT COALESCE(SUM(CASE WHEN type IN ('income','refund') THEN amount_minor "
                "WHEN type = 'expense' THEN -amount_minor ELSE 0 END), 0) FROM transactions "
                "WHERE id > ? AND currency = ?", (b["after_tx"], cur)))
            delta -= int(self.db.scalar(
                "SELECT COALESCE(SUM(from_minor), 0) FROM moves WHERE id > ? AND from_currency = ? "
                "AND kind IN ('exchange','deposit')", (b["after_move"], cur)))
            delta += int(self.db.scalar(
                "SELECT COALESCE(SUM(to_minor), 0) FROM moves WHERE id > ? AND to_currency = ? "
                "AND kind IN ('exchange','withdraw')", (b["after_move"], cur)))
            set_at = parse_utc(b["set_at"]).replace(tzinfo=None) if b.get("set_at") else self.now_utc()
            out[cur] = (b["minor"], b["minor"] + delta, set_at)
        return out

    def _calculated_balance(self, currency: str | None = None) -> tuple[int, int, datetime] | None:
        pockets = self._pockets()
        if not pockets:
            return None
        cur = currency or self.report_currency
        base = sum(self._conv(v[0], c, cur) or 0 for c, v in pockets.items())
        calc = sum(self._conv(v[1], c, cur) or 0 for c, v in pockets.items())
        return base, calc, max(v[2] for v in pockets.values())

    def _payday_numbers(self, currency: str | None = None) -> dict | None:
        """Money-until-payday figures, or None when neither balance nor payday is configured."""
        cur = currency or self.report_currency
        today = self.today()
        payday = self._payday_date()
        bal = self._calculated_balance(cur)
        if payday is None and bal is None:
            return None
        res: dict = {"payday": payday, "balance": bal, "mandatory": 0, "reserves": 0,
                     "available": None, "per_day": None, "days": None}
        res["reserves"] = self._conv(int(self.db.scalar("SELECT COALESCE(SUM(amount_minor), 0) FROM reserves")),
                                     self.currency, cur) or 0
        if payday is not None:
            days = (payday - today).days
            res["days"] = days
            for p in self.db.all("SELECT * FROM payments"):
                d = next_month_day(today, p["day_of_month"])
                while d < payday or (days == 0 and d == payday):
                    if p["last_paid_month"] != d.strftime("%Y-%m"):
                        res["mandatory"] += self._conv(p["amount_minor"], p["currency"], cur) or 0
                    d = add_months(d.replace(day=1), 1, p["day_of_month"])
            if bal is not None:
                res["available"] = bal[1] - res["mandatory"] - res["reserves"]
                if days > 0:
                    a = res["available"]
                    res["per_day"] = a // days if a > 0 else a
        return res

    def payday_block(self, currency: str | None = None) -> list[str]:
        cur = currency or self.report_currency
        today = self.today()
        n = self._payday_numbers(cur)
        if n is None:
            return ["Не настроено. Напишите «остаток 2400» и «день зарплаты 25»."]
        lines = []
        payday, bal = n["payday"], n["balance"]
        if payday is not None:
            days = n["days"]
            head = f"Зарплата: {fmt.day(payday, today)}" + (f", через {fmt.plural_days(days)}" if days > 0 else "")
            salary = self.db.get_setting("salary_amount")
            if salary:
                head += f" (~{fmt.money(self._conv(int(salary), self.currency, cur) or 0, cur)})"
            lines.append(head)
        if bal is not None:
            base, calc, set_at = bal
            pockets = self._pockets()
            lines.append(f"Введённый остаток: {fmt.money(base, cur)} ({fmt.day(self.to_local(set_at).date(), today)})")
            lines.append(f"Расчётный остаток: {fmt.money(calc, cur)} (по записям в боте, не банк)")
            if len(pockets) > 1 or (pockets and next(iter(pockets)) != cur):
                lines.append("  " + " · ".join(fmt.money(v[1], c) for c, v in pockets.items()))
        if payday is None:
            lines.append("День зарплаты не указан — напишите «день зарплаты 25».")
            return lines
        if n["mandatory"]:
            lines.append(f"Обязательные платежи до зарплаты: −{fmt.money(n['mandatory'], cur)}")
        if n["reserves"]:
            lines.append(f"Резервы: −{fmt.money(n['reserves'], cur)}")
        if n["available"] is None:
            lines.append("Чтобы посчитать бюджет на день, укажите остаток: «остаток 2400».")
        elif n["per_day"] is not None:
            lines.append(f"Свободно: {fmt.money(n['available'], cur)} → можно {fmt.money(n['per_day'], cur)}/день")
        else:
            lines.append(f"Свободно: {fmt.money(n['available'], cur)} — сегодня зарплата")
        return lines

    def daily_allowance(self) -> int | None:
        n = self._payday_numbers()
        return None if n is None else n["per_day"]

    # ------------------------------------------------------------ views
    def view_today(self) -> Reply:
        today, now = self.today(), self.now_local()
        lines = [f"📅 Сегодня, {fmt.day(today)}"]
        overdue = [t for t in self._open_tasks() if t["due_date"] and t["due_date"] < today.isoformat()]
        todays = [t for t in self._open_tasks() if t["due_date"] == today.isoformat()]
        events = self._events_between(today, today)
        if overdue:
            lines.append("\n⚠️ Просрочено:")
            lines += [f"• {self._task_line(t)}" for t in overdue]
        if events:
            lines.append("\nСобытия:")
            lines += [f"• {self._event_when(e, with_date=False)} {e['title']}" for e in events]
        if todays:
            lines.append("\nЗадачи:")
            lines += [f"• {self._task_line(t)}" for t in todays]
        pending = self._pending_reminders()
        if pending:
            lines.append("\nЖдут ответа:")
            lines += [f"• 🔔 {r['text']}" for r in pending]
        rems = self._reminders_between(now, datetime.combine(today, time(23, 59)), standalone=True)
        if rems:
            lines.append("\nНапоминания:")
            lines += [f"• {fmt.hm(self.local_of(r['remind_at']))} {r['text']}" for r in rems]
        pays = self._payments_soon(3)
        if pays:
            lines.append("\nПлатежи:")
            lines += [f"• {p['name']} — {fmt.money(p['amount_minor'], p['currency'])}, {fmt.day(d, today)}"
                      for p, d in pays]
        if len(lines) == 1:
            lines.append("\nНа сегодня ничего не запланировано.")
        spent = self._net_expense(today, today, self.currency)
        money_line = f"\n💸 Расходы сегодня: {fmt.money(spent, self.currency)}"
        allowance = self.daily_allowance()
        if allowance is not None:
            money_line += f" · можно {fmt.money(allowance, self.currency)}/день"
        lines.append(money_line)
        buttons = [[(f"✅ {fmt.short(t['title'], 28)}", f"t:s:{t['id']}:d")] for t in (overdue + todays)[:8]]
        buttons += [[(f"💳 Оплачено: {fmt.short(p['name'], 20)}", f"pay:{p['id']}")] for p, d in pays if d <= today]
        return Reply("\n".join(lines), buttons)

    def _pending_reminders(self) -> list[dict]:
        """Reminders that fired but still need an answer (no task attached or recurring)."""
        return [dict(r) for r in self.db.all(
            "SELECT * FROM reminders WHERE task_id IS NULL AND event_id IS NULL AND "
            "((status = 'fired') OR (status = 'active' AND pending_ack = 1)) ORDER BY remind_at")]

    def _reminders_between(self, a_local: datetime, b_local: datetime, standalone: bool = False) -> list[dict]:
        q = "SELECT * FROM reminders WHERE status = 'active' AND remind_at BETWEEN ? AND ?"
        if standalone:
            q += " AND task_id IS NULL AND event_id IS NULL"
        return [dict(r) for r in self.db.all(q + " ORDER BY remind_at",
                                             (fmt_utc(self.to_utc(a_local)), fmt_utc(self.to_utc(b_local))))]

    def _payments_soon(self, days: int) -> list[tuple[dict, date]]:
        today = self.today()
        out = []
        for p in self.db.all("SELECT * FROM payments ORDER BY day_of_month"):
            p = dict(p)
            d = self._payment_due(p, today)
            if (d - today).days <= days:
                out.append((p, d))
        return sorted(out, key=lambda x: x[1])

    def view_tasks(self, show_all: bool = False) -> Reply:
        tasks = self._open_tasks()
        if not tasks:
            return Reply("Открытых задач нет 👌\nНапишите, например: «Завтра купить продукты».")
        today = self.today().isoformat()
        groups = [
            ("⚠️ Просрочено", [t for t in tasks if t["due_date"] and t["due_date"] < today]),
            ("Сегодня", [t for t in tasks if t["due_date"] == today]),
            ("Дальше", [t for t in tasks if t["due_date"] and t["due_date"] > today]),
            ("Без срока", [t for t in tasks if not t["due_date"]]),
        ]
        lines, buttons, n = [f"✅ Задачи ({len(tasks)})"], [], 0
        limit = 40 if show_all else 15
        for title, items in groups:
            if not items:
                continue
            lines.append(f"\n{title}:")
            for t in items:
                n += 1
                if n > limit:
                    break
                lines.append(f"{n}. {self._task_line(t, with_status=True)}")
                buttons.append((f"{n}", f"t:o:{t['id']}"))
        if n > limit:
            lines.append(f"\n…и ещё {len(tasks) - limit}")
        rows = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
        if n > limit and not show_all:
            rows.append([("Показать все", "tasks:all")])
        lines.append("\nНажмите номер, чтобы изменить задачу.")
        return Reply("\n".join(lines), rows)

    def task_card(self, tid: int) -> Reply:
        t = self.db.get("tasks", tid)
        if t is None:
            return Reply("Задача не найдена.", edit=True)
        w = self._task_when(t) or "без срока"
        text = f"{t['title']}\nСрок: {w}\nСтатус: {fmt.STATUS_LABEL[t['status']]}"
        return Reply(text, [
            [("✅ Выполнено", f"t:s:{tid}:d"), ("▶️ В процессе", f"t:s:{tid}:p"), ("⏸ Ожидает", f"t:s:{tid}:w")],
            [("📅 Перенести", f"t:r:{tid}"), ("✏️ Текст", f"t:e:{tid}")],
            [("✖️ Отменить задачу", f"t:s:{tid}:c"), ("🗑 Удалить", f"t:x:{tid}")],
        ], edit=True)

    def _currency_row(self, prefix: str, current: str) -> list[tuple[str, str]]:
        return [(("• " if c == current else "") + c, f"{prefix}{c}") for c in self.tracked_currencies]

    def view_money(self, currency: str | None = None) -> Reply:
        cur = currency or self.report_currency
        e = html.escape
        today = self.today()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        spent_today = self._net_expense(today, today, cur)
        spent_week = self._net_expense(week_start, today, cur)
        spent_month = self._net_expense(month_start, today, cur)
        income_month = self._sum(("income",), month_start, today, cur)
        lines = [f"💰 <b>Деньги · {fmt.MONTHS_NOM[today.month - 1]} {today.year}</b> · {cur}", "",
                 f"Сегодня  <b>{fmt.money(spent_today, cur)}</b>",
                 f"Неделя  <b>{fmt.money(spent_week, cur)}</b>"]
        budget = self.db.get_setting("monthly_budget")
        month_line = f"Месяц  <b>{fmt.money(spent_month, cur)}</b>"
        if budget:
            b = self._conv(int(budget), self.currency, cur) or 0
            month_line += f" из {fmt.money(b, cur)} ({spent_month * 100 // b if b else 0}%)"
        lines.append(month_line)
        lines.append(f"Доходы за месяц  <b>{fmt.money(income_month, cur, '+')}</b>")
        cats = self._by_category(month_start, today, cur)
        limits = {r["category"]: self._conv(r["amount_minor"], self.currency, cur)
                  for r in self.db.all("SELECT * FROM category_limits")}
        if cats:
            lines += ["", "<b>По категориям</b>"]
            for name, v in cats:
                pct = v * 100 // spent_month if spent_month > 0 else 0
                lim = limits.get(name)
                lim_s = f" · лимит {fmt.money(lim)}{' ⚠️' if v > lim else ''}" if lim else ""
                lines.append(f"• {e(name)} — {fmt.money(v)} ({pct}%){lim_s}")
        lines += ["", "🗓 <b>До зарплаты</b>"]
        lines += [e(x) for x in self.payday_block(cur)]
        recent = self.db.all("SELECT * FROM transactions ORDER BY occurred_on DESC, id DESC LIMIT 7")
        if recent:
            lines += ["", "<b>Последние</b>"]
            for r in recent:
                d = date.fromisoformat(r["occurred_on"])
                lines.append(f"{d.strftime('%d.%m')}  {e(self._tx_line(dict(r), show_date=False))}")
        warn = self._fx_warning()
        if warn:
            lines += ["", e(warn)]
        buttons = [[("📊 Аналитика", f"st:m:{cur}"), ("💼 Капитал", f"cap:{cur}"), ("💱 Курсы", "fx:v")],
                   self._currency_row("money:c:", cur),
                   [("Последние 20", "money:recent"), ("Как настроить", "money:help")]]
        return Reply("\n".join(lines), buttons, html=True)

    def view_recent_tx(self) -> Reply:
        rows = self.db.all("SELECT * FROM transactions ORDER BY occurred_on DESC, id DESC LIMIT 20")
        if not rows:
            return Reply("Операций пока нет.")
        lines, buttons = ["Последние операции:"], []
        for n, r in enumerate(rows, 1):
            d = date.fromisoformat(r["occurred_on"])
            lines.append(f"{n}. {d.strftime('%d.%m')} {self._tx_line(dict(r), show_date=False)}")
            buttons.append((str(n), f"tx:e:{r['id']}"))
        lines.append("\nНажмите номер, чтобы исправить или удалить.")
        return Reply("\n".join(lines), [buttons[i:i + 5] for i in range(0, len(buttons), 5)])

    MONEY_HELP = (
        "Настройки денег — просто напишите:\n"
        "• бюджет 3000 — месячный бюджет\n"
        "• лимит кафе 500 — лимит категории (0 — удалить)\n"
        "• остаток 2400 — сколько денег сейчас\n"
        "• день зарплаты 25 — число месяца\n"
        "• сумма зарплаты 6500\n"
        "• платёж интернет 300 1 — обязательный платёж 1-го числа\n"
        "• резерв отпуск 1000 — отложенные деньги (0 — удалить)\n"
        "• не 18, а 20 — исправить сумму последней записи"
    )

    def view_calendar(self, week_offset: int = 0) -> Reply:
        today = self.today()
        start = today + timedelta(days=7 * week_offset)
        end = start + timedelta(days=6)
        events = self._events_between(start, end)
        tasks = [t for t in self._open_tasks() if t["due_date"] and start.isoformat() <= t["due_date"] <= end.isoformat()]
        rems = self._reminders_between(datetime.combine(start, time(0, 0)), datetime.combine(end, time(23, 59)),
                                       standalone=True)
        lines = [f"🗓 Календарь: {fmt.day(start)} — {fmt.day(end)}"]
        buttons = []
        n = 0
        for i in range(7):
            d = start + timedelta(days=i)
            day_items = []
            for e in events:
                if self.local_of(e["start_at"]).date() == d:
                    n += 1
                    day_items.append(f"{n}. {self._event_when(e, with_date=False)} {e['title']}")
                    buttons.append((f"🗑{n}", f"ev:x:{e['id']}"))
            for t in tasks:
                if t["due_date"] == d.isoformat():
                    day_items.append(f"• {self._task_line(t)}")
            for r in rems:
                if self.local_of(r["remind_at"]).date() == d:
                    day_items.append(f"🔔 {fmt.hm(self.local_of(r['remind_at']))} {r['text']}")
            if day_items:
                lines.append(f"\n{fmt.cap(fmt.day(d, today))}" + (f", {fmt.day(d)}" if abs((d - today).days) <= 1 else ""))
                lines += day_items
        if len(lines) == 1:
            lines.append("\nПусто. Добавить: «В четверг пара в 8:30».")
        rows = [buttons[i:i + 6] for i in range(0, min(len(buttons), 18), 6)]
        nav = [("◀️", f"cal:{week_offset - 1}"), ("Эта неделя", "cal:0"), ("▶️", f"cal:{week_offset + 1}")]
        rows.append(nav)
        return Reply("\n".join(lines), rows)

    def view_inbox(self) -> Reply:
        rows = self.db.all("SELECT * FROM inbox WHERE status = 'new' ORDER BY id")
        if not rows:
            return Reply("📥 Inbox пуст.")
        lines = [f"📥 Inbox ({len(rows)}):"]
        for n, r in enumerate(rows[:15], 1):
            err = " ⚠️" if r["error"] else ""
            lines.append(f"{n}. {fmt.short(r['text'], 60)}{err}")
        first = rows[0]
        lines.append(f"\nРазбираем №1: «{first['text']}»")
        return Reply("\n".join(lines), self._inbox_buttons(first["id"]))

    def settings_text(self) -> str:
        g = self.db.get_setting
        cur = self.currency
        onoff = {"1": "вкл", "0": "выкл"}
        budget = g("monthly_budget")
        salary = g("salary_amount")
        bal = " · ".join(fmt.money(v[1], c) for c, v in self._pockets().items())
        lines = [
            "⚙️ Настройки",
            f"Валюта: {cur}",
            f"Часовой пояс: {g('timezone')}",
            f"Утренний план: {onoff[g('morning_enabled')]} в {g('morning_time')}",
            f"Вечерняя сверка: {onoff[g('evening_enabled')]} в {g('evening_time')}",
            f"Напоминание по умолчанию: {g('default_remind_time')}",
            f"Напоминать о событиях за: {g('event_remind_min')} мин",
            f"Бюджет месяца: {fmt.money(int(budget), cur) if budget else '—'}",
            f"День зарплаты: {g('payday_day') or '—'}",
            f"Ожидаемая зарплата: {fmt.money(int(salary), cur) if salary else '—'}",
            f"Валюта отчётов: {self.report_currency} (переключение — кнопками в отчётах)",
            f"Остаток (расчётный): {bal or '—'}",
            f"Отчёт-картинка за месяц 1-го числа: {onoff[g('monthly_report')]}",
            "AI: " + (f"{onoff[g('ai_enabled')]} ({self.ai.cfg.provider}, {self.ai.cfg.model})" if self.ai is not None
                      else "не подключён (см. README)"),
        ]
        pays = self.db.all("SELECT * FROM payments ORDER BY day_of_month")
        if pays:
            lines.append("Платежи: " + "; ".join(f"{p['name']} {fmt.money(p['amount_minor'])} ({p['day_of_month']}-го)"
                                                 for p in pays))
        res = self.db.all("SELECT * FROM reserves")
        if res:
            lines.append("Резервы: " + "; ".join(f"{r['name']} {fmt.money(r['amount_minor'])}" for r in res))
        lims = self.db.all("SELECT * FROM category_limits")
        if lims:
            lines.append("Лимиты: " + "; ".join(f"{r['category']} {fmt.money(r['amount_minor'])}" for r in lims))
        return "\n".join(lines)

    def settings_buttons(self) -> Buttons:
        g = self.db.get_setting
        return [
            [(("🌅 Утро: выкл" if g("morning_enabled") == "1" else "🌅 Утро: вкл"), "set:tog:morning_enabled"),
             ("Время утра", "set:ask:morning_time")],
            [(("🌙 Вечер: выкл" if g("evening_enabled") == "1" else "🌙 Вечер: вкл"), "set:tog:evening_enabled"),
             ("Время вечера", "set:ask:evening_time")],
            [("Валюта", "set:ask:currency"), ("Часовой пояс", "set:ask:timezone"),
             ("Напом. по умолч.", "set:ask:default_remind_time")],
            [("Бюджет", "set:ask:monthly_budget"), ("День зарплаты", "set:ask:payday_day"),
             ("Сумма зарплаты", "set:ask:salary_amount")],
            [("Остаток", "set:ask:balance"), ("События: за N мин", "set:ask:event_remind_min")],
            [("Платежи/резервы/лимиты", "set:list"),
             (("📊 Отчёт 1-го: выкл" if g("monthly_report") == "1" else "📊 Отчёт 1-го: вкл"),
              "set:tog:monthly_report")],
        ] + ([[(("🤖 AI: выкл" if g("ai_enabled") == "1" else "🤖 AI: вкл"), "set:tog:ai_enabled")]]
             if self.ai is not None else [])

    def view_settings(self) -> Reply:
        return Reply(self.settings_text(), self.settings_buttons())

    def _settings_list(self) -> Reply:
        rows: Buttons = []
        lines = ["Нажмите, чтобы удалить:"]
        for p in self.db.all("SELECT * FROM payments ORDER BY day_of_month"):
            rows.append([(f"🗑 Платёж: {p['name']}", f"set:delp:{p['id']}")])
        for r in self.db.all("SELECT * FROM reserves"):
            rows.append([(f"🗑 Резерв: {r['name']}", f"set:delr:{r['id']}")])
        for i, r in enumerate(self.db.all("SELECT * FROM category_limits ORDER BY category")):
            rows.append([(f"🗑 Лимит: {r['category']}", f"set:dell:{CATEGORIES.index(r['category'])}")])
        if not rows:
            lines = ["Платежей, резервов и лимитов пока нет.", "", self.MONEY_HELP]
        return Reply("\n".join(lines), rows)

    # ------------------------------------------------------------ analytics (images)
    PERIODS = {"w": "Неделя", "m": "Месяц", "pm": "Прошлый месяц", "6": "Полгода"}

    def _period_range(self, period: str) -> tuple[date, date, str]:
        today = self.today()
        if period == "w":
            return today - timedelta(days=today.weekday()), today, "эта неделя"
        if period == "6":
            return add_months(today.replace(day=1), -5), today, "полгода"
        if period == "pm":
            end = today.replace(day=1) - timedelta(days=1)
            return end.replace(day=1), end, fmt.MONTHS_NOM[end.month - 1]
        return today.replace(day=1), today, fmt.MONTHS_NOM[today.month - 1]

    def category_drill(self, period: str, cur: str, idx: int | None = None) -> Reply:
        """Tap-through from the report: list of categories -> one category's operations."""
        e = html.escape
        start, end, label = self._period_range(period)
        cats = self._by_category(start, end, cur)
        total = sum(v for _, v in cats) or 1
        if idx is None:
            rows = [[(f"{name} · {fmt.money(v)} · {v * 100 // total}%", f"sc:{period}:{cur}:{CATEGORIES.index(name)}")]
                    for name, v in cats[:12]]
            rows.append([("◀ К отчёту", f"st:{period}:{cur}")])
            return Reply(f"🔎 <b>Категории · {e(label)}</b> · {cur}\nНажмите, чтобы увидеть операции.", rows, html=True)
        name = CATEGORIES[idx]
        txs = self._tx_rows(("expense", "refund"), start, end, name)
        conv = sorted(((r, self._conv(r["amount_minor"], r["currency"], cur, date.fromisoformat(r["occurred_on"])) or 0)
                       for r in txs), key=lambda x: (x[0]["occurred_on"], x[0]["id"]), reverse=True)
        amount = sum(v if r["type"] == "expense" else -v for r, v in conv)
        n = sum(1 for r, _ in conv if r["type"] == "expense")
        lines = [f"<b>{e(name)}</b> · {e(label)}", f"<b>{fmt.money(amount, cur)}</b> · {n} {fmt.plural(n, 'операция', 'операции', 'операций')} · "
                 f"{amount * 100 // total}% расходов", ""]
        prev_day = None
        for r, v in conv[:40]:
            if r["occurred_on"] != prev_day:
                prev_day = r["occurred_on"]
                lines.append(f"<i>{fmt.cap(fmt.day(date.fromisoformat(prev_day), self.today()))}</i>")
            sign = "−" if r["type"] == "expense" else "↩ +"
            orig = f" ({fmt.money(r['amount_minor'], r['currency'])})" if r["currency"] != cur else ""
            lines.append(f"  {sign}{fmt.money(v)}{orig} · {e(r['description'] or name)}")
        if len(conv) > 40:
            lines.append(f"…и ещё {len(conv) - 40}")
        return Reply("\n".join(lines), [[("◀ Категории", f"sc:{period}:{cur}"), ("◀ К отчёту", f"st:{period}:{cur}")]],
                     html=True)

    def _category_colors(self, ranked: list[str]) -> dict[str, int]:
        """Permanent category -> palette slot. New categories take the next free slot (max 8)."""
        colors: dict[str, int] = json.loads(self.db.get_setting("category_colors", "{}"))
        changed = False
        all_time = [r["category"] for r in self.db.all(
            "SELECT category FROM transactions WHERE type = 'expense' GROUP BY category ORDER BY SUM(amount_minor) DESC")]
        for name in all_time + ranked:
            if name not in colors and name != nlp.OTHER and len(colors) < 8:
                colors[name] = len(colors)
                changed = True
        if changed:
            self.db.set_setting("category_colors", json.dumps(colors, ensure_ascii=False))
        return colors

    def analytics(self, period: str = "m", currency: str | None = None) -> Reply:
        from . import charts

        today = self.today()
        cur = currency or self.report_currency
        limits = {r["category"]: r["amount_minor"] for r in self.db.all("SELECT * FROM category_limits")}
        month_names_gen = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
                           "сентября", "октября", "ноября", "декабря"]
        bars: list[tuple[str, int, bool]] = []
        reference = None
        if period == "w":
            start = today - timedelta(days=today.weekday())
            end = today
            prev_start, prev_end = start - timedelta(days=7), end - timedelta(days=7)
            title = "Эта неделя"
            subtitle = f"Расходы · {fmt.day(start)}" + (f" — {fmt.day(end)}" if end != start else "")
            compare_label = "к прошлой неделе за те же дни"
            for i in range(7):
                d = start + timedelta(days=i)
                bars.append((fmt.WD_SHORT[i], self._net_expense(d, d, cur) if d <= today else 0, d == today))
            bars_title = "По дням"
        elif period == "6":
            first = add_months(today.replace(day=1), -5)
            start, end = first, today
            prev_start = prev_end = None
            title = "Полгода"
            subtitle = f"Расходы · {fmt.MONTHS_NOM[first.month - 1]} — {fmt.MONTHS_NOM[today.month - 1]}"
            compare_label = None
            for i in range(6):
                ms = add_months(first, i, 1)
                me = add_months(ms, 1, 1) - timedelta(days=1)
                bars.append((fmt.MONTHS_SHORT[ms.month - 1], self._net_expense(ms, min(me, today), cur), i == 5))
            bars_title = "По месяцам"
        else:
            if period == "pm":
                end = today.replace(day=1) - timedelta(days=1)
                start = end.replace(day=1)
                prev_end = start - timedelta(days=1)
                prev_start = prev_end.replace(day=1)
                compare_label = f"к {fmt.MONTHS_DAT[prev_start.month - 1]}"
            else:
                start, end = today.replace(day=1), today
                prev_start = add_months(start, -1, 1)
                prev_end = min(add_months(start, -1, today.day), start - timedelta(days=1))
                compare_label = "к прошлому месяцу за те же дни"
            title = f"{fmt.cap(fmt.MONTHS_NOM[start.month - 1])} {start.year}"
            subtitle = f"Расходы · {start.day}–{end.day} {month_names_gen[start.month - 1]}"
            month_end = add_months(start, 1, 1) - timedelta(days=1)
            d = start
            while d <= month_end:
                bars.append((str(d.day), self._net_expense(d, d, cur) if d <= end else 0, d == today))
                d += timedelta(days=1)
            bars_title = "По дням"
            budget = self.db.get_setting("monthly_budget")
            if budget:
                reference = ("бюджет/день", (self._conv(int(budget), self.currency, cur) or 0) // month_end.day)
        total = self._net_expense(start, end, cur)
        compare_total = self._net_expense(prev_start, prev_end, cur) if prev_start else None
        income = self._sum(("income",), start, end, cur)
        monthly_view = period in ("m", "pm")
        categories = [charts.CategoryRow(name, v, (self._conv(limits[name], self.currency, cur)
                                                   if monthly_view and name in limits else None))
                      for name, v in self._by_category(start, end, cur)]
        days = (end - start).days + 1
        whole = lambda m: fmt.money(round(m / 100) * 100)  # noqa: E731 - tiles show whole units
        kpis = [("Доходы", "+" + whole(income) if income else "0")]
        if period == "6":
            active_months = sum(1 for _, v, _ in bars if v > 0) or 1
            kpis.append(("В среднем за месяц", whole(total // active_months)))
        else:
            kpis.append(("В среднем за день", whole(total // max(days, 1))))
        allowance = self.daily_allowance() if period in ("m", "w") else None
        if allowance is not None:
            kpis.append(("Можно сегодня", whole(allowance)))
        else:
            n_tx = self.db.scalar("SELECT COUNT(*) FROM transactions WHERE type = 'expense' AND occurred_on "
                                  "BETWEEN ? AND ?", (start.isoformat(), end.isoformat()))
            kpis.append(("Покупок", str(n_tx)))
        conv_rows = [(r, self._conv(r["amount_minor"], r["currency"], cur, date.fromisoformat(r["occurred_on"])) or 0)
                     for r in self._tx_rows(("expense",), start, end)]
        top = [(date.fromisoformat(r["occurred_on"]).strftime("%d.%m"), r["description"] or r["category"], v)
               for r, v in sorted(conv_rows, key=lambda x: -x[1])[:3]]
        rep = charts.Report(colors=self._category_colors([r.name for r in categories]), title=title, subtitle=subtitle, currency=cur, total=total, compare_label=compare_label,
                            compare_total=compare_total, income=income, kpis=kpis, categories=categories,
                            bars=bars, bars_title=bars_title, bar_reference=reference, top=top)
        png = charts.render_report(rep)
        # caption = the same numbers as text (works without seeing colors)
        lines = [f"📊 {title}: {fmt.money(total, cur)}"]
        if compare_total:
            pct = round((total - compare_total) * 100 / compare_total)
            lines[0] += f" ({'+' if pct > 0 else ''}{pct}% {compare_label})"
        lines += [f"{r.name} — {fmt.money(r.amount)} ({r.amount * 100 // max(total, 1)}%)" for r in categories[:5]]
        warn = self._fx_warning()
        if warn:
            lines.append(warn)
        buttons = [[(("• " if k == period else "") + v, f"st:{k}:{cur}") for k, v in self.PERIODS.items()],
                   self._currency_row(f"st:{period}:", cur)]
        if categories:
            buttons.append([("🔎 По категориям", f"sc:{period}:{cur}")])
        return Reply("\n".join(lines), buttons, photo=(f"report-{period}-{today.isoformat()}.png", png))

    # ------------------------------------------------------------ export
    def export(self) -> Reply:
        buf = io.BytesIO()
        tables = ["transactions", "tasks", "events", "reminders", "inbox", "notes", "payments", "reserves",
                  "category_limits", "settings"]
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for t in tables:
                rows = self.db.all(f"SELECT * FROM {t}")
                out = io.StringIO()
                if rows:
                    cols = rows[0].keys()
                    w = csv.writer(out)
                    w.writerow(cols)
                    for r in rows:
                        w.writerow([r[c] for c in cols])
                zf.writestr(f"{t}.csv", "﻿" + out.getvalue())
        name = f"personal-os-export-{self.today().isoformat()}.zip"
        return Reply("📦 Экспорт: CSV по каждой таблице (открывается в Excel/Numbers). "
                     "Суммы в *_minor — в сотых (1850 = 18.50).", document=(name, buf.getvalue()))

    # ------------------------------------------------------------ callbacks
    def handle_callback(self, data: str) -> Reply:
        parts = data.split(":")
        head = parts[0]
        try:
            if head == "u":
                r = self.undo(int(parts[1]))
                r.edit = True
                return r
            if head == "tx":
                return self._cb_tx(parts)
            if head == "t":
                return self._cb_task(parts)
            if head == "tasks":
                return self.view_tasks(show_all=True)
            if head == "r":
                if parts[1] == "d":
                    return self._reminder_done(int(parts[2]))
                if parts[1] == "z":
                    return self._reminder_snooze(int(parts[2]), parts[3])
            if head == "ev" and parts[1] == "x":
                return self._delete_event(int(parts[2]))
            if head == "cal":
                r = self.view_calendar(int(parts[1]))
                r.edit = True
                return r
            if head == "ib":
                return self._inbox_convert(int(parts[1]), parts[2])
            if head == "ch":
                return self._cb_choice(parts[1], parts[2])
            if head == "set":
                return self._cb_settings(parts)
            if head == "cap":
                return self._cb_capital(parts)
            if head == "acc":
                if parts[1] == "x":
                    return self.delete_account(int(parts[2]))
                r = self.account_card(int(parts[1]), parts[2] if len(parts) > 2 else None)
                r.edit = True
                return r
            if head == "fx":
                if parts[1] == "v":
                    return self.view_rates()
                return self._cb_fx(parts)
            if head == "sc":
                return self.category_drill(parts[1], parts[2], int(parts[3]) if len(parts) > 3 else None)
            if head == "st":
                r = self.analytics(parts[1], parts[2] if len(parts) > 2 else None)
                r.edit = True
                return r
            if head == "pay":
                return self._pay_payment(int(parts[1]))
            if head == "money":
                if parts[1] == "recent":
                    return self.view_recent_tx()
                if parts[1] == "c":
                    with self.db.tx():
                        self.db.set_setting("report_currency", parts[2])
                    r = self.view_money(parts[2])
                    r.edit = True
                    return r
                return Reply(self.MONEY_HELP)
            if head == "menu":
                return {"today": self.view_today, "tasks": self.view_tasks, "money": self.view_money,
                        "calendar": self.view_calendar, "inbox": self.view_inbox}[parts[1]]()
        except Exception:
            log.exception("callback %s failed", data)
            return Reply("⚠️ Не получилось выполнить действие. Изменения не сохранены.")
        return Reply("Кнопка устарела.", toast="Кнопка устарела")

    def _cb_capital(self, parts: list[str]) -> Reply:
        arg = parts[1] if len(parts) > 1 else ""
        if arg == "help":
            return Reply(CAPITAL_HELP, html=True)
        if arg == "img":
            return self.capital_image(parts[2] if len(parts) > 2 else None)
        if arg == "ref":
            res = self.refresh_market(force=True)
            r = self.view_capital(parts[2] if len(parts) > 2 else None)
            failed = res["prices_failed"]
            r.toast = "Не удалось: " + ", ".join(failed) if failed else "Обновлено"
            r.edit = True
            return r
        r = self.view_capital(arg or None)
        r.edit = bool(arg)
        return r

    def _cb_tx(self, parts: list[str]) -> Reply:
        op, tx_id = parts[1], int(parts[2])
        tx = self.db.get("transactions", tx_id)
        if tx is None:
            return Reply("Запись не найдена (возможно, отменена).", edit=True)
        if op == "e":
            return Reply(f"Изменить: {self._tx_line(tx)}", [
                [("Сумма", f"tx:a:{tx_id}"), ("Категория", f"tx:c:{tx_id}")],
                [("Тип: расход/доход", f"tx:t:{tx_id}"), ("🗑 Удалить", f"tx:d:{tx_id}")],
            ], edit=True)
        if op == "a":
            self._set_pending("tx_amount", id=tx_id)
            return Reply(f"Новая сумма для «{self._tx_line(tx)}»? Напишите числом.")
        if op == "c":
            cats = self._categories_ordered()
            rows = [[(c, f"tx:sc:{tx_id}:{CATEGORIES.index(c)}") for c in cats[i:i + 3]] for i in range(0, len(cats), 3)]
            return Reply(f"Категория для «{self._tx_line(tx)}»:", rows, edit=True)
        if op == "sc":
            return self._set_tx_category(tx_id, CATEGORIES[int(parts[3])])
        if op == "t":
            order = ["expense", "income", "refund", "transfer"]
            new_type = order[(order.index(tx["type"]) + 1) % len(order)]
            with self.db.tx():
                upd = self._update("transactions", tx_id, {"type": new_type})
                aid = self._action("смена типа операции", updated=[upd])
            tx = self.db.get("transactions", tx_id)
            return Reply(f"Тип изменён: {self._tx_line(tx)}",
                         [[("Отменить", f"u:{aid}"), ("Ещё раз сменить тип", f"tx:t:{tx_id}")]], edit=True)
        if op == "d":
            with self.db.tx():
                self.db.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
                aid = self._action("удаление операции", deleted=[("transactions", tx)])
            return Reply(f"🗑 Удалено: {self._tx_line(tx)}", [[("Отменить", f"u:{aid}")]], edit=True)
        return Reply("?")

    def _cb_task(self, parts: list[str]) -> Reply:
        op, tid = parts[1], int(parts[2])
        if op == "all":
            return self.move_open_to_tomorrow()
        if op == "o":
            r = self.task_card(tid)
            r.edit = False
            return r
        if op == "s":
            status = {"d": "done", "p": "in_progress", "w": "waiting", "c": "cancelled", "n": "new"}[parts[3]]
            r = self._set_task_status(tid, status)
            r.edit = True
            return r
        if op == "x":
            return self._delete_task(tid)
        if op == "e":
            self._set_pending("task_title", id=tid)
            return Reply("Напишите новый текст задачи.")
        if op == "r":
            return Reply("Перенести на:", [
                [("Сегодня", f"t:rd:{tid}:0"), ("Завтра", f"t:rd:{tid}:1"), ("Через неделю", f"t:rd:{tid}:7")],
                [("Без срока", f"t:rd:{tid}:n"), ("Ввести дату", f"t:rd:{tid}:ask")],
            ], edit=True)
        if op == "rd":
            code = parts[3]
            task = self.db.get("tasks", tid)
            if task is None:
                return Reply("Задача не найдена.", edit=True)
            if code == "ask":
                self._set_pending("task_due", id=tid)
                return Reply("Когда? Например «в пятницу в 15:00» или «20 октября».")
            if code == "n":
                r = self._reschedule_task(tid, None, None)
            else:
                d = self.today() + timedelta(days=int(code))
                t = self.local_of(task["due_at"]).time() if task["due_at"] else None
                r = self._reschedule_task(tid, d, t)
            r.edit = True
            return r
        return Reply("?")

    def _cb_choice(self, key: str, opt: str) -> Reply:
        payload = self.db.kv_get(f"ch:{key}", self.now_utc())
        if payload is None:
            return Reply("Вопрос устарел — отправьте сообщение ещё раз.", edit=True)
        self.db.kv_del(f"ch:{key}")
        kind = payload["kind"]
        if opt == "x":
            self._clear_pending()
            return Reply("Ок, не записываю.", edit=True)
        if kind == "save_money":
            if opt == "0":
                return Reply("Ок, не записываю повтор.", edit=True)
            items = [MoneyItem.from_json(i) for i in payload["items"]]
            r = self._save_money(items, payload.get("msg"), skip_dup=True)
        elif kind == "amount":
            chosen = Decimal(payload["candidates"][int(opt)])
            item = nlp.money_item_with_amount(payload["text"], chosen, self.now_local(), self.currency, self._memory())
            r = self._save_money([item], payload.get("msg"), skip_dup=True)
        elif kind == "date":
            chosen = date.fromisoformat(payload["dates"][int(opt)])
            r = self._process(payload["text"], payload.get("msg"), tomorrow_date=chosen)
        elif kind == "rate":
            r = self._set_manual_rate(payload["from"], opt, Decimal(payload["value"]))
        elif kind == "when":
            self._clear_pending()
            r = self._remind_from_choice(payload["title"], opt, payload.get("msg"))
        else:
            return Reply("?")
        r.edit = True
        return r

    def _cb_settings(self, parts: list[str]) -> Reply:
        op = parts[1]
        if op == "tog":
            key = parts[2]
            with self.db.tx():
                self.db.set_setting(key, "0" if self.db.get_setting(key) == "1" else "1")
            return Reply(self.settings_text(), self.settings_buttons(), edit=True)
        if op == "ask":
            key = parts[2]
            self._set_pending("setting", key=key)
            return Reply(self.SETTING_PROMPTS[key] + "\n(«отмена» — выйти)")
        if op == "list":
            return self._settings_list()
        if op in ("delp", "delr", "dell"):
            with self.db.tx():
                if op == "dell":
                    cat = CATEGORIES[int(parts[2])]
                    self.db.execute("DELETE FROM category_limits WHERE category = ?", (cat,))
                    return Reply(f"Лимит «{cat}» удалён.", edit=True)
                table = "payments" if op == "delp" else "reserves"
                row = self.db.get(table, int(parts[2]))
                if row is None:
                    return Reply("Уже удалено.", edit=True)
                self.db.execute(f"DELETE FROM {table} WHERE id = ?", (row["id"],))
                aid = self._action(f"удаление «{row['name']}»", deleted=[(table, row)])
            return Reply(f"🗑 Удалено: {row['name']}", [[("Отменить", f"u:{aid}")]], edit=True)
        return Reply("?")

    # ------------------------------------------------------------ scheduled notifications
    def collect_due(self) -> list[Notification]:
        """Everything that should be sent now. Mark as sent only after successful delivery."""
        out: list[Notification] = []
        now_utc = self.now_utc()
        rows = [dict(r) for r in self.db.all(
            "SELECT * FROM reminders WHERE status = 'active' AND remind_at <= ? ORDER BY remind_at",
            (fmt_utc(now_utc),))]
        due = []
        for r in rows:
            if r["task_id"]:
                task = self.db.get("tasks", r["task_id"])
                if task is None or task["status"] in ("done", "cancelled"):
                    self.db.update("reminders", r["id"], {"status": "cancelled"})
                    continue
            due.append(r)
        if due:
            out.append(Notification(self._reminders_message(due), lambda ids=[r["id"] for r in due]: self._mark_fired(ids)))
        local = self.now_local()
        today = local.date().isoformat()
        for kind in ("morning", "evening"):
            if self.db.get_setting(f"{kind}_last") == today:
                continue
            at = datetime.combine(local.date(), self._setting_time(f"{kind}_time"))
            if local < at:
                continue
            window = timedelta(hours=4 if kind == "morning" else 3)
            if self.db.get_setting(f"{kind}_enabled") != "1" or local > at + window:
                self.db.set_setting(f"{kind}_last", today)  # missed or disabled: skip silently
                continue
            reply = self.morning_digest() if kind == "morning" else self.evening_digest()
            out.append(Notification(reply, lambda k=kind, d=today: self.db.set_setting(f"{k}_last", d)))
        month = local.date().strftime("%Y-%m")
        if (local.date().day == 1 and self.db.get_setting("monthly_report") == "1"
                and self.db.get_setting("monthly_report_last") != month
                and local.time() >= self._setting_time("morning_time")):
            has_data = self.db.scalar("SELECT 1 FROM transactions WHERE occurred_on >= ? AND occurred_on < ? LIMIT 1",
                                      (add_months(local.date(), -1, 1).isoformat(), local.date().isoformat()))
            if has_data:
                rep = self.analytics("pm")
                rep.text = "📊 Итоги прошлого месяца\n" + rep.text
                out.append(Notification(rep, lambda m=month: self.db.set_setting("monthly_report_last", m)))
            else:
                self.db.set_setting("monthly_report_last", month)
        return out

    def _reminders_message(self, due: list[dict]) -> Reply:
        now_utc = self.now_utc()

        def late(r):
            at = parse_utc(r["remind_at"]).replace(tzinfo=None)
            if now_utc - at > timedelta(minutes=30):
                return f" (было {fmt.when(self.to_local(at).date(), self.to_local(at).time(), self.today())})"
            return ""

        if len(due) == 1:
            r = due[0]
            rid = r["id"]
            return Reply(f"🔔 {r['text']}{late(r)}", [[("✅ Готово", f"r:d:{rid}"), ("⏰ +1 ч", f"r:z:{rid}:60"),
                                                       ("Завтра", f"r:z:{rid}:tm")]])
        lines = ["🔔 Напоминания:"]
        rows: Buttons = []
        for n, r in enumerate(due, 1):
            lines.append(f"{n}. {r['text']}{late(r)}")
            if n <= 8:
                rows.append([(f"✅ {n}", f"r:d:{r['id']}"), (f"⏰ {n} +1 ч", f"r:z:{r['id']}:60"),
                             (f"{n} завтра", f"r:z:{r['id']}:tm")])
        return Reply("\n".join(lines), rows)

    def _mark_fired(self, ids: list[int]) -> None:
        now_utc = self.now_utc()
        with self.db.tx():
            for rid in ids:
                r = self.db.get("reminders", rid)
                if r is None or r["status"] != "active":
                    continue
                if r["recurrence"]:
                    local = self.local_of(r["remind_at"])
                    if r["local_time"]:
                        h, m = map(int, r["local_time"].split(":"))
                        local = local.replace(hour=h, minute=m)
                    while self.to_utc(local) <= now_utc:
                        local = timeparse.next_occurrence(local, r["recurrence"], r["rec_day"])
                    self.db.update("reminders", rid, {"remind_at": fmt_utc(self.to_utc(local)), "pending_ack": 1,
                                                      "last_fired_at": fmt_utc(now_utc)})
                else:
                    self.db.update("reminders", rid, {"status": "fired", "last_fired_at": fmt_utc(now_utc)})

    def morning_digest(self) -> Reply:
        today = self.today()
        lines = [f"☀️ Доброе утро! {fmt.cap(fmt.day(today))}"]
        tasks = [t for t in self._open_tasks() if t["due_date"] == today.isoformat()]
        overdue = [t for t in self._open_tasks() if t["due_date"] and t["due_date"] < today.isoformat()]
        events = self._events_between(today, today)
        soon = [t for t in self._open_tasks() if t["due_date"] and t["is_deadline"]
                and today.isoformat() < t["due_date"] <= (today + timedelta(days=3)).isoformat()]
        if events:
            lines.append("\nСобытия:")
            lines += [f"• {self._event_when(e, with_date=False)} {e['title']}" for e in events]
        if tasks:
            lines.append("\nЗадачи на сегодня:")
            lines += [f"• {self._task_line(t)}" for t in tasks]
        if overdue:
            lines.append("\n⚠️ Просрочено:")
            lines += [f"• {self._task_line(t)}" for t in overdue]
        pending = self._pending_reminders()
        if pending:
            lines.append("\nЖдут ответа:")
            lines += [f"• 🔔 {r['text']}" for r in pending]
        if soon:
            lines.append("\nБлижайшие дедлайны:")
            lines += [f"• {self._task_line(t)}" for t in soon]
        pays = self._payments_soon(3)
        if pays:
            lines.append("\nПлатежи:")
            lines += [f"• {p['name']} — {fmt.money(p['amount_minor'], p['currency'])}, {fmt.day(d, today)}"
                      for p, d in pays]
        if len(lines) == 1:
            lines.append("На сегодня ничего не запланировано.")
        allowance = self.daily_allowance()
        if allowance is not None:
            lines.append(f"\n💸 Можно тратить сегодня: {fmt.money(allowance, self.currency)}")
        buttons = [[(f"💳 Оплачено: {fmt.short(p['name'], 20)}", f"pay:{p['id']}")] for p, d in pays if d <= today]
        buttons.append([("📅 Сегодня", "menu:today"), ("✅ Задачи", "menu:tasks")])
        return Reply("\n".join(lines), buttons)

    def evening_digest(self) -> Reply:
        today = self.today()
        start_utc = fmt_utc(self.to_utc(datetime.combine(today, time(0, 0))))
        done = self.db.all("SELECT * FROM tasks WHERE status = 'done' AND done_at >= ?", (start_utc,))
        open_today = [t for t in self._open_tasks() if t["due_date"] and t["due_date"] <= today.isoformat()]
        spent = self._net_expense(today, today, self.currency)
        n_tx = self.db.scalar("SELECT COUNT(*) FROM transactions WHERE occurred_on = ? AND type = 'expense'",
                              (today.isoformat(),))
        tomorrow = today + timedelta(days=1)
        events = self._events_between(tomorrow, tomorrow)
        lines = ["🌙 Итоги дня"]
        lines.append(f"\nСделано: {len(done)}" + ("" if not done else "\n" + "\n".join(f"✅ {t['title']}" for t in done)))
        if open_today:
            lines.append(f"\nНе сделано: {len(open_today)}")
            lines += [f"• {self._task_line(t)}" for t in open_today]
        if n_tx:
            lines.append(f"\n💸 Расходы за день: {fmt.money(spent, self.currency)} ({n_tx} зап.)")
        else:
            lines.append("\n💸 Расходов сегодня не записано. Точно ничего не тратили? "
                         "Если были — просто напишите, например «такси 25».")
        if events:
            lines.append("\nЗавтра:")
            lines += [f"• {self._event_when(e, with_date=False)} {e['title']}" for e in events]
        buttons = []
        if open_today:
            buttons.append([("Перенести незавершённое на завтра", "t:all:0:tom")])
        return Reply("\n".join(lines), buttons)

    def move_open_to_tomorrow(self) -> Reply:
        today = self.today()
        tomorrow = today + timedelta(days=1)
        tasks = [t for t in self._open_tasks() if t["due_date"] and t["due_date"] <= today.isoformat()]
        if not tasks:
            return Reply("Переносить нечего.", edit=True)
        with self.db.tx():
            updated, created = [], []
            for t in tasks:
                due_at = None
                if t["due_at"]:
                    loc = self.local_of(t["due_at"])
                    due_local = datetime.combine(tomorrow, loc.time())
                    due_at = fmt_utc(self.to_utc(due_local))
                    for r in self.db.all("SELECT id FROM reminders WHERE task_id = ? AND status IN ('active','fired')",
                                         (t["id"],)):
                        updated.append(self._update("reminders", r["id"], {"status": "cancelled"}))
                    created.append(("reminders", self._insert_reminder(t["title"], self.to_utc(due_local),
                                                                       task_id=t["id"])))
                updated.append(self._update("tasks", t["id"], {"due_date": tomorrow.isoformat(), "due_at": due_at,
                                                               "updated_at": fmt_utc(self.now_utc())}))
            aid = self._action(f"перенос {len(tasks)} задач на завтра", created=created, updated=updated)
        return Reply(f"Перенёс на завтра: {len(tasks)}", [[("Отменить", f"u:{aid}")]], edit=True)

"""Telegram layer (aiogram 3, long polling). Thin: all logic lives in ``service.Service``."""
from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import date

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.types import (BotCommand, BufferedInputFile, CallbackQuery, FSInputFile, InlineKeyboardButton,
                           InlineKeyboardMarkup, InputMediaPhoto, KeyboardButton, MenuButtonWebApp, Message,
                           ReplyKeyboardMarkup, WebAppInfo)

from .backup import make_backup
from .config import Config
from .service import Reply, Service

log = logging.getLogger(__name__)

MENU = {"📅 Сегодня": "today", "✅ Задачи": "tasks", "💰 Деньги": "money", "🗓 Календарь": "calendar",
        "📥 Inbox": "inbox"}
MENU_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="✅ Задачи"), KeyboardButton(text="💰 Деньги")],
              [KeyboardButton(text="🗓 Календарь"), KeyboardButton(text="📥 Inbox")]],
    resize_keyboard=True, is_persistent=True, input_field_placeholder="Кофе 18 · Завтра в 11 позвонить…")

COMMANDS = [
    BotCommand(command="today", description="Дела на сегодня"),
    BotCommand(command="tasks", description="Задачи"),
    BotCommand(command="money", description="Финансовая сводка"),
    BotCommand(command="stats", description="Аналитика картинкой"),
    BotCommand(command="capital", description="Капитал: счета и инвестиции"),
    BotCommand(command="rates", description="Курсы валют"),
    BotCommand(command="calendar", description="Календарь"),
    BotCommand(command="inbox", description="Неразобранное"),
    BotCommand(command="settings", description="Настройки"),
    BotCommand(command="undo", description="Отменить последнее действие"),
    BotCommand(command="export", description="Экспорт данных (CSV)"),
    BotCommand(command="backup", description="Резервная копия базы в чат"),
    BotCommand(command="help", description="Примеры"),
]

HELP = """<b>Пишите обычным текстом — я разберусь.</b>

💸 <b>Деньги</b>
«Кофе 18» · «Такси 25, продукты 60» · «такси 5000 тенге» · «Получил зарплату 6500»

✅ <b>Задачи и напоминания</b>
«Завтра в 11 позвонить преподавателю» · «До пятницы закончить презентацию»
«Напомни оплатить интернет первого числа» · «Купил продукты» — закрою задачу

🗓 <b>Календарь</b>
«В четверг пара в 8:30» · «Смена с 22 до 6 в субботу»

💼 <b>Капитал и валюты</b>
«Закинул 50к тенге на брокерский, вышло 110$» · «Купил 2 AAPL по 55$»
«Обменял 100$ на 51 200 тенге» · «Курс доллара 512 тенге» · /capital · /rates

📊 /stats — отчёт картинкой: неделя, месяц, полгода, в AED / USD / KZT

Исправить — кнопка «Изменить», «не 18, а 20» или отредактируйте сообщение. Отменить — «Отменить» или /undo.
🤖 С бесплатным AI понимаю ещё SMS банка, длинные фразы и фото чеков."""

TG_LIMIT = 4000


# "@webapp" / "@webapp:cap" button data is replaced by a Mini App link with fresh data
WEBAPP_LINK = None   # callable(tab) -> url | None, set in run()


def _button(text: str, data: str) -> InlineKeyboardButton | None:
    if data.startswith("@webapp"):
        tab = data.partition(":")[2]
        u = WEBAPP_LINK(tab) if WEBAPP_LINK else None
        return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=u)) if u else None
    return InlineKeyboardButton(text=text, callback_data=data)


def keyboard(reply: Reply) -> InlineKeyboardMarkup | None:
    rows = [[b for b in (_button(t, d) for t, d in row) if b] for row in reply.buttons if row]
    rows = [r for r in rows if r]
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def without_webapp(reply: Reply) -> bool:
    """Drop Mini App buttons (e.g. Telegram rejected the link). Returns True if something was dropped."""
    before = sum(len(r) for r in reply.buttons)
    reply.buttons = [[b for b in row if not b[1].startswith("@webapp")] for row in reply.buttons]
    return sum(len(r) for r in reply.buttons) != before


def chunks(text: str) -> list[str]:
    if len(text) <= TG_LIMIT:
        return [text]
    out, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > TG_LIMIT:
            out.append(cur)
            cur = ""
        cur += line + "\n"
    if cur:
        out.append(cur)
    return out


def strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def mode(reply: Reply) -> str | None:
    return "HTML" if reply.html else None


async def send(bot: Bot, chat_id: int, reply: Reply) -> None:
    try:
        await _send(bot, chat_id, reply)
    except TelegramBadRequest as e:
        if without_webapp(reply):
            log.warning("message with Mini App button rejected (%s), sending without it", e)
            await send(bot, chat_id, reply)
        elif reply.html and "parse" in str(e).lower():
            log.warning("HTML rejected (%s), sending as plain text", e)
            reply.text, reply.html = strip_html(reply.text), False
            await _send(bot, chat_id, reply)
        else:
            raise


async def _send(bot: Bot, chat_id: int, reply: Reply) -> None:
    if reply.photo:
        name, data = reply.photo
        await bot.send_photo(chat_id, BufferedInputFile(data, filename=name), caption=reply.text[:1000],
                             reply_markup=keyboard(reply), parse_mode=mode(reply))
        return
    if reply.document:
        name, data = reply.document
        await bot.send_document(chat_id, BufferedInputFile(data, filename=name), caption=reply.text[:1000],
                                parse_mode=mode(reply))
        return
    parts = chunks(reply.text)
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        markup = keyboard(reply) if last else None
        if last and markup is None and reply.show_menu:
            markup = MENU_KB
        await bot.send_message(chat_id, part, reply_markup=markup, parse_mode=mode(reply))


class OwnerOnly(BaseMiddleware):
    """Drop every update that does not come from the owner. Strangers get no answer at all."""

    def __init__(self, owner_id: int):
        self.owner_id = owner_id

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user is None or user.id != self.owner_id:
            log.warning("ignored update from foreign user %s", getattr(user, "id", None))
            return None
        return await handler(event, data)


def build_router(service: Service, cfg: Config) -> Router:
    r = Router()

    async def answer(message: Message, reply: Reply | None) -> None:
        if reply is not None:
            await send(message.bot, message.chat.id, reply)

    @r.message(CommandStart())
    async def start(message: Message):
        await message.answer(
            "🧭 <b>Привет! Я Kompas</b> — ваш личный помощник: деньги, задачи, напоминания, календарь и капитал.\n\n"
            + HELP + f"\n\n<i>Сейчас: валюта {service.currency}, отчёты в {service.report_currency}, "
            f"часовой пояс {service.tz.key}. Изменить — /settings.</i>", reply_markup=MENU_KB, parse_mode="HTML")

    @r.message(Command("help"))
    async def help_(message: Message):
        await message.answer(HELP, reply_markup=MENU_KB, parse_mode="HTML")

    views = {
        "today": service.view_today, "tasks": service.view_tasks, "money": service.view_money,
        "calendar": service.view_calendar, "inbox": service.view_inbox, "settings": service.view_settings,
        "undo": service.undo, "export": service.export, "capital": service.view_capital, "rates": service.view_rates,
    }

    for name, fn in views.items():
        def make(fn=fn):
            async def h(message: Message):
                await answer(message, fn())
            return h
        r.message(Command(name))(make())

    @r.message(Command("backup"))
    async def backup_cmd(message: Message):
        path = await asyncio.to_thread(make_backup, cfg.db_path, cfg.backup_dir, cfg.backup_keep)
        await message.answer_document(FSInputFile(path), caption="💾 Резервная копия базы. Храните её в «Избранном».")

    @r.message(F.text.in_(MENU.keys()))
    async def menu(message: Message):
        await answer(message, views[MENU[message.text]]())

    @r.message(Command("stats"))
    async def stats(message: Message):
        await message.bot.send_chat_action(message.chat.id, "upload_photo")
        await answer(message, await asyncio.to_thread(service.analytics, "m"))

    @r.message(F.text)
    async def text(message: Message):
        # worker thread: a slow AI request must not block reminders or other updates
        await answer(message, await asyncio.to_thread(service.process_text, message.text, message.message_id))

    async def image_message(message: Message, file_id: str, mime: str = "image/jpeg"):
        await message.bot.send_chat_action(message.chat.id, "typing")
        buf = await message.bot.download(file_id)
        reply = await asyncio.to_thread(service.process_photo, buf.read(), message.caption or "", message.message_id)
        await answer(message, reply)

    @r.message(F.photo)
    async def photo(message: Message):
        await image_message(message, message.photo[-1].file_id)

    @r.message(F.document.mime_type.startswith("image/"))
    async def image_file(message: Message):
        await image_message(message, message.document.file_id, message.document.mime_type)

    @r.edited_message(F.text)
    async def edited(message: Message):
        reply = await asyncio.to_thread(service.process_edit, message.text, message.message_id)
        if reply is None:
            reply = Reply("Изменение получено, но это сообщение ничего не создавало — "
                          "отправьте исправленный текст новым сообщением.")
        await answer(message, reply)

    @r.message()
    async def other(message: Message):
        await message.answer("Я понимаю текст и фото. Голосовые и другие файлы не обрабатываю.")

    @r.callback_query()
    async def callback(cb: CallbackQuery):
        reply = await asyncio.to_thread(service.handle_callback, cb.data or "")
        try:
            await cb.answer(reply.toast or None)
        except TelegramBadRequest:
            pass  # callback too old
        if cb.message is None:
            return
        if reply.edit and reply.photo and cb.message.photo:
            name, data = reply.photo
            try:
                await cb.message.edit_media(
                    InputMediaPhoto(media=BufferedInputFile(data, filename=name), caption=reply.text[:1000],
                                    parse_mode=mode(reply)),
                    reply_markup=keyboard(reply))
                return
            except TelegramBadRequest as e:
                log.info("edit_media failed (%s), sending new photo", e)
        elif reply.edit and not reply.document and not reply.photo:
            try:
                await cb.message.edit_text(reply.text[:TG_LIMIT], reply_markup=keyboard(reply), parse_mode=mode(reply))
                return
            except TelegramBadRequest as e:
                if "not modified" in str(e):
                    return
                log.info("edit failed (%s), sending new message", e)
        await send(cb.bot, cb.message.chat.id, reply)

    return r


async def scheduler_loop(bot: Bot, service: Service, cfg: Config, interval: float = 20.0) -> None:
    """Checks reminders/digests every ``interval`` seconds. State lives in SQLite, so restarts lose nothing."""
    chat_id = cfg.owner_id
    loop = asyncio.get_running_loop()
    while True:
        try:
            for n in service.collect_due():
                try:
                    await send(bot, chat_id, n.reply)
                except TelegramRetryAfter as e:
                    log.warning("flood control, retry in %s s", e.retry_after)
                    await asyncio.sleep(e.retry_after)
                    break
                except TelegramNetworkError:
                    log.warning("network error while sending notification, will retry")
                    break
                n.on_sent()  # only after the message really left
            await update_menu_button(bot, service, cfg)
            if not hasattr(scheduler_loop, "market_at") or loop.time() - scheduler_loop.market_at > 3600:
                scheduler_loop.market_at = loop.time()
                await asyncio.to_thread(service.refresh_market)
            today = date.today().isoformat()
            if service.db.get_setting("backup_last") != today:
                path = await asyncio.to_thread(make_backup, cfg.db_path, cfg.backup_dir, cfg.backup_keep)
                service.db.set_setting("backup_last", today)
                log.info("daily backup: %s", path)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(interval)


_menu_state = {"version": None, "at": 0.0, "max": None}


def data_version(service: Service) -> tuple:
    q = service.db.scalar
    return (service.today().isoformat(), q("SELECT MAX(id) FROM actions"), q("SELECT COUNT(*) FROM actions WHERE undone=1"),
            service.db.get_setting("rates_fetched_on"), service.db.get_setting("prices_fetched_at"),
            service.report_currency)


async def update_menu_button(bot: Bot, service: Service, cfg: Config) -> None:
    """Keep the "Открыть" button next to the input field pointing at fresh data (at most once a minute)."""
    if not cfg.webapp_url:
        return
    from . import webapp

    loop = asyncio.get_running_loop()
    version = data_version(service)
    if version == _menu_state["version"] or loop.time() - _menu_state["at"] < 60:
        return
    _menu_state["at"] = loop.time()
    limit = _menu_state["max"] or cfg.webapp_max_url
    try:
        url = webapp.url(service, cfg.webapp_url, limit)
        await bot.set_chat_menu_button(chat_id=cfg.owner_id, menu_button=MenuButtonWebApp(
            text="Kompas", web_app=WebAppInfo(url=url)))
        _menu_state["version"] = version
    except TelegramBadRequest as e:
        _menu_state["max"] = max(1500, limit // 2)   # link too long? try a shorter one next minute
        log.warning("menu button update failed (%s), next try with max %s chars", e, _menu_state["max"])


async def run_setup_mode(bot: Bot) -> None:
    """OWNER_ID is not set yet: tell whoever writes their id, store nothing."""
    dp = Dispatcher()

    @dp.message()
    async def who(message: Message):
        uid = message.from_user.id if message.from_user else "?"
        await message.answer(f"Ваш Telegram ID: {uid}\nВпишите OWNER_ID={uid} в файл .env и перезапустите бота.")

    log.warning("OWNER_ID is not set: running in setup mode (bot only reports user ids)")
    await dp.start_polling(bot)


async def run(cfg: Config, service: Service) -> None:
    bot = Bot(cfg.bot_token)
    if cfg.owner_id is None:
        await run_setup_mode(bot)
        return
    dp = Dispatcher()
    dp.update.outer_middleware(OwnerOnly(cfg.owner_id))
    dp.include_router(build_router(service, cfg))
    if cfg.webapp_url:
        from . import webapp

        global WEBAPP_LINK
        service.webapp_on = True
        WEBAPP_LINK = lambda tab: webapp.url(service, cfg.webapp_url, _menu_state["max"] or cfg.webapp_max_url) \
            + (f"&tab={tab}" if tab else "")  # noqa: E731
    await bot.set_my_commands(COMMANDS)
    task = asyncio.create_task(scheduler_loop(bot, service, cfg))
    try:
        await dp.start_polling(bot, allowed_updates=["message", "edited_message", "callback_query"])
    finally:
        task.cancel()
        await bot.session.close()

"""Telegram layer (aiogram 3, long polling). Thin: all logic lives in ``service.Service``."""
from __future__ import annotations

import asyncio
import logging
from datetime import date

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.types import (BotCommand, BufferedInputFile, CallbackQuery, FSInputFile, InlineKeyboardButton,
                           InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup)

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
    BotCommand(command="calendar", description="Календарь"),
    BotCommand(command="inbox", description="Неразобранное"),
    BotCommand(command="settings", description="Настройки"),
    BotCommand(command="undo", description="Отменить последнее действие"),
    BotCommand(command="export", description="Экспорт данных (CSV)"),
    BotCommand(command="backup", description="Резервная копия базы в чат"),
    BotCommand(command="help", description="Примеры"),
]

HELP = """Пишите обычным текстом — я разберусь:

💸 «Кофе 18» · «Такси 25, продукты 60» · «Получил зарплату 6500» · «вчера обед 45»
✅ «Завтра купить продукты» · «До пятницы закончить презентацию»
🔔 «Завтра в 11 позвонить преподавателю» · «Напомни оплатить интернет первого числа»
🗓 «В четверг пара в 8:30» · «Смена с 22 до 6 в субботу»
☑️ «Купил продукты» — закрою подходящую задачу
📝 «Заметка: …» — просто заметка

Исправить: кнопка «Изменить», «не 18, а 20» или отредактируйте своё сообщение.
Отменить: кнопка «Отменить» или /undo.
Деньги до зарплаты: «остаток 2400», «день зарплаты 25», «платёж интернет 300 1», «бюджет 3000»."""

TG_LIMIT = 4000


def keyboard(reply: Reply) -> InlineKeyboardMarkup | None:
    if not reply.buttons:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in reply.buttons if row])


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


async def send(bot: Bot, chat_id: int, reply: Reply) -> None:
    if reply.document:
        name, data = reply.document
        await bot.send_document(chat_id, BufferedInputFile(data, filename=name), caption=reply.text[:1000])
        return
    parts = chunks(reply.text)
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        markup = keyboard(reply) if last else None
        if last and markup is None and reply.show_menu:
            markup = MENU_KB
        await bot.send_message(chat_id, part, reply_markup=markup)


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
            "Привет! Я Personal OS — ваш личный помощник: задачи, деньги, напоминания и календарь.\n\n"
            + HELP + f"\n\nСейчас: валюта {service.currency}, часовой пояс {service.tz.key}. Изменить — /settings.",
            reply_markup=MENU_KB)

    @r.message(Command("help"))
    async def help_(message: Message):
        await message.answer(HELP, reply_markup=MENU_KB)

    views = {
        "today": service.view_today, "tasks": service.view_tasks, "money": service.view_money,
        "calendar": service.view_calendar, "inbox": service.view_inbox, "settings": service.view_settings,
        "undo": service.undo, "export": service.export,
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

    @r.message(F.text)
    async def text(message: Message):
        await answer(message, service.process_text(message.text, message.message_id))

    @r.edited_message(F.text)
    async def edited(message: Message):
        reply = service.process_edit(message.text, message.message_id)
        if reply is None:
            reply = Reply("Изменение получено, но это сообщение ничего не создавало — "
                          "отправьте исправленный текст новым сообщением.")
        await answer(message, reply)

    @r.message(F.caption)
    async def caption(message: Message):
        await answer(message, service.process_text(message.caption, message.message_id))

    @r.message()
    async def other(message: Message):
        await message.answer("Я понимаю только текст. Голосовые и файлы не обрабатываю.")

    @r.callback_query()
    async def callback(cb: CallbackQuery):
        reply = service.handle_callback(cb.data or "")
        try:
            await cb.answer(reply.toast or None)
        except TelegramBadRequest:
            pass  # callback too old
        if cb.message is None:
            return
        if reply.edit and not reply.document:
            try:
                await cb.message.edit_text(reply.text[:TG_LIMIT], reply_markup=keyboard(reply))
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
    await bot.set_my_commands(COMMANDS)
    task = asyncio.create_task(scheduler_loop(bot, service, cfg))
    try:
        await dp.start_polling(bot, allowed_updates=["message", "edited_message", "callback_query"])
    finally:
        task.cancel()
        await bot.session.close()

"""Feeds real Telegram updates through the aiogram dispatcher with a fake HTTP session."""
import asyncio
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import Chat, Message, Update, User

from bot.config import Config
from bot.telegram_app import OwnerOnly, build_router

OWNER = 42


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, (SendMessage, EditMessageText)):
            return Message(message_id=999, date=datetime.now(), chat=Chat(id=OWNER, type="private"),
                           text=method.text)
        return True

    async def stream_content(self, *a, **k):  # pragma: no cover
        yield b""

    async def close(self):
        pass


def make(svc, tmp_path):
    cfg = Config("1:x", OWNER, tmp_path / "db", tmp_path / "b", 3, tmp_path / "l", "Asia/Dubai")
    session = FakeSession()
    bot = Bot("123456:ABCDEF", session=session)
    dp = Dispatcher()
    dp.update.outer_middleware(OwnerOnly(OWNER))
    dp.include_router(build_router(svc, cfg))
    return bot, dp, session


def msg_update(uid, text, message_id=1, update_id=1):
    return Update.model_validate({
        "update_id": update_id,
        "message": {"message_id": message_id, "date": 1760000000, "chat": {"id": uid, "type": "private"},
                    "from": {"id": uid, "is_bot": False, "first_name": "U"}, "text": text},
    })


def cb_update(uid, data, update_id=10):
    return Update.model_validate({
        "update_id": update_id,
        "callback_query": {"id": "cb1", "chat_instance": "x", "data": data,
                           "from": {"id": uid, "is_bot": False, "first_name": "U"},
                           "message": {"message_id": 5, "date": 1760000000, "chat": {"id": uid, "type": "private"},
                                       "from": {"id": 1, "is_bot": True, "first_name": "B"}, "text": "old"}},
    })


def test_full_flow(svc, tmp_path):
    bot, dp, session = make(svc, tmp_path)

    async def go():
        await dp.feed_update(bot, msg_update(OWNER, "/start", 1, 1))
        await dp.feed_update(bot, msg_update(OWNER, "Кофе 18", 2, 2))
        await dp.feed_update(bot, msg_update(OWNER, "💰 Деньги", 3, 3))
        await dp.feed_update(bot, msg_update(777, "Кофе 99", 4, 4))  # stranger
        await dp.feed_update(bot, cb_update(777, "u:1", 5))         # stranger presses a button
        aid = svc.db.scalar("SELECT id FROM actions")
        await dp.feed_update(bot, cb_update(OWNER, f"u:{aid}", 6))

    asyncio.run(go())
    sent = [c for c in session.calls if isinstance(c, SendMessage)]
    assert "Personal OS" in sent[0].text
    assert sent[1].text.startswith("Записал: −18 AED")
    assert sent[1].reply_markup.inline_keyboard[0][0].text == "Отменить"
    assert sent[2].text.startswith("💰 Деньги")
    assert all(c.chat_id == OWNER for c in sent)  # nothing went to the stranger
    edits = [c for c in session.calls if isinstance(c, EditMessageText)]
    assert edits and edits[0].text.startswith("↩️ Отменено")
    assert any(isinstance(c, AnswerCallbackQuery) for c in session.calls)
    assert svc.db.scalar("SELECT COUNT(*) FROM transactions") == 0

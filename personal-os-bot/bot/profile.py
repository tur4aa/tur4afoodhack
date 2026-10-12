"""Sets the bot's public name, descriptions and command list.

Usage:  python -m bot.profile            (needs BOT_TOKEN in .env)
The profile photo can't be set through the Bot API: send branding/avatar.png to @BotFather -> /setuserpic.
"""
from __future__ import annotations

import asyncio
import sys

NAME = "Kompas"
SHORT = "Личный помощник: расходы, задачи, напоминания, капитал. Пишите как другу — я разложу по полочкам."
DESCRIPTION = (
    "Kompas — ваш личный органайзер в Telegram.\n\n"
    "💸 «Кофе 18», «такси 5000 тенге» — запишу расход, посчитаю в AED, USD или KZT\n"
    "✅ «Завтра в 11 позвонить преподавателю» — задача и напоминание\n"
    "🗓 «В четверг пара в 8:30» — календарь\n"
    "💼 «Закинул 50к тенге на брокерский, вышло 110$», «купил 2 AAPL по 55$» — капитал и инвестиции\n"
    "📊 Красивая аналитика картинкой и в приложении\n\n"
    "Работает только для владельца. Данные хранятся у вас."
)


async def main() -> int:
    from aiogram import Bot

    from .config import load_config
    from .telegram_app import COMMANDS

    cfg = load_config()
    if not cfg.bot_token:
        print("BOT_TOKEN не задан")
        return 1
    bot = Bot(cfg.bot_token)
    try:
        await bot.set_my_name(NAME)
        await bot.set_my_short_description(SHORT)
        await bot.set_my_description(DESCRIPTION)
        await bot.set_my_commands(COMMANDS)
        print(f"Готово: имя «{NAME}», описания и команды обновлены.")
        print("Аватар: отправьте branding/avatar.png в @BotFather → /setuserpic.")
    finally:
        await bot.session.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

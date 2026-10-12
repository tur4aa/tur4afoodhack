"""Optional free AI for messages the rule-based parser could not understand (and for photos).

Works with any OpenAI-compatible chat endpoint; presets for free options:
  gemini - Google AI Studio key, free tier, understands photos
  groq   - free tier, very fast
  ollama - runs locally on your Mac, nothing leaves the computer
Only the message itself (and the photo, if you send one) is sent - never your database.

Check your setup:  python -m bot.ai "вчера такси 30 и купил лекарства на 85"
"""
from __future__ import annotations

import base64
import json
import logging
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta

log = logging.getLogger(__name__)

PRESETS = {
    # provider: (base_url, text model, vision model)
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-flash-latest", "gemini-flash-latest"),
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", "meta-llama/llama-4-scout-17b-16e-instruct"),
    "openrouter": ("https://openrouter.ai/api/v1", "meta-llama/llama-3.3-70b-instruct:free", ""),
    "ollama": ("http://localhost:11434/v1", "qwen2.5:7b", ""),
}

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]

ITEM_TYPES = {"expense", "income", "refund", "transfer", "task", "reminder", "event", "note"}

SYSTEM_PROMPT = """Ты — модуль разбора сообщений личного бота-органайзера. Пользователь пишет по-русски или по-английски, \
может переслать SMS банка, вставить список покупок, прислать фото чека или скриншот.
Верни ТОЛЬКО JSON-объект без пояснений:
{{"items": [ITEM, ...], "question": null}}
ITEM = {{
  "type": "expense" | "income" | "refund" | "transfer" | "task" | "reminder" | "event" | "note",
  "amount": число или null, "currency": "AED"/"USD"/... или null,
  "category": одна из [{categories}] или null,
  "description": "коротко, что это (2-4 слова)",
  "title": "текст задачи/напоминания/события" или null,
  "date": "YYYY-MM-DD" или null, "time": "HH:MM" или null,
  "end_date": "YYYY-MM-DD" или null, "end_time": "HH:MM" или null,
  "recurrence": "daily" | "weekly" | "monthly" | null,
  "deadline": true/false
}}
Правила:
- Сегодня {today}, {weekday}, сейчас {now}, часовой пояс {tz}. Валюта по умолчанию {currency}.
- НИКОГДА не выдумывай сумму. Сумма — только если она явно есть в тексте/на фото.
- В SMS банка сумма покупки — это сумма операции; остаток/баланс/лимит/номер карты — НЕ сумма.
- Покупка/оплата/списание → expense; зачисление/зарплата/перевод тебе → income; возврат → refund;
  перевод между своими счетами/снятие наличных → transfer.
- Чек: одна запись expense на ИТОГОВУЮ сумму чека, описание — магазин, категория по магазину.
- task — дело без конкретного времени; reminder — когда просят напомнить или есть точное время;
  event — встреча/пара/смена/приём с датой и временем. "до пятницы" → deadline true.
- Даты в прошлом допустимы только для операций с деньгами.
- Если сообщение — не данные (вопрос, болтовня) или ты не уверен, верни {{"items": [], "question": "короткий уточняющий вопрос"}}.
"""


class AIError(Exception):
    pass


@dataclass
class AIConfig:
    provider: str
    api_key: str
    base_url: str
    model: str
    vision_model: str
    timeout: float = 30.0

    @property
    def can_see_images(self) -> bool:
        return bool(self.vision_model)


def config_from_env(env: dict) -> AIConfig | None:
    provider = (env.get("AI_PROVIDER") or "").strip().lower()
    if not provider or provider in ("none", "off", "0"):
        return None
    base, model, vision = PRESETS.get(provider, ("", "", ""))
    base = (env.get("AI_BASE_URL") or base).rstrip("/")
    model = env.get("AI_MODEL") or model
    vision = env.get("AI_VISION_MODEL", vision)
    key = env.get("AI_API_KEY", "")
    if not base or not model:
        log.warning("AI_PROVIDER=%s needs AI_BASE_URL and AI_MODEL", provider)
        return None
    if provider != "ollama" and not key:
        log.warning("AI_PROVIDER=%s is set but AI_API_KEY is empty - AI disabled", provider)
        return None
    return AIConfig(provider, key, base, model, vision, float(env.get("AI_TIMEOUT", "30")))


class AIClient:
    def __init__(self, cfg: AIConfig):
        self.cfg = cfg

    # -- transport
    def _post(self, payload: dict) -> dict:
        req = urllib.request.Request(
            f"{self.cfg.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {self.cfg.api_key}"} if self.cfg.api_key else {})},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:500]
            if e.code == 429:
                raise AIError("лимит бесплатных запросов исчерпан, попробуйте позже") from e
            if e.code in (401, 403):
                raise AIError("ключ AI не подходит (проверьте AI_API_KEY)") from e
            if e.code == 404:
                raise AIError(f"модель {payload.get('model')} не найдена — укажите AI_MODEL") from e
            raise AIError(f"HTTP {e.code}: {body}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise AIError(f"нет связи с AI: {e}") from e

    def _chat(self, model: str, messages: list[dict]) -> dict:
        payload = {"model": model, "messages": messages, "temperature": 0,
                   "response_format": {"type": "json_object"}}
        try:
            data = self._post(payload)
        except AIError as e:
            if "response_format" not in str(e) and "HTTP 400" not in str(e):
                raise
            payload.pop("response_format")  # some providers don't support JSON mode
            data = self._post(payload)
        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise AIError(f"неожиданный ответ AI: {str(data)[:200]}") from e
        return extract_json(content)

    # -- public
    def parse_text(self, text: str, ctx: dict) -> dict:
        return self._chat(self.cfg.model, [
            {"role": "system", "content": system_prompt(ctx)},
            {"role": "user", "content": text},
        ])

    def parse_image(self, image: bytes, caption: str, ctx: dict, mime: str = "image/jpeg") -> dict:
        if not self.cfg.can_see_images:
            raise AIError("выбранный AI не понимает фото (нужен AI_VISION_MODEL, например Gemini)")
        b64 = base64.b64encode(image).decode("ascii")
        return self._chat(self.cfg.vision_model, [
            {"role": "system", "content": system_prompt(ctx)},
            {"role": "user", "content": [
                {"type": "text", "text": caption or "Разбери это изображение (чек, SMS, скриншот)."},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]},
        ])


def system_prompt(ctx: dict) -> str:
    now: datetime = ctx["now"]
    return SYSTEM_PROMPT.format(
        categories=", ".join(ctx["categories"]), today=now.date().isoformat(), weekday=WEEKDAYS[now.weekday()],
        now=now.strftime("%H:%M"), tz=ctx["tz"], currency=ctx["currency"])


def extract_json(content: str) -> dict:
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            raise AIError("AI ответил не JSON")
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            raise AIError("AI ответил не JSON") from e
    if not isinstance(data, dict):
        raise AIError("AI ответил не объектом")
    return data


# ---------------------------------------------------------------- validation


@dataclass
class AIItem:
    type: str
    amount: float | None
    currency: str | None
    category: str | None
    description: str
    title: str
    date: date | None
    time: tuple[int, int] | None
    end_date: date | None
    end_time: tuple[int, int] | None
    recurrence: str | None
    deadline: bool


def _date(v, today: date) -> date | None:
    if not v:
        return None
    try:
        d = date.fromisoformat(str(v)[:10])
    except ValueError:
        return None
    return d if abs((d - today).days) <= 400 else None


def _time(v) -> tuple[int, int] | None:
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(v or ""))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return int(m.group(1)), int(m.group(2))


def validate(data: dict, today: date, categories: list[str]) -> tuple[list[AIItem], str | None]:
    """Turn raw AI JSON into safe items. Anything doubtful is dropped, never guessed."""
    items: list[AIItem] = []
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raw_items = []
    for raw in raw_items[:20]:
        if not isinstance(raw, dict):
            continue
        t = str(raw.get("type", "")).lower()
        if t not in ITEM_TYPES:
            continue
        amount = raw.get("amount")
        try:
            amount = float(amount) if amount not in (None, "") else None
        except (TypeError, ValueError):
            amount = None
        if t in ("expense", "income", "refund", "transfer"):
            if amount is None or not (0 < amount < 10_000_000):
                continue
        cur = raw.get("currency")
        cur = str(cur).upper() if cur and re.fullmatch(r"[A-Za-z]{3}", str(cur)) else None
        cat = raw.get("category") if raw.get("category") in categories else None
        title = str(raw.get("title") or raw.get("description") or "").strip()[:200]
        if t in ("task", "reminder", "event", "note") and not title:
            continue
        rec = raw.get("recurrence") if raw.get("recurrence") in ("daily", "weekly", "monthly") else None
        d = _date(raw.get("date"), today)
        if t in ("task", "reminder", "event") and d is not None and d < today - timedelta(days=1):
            d = None  # plans in the past make no sense
        items.append(AIItem(
            type=t, amount=amount, currency=cur, category=cat,
            description=str(raw.get("description") or "").strip()[:120], title=title,
            date=d, time=_time(raw.get("time")), end_date=_date(raw.get("end_date"), today),
            end_time=_time(raw.get("end_time")), recurrence=rec, deadline=bool(raw.get("deadline")),
        ))
    q = data.get("question")
    return items, (str(q)[:300] if q else None)


def main(argv: list[str]) -> int:
    import os

    from .config import BASE_DIR, load_dotenv
    from .nlp import CATEGORIES

    load_dotenv(BASE_DIR / ".env")
    cfg = config_from_env(dict(os.environ))
    if cfg is None:
        print("AI не настроен: задайте AI_PROVIDER и AI_API_KEY в .env")
        return 1
    text = " ".join(argv) or "вчера такси 30, купил лекарства на 85 и завтра в 10 к врачу"
    ctx = {"now": datetime.now(), "tz": os.environ.get("DEFAULT_TIMEZONE", "Asia/Dubai"),
           "currency": "AED", "categories": CATEGORIES}
    print(f"{cfg.provider} · {cfg.model} → {text}")
    try:
        data = AIClient(cfg).parse_text(text, ctx)
    except AIError as e:
        print(f"Ошибка: {e}")
        return 2
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Rule-based understanding of free text: money, tasks, reminders, events, "done" messages.

No AI, no network. The goal is to be right on everyday short messages and to
*ask* (or put the message into Inbox) instead of guessing when unsure.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from . import timeparse
from .timeparse import TimeInfo, normalize

F = re.IGNORECASE | re.UNICODE

CATEGORIES = [
    "Продукты", "Кафе и рестораны", "Транспорт", "Жильё", "Учёба", "Здоровье", "Покупки",
    "Подписки", "Развлечения", "Подарки", "Работа", "Переводы", "Прочее",
]
OTHER = "Прочее"

# word stems (prefix match on lowercased words); multi-word phrases are matched as substrings
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Продукты": [
        "продукт", "магазин", "супермаркет", "grocer", "carrefour", "lulu", "spinneys", "waitrose",
        "kibsons", "молок", "хлеб", "овощ", "фрукт", "мяс", "куриц", "яйц", "сыр", "бакале",
        "вода ", "водичк", "supermarket", "market", "продукт", "milk", "bread",
    ],
    "Кафе и рестораны": [
        "кофе", "кофейн", "кафе", "ресторан", "обед", "ужин", "завтрак", "ланч", "бургер", "пицц",
        "шаурм", "шаверм", "суши", "роллы", "фастфуд", "макдак", "доставк", "кальян", "coffee", "cafe",
        "café", "restaurant", "lunch", "dinner", "breakfast", "starbucks", "costa", "mcdonald", "kfc",
        "talabat", "deliveroo", "burger", "pizza", "латте", "капучино", "чай", "tea", "смузи",
    ],
    "Транспорт": [
        "такси", "taxi", "uber", "careem", "метро", "metro", "автобус", "bus", "бензин", "топлив",
        "заправк", "fuel", "petrol", "парковк", "parking", "salik", "салик", "nol", "трамва", "tram",
        "поезд", "train", "каршеринг", "udrive", "ekar", "самокат", "яндекс го", "bolt", "автомойк",
    ],
    "Жильё": [
        "аренд", "квартир", "rent", "коммунал", "dewa", "электричеств", "интернет", "internet", "wifi",
        "вайфай", "etisalat", "e&", "du ", "связь", "мобильн", "телефон за", "уборк", "ремонт", "мебел",
    ],
    "Учёба": [
        "учеб", "курс", "книг", "учебник", "универ", "колледж", "tuition", "course", "book", "school",
        "репетитор", "тетрад", "канцеляр", "экзамен", "exam", "семинар", "лекци",
    ],
    "Здоровье": [
        "аптек", "лекарств", "таблет", "врач", "доктор", "стоматолог", "зубн", "анализ", "pharmacy",
        "medicine", "doctor", "clinic", "клиник", "витамин", "спортзал", "gym", "фитнес", "массаж",
        "больниц", "hospital", "dentist", "страховк",
    ],
    "Покупки": [
        "одежд", "обув", "кроссовк", "футболк", "куртк", "джинс", "amazon", "noon", "техник",
        "наушник", "ikea", "икеа", "shopping", "clothes", "shoes", "косметик", "шампун", "зарядк",
        "чехол", "покупк", "мыло", "hygiene", "household", "хозтовар",
    ],
    "Подписки": [
        "подписк", "subscription", "netflix", "spotify", "youtube", "apple music", "icloud", "chatgpt",
        "openai", "claude", "яндекс плюс", "prime", "osn", "shahid", "disney",
    ],
    "Развлечения": [
        "кино", "cinema", "movie", "фильм", "игр", "game", "steam", "playstation", "концерт", "concert",
        "бар ", "клуб", "club", "боулинг", "развлеч", "парк", "музей", "museum", "театр", "квест",
        "караоке", "пляж", "beach",
    ],
    "Подарки": ["подар", "gift", "цвет", "flowers", "букет", "present"],
    "Работа": ["работ", "офис", "коворкинг", "work", "office", "coworking", "визитк", "командиров"],
    "Переводы": ["перевод", "перевел", "перевела", "отправил маме", "отправил папе", "transfer", "remit",
                 "western union", "долг", "вернул долг"],
}

CURRENCY_PATTERNS: list[tuple[str, str]] = [
    ("AED", r"aed|dhs?|дирхам\w*|дирх\w*|дрх|dirhams?|дх"),
    ("USD", r"usd|\$|долл\w*|бакс\w*|dollars?"),
    ("EUR", r"eur|€|евро|euros?"),
    ("RUB", r"rub|руб\w*|₽|р\.(?!\w)"),
    ("GBP", r"gbp|£|фунт\w*|pounds?"),
    ("KZT", r"kzt|₸|тенге|тг\.?"),
]
CURRENCY_RE = re.compile(
    r"(?<!\w)(?:" + "|".join(f"(?P<{code}>{p})" for code, p in CURRENCY_PATTERNS) + r")(?!\w)", F
)

AMOUNT_RE = re.compile(
    r"(?<![\w.,:/])"
    r"(?P<int>\d{1,3}(?:[  ]\d{3})+|\d+)"
    r"(?:[.,](?P<frac>\d{1,2}))?"
    r"(?:\s?(?P<k>k|к|тыс\.?|тысяч\w*)(?!\w))?"
    r"(?![\w.:/]|,\d)",
    F,
)

INCOME_RE = re.compile(
    r"\b(?:получил\w*|получен\w*|зарплат\w*|зп\b|доход\w*|заработал\w*|пришл[аои]\b|пришел|поступ\w*|"
    r"аванс\w*|преми\w*|кешб[эе]к\w*|кэшб[эе]к\w*|фриланс\w*|income|salary|received|earned|got\s+paid|"
    r"bonus|cashback|paycheck)", F)
REFUND_RE = re.compile(r"\b(?:возврат\w*|вернули|refund\w*|returned\s+money)", F)
OWN_TRANSFER_RE = re.compile(
    r"\b(?:между\s+(?:своими\s+)?счетами|на\s+(?:свой|свою|сберегат\w*|накопит\w*|депозит\w*|"
    r"копилк\w*|вклад\w*|savings)|в\s+копилку|с\s+карты\s+на\s+карту|снял\w*\s+(?:нал\w*|с\s+карты|деньги)|"
    r"(?:transfer|moved?)\s+(?:\w+\s+)?to\s+(?:my\s+)?(?:savings|own|deposit)|between\s+(?:my\s+)?accounts|"
    r"atm|cash\s+withdrawal|банкомат\w*)", F)

MONEY_VERB_RE = re.compile(
    r"\b(?:купил\w*|заплатил\w*|потратил\w*|оплатил\w*|отдал\w*|spent|paid|bought|payed|"
    r"за\s+\d|for\s+\d|on\s+\d)", F)

EVENT_RE = re.compile(
    r"\b(?:пар[аыу]|лекци\w*|семинар\w*|встреч\w*|созвон\w*|урок\w*|экзамен\w*|смен[аыу]|ночн\w+\s+смен\w*|"
    r"при[её]м\w*|стоматолог\w*|собеседован\w*|концерт\w*|день\s+рождени\w*|др\b|тренировк\w*|"
    r"занят\w*|конференци\w*|вебинар\w*|meeting|class|lecture|appointment|shift|exam|interview|"
    r"workout|training|call\s+with|webinar|birthday|conference)", F)

NOTE_PREFIX_RE = re.compile(r"^\s*(?:заметка|note|идея|idea|запомни|мысль)\s*[:\-—]?\s*", F)
TASK_PREFIX_RE = re.compile(r"^\s*(?:задача|todo|to-do|task|сделать)\s*[:\-—]\s*", F)
REMIND_PREFIX_RE = re.compile(
    r"^\s*(?:напомни(?:ть)?(?:\s+мне)?|напоминание|remind\s+me(?:\s+to)?|reminder)\b\s*[:,\-—]?\s*", F)
DONE_RE = re.compile(
    r"^\s*(?:сделал\w*|сделано|готово|выполнил\w*|выполнено|закончил\w*|купил\w*|позвонил\w*|написал\w*|"
    r"оплатил\w*|отправил\w*|забрал\w*|проверил\w*|сдал\w*|отнес\w*|done|finished|did|completed|bought|"
    r"called|paid|sent|submitted)\b", F)
CORRECTION_RE = re.compile(
    r"^\s*(?:не\s+\d+(?:[.,]\d{1,2})?\s*,?\s*а|исправь(?:\s+сумму)?(?:\s+на)?|"
    r"correct(?:ion)?(?:\s+to)?|fix\s+amount(?:\s+to)?)\s+(?P<amount>\d+(?:[.,]\d{1,2})?)\s*$", F)

EN_TASK_VERBS = {
    "call", "buy", "write", "pay", "send", "check", "finish", "email", "book", "clean", "fix", "make",
    "do", "read", "prepare", "submit", "review", "order", "cancel", "renew", "visit", "meet", "pick",
    "get", "go", "return", "print", "schedule", "text", "ask", "learn", "study", "wash", "cook",
    "bring", "take", "find", "update", "plan", "sign", "apply", "remember", "collect", "transfer",
}
NOT_INFINITIVES = {"часть", "сеть", "мать", "путь", "грусть", "кровать", "дочь", "ночь", "печь", "речь",
                   "помощь", "мощь", "вещь", "почти", "пути", "сети", "степь", "плоть", "суть", "нить",
                   "треть", "четверть", "радость", "площадь", "лошадь", "тетрадь", "ведь", "опять"}

STOPWORDS = {
    "в", "во", "на", "и", "с", "со", "за", "по", "к", "у", "о", "об", "от", "до", "из", "для", "мне",
    "a", "an", "the", "to", "for", "on", "in", "at", "of", "and", "my", "уже", "все", "всё", "это",
}

DESC_FILLERS_RE = re.compile(
    r"\b(?:купил\w*|заплатил\w*|потратил\w*|оплатил\w*|отдал\w*|получил\w*|spent|paid|bought|got|"
    r"received|за|for|on|на)\b", F)


def first_word(text: str) -> str:
    m = re.match(r"\s*([\w-]+)", text, F)
    return m.group(1).lower() if m else ""


def is_task_verb(word: str) -> bool:
    w = normalize(word.lower())
    if w in EN_TASK_VERBS:
        return True
    if w in NOT_INFINITIVES or len(w) < 4:
        return False
    return bool(re.search(r"(?:ть|ти|чь|ться|тись)$", w))


def stems(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[\w]+", normalize(text.lower()), F):
        if w in STOPWORDS or w.isdigit():
            continue
        out.add(w[:4] if len(w) >= 4 else w)
    return out


def match_score(query: str, title: str) -> float:
    q, t = stems(query), stems(title)
    if not q or not t:
        return 0.0
    common = q & t
    if not common:
        return 0.0
    return len(common) / len(q)


def norm_title(text: str) -> str:
    return " ".join(re.findall(r"\w+", normalize(text.lower()), F))


# ---------------------------------------------------------------- money


@dataclass
class Amount:
    value: Decimal
    start: int
    end: int
    raw: str


def find_amounts(text: str) -> list[Amount]:
    out = []
    for m in AMOUNT_RE.finditer(text):
        int_part = re.sub(r"[  ]", "", m.group("int"))
        try:
            val = Decimal(int_part)
            if m.group("frac"):
                frac = m.group("frac")
                val += Decimal(frac) / (10 ** len(frac))
        except InvalidOperation:
            continue
        if m.group("k"):
            val *= 1000
        out.append(Amount(val, m.start(), m.end(), m.group(0)))
    return out


def find_currency(text: str) -> tuple[str | None, tuple[int, int] | None]:
    m = CURRENCY_RE.search(text)
    if not m:
        return None, None
    for code, _ in CURRENCY_PATTERNS:
        if m.group(code):
            return code, m.span()
    return None, None


def guess_category(desc: str, memory: dict[str, str] | None = None) -> tuple[str, bool]:
    """Return (category, matched). ``matched`` is False when we fell back to "Прочее"."""
    low = normalize(desc.lower())
    words = re.findall(r"\w+", low, F)
    if memory:
        for w in words:
            if w in memory:
                return memory[w], True
    padded = f" {low} "
    for cat, keys in CATEGORY_KEYWORDS.items():
        for k in keys:
            if " " in k or not k.isalnum():
                if k in padded:
                    return cat, True
            elif any(w.startswith(k) for w in words):
                return cat, True
    return OTHER, False


@dataclass
class MoneyItem:
    type: str  # expense | income | refund | transfer
    amount: Decimal
    currency: str
    category: str
    description: str
    occurred_on: date

    def to_json(self) -> dict:
        return {
            "type": self.type, "amount": str(self.amount), "currency": self.currency,
            "category": self.category, "description": self.description,
            "occurred_on": self.occurred_on.isoformat(),
        }

    @classmethod
    def from_json(cls, d: dict) -> "MoneyItem":
        return cls(d["type"], Decimal(d["amount"]), d["currency"], d["category"], d["description"],
                   date.fromisoformat(d["occurred_on"]))


def _money_type(text: str) -> str:
    if OWN_TRANSFER_RE.search(text):
        return "transfer"
    if REFUND_RE.search(text):
        return "refund"
    if INCOME_RE.search(text):
        return "income"
    return "expense"


def build_money_item(segment: str, amount: Amount, ti: TimeInfo, default_currency: str, today: date,
                     memory: dict[str, str] | None, fallback_type: str | None = None) -> MoneyItem:
    rest = segment[:amount.start] + " " + segment[amount.end:]
    currency, span = find_currency(rest)
    if span:
        rest = rest[:span[0]] + " " + rest[span[1]:]
    desc = DESC_FILLERS_RE.sub(" ", rest)
    desc = re.sub(r"\s+", " ", desc).strip(" ,.;:-—")
    mtype = _money_type(segment)
    if mtype == "expense" and fallback_type:
        mtype = fallback_type
    if mtype == "income":
        low = normalize(segment.lower())
        if re.search(r"зарплат|зп\b|salary|аванс|преми|bonus|фриланс|freelance|paycheck|работ", low):
            category, _ = "Работа", True
        elif "перевод" in low or "transfer" in low:
            category = "Переводы"
        else:
            category, _ = guess_category(desc, memory)
    elif mtype == "transfer":
        category = "Переводы"
    else:
        category, _ = guess_category(desc or segment, memory)
    return MoneyItem(
        type=mtype, amount=amount.value, currency=currency or default_currency, category=category,
        description=desc, occurred_on=ti.date or today,
    )


def split_segments(text: str) -> list[str]:
    parts = re.split(r"\s*[;\n]\s*|,\s+|\s+(?:и|and|плюс|\+)\s+", text, flags=F)
    return [p.strip() for p in parts if p and p.strip()]


def has_money_signal(text: str, amounts: list[Amount], ti: TimeInfo) -> bool:
    if find_currency(text)[0]:
        return True
    if MONEY_VERB_RE.search(text) or INCOME_RE.search(text) or REFUND_RE.search(text) \
            or OWN_TRANSFER_RE.search(text):
        return True
    _, matched = guess_category(text)
    if matched:
        return True
    # "<слово> <число>" / "<число> <слово>" - short notes like "шаверма 22"
    words = [w for w in re.findall(r"[^\W\d]+", ti.remaining, F) if w.lower() not in STOPWORDS]
    if len(amounts) == 1 and 1 <= len(words) <= 3:
        rem = ti.remaining.strip()
        a = amounts[0].raw.strip()
        return rem.endswith(a) or rem.startswith(a)
    return False


# ---------------------------------------------------------------- intents


@dataclass
class Intent:
    kind: str  # money | ask_amount | task | reminder | ask_when | event | done | note | correction | unknown
    text: str = ""
    title: str = ""
    time: TimeInfo | None = None
    items: list[MoneyItem] = field(default_factory=list)
    candidates: list[Decimal] = field(default_factory=list)
    amount: Decimal | None = None
    ambiguous_dates: list[date] = field(default_factory=list)


def _strip_lead(text: str) -> str:
    return re.sub(r"^(?:что(?:бы)?|о|об|про|to)\s+", "", text.strip(), flags=F).strip(" ,.:-—")


def classify(text: str, now: datetime, default_currency: str = "AED",
             memory: dict[str, str] | None = None, tomorrow_date: date | None = None) -> Intent:
    """Classify a message. ``now`` is local naive time."""
    raw = text.strip()
    norm = normalize(raw)
    today = now.date()
    if not raw:
        return Intent("unknown", raw)

    m = CORRECTION_RE.match(norm)
    if m:
        return Intent("correction", raw, amount=Decimal(m.group("amount").replace(",", ".")))

    m = NOTE_PREFIX_RE.match(norm)
    if m and norm[m.end():].strip():
        return Intent("note", raw, title=raw[m.end():].strip())

    m = REMIND_PREFIX_RE.match(norm)
    if m:
        body = raw[m.end():]
        ti = timeparse.parse(body, now, tomorrow_date=tomorrow_date)
        title = _strip_lead(ti.remaining) or body.strip()
        if ti.ambiguous:
            return Intent("reminder", raw, title=title, time=ti, ambiguous_dates=ti.ambiguous)
        # "Напомни оплатить интернет первого числа" -> every month (bills repeat)
        if ti.day_of_month_form and not ti.recurrence and re.search(
                r"оплат|заплат|плат[её]ж|pay|аренд|rent|сч[её]т|подписк|bill|взнос", normalize(title.lower())):
            ti.recurrence = "monthly"
            ti.rec_day = ti.date.day if ti.date else None
        if not ti.has_when:
            return Intent("ask_when", raw, title=title)
        return Intent("reminder", raw, title=title, time=ti)

    task_prefix = TASK_PREFIX_RE.match(norm)
    if task_prefix:
        body = raw[task_prefix.end():]
        ti = timeparse.parse(body, now, tomorrow_date=tomorrow_date)
        return Intent("task", raw, title=ti.remaining or body.strip(), time=ti,
                      ambiguous_dates=ti.ambiguous)

    ti_future = timeparse.parse(raw, now, tomorrow_date=tomorrow_date)
    ti_past = timeparse.parse(raw, now, prefer_future=False, tomorrow_date=tomorrow_date)
    remaining = ti_future.remaining
    lead = first_word(remaining)

    # ---- money
    amounts = find_amounts(ti_past.remaining)
    starts_with_task_verb = is_task_verb(lead) and not MONEY_VERB_RE.match(remaining)
    is_event = bool(EVENT_RE.search(remaining)) and (ti_future.time is not None or ti_future.date is not None)
    if amounts and not is_event and not (starts_with_task_verb and not find_currency(raw)[0]):
        if has_money_signal(raw, amounts, ti_past):
            return _money_intent(raw, ti_past, amounts, now, default_currency, memory)

    # ---- "done" messages without amount
    if DONE_RE.match(remaining) and not amounts:
        return Intent("done", raw, title=remaining)

    if ti_future.ambiguous:
        kind = "event" if EVENT_RE.search(remaining) else "task"
        return Intent(kind, raw, title=remaining, time=ti_future, ambiguous_dates=ti_future.ambiguous)

    # ---- events
    if is_event and remaining:
        return Intent("event", raw, title=remaining, time=ti_future)

    # ---- tasks
    if remaining and (starts_with_task_verb or ti_future.has_when or ti_future.after_payday
                      or ti_future.deadline):
        return Intent("task", raw, title=remaining, time=ti_future)

    return Intent("unknown", raw)


def _money_intent(raw: str, ti: TimeInfo, amounts: list[Amount], now: datetime, currency: str,
                  memory: dict[str, str] | None) -> Intent:
    today = now.date()
    segments = split_segments(raw)
    if len(segments) > 1:
        parsed = []
        for seg in segments:
            sti = timeparse.parse(seg, now, prefer_future=False)
            samounts = find_amounts(sti.remaining)
            parsed.append((seg, sti, samounts))
        if all(len(a) == 1 for _, _, a in parsed):
            common_date = next((p[1].date for p in parsed if p[1].date), None)
            fallback_type = None
            items = []
            for seg, sti, samounts in parsed:
                if sti.date is None and common_date:
                    sti.date = common_date
                item = build_money_item(sti.remaining, samounts[0], sti, currency, today, memory, fallback_type)
                # "получил 500 и 300" - keep the type of the first part for the following ones
                fallback_type = item.type if item.type != "expense" else None
                items.append(item)
            return Intent("money", raw, items=items, time=ti)
    if len(amounts) == 1:
        if amounts[0].value <= 0:
            return Intent("ask_amount", raw, time=ti)
        return Intent("money", raw, items=[build_money_item(ti.remaining, amounts[0], ti, currency, today, memory)],
                      time=ti)
    return Intent("ask_amount", raw, time=ti, candidates=[a.value for a in amounts])


def money_item_with_amount(raw: str, chosen: Decimal, now: datetime, currency: str,
                           memory: dict[str, str] | None) -> MoneyItem:
    """Build an item from ``raw`` once the user picked which number is the amount."""
    ti = timeparse.parse(raw, now, prefer_future=False)
    amounts = find_amounts(ti.remaining)
    target = next((a for a in amounts if a.value == chosen), None)
    if target is None:
        target = Amount(chosen, len(ti.remaining), len(ti.remaining), "")
    return build_money_item(ti.remaining, target, ti, currency, now.date(), memory)

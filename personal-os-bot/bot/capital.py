"""Capital: savings, brokerage, deposits, crypto and other assets.

Pure logic. Parsing turns phrases like
  «закинул 50к тенге на брокерский, вышло 110$»  «купил 2 AAPL по 55$»  «обменял 100$ на 51 200 тенге»
into ``CapitalIntent``; ``compute_accounts`` turns stored moves into balances, holdings and P/L.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from . import nlp
from .market import ALIASES, CRYPTO, METALS, is_crypto, normalize_symbol
from .timeparse import normalize

F = re.IGNORECASE | re.UNICODE

KIND_LABEL = {"savings": "сбережения", "broker": "брокерский", "deposit": "депозит", "crypto": "крипто",
              "asset": "имущество", "other": "другое"}
KIND_ICON = {"savings": "🐷", "broker": "📈", "deposit": "🏦", "crypto": "🪙", "asset": "🏠", "other": "💼"}

ACCOUNT_WORDS = {
    "broker": r"брокер\w*|инвест\w*|freedom|фридом|tabys|табыс|interactive|ibkr|tinkoff|тинькофф|broker\w*|invest\w*",
    "deposit": r"депозит\w*|вклад\w*|deposit\w*",
    "savings": r"копилк\w*|сбереж\w*|сберег\w*|накоп\w*|savings?|заначк\w*",
    "crypto": r"крипт\w*|binance|бинанс\w*|bybit|байбит\w*|okx|кошел[её]к\w*\s+крипт\w*|crypto|wallet",
}

VERB_DEPOSIT = r"закинул\w*|пополнил\w*|перев[её]л\w*|положил\w*|вн[её]с\w*|внесл\w*|отправил\w*|скинул\w*|вложил\w*|" \
               r"отложил\w*|deposit\w*|put|added|moved|transferred|topped\s+up"
VERB_WITHDRAW = r"вывел\w*|снял\w*|забрал\w*|withdr[ae]w\w*|took\s+out"
VERB_BUY = r"купил\w*|докупил\w*|bought|buy"
VERB_SELL = r"продал\w*|sold|sell"
QTY_UNITS = r"(?:шт\.?|штук\w*|акци\w*|бумаг\w*|лот\w*|shares?|units?|coins?|монет\w*)"
CUR_WORDS = r"доллар\w*|usd|\$|бакс\w*|дирхам\w*|aed|dhs?|тенге|тг|kzt|₸|евро|eur|€|рубл\w*|руб|rub|₽|фунт\w*|gbp|£"


@dataclass
class Money:
    amount: Decimal
    currency: str | None


@dataclass
class CapitalIntent:
    kind: str           # rate|exchange|deposit|withdraw|buy|sell|dividend|interest|price|asset_value|open
    account: str | None = None          # account phrase as written
    account_kind: str | None = None     # guessed kind for a new account
    src: Money | None = None
    dst: Money | None = None
    symbol: str | None = None
    qty: Decimal | None = None
    unit_price: Money | None = None
    rate_pct: float | None = None
    rate_from: str | None = None        # 1 rate_from = rate_value rate_to
    rate_to: str | None = None
    rate_value: Decimal | None = None


def _num(s: str) -> Decimal:
    s = s.replace(" ", "").replace(" ", "").replace(",", ".")
    mult = 1
    if s[-1:] in ("k", "к"):
        s, mult = s[:-1], 1000
    return Decimal(s) * mult


def _money_in(text: str, default: str | None = None) -> Money | None:
    amounts = nlp.find_amounts(text)
    if not amounts:
        return None
    a = amounts[0]
    cur, _ = nlp.find_currency(text)
    return Money(a.value, cur or default)


def currency_code(word: str) -> str | None:
    cur, _ = nlp.find_currency(word)
    return cur


def guess_kind(phrase: str) -> str | None:
    p = normalize(phrase.lower())
    for kind, rx in ACCOUNT_WORDS.items():
        if re.search(rf"\b(?:{rx})", p, F):
            return kind
    return None


GENERIC_WORDS = r"брокер\w*|инвест\w*|депозит\w*|вклад\w*|копилк\w*|сбереж\w*|сберег\w*|накоп\w*|заначк\w*|" \
                r"крипт\w*|broker\w*|savings?|deposit|crypto"
DEFAULT_NAMES = {"broker": "Брокерский счёт", "deposit": "Депозит", "savings": "Копилка", "crypto": "Крипта",
                 "asset": "Имущество", "other": "Счёт"}


def account_title(phrase: str, kind: str | None) -> str:
    """«брокерского» -> «Брокерский счёт», «Freedom» -> «Freedom», «депозит kaspi» -> «Депозит Kaspi»."""
    name = clean_account_name(phrase)
    words = name.split()
    if kind and words and all(re.fullmatch(GENERIC_WORDS, normalize(w.lower()), F) for w in words):
        return DEFAULT_NAMES[kind]
    if kind and words and re.fullmatch(GENERIC_WORDS, normalize(words[0].lower()), F):
        rest = " ".join(words[1:])
        return f"{DEFAULT_NAMES[kind]} {rest[:1].upper() + rest[1:]}".strip()
    return name or DEFAULT_NAMES.get(kind or "other", "Счёт")


def clean_account_name(phrase: str) -> str:
    p = re.sub(r"\b(?:сч[её]т\w*|account)\b", " ", phrase, flags=F)
    p = re.sub(rf"\b(?:{CUR_WORDS})(?!\w)", " ", p, flags=F)
    p = re.sub(r"[\d.,]+\s*%?", " ", p)
    p = re.sub(r"\b(?:мой|мою|мое|свой|свою|the|my|под|на|в)\b", " ", p, flags=F)
    p = re.sub(r"\s+", " ", p).strip(" ,.-")
    return nlp.timeparse.normalize(p)[:40].strip().capitalize() if p else ""


def _symbol(token: str, has_unit_word: bool) -> str | None:
    raw = token.strip(" ,.;:")
    if not raw:
        return None
    low = normalize(raw.lower())
    if low in ALIASES:
        return ALIASES[low]
    up = raw.upper()
    if up in CRYPTO or up in METALS:
        return up
    if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", raw):          # written as a ticker: AAPL, BRK.B
        return up
    if has_unit_word and re.fullmatch(r"[A-Za-z][A-Za-z0-9.\-]{0,9}", raw):
        return up
    return None


def parse(text: str, default_currency: str, account_names: list[str] | None = None) -> CapitalIntent | None:
    """Return a capital intent or None (then the message goes to the usual parser)."""
    t = normalize(text.strip())
    low = t.lower()
    account_names = account_names or []

    # --- manual exchange rate: «курс доллара 512 тенге», «1$ = 512 тг», «курс usd 3.67 aed»
    m = re.fullmatch(rf"(?:курс\s+(?P<a>{CUR_WORDS})|1\s*(?P<a2>{CUR_WORDS})\s*=)\s*(?P<n>\d+(?:[.,]\d+)?)\s*"
                     rf"(?P<b>{CUR_WORDS})?", low, F)
    if m:
        a = currency_code(m.group("a") or m.group("a2"))
        b = currency_code(m.group("b")) if m.group("b") else None
        if a and b is None and a == "USD" and default_currency != "USD":
            b = default_currency
        if a and a != b:  # rate_to None -> the bot asks "139 чего?"
            return CapitalIntent("rate", rate_from=a, rate_to=b, rate_value=_num(m.group("n")))

    # --- currency exchange in the wallet: «обменял 100$ на 51 200 тенге»
    m = re.match(r"^(?:обменял\w*|поменял\w*|обмен|конвертировал\w*|exchanged|converted|swapped)\s+(?P<a>.+?)\s+"
                 r"(?:на|в|to|into|→|->)\s+(?P<b>.+)$", t, F)
    if m:
        src = _money_in(m.group("a"))
        dst = _money_in(m.group("b"))
        dst_cur = currency_code(m.group("b"))
        if src and src.currency and dst_cur and dst_cur != src.currency:
            return CapitalIntent("exchange", src=src, dst=Money(dst.amount, dst_cur) if dst else Money(Decimal(0), dst_cur))

    # --- price update: «цена AAPL 190$»
    m = re.fullmatch(r"(?:цена|price)\s+(?P<sym>\S+)\s+(?P<rest>.+)", t, F)
    if m:
        sym = _symbol(m.group("sym"), True)
        price = _money_in(m.group("rest"), "USD")
        if sym and price:
            return CapitalIntent("price", symbol=sym, unit_price=price)

    # --- other assets: «актив машина 15000$», «имущество квартира 120000 usd»
    m = re.fullmatch(r"(?:актив|имущество|asset)\s+(?P<name>.+?)\s+(?P<rest>\d[\d\s.,]*\s*(?:k|к)?\s*(?:\S+)?)", t, F)
    if m:
        val = _money_in(m.group("rest"), default_currency)
        if val:
            return CapitalIntent("asset_value", account=clean_account_name(m.group("name")), account_kind="asset",
                                 dst=val)

    # --- buy / sell: «купил 2 AAPL по 55$», «купил 0.01 btc за 600$», «продал 1 TSLA по 250»
    m = re.match(rf"^(?P<verb>{VERB_BUY}|{VERB_SELL})\s+(?P<qty>\d+(?:[.,]\d+)?)\s*(?P<unit>{QTY_UNITS})?\s*"
                 rf"(?P<sym>[^\s,]+)(?P<rest>.*)$", t, F)
    if m:
        sym = _symbol(m.group("sym"), bool(m.group("unit")))
        rest = m.group("rest")
        pm = re.search(r"(?:(?P<per>\bпо\b|\bat\b|@|по\s+цене)|(?P<tot>\bза\b|\bfor\b))\s*(?P<price>\d[\d\s.,]*\s*(?:k|к)?"
                       rf"\s*(?:{CUR_WORDS})?)", rest, F)
        if sym and pm:
            price = _money_in(pm.group("price"), "USD")
            qty = _num(m.group("qty"))
            if price and qty > 0:
                if pm.group("tot"):
                    price = Money(price.amount / qty, price.currency)
                acc = re.search(r"\b(?:на|в|on|at|in)\s+(?P<acc>[\w\- ]{2,30})$", rest[:pm.start()] + rest[pm.end():], F)
                verb = normalize(m.group("verb").lower())
                kind = "sell" if re.match(VERB_SELL, verb, F) else "buy"
                return CapitalIntent(kind, symbol=sym, qty=qty, unit_price=price,
                                     account=clean_account_name(acc.group("acc")) if acc else None,
                                     account_kind="crypto" if is_crypto(sym) else "broker")

    # --- dividends / interest
    m = re.match(r"^(?P<k>дивиденд\w*|дивы|купон\w*|dividends?|проценты|процент\w*\s+по\s+\w+|начислил\w*|interest)\s+"
                 r"(?P<rest>.+)$", t, F)
    if m:
        rest = m.group("rest")
        amount = _money_in(rest)
        if amount:
            sym = None
            for tok in rest.split():
                sym = _symbol(tok, False)
                if sym:
                    break
            acc = re.search(r"\b(?:на|по|в|on|from)\s+(?P<acc>[^\d\s][\w\- ]{1,30})$", rest, F)
            kind = "dividend" if re.match(r"див|купон|divid", m.group("k"), F) else "interest"
            return CapitalIntent(kind, symbol=sym, dst=amount,
                                 account=clean_account_name(acc.group("acc")) if acc else None,
                                 account_kind="broker" if kind == "dividend" else "deposit")

    # --- open an account: «открыл депозит 1 000 000 тенге под 15%», «новый счёт Freedom usd»
    m = re.match(r"^(?:открыл\w*|новый\s+сч[её]т|создай\s+сч[её]т|open(?:ed)?)\s+(?P<rest>.+)$", t, F)
    if m:
        rest = m.group("rest")
        kind = guess_kind(rest)
        if kind or re.match(r"новый|создай", t, F):
            pct = re.search(r"(?:под\s+)?(\d+(?:[.,]\d+)?)\s*%", rest)
            amount = _money_in(re.sub(r"(?:под\s+)?\d+(?:[.,]\d+)?\s*%", " ", rest), None)
            name_part = re.split(r"\d", rest, maxsplit=1)[0]
            return CapitalIntent("open", account=clean_account_name(name_part) or (kind or "Счёт").capitalize(),
                                 account_kind=kind or "other", src=amount,
                                 rate_pct=float(pct.group(1).replace(",", ".")) if pct else None)

    # --- deposit into an account: «закинул 50к тенге на брокерский, вышло 110$»
    m = re.match(rf"^(?:{VERB_DEPOSIT})\b(?P<rest>.+)$", t, F)
    if m:
        rest = m.group("rest")
        dest = _destination(rest, account_names, ("на", "в", "во", "to", "into"))
        if dest:
            phrase, kind = dest
            parts = re.split(r"\b(?:вышло|получилось|пришло|зачислил\w*|зачислено|это|that'?s|got)\b|=|→|->", rest,
                             maxsplit=1, flags=F)
            src = _money_in(_strip_dest(parts[0], phrase))
            dst = _money_in(parts[1]) if len(parts) > 1 else None
            if src:
                return CapitalIntent("deposit", account=clean_account_name(phrase), account_kind=kind, src=src, dst=dst)

    # --- withdraw: «вывел 100$ с брокерского»
    m = re.match(rf"^(?:{VERB_WITHDRAW})\b(?P<rest>.+)$", t, F)
    if m:
        rest = m.group("rest")
        dest = _destination(rest, account_names, ("с", "со", "из", "from"))
        if dest:
            phrase, kind = dest
            parts = re.split(r"\b(?:вышло|получилось|пришло|это|got)\b|=|→|->", rest, maxsplit=1, flags=F)
            src = _money_in(_strip_dest(parts[0], phrase))
            dst = _money_in(parts[1]) if len(parts) > 1 else None
            if src:
                return CapitalIntent("withdraw", account=clean_account_name(phrase), account_kind=kind, src=src, dst=dst)
    return None


def _strip_dest(text: str, phrase: str) -> str:
    return text.replace(phrase, " ")


def _destination(rest: str, account_names: list[str], preps: tuple[str, ...]) -> tuple[str, str | None] | None:
    """Find «на брокерский счёт» / «с депозита» or an existing account name. Returns (phrase, guessed kind)."""
    prep = "|".join(preps)
    for m in re.finditer(rf"\b(?:{prep})\s+(?P<acc>[^\d,;]+?)(?=$|[,;]|\s+(?:вышло|получилось|пришло|это|по|=|\d))",
                         rest, F):
        phrase = m.group("acc").strip()
        kind = guess_kind(phrase)
        if kind:
            return phrase, kind
        for name in account_names:
            if nlp.match_score(phrase, name) >= 0.5 or nlp.match_score(name, phrase) >= 0.5:
                return phrase, None
    return None


# ---------------------------------------------------------------- balances


@dataclass
class Holding:
    symbol: str
    qty: float
    cost_minor: int                  # total cost, account currency
    price: float | None = None       # latest price per unit
    price_currency: str | None = None
    price_day: str | None = None
    value_minor: int | None = None   # account currency

    @property
    def pnl_minor(self) -> int | None:
        return None if self.value_minor is None else self.value_minor - self.cost_minor


@dataclass
class AccountState:
    id: int
    name: str
    kind: str
    currency: str
    rate_pct: float | None
    cash_minor: int = 0
    invested_minor: int = 0          # net money put in (deposits - withdrawals), account currency
    income_minor: int = 0            # dividends + interest received
    accrued_minor: int = 0           # estimated interest for deposits
    asset_value_minor: int | None = None
    holdings: list[Holding] = field(default_factory=list)
    missing_prices: list[str] = field(default_factory=list)
    last_move: str | None = None

    @property
    def value_minor(self) -> int:
        if self.kind == "asset" and self.asset_value_minor is not None:
            return self.asset_value_minor
        return self.cash_minor + self.accrued_minor + sum(h.value_minor or 0 for h in self.holdings)

    @property
    def pnl_minor(self) -> int:
        return self.value_minor - self.invested_minor


def compute_accounts(accounts: list[dict], moves: list[dict], market, today: date) -> list[AccountState]:
    states = {a["id"]: AccountState(a["id"], a["name"], a["kind"], a["currency"], a["rate_pct"]) for a in accounts}
    pos: dict[int, dict[str, Holding]] = {a["id"]: {} for a in accounts}
    for mv in sorted(moves, key=lambda m: (m["occurred_on"], m["id"])):
        st = states.get(mv["account_id"])
        if st is None:
            continue
        k = mv["kind"]
        st.last_move = mv["occurred_on"]
        if k == "deposit":
            st.cash_minor += mv["to_minor"] or 0
            st.invested_minor += mv["to_minor"] or 0
            if st.rate_pct:
                days = max((today - date.fromisoformat(mv["occurred_on"])).days, 0)
                st.accrued_minor += round((mv["to_minor"] or 0) * st.rate_pct / 100 * days / 365)
        elif k == "withdraw":
            st.cash_minor -= mv["from_minor"] or 0
            st.invested_minor -= mv["from_minor"] or 0
        elif k == "buy":
            st.cash_minor -= mv["from_minor"] or 0
            h = pos[st.id].setdefault(mv["symbol"], Holding(mv["symbol"], 0.0, 0))
            h.qty += mv["qty"] or 0
            h.cost_minor += mv["from_minor"] or 0
        elif k == "sell":
            st.cash_minor += mv["to_minor"] or 0
            h = pos[st.id].setdefault(mv["symbol"], Holding(mv["symbol"], 0.0, 0))
            if h.qty > 0:
                share = min((mv["qty"] or 0) / h.qty, 1)
                h.cost_minor -= round(h.cost_minor * share)
            h.qty -= mv["qty"] or 0
        elif k in ("dividend", "interest"):
            st.cash_minor += mv["to_minor"] or 0
            st.income_minor += mv["to_minor"] or 0
        elif k == "fee":
            st.cash_minor -= mv["from_minor"] or 0
        elif k == "value":
            st.asset_value_minor = mv["to_minor"]
            if st.invested_minor == 0:
                st.invested_minor = mv["to_minor"] or 0
    for st in states.values():
        for h in pos[st.id].values():
            if h.qty <= 1e-12:
                continue
            p = market.price(h.symbol)
            if p is None:
                st.missing_prices.append(h.symbol)
            else:
                price, pcur, pday, _ = p
                h.price, h.price_currency, h.price_day = price, pcur, pday
                conv = market.convert(round(h.qty * price * 100), pcur, st.currency, today)
                h.value_minor = conv
                if conv is None:
                    st.missing_prices.append(h.symbol)
            st.holdings.append(h)
        st.holdings.sort(key=lambda h: -(h.value_minor or 0))
    return list(states.values())


def fmt_qty(q: float) -> str:
    if abs(q - round(q)) < 1e-9:
        return str(int(round(q)))
    return f"{q:.8f}".rstrip("0").rstrip(".")

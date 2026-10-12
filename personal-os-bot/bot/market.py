"""Exchange rates and asset prices from free, key-less sources (with fallbacks).

Rates are stored as "units of currency per 1 USD", so any pair converts through USD.
Nothing is ever guessed: if there is no rate, conversion returns None and the UI says so.
"""
from __future__ import annotations

import json
import math
import logging
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from typing import Callable

log = logging.getLogger(__name__)

PEGS = {"USD": 1.0, "AED": 3.6725}      # AED is officially pegged to USD

RATES_LATEST = [
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.min.json",
    "https://latest.currency-api.pages.dev/v1/currencies/usd.min.json",
]
RATES_DAY = [
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{day}/v1/currencies/usd.min.json",
    "https://{day}.currency-api.pages.dev/v1/currencies/usd.min.json",
]
RATES_ER_API = "https://open.er-api.com/v6/latest/USD"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
STOOQ = "https://stooq.com/q/l/?s={symbol}.us&f=sd2t2ohlcv&h&e=csv"

CRYPTO = {"BTC", "ETH", "USDT", "USDC", "SOL", "TON", "BNB", "XRP", "DOGE", "ADA", "TRX", "LTC", "DOT",
          "AVAX", "LINK", "NOT"}
METALS = {"XAU", "XAG"}   # price per troy ounce

ALIASES = {
    "биткоин": "BTC", "биткоина": "BTC", "биткоинов": "BTC", "биток": "BTC", "битка": "BTC", "bitcoin": "BTC",
    "эфир": "ETH", "эфира": "ETH", "эфириум": "ETH", "ethereum": "ETH", "тон": "TON", "toncoin": "TON",
    "usdt": "USDT", "тезер": "USDT", "золото": "XAU", "золота": "XAU", "gold": "XAU", "серебро": "XAG",
    "серебра": "XAG", "каспи": "KSPI", "kaspi": "KSPI", "эппл": "AAPL", "apple": "AAPL", "тесла": "TSLA",
    "tesla": "TSLA", "нвидиа": "NVDA", "nvidia": "NVDA", "майкрософт": "MSFT", "microsoft": "MSFT",
    "гугл": "GOOGL", "google": "GOOGL", "амазон": "AMZN", "amazon": "AMZN", "s&p": "VOO", "sp500": "VOO",
}

UA = {"User-Agent": "Mozilla/5.0 (PersonalOS bot)", "Accept": "*/*"}


class MarketError(Exception):
    pass


def http_get(url: str, timeout: float = 10.0) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise MarketError(f"{url.split('/')[2]}: {e}") from e


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def is_crypto(symbol: str) -> bool:
    return symbol.upper() in CRYPTO or symbol.upper() in METALS


def normalize_symbol(raw: str) -> str:
    low = raw.strip().lower()
    return ALIASES.get(low, raw.strip().upper())


class Market:
    def __init__(self, db, fetch: Callable[[str], bytes] = http_get):
        self.db = db
        self.fetch = fetch
        self._cache: dict[tuple[str, str], float | None] = {}

    # ------------------------------------------------------------ rates
    def per_usd(self, code: str, day: date) -> float | None:
        code = code.upper()
        if code == "USD":
            return 1.0
        key = (code, day.isoformat())
        if key in self._cache:
            return self._cache[key]
        row = self.db.one(
            "SELECT per_usd FROM rates WHERE code = ? AND day <= ? "
            "ORDER BY day DESC, CASE source WHEN 'manual' THEN 0 ELSE 1 END LIMIT 1", (code, day.isoformat()))
        if row is None:  # nothing before that day: take the earliest known after it
            row = self.db.one("SELECT per_usd FROM rates WHERE code = ? ORDER BY day, "
                              "CASE source WHEN 'manual' THEN 0 ELSE 1 END LIMIT 1", (code,))
        val = float(row[0]) if row else PEGS.get(code)
        self._cache[key] = val
        return val

    def convert(self, minor: int, frm: str, to: str, day: date) -> int | None:
        if frm.upper() == to.upper():
            return minor
        a, b = self.per_usd(frm, day), self.per_usd(to, day)
        if a is None or b is None:
            return None
        return math.floor(minor / a * b + 0.5)   # money rounds half up, not to even

    def rate_info(self, code: str) -> tuple[float, str, str] | None:
        """(per_usd, day, source) of the newest rate."""
        row = self.db.one("SELECT per_usd, day, source FROM rates WHERE code = ? ORDER BY day DESC, "
                          "CASE source WHEN 'manual' THEN 0 ELSE 1 END LIMIT 1", (code.upper(),))
        if row:
            return float(row[0]), row[1], row[2]
        if code.upper() in PEGS:
            return PEGS[code.upper()], "", "peg"
        return None

    def store_rates(self, day: str, rates: dict[str, float], source: str = "api") -> int:
        n = 0
        with self.db.tx():
            for code, v in rates.items():
                if not v or v <= 0:
                    continue
                self.db.execute(
                    "INSERT INTO rates(code, day, source, per_usd, fetched_at) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(code, day, source) DO UPDATE SET per_usd = excluded.per_usd, "
                    "fetched_at = excluded.fetched_at", (code.upper(), day, source, float(v), _now()))
                n += 1
        self._cache.clear()
        return n

    def set_manual(self, code: str, per_usd: float, day: date) -> None:
        self.store_rates(day.isoformat(), {code: per_usd}, "manual")

    def _parse_currency_api(self, raw: bytes) -> tuple[str, dict[str, float]]:
        data = json.loads(raw)
        return data["date"], {k.upper(): float(v) for k, v in data["usd"].items() if isinstance(v, (int, float))}

    def refresh_latest(self, codes: set[str]) -> str:
        """Download today's rates. Returns the source date. Raises MarketError if every source fails."""
        errors = []
        for url in RATES_LATEST:
            try:
                day, rates = self._parse_currency_api(self.fetch(url))
                self.store_rates(day, {c: rates[c] for c in codes | CRYPTO | METALS if c in rates})
                return day
            except (MarketError, ValueError, KeyError) as e:
                errors.append(str(e))
        try:
            data = json.loads(self.fetch(RATES_ER_API))
            if data.get("result") != "success":
                raise MarketError("open.er-api: no success")
            day = datetime.fromtimestamp(int(data["time_last_update_unix"]), timezone.utc).date().isoformat()
            self.store_rates(day, {c: data["rates"][c] for c in codes if c in data["rates"]})
            return day
        except (MarketError, ValueError, KeyError) as e:
            errors.append(str(e))
        raise MarketError("; ".join(errors))

    def backfill(self, day: date, codes: set[str]) -> bool:
        """Historical rates for a past day (used for old transactions)."""
        for tpl in RATES_DAY:
            try:
                src_day, rates = self._parse_currency_api(self.fetch(tpl.format(day=day.isoformat())))
                self.store_rates(day.isoformat(), {c: rates[c] for c in codes if c in rates})
                return True
            except (MarketError, ValueError, KeyError):
                continue
        return False

    def has_rate_on(self, code: str, day: date) -> bool:
        return code.upper() in ("USD",) or bool(self.db.scalar(
            "SELECT 1 FROM rates WHERE code = ? AND day = ?", (code.upper(), day.isoformat())))

    # ------------------------------------------------------------ prices
    def price(self, symbol: str) -> tuple[float, str, str, str] | None:
        """(price, currency, day, source) of the newest known price."""
        row = self.db.one("SELECT price, currency, day, source FROM prices WHERE symbol = ? ORDER BY day DESC LIMIT 1",
                          (symbol.upper(),))
        best = (float(row[0]), row[1], row[2], row[3]) if row else None
        if is_crypto(symbol):
            info = self.rate_info(symbol)
            if info and info[1] and (best is None or info[1] > best[2]):
                best = (1 / info[0], "USD", info[1], "rates")
        return best

    def set_price(self, symbol: str, price: float, currency: str, day: date, source: str = "manual") -> None:
        with self.db.tx():
            self.db.execute(
                "INSERT INTO prices(symbol, day, price, currency, source, fetched_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(symbol, day) DO UPDATE SET price = excluded.price, currency = excluded.currency, "
                "source = excluded.source, fetched_at = excluded.fetched_at",
                (symbol.upper(), day.isoformat(), float(price), currency.upper(), source, _now()))

    def fetch_stock(self, symbol: str) -> tuple[float, str, str]:
        """Latest price of a stock/ETF: Yahoo, then Stooq. Returns (price, currency, source)."""
        errors = []
        try:
            data = json.loads(self.fetch(YAHOO.format(symbol=symbol)))
            meta = data["chart"]["result"][0]["meta"]
            price = float(meta.get("regularMarketPrice") or meta["previousClose"])
            return price, (meta.get("currency") or "USD").upper(), "yahoo"
        except (MarketError, ValueError, KeyError, TypeError, IndexError) as e:
            errors.append(f"yahoo: {e}")
        try:
            lines = self.fetch(STOOQ.format(symbol=symbol.lower())).decode().strip().splitlines()
            header, row = lines[0].lower().split(","), lines[1].split(",")
            close = row[header.index("close")]
            if close in ("N/D", ""):
                raise MarketError("stooq: no data")
            return float(close), "USD", "stooq"
        except (MarketError, ValueError, IndexError) as e:
            errors.append(f"stooq: {e}")
        raise MarketError("; ".join(errors))

    def refresh_prices(self, symbols: set[str], today: date) -> dict[str, str]:
        """Update prices for held symbols. Returns {symbol: error} for the ones that failed."""
        failed = {}
        for sym in sorted(symbols):
            if is_crypto(sym):
                continue  # comes with the rates download
            if self.db.scalar("SELECT 1 FROM prices WHERE symbol = ? AND day = ? AND source = 'manual'",
                              (sym, today.isoformat())):
                continue
            try:
                price, cur, src = self.fetch_stock(sym)
                self.set_price(sym, price, cur, today, src)
            except MarketError as e:
                failed[sym] = str(e)
                log.warning("price %s failed: %s", sym, e)
        return failed

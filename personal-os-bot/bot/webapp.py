"""Data for the Telegram Mini App.

There is no server: the bot packs a compact snapshot (JSON -> raw deflate -> base64url) into the
fragment of the Mini App URL (``…/index.html#d=…``). The fragment never leaves the phone - the page
host (GitHub Pages) only serves the static file. If the link gets too long, older history is dropped.
"""
from __future__ import annotations

import base64
import json
import zlib
from datetime import date, timedelta

from . import capital as cap
from .nlp import CATEGORIES

TYPE_CODE = {"expense": 0, "income": 1, "refund": 2}


def encode(data: dict) -> str:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    comp = zlib.compressobj(9, zlib.DEFLATED, -15)
    packed = comp.compress(raw) + comp.flush()
    return base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")


def decode(token: str) -> dict:
    packed = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    return json.loads(zlib.decompress(packed, -15).decode("utf-8"))


def _usd(svc, minor: int, cur: str, day: date) -> int | None:
    return svc.market.convert(minor, cur, "USD", day)


def build(svc, months: int = 6) -> dict:
    today = svc.today()
    start = (today.replace(day=1) - timedelta(days=31 * (months - 1))).replace(day=1)
    rates = {}
    for c in set(svc.tracked_currencies) | {svc.report_currency}:
        v = svc.market.per_usd(c, today)
        if v:
            rates[c] = round(v, 6)
    descs: list[str] = []
    dmap: dict[str, int] = {}
    cur_list: list[str] = []
    tx = []
    for r in svc.db.all("SELECT * FROM transactions WHERE type IN ('expense','income','refund') AND occurred_on >= ? "
                        "ORDER BY occurred_on, id", (start.isoformat(),)):
        d = date.fromisoformat(r["occurred_on"])
        usd = _usd(svc, r["amount_minor"], r["currency"], d)
        if usd is None:
            continue
        desc = (r["description"] or "")[:40]
        if desc not in dmap:
            dmap[desc] = len(descs)
            descs.append(desc)
        if r["currency"] not in cur_list:
            cur_list.append(r["currency"])
        row = [(d - start).days, CATEGORIES.index(r["category"]) if r["category"] in CATEGORIES else 12, usd,
               TYPE_CODE[r["type"]], dmap[desc]]
        if r["currency"] != "USD":
            row += [cur_list.index(r["currency"]), r["amount_minor"]]
        tx.append(row)
    colors = svc._category_colors([c for c, _ in svc._by_category(start, today, svc.report_currency)])
    budget = svc.db.get_setting("monthly_budget")
    limits = {r["category"]: _usd(svc, r["amount_minor"], svc.currency, today)
              for r in svc.db.all("SELECT * FROM category_limits")}
    pay = svc._payday_numbers("USD")
    data = {
        "v": 1, "today": today.isoformat(), "start": start.isoformat(), "cur": svc.report_currency,
        "cs": svc.tracked_currencies, "fx": rates, "cats": CATEGORIES, "col": colors, "tx": tx, "ds": descs,
        "oc": cur_list,
        "budget": _usd(svc, int(budget), svc.currency, today) if budget else None,
        "limits": {k: v for k, v in limits.items() if v},
        "pay": None if not pay or pay["payday"] is None else {
            "day": pay["payday"].isoformat(), "perDay": pay["per_day"], "free": pay["available"]},
        "cap": _capital(svc, today),
    }
    svc._fx_missing.clear()
    return data


def _capital(svc, today: date) -> dict | None:
    states = svc._states()
    pockets = svc._pockets()
    if not states and not pockets:
        return None
    acc_colors = svc._account_colors([s.name for s in states])
    accounts, holdings = [], []
    for i, s in enumerate(states):
        accounts.append([s.name, s.kind, svc.market.convert(s.value_minor, s.currency, "USD", today) or 0,
                         svc.market.convert(s.invested_minor, s.currency, "USD", today) or 0, s.currency,
                         s.value_minor, acc_colors.get(s.name, -1), s.rate_pct])
        for h in s.holdings:
            if h.value_minor is None:
                continue
            holdings.append([h.symbol, cap.fmt_qty(h.qty), svc.market.convert(h.value_minor, s.currency, "USD", today) or 0,
                             svc.market.convert(h.cost_minor, s.currency, "USD", today) or 0, i,
                             round(h.price, 4) if h.price else None, h.price_currency])
    wallet = [[c, v[1], svc.market.convert(v[1], c, "USD", today) or 0] for c, v in pockets.items()]
    hist = [[(date.fromisoformat(r["day"]) - today).days, round(r["usd"] * 100)]
            for r in svc.db.all("SELECT day, usd FROM networth WHERE day >= ? ORDER BY day",
                                ((today - timedelta(days=365)).isoformat(),))]
    return {"acc": accounts, "hold": holdings, "wallet": wallet, "hist": hist, "walletColor": acc_colors.get("Кошелёк")}


def url(svc, base_url: str, max_len: int = 6000) -> str | None:
    """Mini App URL with data, shortened (fewer months) to fit ``max_len``. None when no URL is configured."""
    if not base_url:
        return None
    for months in (6, 4, 3, 2, 1):
        data = build(svc, months)
        token = encode(data)
        u = f"{base_url}#d={token}"
        if len(u) <= max_len:
            return u
    while data["tx"]:
        data["tx"] = data["tx"][len(data["tx"]) // 4 + 1:]     # drop the oldest quarter until it fits
        u = f"{base_url}#d={encode(data)}"
        if len(u) <= max_len:
            return u
    return f"{base_url}#d={encode(data)}"

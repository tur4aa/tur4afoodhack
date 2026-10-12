"""Capital & currencies part of the service (mixed into ``Service``)."""
from __future__ import annotations

import html
import json
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

from . import capital, nlp
from . import formatting as fmt
from .capital import KIND_ICON, KIND_LABEL, CapitalIntent
from .db import fmt_utc, new_uid
from .market import MarketError, is_crypto

log = logging.getLogger(__name__)
e = html.escape

CAPITAL_HELP = (
    "💼 <b>Как вести капитал</b> — пишите обычными фразами:\n\n"
    "<b>Пополнить счёт</b>\n«закинул 50к тенге на брокерский, вышло 110$» — сколько ушло и сколько пришло\n"
    "«отложил 300$ в копилку» · «перевёл 1000$ на депозит Kaspi»\n\n"
    "<b>Купить / продать</b>\n«купил 2 AAPL по 55$» · «купил 0.01 btc за 600$» · «продал 1 TSLA по 250»\n\n"
    "<b>Доход</b>\n«дивиденды AAPL 3$» · «проценты 12 000 тенге по депозиту»\n\n"
    "<b>Вывести</b>\n«вывел 100$ с брокерского»\n\n"
    "<b>Счета и имущество</b>\n«открыл депозит 1 000 000 тенге под 15%» · «актив машина 15000$»\n\n"
    "<b>Валюты</b>\n«обменял 100$ на 51 200 тенге» · «курс доллара 512 тенге» · «остаток 150000 тенге»\n\n"
    "Цены акций и крипты обновляются сами (бесплатные источники), можно задать вручную: «цена AAPL 190$». "
    "Деньги, отправленные на счета, — это не расходы: они уменьшают кошелёк и увеличивают капитал."
)


def _rate(v: float) -> str:
    return (f"{v:,.4f}" if v < 10 else f"{v:,.2f}").replace(",", " ")


class CapitalMixin:
    # ------------------------------------------------------------ accounts
    def _accounts(self) -> list[dict]:
        return [dict(r) for r in self.db.all("SELECT * FROM accounts ORDER BY id")]

    def _find_account(self, phrase: str | None, kind: str | None, symbol: str | None = None) -> dict | None:
        accounts = self._accounts()
        if phrase:
            title = capital.account_title(phrase, kind)
            for a in accounts:
                if a["name"].lower() == title.lower() or a["name"].lower() == phrase.lower():
                    return a
            scored = sorted(((max(nlp.match_score(phrase, a["name"]), nlp.match_score(a["name"], phrase)), a)
                             for a in accounts), key=lambda x: -x[0])
            if scored and scored[0][0] >= 0.5:
                return scored[0][1]
            same_kind = [a for a in accounts if a["kind"] == kind]
            if kind and len(same_kind) == 1 and capital.account_title(phrase, kind) == capital.DEFAULT_NAMES.get(kind):
                return same_kind[0]
            return None
        if symbol:
            holders = {m["account_id"] for m in self.db.all("SELECT account_id FROM moves WHERE symbol = ?", (symbol,))}
            if len(holders) == 1:
                return self.db.get("accounts", holders.pop())
        same_kind = [a for a in accounts if a["kind"] == kind]
        if len(same_kind) == 1:
            return same_kind[0]
        return None

    def _create_account(self, name: str, kind: str, currency: str, rate_pct: float | None = None) -> int:
        return self.db.insert("accounts", {"uid": new_uid(), "name": name, "kind": kind, "currency": currency.upper(),
                                           "rate_pct": rate_pct, "created_at": fmt_utc(self.now_utc())})

    def _insert_move(self, kind: str, msg_id: int | None, **f) -> int:
        row = {"uid": new_uid(), "kind": kind, "occurred_on": self.today().isoformat(),
               "created_at": fmt_utc(self.now_utc()), "source_msg_id": msg_id}
        row.update(f)
        return self.db.insert("moves", row)

    def _states(self):
        accounts = self._accounts()
        moves = [dict(m) for m in self.db.all("SELECT * FROM moves WHERE account_id IS NOT NULL")]
        return capital.compute_accounts(accounts, moves, self.market, self.today())

    def _state(self, account_id: int):
        return next((s for s in self._states() if s.id == account_id), None)

    def _rate_text(self, src_minor: int, src_cur: str, dst_minor: int, dst_cur: str) -> str:
        if not src_minor or not dst_minor or src_cur == dst_cur:
            return ""
        big, small = (src_minor, dst_minor) if src_minor >= dst_minor else (dst_minor, src_minor)
        big_cur, small_cur = (src_cur, dst_cur) if src_minor >= dst_minor else (dst_cur, src_cur)
        return f"курс 1 {small_cur} = {big / small:,.2f} {big_cur}".replace(",", " ")

    # ------------------------------------------------------------ intents
    def _h_capital(self, ci: CapitalIntent, msg_id: int | None) -> Reply:  # noqa: F821 - Reply from service
        from .service import Reply

        handler = getattr(self, f"_cap_{ci.kind}")
        try:
            return handler(ci, msg_id)
        except MarketError as exc:
            return Reply(f"⚠️ {exc}")

    def _cap_done(self, lines: list[str], created: list, msg_id, desc: str, updated=(), extra_buttons=None):
        from .service import Reply

        aid = self._action(desc, created=created, updated=list(updated), msg_id=msg_id)
        buttons = [[("Отменить", f"u:{aid}"), ("💼 Капитал", "cap:")]]
        if extra_buttons:
            buttons.insert(0, extra_buttons)
        return Reply("\n".join(lines), buttons, html=True)

    def _cap_rate(self, ci: CapitalIntent, msg_id):
        from .service import Reply

        if ci.rate_to is None:
            key = self._choice({"kind": "rate", "from": ci.rate_from, "value": str(ci.rate_value)})
            row = [(c, f"ch:{key}:{c}") for c in self.tracked_currencies if c != ci.rate_from]
            return Reply(f"1 {ci.rate_from} = {ci.rate_value} — в какой валюте?", [row])
        return self._set_manual_rate(ci.rate_from, ci.rate_to, ci.rate_value)

    def _set_manual_rate(self, frm: str, to: str, value: Decimal):
        from .service import Reply

        today = self.today()
        v = float(value)
        if v <= 0:
            return Reply("Курс должен быть больше нуля.")
        if frm == "USD":
            code, per_usd = to, v
        elif to == "USD":
            code, per_usd = frm, 1 / v
        else:
            base = self.market.per_usd(frm, today)
            if base is None:
                return Reply(f"Сначала нужен курс {frm} к доллару: «курс доллара … {frm}».")
            code, per_usd = to, v * base
        self.market.set_manual(code, per_usd, today)
        return Reply(f"💱 Курс на сегодня: <b>1 {frm} = {v:g} {to}</b> (ваш, ручной).\n"
                     f"Он используется для операций с сегодняшней датой; дальше — автоматические курсы.",
                     [[("💱 Все курсы", "fx:v")]], html=True)

    def _cap_exchange(self, ci: CapitalIntent, msg_id):
        from .service import Reply

        src_minor = fmt.to_minor(ci.src.amount)
        if ci.dst.amount and ci.dst.amount > 0:
            dst_minor = fmt.to_minor(ci.dst.amount)
        else:
            dst_minor = self.market.convert(src_minor, ci.src.currency, ci.dst.currency, self.today())
            if dst_minor is None:
                return Reply(f"Нет курса {ci.src.currency}→{ci.dst.currency}. Напишите, сколько получили: "
                             f"«обменял 100$ на 51 200 тенге».")
        with self.db.tx():
            mid = self._insert_move("exchange", msg_id, from_currency=ci.src.currency, from_minor=src_minor,
                                    to_currency=ci.dst.currency, to_minor=dst_minor)
            rate = self._rate_text(src_minor, ci.src.currency, dst_minor, ci.dst.currency)
            return self._cap_done([f"💱 Обмен: <b>−{fmt.money(src_minor, ci.src.currency)}</b> → "
                                   f"<b>+{fmt.money(dst_minor, ci.dst.currency)}</b>", e(rate)],
                                  [("moves", mid)], msg_id, "обмен валюты")

    def _resolve_or_create(self, phrase, kind, currency, created: list, rate_pct=None) -> tuple[dict, bool]:
        acc = self._find_account(phrase, kind)
        if acc:
            return acc, False
        name = capital.account_title(phrase or "", kind)
        aid = self._create_account(name, kind or "other", currency, rate_pct)
        created.append(("accounts", aid))
        return self.db.get("accounts", aid), True

    def _cap_deposit(self, ci: CapitalIntent, msg_id, withdraw: bool = False):
        from .service import Reply

        src_cur = ci.src.currency or self.currency
        src_minor = fmt.to_minor(ci.src.amount)
        with self.db.tx():
            created: list = []
            existing = self._find_account(ci.account, ci.account_kind)
            if withdraw and existing is None:
                return Reply(f"Не нашёл счёт «{e(ci.account or '')}». Счета — в /capital.", html=True)
            acc_cur = existing["currency"] if existing else ((ci.dst.currency if ci.dst else None) or src_cur)
            acc, is_new = (existing, False) if existing else self._resolve_or_create(
                ci.account, ci.account_kind, acc_cur, created)
            if withdraw:
                # amount is taken from the account (its currency unless stated); lands in the wallet
                from_cur = ci.src.currency or acc["currency"]
                from_minor = src_minor if from_cur == acc["currency"] else \
                    self.market.convert(src_minor, from_cur, acc["currency"], self.today())
                to_cur = (ci.dst.currency if ci.dst else None) or from_cur
                to_minor = fmt.to_minor(ci.dst.amount) if ci.dst else \
                    self.market.convert(from_minor, acc["currency"], to_cur, self.today())
                if from_minor is None or to_minor is None:
                    return Reply("Нет курса для пересчёта — укажите, сколько пришло: «вывел 100$ с брокерского, "
                                 "вышло 51 000 тенге».")
                st = self._state(acc["id"])
                free = st.value_minor if acc["kind"] in ("asset", "deposit") else st.cash_minor
                if from_minor > free:
                    return Reply(f"На «{e(acc['name'])}» свободно только {fmt.money(free, acc['currency'])}"
                                 + (" (остальное в бумагах — сначала продайте)" if st.holdings else "")
                                 + ". Ничего не записал.", html=True)
                mid = self._insert_move("withdraw", msg_id, account_id=acc["id"], from_currency=acc["currency"],
                                        from_minor=from_minor, to_currency=to_cur, to_minor=to_minor)
                state = self._state(acc["id"])
                lines = [f"{KIND_ICON[acc['kind']]} {e(acc['name'])}: <b>−{fmt.money(from_minor, acc['currency'])}</b>"
                         f" → в кошелёк +{fmt.money(to_minor, to_cur)}",
                         f"На счёте: {fmt.money(state.value_minor, acc['currency'])}"]
                return self._cap_done(lines, created + [("moves", mid)], msg_id, f"вывод с «{acc['name']}»")
            dst_cur = acc["currency"]
            if ci.dst:
                dst_minor = fmt.to_minor(ci.dst.amount)
                if ci.dst.currency and ci.dst.currency != dst_cur:
                    dst_minor = self.market.convert(dst_minor, ci.dst.currency, dst_cur, self.today())
            else:
                dst_minor = self.market.convert(src_minor, src_cur, dst_cur, self.today())
            if dst_minor is None:
                return Reply(f"Нет курса {src_cur}→{dst_cur}. Напишите, сколько пришло на счёт: "
                             f"«… вышло 110$».")
            mid = self._insert_move("deposit", msg_id, account_id=acc["id"], from_currency=src_cur,
                                    from_minor=src_minor, to_currency=dst_cur, to_minor=dst_minor)
            state = self._state(acc["id"])
            lines = [f"{KIND_ICON[acc['kind']]} {e(acc['name'])}: <b>+{fmt.money(dst_minor, dst_cur)}</b>"
                     + (f" (из {fmt.money(src_minor, src_cur)})" if src_cur != dst_cur else "")]
            rate = self._rate_text(src_minor, src_cur, dst_minor, dst_cur)
            if rate:
                lines.append(e(rate) + ("" if ci.dst else " — по текущему курсу"))
            lines.append(f"На счёте: {fmt.money(state.value_minor, dst_cur)}"
                         + (f" · <i>новый счёт ({KIND_LABEL[acc['kind']]}, {dst_cur})</i>" if is_new else ""))
            lines.append("<i>Это не расход: кошелёк уменьшился, капитал вырос.</i>")
            return self._cap_done(lines, created + [("moves", mid)], msg_id, f"пополнение «{acc['name']}»")

    def _cap_withdraw(self, ci: CapitalIntent, msg_id):
        return self._cap_deposit(ci, msg_id, withdraw=True)

    def _cap_open(self, ci: CapitalIntent, msg_id):
        from .service import Reply

        cur = (ci.src.currency if ci.src else None) or self.currency
        with self.db.tx():
            created: list = []
            acc, is_new = self._resolve_or_create(ci.account, ci.account_kind, cur, created, ci.rate_pct)
            updated = []
            if not is_new and ci.rate_pct is not None:
                updated.append(self._update("accounts", acc["id"], {"rate_pct": ci.rate_pct}))
            if ci.src:
                minor = fmt.to_minor(ci.src.amount)
                conv = minor if cur == acc["currency"] else self.market.convert(minor, cur, acc["currency"], self.today())
                if conv is None:
                    return Reply("Нет курса для пересчёта в валюту счёта.")
                # opening balance: money that was already there, not taken from the wallet
                created.append(("moves", self._insert_move("deposit", msg_id, account_id=acc["id"], to_currency=acc["currency"],
                                                           to_minor=conv, note="начальный баланс")))
            acc = self.db.get("accounts", acc["id"])
            state = self._state(acc["id"])
            lines = [f"{KIND_ICON[acc['kind']]} {'Новый счёт' if is_new else 'Счёт'}: <b>{e(acc['name'])}</b> · "
                     f"{KIND_LABEL[acc['kind']]} · {acc['currency']}"
                     + (f" · {acc['rate_pct']:g}% годовых" if acc["rate_pct"] else ""),
                     f"На счёте: {fmt.money(state.value_minor, acc['currency'])}"]
            if ci.src:
                lines.append("<i>Записал как начальный баланс, кошелёк не трогал. Если переводите из кошелька — "
                             "«закинул … на " + e(acc["name"].lower()) + "».</i>")
            if acc["rate_pct"]:
                lines.append("<i>Проценты считаю примерно (простые, без капитализации), для ориентира.</i>")
            return self._cap_done(lines, created, msg_id, f"счёт «{acc['name']}»", updated)

    def _cap_buy(self, ci: CapitalIntent, msg_id, sell: bool = False):
        from .service import Reply

        sym = ci.symbol
        qty = float(ci.qty)
        price_cur = ci.unit_price.currency or "USD"
        total_minor = fmt.to_minor(ci.unit_price.amount * ci.qty)
        with self.db.tx():
            created: list = []
            acc = self._find_account(ci.account, ci.account_kind, sym if sell or not ci.account else None)
            if acc is None and sell:
                return Reply(f"Не нашёл, где лежит {sym}. Укажите счёт: «продал 1 {sym} по 250 на Freedom».")
            if acc is None:
                acc, _ = self._resolve_or_create(ci.account, ci.account_kind, price_cur, created)
            acc_cur = acc["currency"]
            amount = total_minor if price_cur == acc_cur else \
                self.market.convert(total_minor, price_cur, acc_cur, self.today())
            if amount is None:
                return Reply(f"Нет курса {price_cur}→{acc_cur} для пересчёта.")
            state = self._state(acc["id"])
            note = ""
            if sell:
                have = next((h.qty for h in (state.holdings if state else []) if h.symbol == sym), 0.0)
                if have + 1e-9 < qty:
                    return Reply(f"На «{e(acc['name'])}» только {capital.fmt_qty(have)} {sym} — продать "
                                 f"{capital.fmt_qty(qty)} нельзя. Ничего не записал.", html=True)
                mid = self._insert_move("sell", msg_id, account_id=acc["id"], symbol=sym, qty=qty,
                                        to_currency=acc_cur, to_minor=amount)
            else:
                cash = state.cash_minor if state else 0
                if cash < amount:
                    short = amount - max(cash, 0)
                    created.append(("moves", self._insert_move(
                        "deposit", msg_id, account_id=acc["id"], from_currency=acc_cur, from_minor=short,
                        to_currency=acc_cur, to_minor=short, note="авто: на покупку")))
                    note = (f"\n<i>На счёте не хватало {fmt.money(short, acc_cur)} — записал пополнение из "
                            f"кошелька. Если деньги пришли из другой валюты, отмените и напишите «закинул … на "
                            f"«{e(acc['name'])}», вышло …», потом покупку ещё раз.</i>")
                mid = self._insert_move("buy", msg_id, account_id=acc["id"], symbol=sym, qty=qty,
                                        from_currency=acc_cur, from_minor=amount)
            if not self.db.scalar("SELECT 1 FROM prices WHERE symbol = ? AND day >= ?", (sym, self.today().isoformat())):
                self.market.set_price(sym, float(ci.unit_price.amount), price_cur, self.today(), "trade")
            created.append(("moves", mid))
            state = self._state(acc["id"])
            h = next((h for h in state.holdings if h.symbol == sym), None)
            verb = "Продал" if sell else "Купил"
            lines = [f"{KIND_ICON[acc['kind']]} {verb} <b>{capital.fmt_qty(qty)} {e(sym)}</b> по "
                     f"{fmt.money(fmt.to_minor(ci.unit_price.amount), price_cur)} = "
                     f"<b>{fmt.money(total_minor, price_cur)}</b> · {e(acc['name'])}"]
            if h and h.qty > 1e-12:
                lines.append(f"Всего {e(sym)}: {capital.fmt_qty(h.qty)} · средняя цена "
                             f"{fmt.money(round(h.cost_minor / h.qty), acc_cur)}")
            lines.append(f"Свободно на счёте: {fmt.money(state.cash_minor, acc_cur)}")
            return self._cap_done(lines + ([note] if note else []), created, msg_id,
                                  f"{'продажа' if sell else 'покупка'} {sym}")

    def _cap_sell(self, ci: CapitalIntent, msg_id):
        return self._cap_buy(ci, msg_id, sell=True)

    def _cap_dividend(self, ci: CapitalIntent, msg_id):
        from .service import Reply

        with self.db.tx():
            acc = self._find_account(ci.account, ci.account_kind, ci.symbol)
            if acc is None:
                return Reply("На какой счёт? Например: «дивиденды AAPL 3$ на Freedom».")
            cur = ci.dst.currency or acc["currency"]
            minor = fmt.to_minor(ci.dst.amount)
            conv = minor if cur == acc["currency"] else self.market.convert(minor, cur, acc["currency"], self.today())
            if conv is None:
                return Reply("Нет курса для пересчёта.")
            mid = self._insert_move(ci.kind, msg_id, account_id=acc["id"], symbol=ci.symbol, to_currency=acc["currency"],
                                    to_minor=conv)
            label = "Дивиденды" if ci.kind == "dividend" else "Проценты"
            return self._cap_done([f"{KIND_ICON[acc['kind']]} {label}{(' ' + e(ci.symbol)) if ci.symbol else ''}: "
                                   f"<b>+{fmt.money(conv, acc['currency'])}</b> · {e(acc['name'])}"],
                                  [("moves", mid)], msg_id, label.lower())

    _cap_interest = _cap_dividend

    def _cap_price(self, ci: CapitalIntent, msg_id):
        from .service import Reply

        self.market.set_price(ci.symbol, float(ci.unit_price.amount), ci.unit_price.currency or "USD", self.today())
        return Reply(f"Цена {e(ci.symbol)}: <b>{fmt.money(fmt.to_minor(ci.unit_price.amount), ci.unit_price.currency)}"
                     f"</b> (вручную, на сегодня)", [[("💼 Капитал", "cap:")]], html=True)

    def _cap_asset_value(self, ci: CapitalIntent, msg_id):
        cur = ci.dst.currency or self.currency
        with self.db.tx():
            created: list = []
            acc, is_new = self._resolve_or_create(ci.account, "asset", cur, created)
            minor = fmt.to_minor(ci.dst.amount)
            conv = minor if cur == acc["currency"] else self.market.convert(minor, cur, acc["currency"], self.today())
            mid = self._insert_move("value", msg_id, account_id=acc["id"], to_currency=acc["currency"], to_minor=conv)
            return self._cap_done([f"🏠 {e(acc['name'])}: оценка <b>{fmt.money(conv, acc['currency'])}</b>"
                                   + (" · новый актив" if is_new else ""),
                                   "<i>Обновляйте оценку той же фразой, когда цена изменится.</i>"],
                                  created + [("moves", mid)], msg_id, f"оценка «{acc['name']}»")

    # ------------------------------------------------------------ views
    def net_worth(self, cur: str) -> dict:
        states = self._states()
        pockets = self._pockets()
        wallet = sum(self._conv(v[1], c, cur) or 0 for c, v in pockets.items())
        accounts = []
        for s in states:
            v = self._conv(s.value_minor, s.currency, cur)
            accounts.append((s, v if v is not None else 0))
        invested = sum(self._conv(s.invested_minor, s.currency, cur) or 0 for s in states)
        total = wallet + sum(v for _, v in accounts)
        return {"total": total, "wallet": wallet, "pockets": pockets, "accounts": accounts, "invested": invested,
                "capital": sum(v for _, v in accounts)}

    def _networth_change(self, cur: str, days: int = 30) -> tuple[int, str] | None:
        row = self.db.one("SELECT day, usd FROM networth WHERE day <= ? ORDER BY day DESC LIMIT 1",
                          ((self.today() - timedelta(days=days)).isoformat(),))
        if row is None:
            row = self.db.one("SELECT day, usd FROM networth WHERE day < ? ORDER BY day LIMIT 1",
                              (self.today().isoformat(),))
        if row is None:
            return None
        then = self._conv(round(row["usd"] * 100), "USD", cur)
        return (then, row["day"]) if then is not None else None

    def view_capital(self, cur: str | None = None):
        from .service import Reply

        cur = cur or self.report_currency
        nw = self.net_worth(cur)
        accounts = nw["accounts"]
        if not accounts and not nw["pockets"]:
            return Reply("💼 <b>Капитал</b>\n\nПока пусто. " + CAPITAL_HELP.split("\n\n", 1)[1],
                         [[("❓ Как вести учёт", "cap:help")]], html=True)
        lines = [f"💼 <b>Капитал</b> · {cur}", f"<b>{fmt.money(nw['total'], cur)}</b>"]
        ch = self._networth_change(cur)
        if ch and ch[0]:
            diff = nw["total"] - ch[0]
            pct = diff * 100 / ch[0] if ch[0] else 0
            lines[-1] += f"  {'▲' if diff >= 0 else '▼'} {abs(pct):.1f}% с {fmt.day(date.fromisoformat(ch[1]))}"
        if nw["pockets"]:
            lines += ["", "👛 <b>Кошелёк</b> (расчётный остаток)",
                      " · ".join(fmt.money(v[1], c) for c, v in nw["pockets"].items())
                      + (f" ≈ {fmt.money(nw['wallet'], cur)}" if len(nw["pockets"]) > 1 or
                         next(iter(nw["pockets"])) != cur else "")]
        missing = []
        for s, v in accounts:
            lines.append("")
            head = f"{KIND_ICON[s.kind]} <b>{e(s.name)}</b> — <b>{fmt.money(s.value_minor, s.currency)}</b>"
            if s.currency != cur:
                head += f" ≈ {fmt.money(v, cur)}"
            if s.invested_minor and s.kind != "asset":
                pnl = s.pnl_minor
                head += f" · {'+' if pnl >= 0 else '−'}{fmt.money(abs(pnl))} ({pnl * 100 / s.invested_minor:+.1f}%)"
            lines.append(head)
            for h in s.holdings:
                if h.value_minor is None:
                    lines.append(f"   {e(h.symbol)} {capital.fmt_qty(h.qty)} — нет цены")
                    continue
                pnl = h.pnl_minor
                pct = f" · {pnl * 100 / h.cost_minor:+.1f}%" if h.cost_minor else ""
                lines.append(f"   {e(h.symbol)} {capital.fmt_qty(h.qty)} × {h.price:,.2f}".replace(",", " ")
                             + f" = {fmt.money(h.value_minor)}{pct}")
            if s.holdings and s.cash_minor:
                lines.append(f"   свободно {fmt.money(s.cash_minor)}")
            if s.rate_pct:
                lines.append(f"   {s.rate_pct:g}% годовых · ≈ +{fmt.money(s.accrued_minor)} начислено (оценка)")
            missing += s.missing_prices
        if missing:
            lines += ["", f"⚠️ Нет цены для {', '.join(sorted(set(missing)))} — обновится сама или задайте: "
                      f"«цена {missing[0]} 100$»"]
        stamp = self.db.get_setting("prices_fetched_at")
        if stamp:
            lines.append(f"<i>Цены обновлены {fmt.day(self.local_of(stamp).date(), self.today())} "
                         f"{fmt.hm(self.local_of(stamp))}</i>")
        warn = self._fx_warning()
        if warn:
            lines += ["", e(warn)]
        buttons = [[("📊 Картинкой", f"cap:img:{cur}"), ("🔄 Обновить цены", f"cap:ref:{cur}")],
                   self._currency_row("cap:", cur)]
        acc_buttons = [(f"{KIND_ICON[s.kind]} {fmt.short(s.name, 18)}", f"acc:{s.id}:{cur}") for s, _ in accounts]
        buttons += [acc_buttons[i:i + 2] for i in range(0, len(acc_buttons), 2)]
        buttons.append([("❓ Как вести учёт", "cap:help"), ("💱 Курсы", "fx:v")])
        return Reply("\n".join(lines), buttons, html=True)

    def account_card(self, account_id: int, cur: str | None = None):
        from .service import Reply

        s = self._state(account_id)
        if s is None:
            return Reply("Счёт не найден.", edit=True)
        cur = cur or self.report_currency
        lines = [f"{KIND_ICON[s.kind]} <b>{e(s.name)}</b> · {KIND_LABEL[s.kind]} · {s.currency}",
                 f"Стоимость: <b>{fmt.money(s.value_minor, s.currency)}</b>"]
        if s.currency != cur:
            v = self._conv(s.value_minor, s.currency, cur)
            if v is not None:
                lines[-1] += f" ≈ {fmt.money(v, cur)}"
        if s.kind != "asset":
            lines.append(f"Вложено: {fmt.money(s.invested_minor, s.currency)} · результат "
                         f"{'+' if s.pnl_minor >= 0 else '−'}{fmt.money(abs(s.pnl_minor), s.currency)}")
        if s.income_minor:
            lines.append(f"Дивиденды и проценты: +{fmt.money(s.income_minor, s.currency)}")
        if s.holdings:
            lines += ["", "<b>Позиции</b>"]
            for h in s.holdings:
                avg = round(h.cost_minor / h.qty) if h.qty else 0
                if h.value_minor is None:
                    lines.append(f"{e(h.symbol)} · {capital.fmt_qty(h.qty)} шт · средняя {fmt.money(avg)} · нет цены")
                else:
                    lines.append(f"{e(h.symbol)} · {capital.fmt_qty(h.qty)} шт · средняя {fmt.money(avg)} · "
                                 f"сейчас {h.price:,.2f}".replace(",", " ") +
                                 f" {h.price_currency} · {'+' if h.pnl_minor >= 0 else '−'}{fmt.money(abs(h.pnl_minor))}")
            lines.append(f"Свободно: {fmt.money(s.cash_minor, s.currency)}")
        moves = self.db.all("SELECT * FROM moves WHERE account_id = ? ORDER BY occurred_on DESC, id DESC LIMIT 12",
                            (account_id,))
        if moves:
            lines += ["", "<b>История</b>"]
            names = {"deposit": "пополнение", "withdraw": "вывод", "buy": "покупка", "sell": "продажа",
                     "dividend": "дивиденды", "interest": "проценты", "fee": "комиссия", "value": "оценка"}
            for m in moves:
                d = date.fromisoformat(m["occurred_on"]).strftime("%d.%m")
                if m["kind"] in ("buy", "sell"):
                    lines.append(f"{d} {names[m['kind']]} {capital.fmt_qty(m['qty'])} {e(m['symbol'])}")
                elif m["kind"] == "withdraw":
                    lines.append(f"{d} вывод −{fmt.money(m['from_minor'], m['from_currency'])}")
                else:
                    extra = f" (из {fmt.money(m['from_minor'], m['from_currency'])})" if m["from_currency"] and \
                        m["from_currency"] != m["to_currency"] else ""
                    lines.append(f"{d} {names[m['kind']]} +{fmt.money(m['to_minor'], m['to_currency'])}{extra}")
        return Reply("\n".join(lines), [[("🗑 Удалить счёт", f"acc:x:{account_id}"), ("◀ Капитал", f"cap:{cur}")]],
                     html=True)

    def delete_account(self, account_id: int):
        from .service import Reply

        with self.db.tx():
            acc = self.db.get("accounts", account_id)
            if acc is None:
                return Reply("Уже удалён.", edit=True)
            moves = [dict(m) for m in self.db.all("SELECT * FROM moves WHERE account_id = ?", (account_id,))]
            self.db.execute("DELETE FROM moves WHERE account_id = ?", (account_id,))
            self.db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            aid = self._action(f"удаление счёта «{acc['name']}»",
                               deleted=[("accounts", acc)] + [("moves", m) for m in moves])
        return Reply(f"🗑 Удалён счёт «{e(acc['name'])}» и его история.", [[("Отменить", f"u:{aid}")]],
                     edit=True, html=True)

    def capital_image(self, cur: str | None = None):
        from . import charts
        from .service import Reply

        cur = cur or self.report_currency
        nw = self.net_worth(cur)
        colors = self._account_colors([s.name for s, _ in nw["accounts"]])
        history = []
        for r in self.db.all("SELECT day, usd FROM networth WHERE day >= ? ORDER BY day",
                             ((self.today() - timedelta(days=180)).isoformat(),)):
            v = self._conv(round(r["usd"] * 100), "USD", cur)
            if v is not None:
                history.append((r["day"], v))
        ch = self._networth_change(cur)
        holdings = []
        for s, _ in nw["accounts"]:
            for h in s.holdings:
                if h.value_minor is not None:
                    holdings.append((h.symbol, capital.fmt_qty(h.qty), self._conv(h.value_minor, s.currency, cur) or 0,
                                     h.pnl_minor * 100 / h.cost_minor if h.cost_minor else None))
        rep = charts.CapitalReport(
            currency=cur, total=nw["total"], change=(nw["total"] - ch[0], ch[1]) if ch and ch[0] else None,
            wallet=nw["wallet"], invested=nw["invested"], capital=nw["capital"],
            parts=[(s.name, KIND_LABEL[s.kind], v) for s, v in nw["accounts"] if v > 0]
            + ([("Кошелёк", "наличные и карты", nw["wallet"])] if nw["wallet"] > 0 else []),
            colors=colors, history=history, holdings=sorted(holdings, key=lambda x: -x[2])[:6])
        png = charts.render_capital(rep)
        text = f"💼 Капитал: {fmt.money(nw['total'], cur)}"
        buttons = [self._currency_row("cap:img:", cur), [("◀ Подробно", f"cap:{cur}")]]
        return Reply(text, buttons, photo=(f"capital-{self.today().isoformat()}.png", png))

    def _account_colors(self, names: list[str]) -> dict[str, int]:
        colors: dict[str, int] = json.loads(self.db.get_setting("account_colors", "{}"))
        changed = False
        for n in names + ["Кошелёк"]:
            if n not in colors and len(colors) < 8:
                colors[n] = len(colors)
                changed = True
        if changed:
            self.db.set_setting("account_colors", json.dumps(colors, ensure_ascii=False))
        return colors

    # ------------------------------------------------------------ rates view
    def view_rates(self):
        from .service import Reply

        cur_list = self.tracked_currencies
        today = self.today()
        lines = ["💱 <b>Курсы валют</b>", ""]
        sources = []
        for c in cur_list:
            if c == "USD":
                continue
            info = self.market.rate_info(c)
            if info is None:
                lines.append(f"1 USD = <i>нет курса {c}</i>")
                continue
            per_usd, day, src = info
            lines.append(f"1 USD = <b>{_rate(per_usd)} {c}</b>")
            label = {"api": "авто", "manual": "ваш", "peg": "фикс."}.get(src, src)
            if day:
                sources.append(f"{c}: {label}, {fmt.day(date.fromisoformat(day), today)}")
            else:
                sources.append(f"{c}: {label}")
        others = [c for c in cur_list if c != "USD"]
        for i, a in enumerate(others):
            for b in others[i + 1:]:
                pa, pb = self.market.per_usd(a, today), self.market.per_usd(b, today)
                if pa and pb:
                    hi, lo = (a, b) if pb / pa >= 1 else (b, a)
                    lines.append(f"1 {hi} = <b>{_rate(max(pb / pa, pa / pb))} {lo}</b>")
        if sources:
            lines += ["", "<i>" + e(" · ".join(sources)) + "</i>"]
        lines += ["", f"Отчёты в: <b>{self.report_currency}</b> · без валюты пишу в: <b>{self.currency}</b>",
                  "Свой курс (обменника): «курс доллара 512 тенге»."]
        err = self.db.get_setting("market_error")
        if err:
            lines.append(f"<i>Последняя ошибка обновления: {e(err[:150])}</i>")
        return Reply("\n".join(lines), [
            [("Отчёты в " + c, f"fx:rc:{c}") for c in cur_list],
            [("Ввод в " + c, f"fx:ic:{c}") for c in cur_list],
            [("🔄 Обновить курсы", "fx:r")],
        ], html=True)

    def _cb_fx(self, parts: list[str]):
        from .service import Reply

        op = parts[1]
        if op == "rc":
            with self.db.tx():
                self.db.set_setting("report_currency", parts[2])
        elif op == "ic":
            with self.db.tx():
                self.db.set_setting("currency", parts[2])
        elif op == "r":
            self.refresh_market(force=True)
        r = self.view_rates()
        r.edit = True
        return r

    # ------------------------------------------------------------ market refresh (scheduler, worker thread)
    def _codes_in_use(self) -> set[str]:
        codes = set(self.tracked_currencies) | {self.currency, self.report_currency}
        codes |= {r[0] for r in self.db.all("SELECT DISTINCT currency FROM transactions")}
        codes |= {r[0] for r in self.db.all("SELECT DISTINCT currency FROM accounts")}
        return {c.upper() for c in codes if c}

    def refresh_market(self, force: bool = False) -> dict:
        """Daily rates, historical backfill, prices every 6h, net-worth snapshot. Never raises."""
        now = self.now_utc()
        result: dict = {"rates": None, "prices_failed": {}, "backfilled": 0}
        codes = self._codes_in_use()
        try:
            if force or self.db.get_setting("rates_fetched_on") != self.today().isoformat():
                result["rates"] = self.market.refresh_latest(codes)
                self.db.set_setting("rates_fetched_on", self.today().isoformat())
                self.db.del_setting("market_error")
            # historical rates for days that have operations in non-USD currencies
            need = []
            for r in self.db.all("SELECT DISTINCT occurred_on, currency FROM transactions WHERE currency NOT IN "
                                 "('USD','AED') ORDER BY occurred_on DESC LIMIT 400"):
                d = date.fromisoformat(r[0])
                if d < self.today() and not self.market.has_rate_on(r[1], d):
                    need.append(d)
            for d in sorted(set(need), reverse=True)[:5]:
                if self.market.backfill(d, codes):
                    result["backfilled"] += 1
        except MarketError as exc:
            log.warning("rates refresh failed: %s", exc)
            self.db.set_setting("market_error", str(exc)[:300])
        symbols = {r[0] for r in self.db.all("SELECT DISTINCT symbol FROM moves WHERE symbol IS NOT NULL")}
        last = self.db.get_setting("prices_fetched_at")
        if symbols and (force or not last or (now - datetime.strptime(last, "%Y-%m-%d %H:%M:%S")) > timedelta(hours=6)):
            result["prices_failed"] = self.market.refresh_prices(symbols, self.today())
            self.db.set_setting("prices_fetched_at", fmt_utc(now))
        self.snapshot_networth()
        return result

    def snapshot_networth(self) -> None:
        if not self._accounts() and not self._balances():
            return
        nw = self.net_worth("USD")
        with self.db.tx():
            self.db.execute("INSERT INTO networth(day, usd, detail) VALUES (?, ?, ?) ON CONFLICT(day) DO UPDATE SET "
                            "usd = excluded.usd, detail = excluded.detail",
                            (self.today().isoformat(), nw["total"] / 100,
                             json.dumps({"wallet": nw["wallet"] / 100, "capital": nw["capital"] / 100})))

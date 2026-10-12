"""Multi-currency totals, wallet pockets, rates, and the capital module (offline: rates stored by hand)."""
import json
from datetime import date, datetime

import pytest

from bot.db import DB
from bot.market import Market, MarketError
from bot.service import Service
from tests.conftest import plain


def offline(url):
    raise MarketError("offline")


@pytest.fixture
def fx(db, clock):
    svc = Service(db, clock=clock, fetch=offline)
    svc.market.store_rates("2026-10-01", {"KZT": 500.0, "AED": 3.6725, "BTC": 1 / 60000})
    return svc


def say(svc, mid, text):
    r = svc.process_text(text, mid())
    return plain(r.text) if r else None


# ---------------------------------------------------------------- currencies

def test_totals_convert_each_operation(fx, mid):
    say(fx, mid, "кофе 18")                  # AED
    say(fx, mid, "такси 5000 тенге")         # 10 USD = 36.73 AED
    say(fx, mid, "обед 10$")                 # 36.73 AED
    m = plain(fx.view_money("AED").text)
    assert "Сегодня 91.46 AED" in m
    assert "Сегодня 24.90 USD" in plain(fx.view_money("USD").text)
    assert "Сегодня 12 450.65 KZT" in plain(fx.view_money("KZT").text)


def test_historical_rate_is_used(fx, mid, clock):
    fx.market.store_rates("2026-10-12", {"KZT": 400.0})
    clock.set_local(datetime(2026, 10, 5, 12))
    say(fx, mid, "такси 5000 тенге")          # on 5 Oct the rate was 500 -> 10 USD
    clock.set_local(datetime(2026, 10, 12, 12))
    assert "Месяц 10 USD" in plain(fx.view_money("USD").text)


def test_missing_rate_is_reported_not_guessed(db, clock, mid):
    svc = Service(db, clock=clock, fetch=offline)
    svc.process_text("такси 5000 тенге", mid())
    m = plain(svc.view_money("AED").text)
    assert "Нет курса для KZT" in m and "Сегодня 0 AED" in m


def test_manual_rate(db, clock, mid):
    svc = Service(db, clock=clock, fetch=offline)
    r = say(svc, mid, "курс доллара 512 тенге")
    assert "1 USD = 512 KZT" in r
    assert svc.market.per_usd("KZT", date(2026, 10, 12)) == 512
    say(svc, mid, "такси 5120 тенге")
    assert "Сегодня 10 USD" in plain(svc.view_money("USD").text)


def test_rate_without_second_currency_asks(fx, mid):
    r = fx.process_text("курс дирхама 139", mid())
    assert "в какой валюте" in r.text
    fx.handle_callback(next(d for row in r.buttons for t, d in row if t == "KZT"))
    assert round(fx.market.per_usd("KZT", date(2026, 10, 12)), 2) == round(139 * 3.6725, 2)


def test_report_currency_switch_button(fx, mid):
    say(fx, mid, "кофе 18")
    r = fx.view_money()
    usd_cb = next(d for row in r.buttons for t, d in row if t == "USD")
    r2 = fx.handle_callback(usd_cb)
    assert "· USD" in plain(r2.text) and fx.report_currency == "USD"


def test_wallet_pockets_and_exchange(fx, mid):
    say(fx, mid, "остаток 1000")
    say(fx, mid, "остаток 100000 тенге")
    say(fx, mid, "такси 5000 тенге")
    r = say(fx, mid, "обменял 100 aed на 13 600 тенге")
    assert "−100 AED → +13 600 KZT" in r
    p = fx._pockets()
    assert p["AED"][1] == 90000 and p["KZT"][1] == 10860000


def test_old_single_balance_is_migrated(db, clock, mid):
    db.set_setting("balance_minor", 50000)
    db.set_setting("balance_set_at", "2026-10-12 09:00:00")
    db.set_setting("balance_after_tx", 0)
    svc = Service(db, clock=clock, fetch=offline)
    svc.process_text("кофе 20", mid())
    assert svc._pockets()["AED"][1] == 48000


def test_market_refresh_parses_sources(db, clock):
    payload = json.dumps({"date": "2026-10-12", "usd": {"aed": 3.6725, "kzt": 515.5, "btc": 0.0000155}}).encode()
    svc = Service(db, clock=clock, fetch=lambda url: payload)
    res = svc.refresh_market(force=True)
    assert res["rates"] == "2026-10-12"
    assert svc.market.per_usd("KZT", date(2026, 10, 12)) == 515.5


def test_market_falls_back_to_second_source(db, clock):
    def fetch(url):
        if "jsdelivr" in url:
            raise MarketError("blocked")
        return json.dumps({"date": "2026-10-12", "usd": {"kzt": 510.0}}).encode()
    svc = Service(db, clock=clock, fetch=fetch)
    svc.refresh_market(force=True)
    assert svc.market.per_usd("KZT", date(2026, 10, 12)) == 510.0


def test_market_failure_is_recorded_not_raised(db, clock):
    svc = Service(db, clock=clock, fetch=offline)
    svc.refresh_market(force=True)
    assert "offline" in svc.db.get_setting("market_error")
    assert "Последняя ошибка" in plain(svc.view_rates().text)


def test_stock_price_yahoo_then_stooq():
    d = DB(":memory:")
    yahoo = json.dumps({"chart": {"result": [{"meta": {"regularMarketPrice": 191.5, "currency": "USD"}}]}}).encode()
    m = Market(d, fetch=lambda url: yahoo)
    assert m.fetch_stock("AAPL") == (191.5, "USD", "yahoo")

    def fetch(url):
        if "yahoo" in url:
            raise MarketError("429")
        return b"Symbol,Date,Time,Open,High,Low,Close,Volume\nAAPL.US,2026-10-12,22:00:00,190,192,189,190.7,1\n"
    assert Market(d, fetch=fetch).fetch_stock("AAPL") == (190.7, "USD", "stooq")


# ---------------------------------------------------------------- capital

def test_deposit_with_real_exchange_rate(fx, mid):
    say(fx, mid, "остаток 200000 тенге")
    r = say(fx, mid, "закинул 50к тенге на брокерский, вышло 104$")
    assert "Брокерский счёт: +104 USD (из 50 000 KZT)" in r and "новый счёт" in r
    assert "1 USD = 480.77 KZT" in r
    assert fx._pockets()["KZT"][1] == 15000000       # 150 000 KZT left in the wallet
    # not an expense
    assert fx.db.scalar("SELECT COUNT(*) FROM transactions") == 0


def test_deposit_without_received_amount_uses_rate(fx, mid):
    r = say(fx, mid, "закинул 50к тенге на брокерский")
    assert "+50 000 KZT" in r   # new account takes the source currency


def test_buy_sell_average_cost_and_pnl(fx, mid):
    say(fx, mid, "закинул 1000$ на брокерский")
    say(fx, mid, "купил 2 AAPL по 100$")
    say(fx, mid, "купил 2 AAPL по 150$")
    r = say(fx, mid, "продал 1 AAPL по 200$")
    assert "Всего AAPL: 3 · средняя цена 125 USD" in r
    fx.market.set_price("AAPL", 200, "USD", date(2026, 10, 12))
    st = fx._states()[0]
    h = st.holdings[0]
    assert h.qty == 3 and h.cost_minor == 37500 and h.value_minor == 60000
    assert st.cash_minor == 100000 - 50000 + 20000
    assert st.pnl_minor == st.value_minor - 100000


def test_cannot_sell_more_than_held(fx, mid):
    say(fx, mid, "закинул 100$ на брокерский")
    say(fx, mid, "купил 1 TSLA по 50$")
    r = say(fx, mid, "продал 5 TSLA по 60$")
    assert "Ничего не записал" in r


def test_buy_without_cash_records_topup(fx, mid):
    r = say(fx, mid, "купил 0.01 btc за 600$")
    assert "Крипта" in r and "не хватало 600 USD" in r
    st = fx._states()[0]
    assert st.cash_minor == 0 and st.holdings[0].symbol == "BTC"
    assert st.holdings[0].value_minor == 60000      # BTC price from stored rates


def test_withdraw_limited_to_free_cash(fx, mid):
    say(fx, mid, "закинул 100$ на брокерский")
    say(fx, mid, "купил 1 TSLA по 80$")
    assert "свободно только 20 USD" in say(fx, mid, "вывел 50$ с брокерского")
    assert "−20 USD" in say(fx, mid, "вывел 20$ с брокерского")


def test_deposit_account_with_interest(fx, mid, clock):
    r = say(fx, mid, "открыл депозит 1 000 000 тенге под 15%")
    assert "Депозит · депозит · KZT · 15% годовых" in r and "начальный баланс" in r
    clock.set_local(datetime(2027, 4, 11, 12))
    st = fx._states()[0]
    assert st.accrued_minor == round(100000000 * 0.15 * 181 / 365)


def test_asset_and_net_worth(fx, mid):
    say(fx, mid, "остаток 3672.50")            # AED = 1000 USD
    say(fx, mid, "актив машина 15000$")
    say(fx, mid, "закинул 500$ на копилку")
    nw = fx.net_worth("USD")
    # wallet 1000 USD (AED pocket untouched: the 500$ came from dollars) + car 15000 + savings 500
    assert nw["total"] == 100000 + 1500000 + 50000
    text = plain(fx.view_capital("USD").text)
    assert "Машина — 15 000 USD" in text and "Копилка" in text


def test_capital_actions_undo(fx, mid):
    r = fx.process_text("закинул 50к тенге на брокерский, вышло 104$", mid())
    fx.handle_callback(r.buttons[0][0][1])
    assert fx.db.scalar("SELECT COUNT(*) FROM accounts") == 0
    assert fx.db.scalar("SELECT COUNT(*) FROM moves") == 0


def test_delete_account_and_undo(fx, mid):
    say(fx, mid, "закинул 100$ на брокерский")
    aid = fx.db.scalar("SELECT id FROM accounts")
    r = fx.handle_callback(f"acc:x:{aid}")
    assert fx.db.scalar("SELECT COUNT(*) FROM accounts") == 0
    fx.handle_callback(r.buttons[0][0][1])
    assert fx.db.scalar("SELECT COUNT(*) FROM moves") == 1


def test_ordinary_purchases_are_not_investments(fx, mid):
    assert "Записал" in say(fx, mid, "купил 2 батарейки за 10")
    assert "Записал" in say(fx, mid, "Купил продукты за 120 дирхам")
    assert fx.db.scalar("SELECT COUNT(*) FROM moves") == 0


def test_capital_views_render(fx, mid):
    for t in ["остаток 1000", "закинул 100$ на брокерский", "купил 1 AAPL по 50$", "актив машина 15000$"]:
        say(fx, mid, t)
    fx.market.set_price("AAPL", 60, "USD", date(2026, 10, 12))
    fx.snapshot_networth()
    img = fx.capital_image("USD")
    assert img.photo[1][:8] == b"\x89PNG\r\n\x1a\n"
    aid = fx.db.scalar("SELECT id FROM accounts WHERE name = 'Брокерский счёт'")
    card = plain(fx.account_card(aid, "USD").text)
    assert "AAPL · 1 шт · средняя 50 · сейчас 60.00 USD · +10" in card
    assert "Курсы валют" in plain(fx.view_rates().text)


def test_category_drilldown(fx, mid):
    say(fx, mid, "кофе 18")
    say(fx, mid, "обед 10$")
    lst = fx.handle_callback("sc:m:AED")
    cb = next(d for row in lst.buttons for t, d in row if t.startswith("Кафе"))
    detail = plain(fx.handle_callback(cb).text)
    assert "Кафе и рестораны" in detail and "−36.73 (10 USD) · обед" in detail and "2 операции" in detail

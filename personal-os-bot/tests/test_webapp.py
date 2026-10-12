"""Mini App payload: compact, decodable, trimmed to fit the link limit."""
from datetime import date

from bot import webapp
from bot.market import MarketError
from bot.service import Service


def offline(url):
    raise MarketError("offline")


def test_roundtrip_and_content(db, clock, mid):
    svc = Service(db, clock=clock, fetch=offline)
    svc.market.store_rates("2026-10-01", {"KZT": 500.0})
    for t in ["кофе 18", "такси 5000 тенге", "Получил зарплату 6500", "возврат за кроссовки 20", "остаток 1000",
              "закинул 100$ на брокерский", "купил 1 AAPL по 50$"]:
        svc.process_text(t, mid())
    u = webapp.url(svc, "https://me.github.io/app/index.html")
    assert u.startswith("https://me.github.io/app/index.html#d=")
    d = webapp.decode(u.split("#d=")[1])
    assert d["today"] == "2026-10-12" and d["cur"] == "AED" and d["fx"]["KZT"] == 500.0
    kinds = sorted(t[3] for t in d["tx"])
    assert kinds == [0, 0, 1, 2]
    taxi = next(t for t in d["tx"] if d["ds"][t[4]] == "такси")
    assert taxi[2] == 1000 and d["oc"][taxi[5]] == "KZT" and taxi[6] == 500000   # 10 USD, original 5000 KZT
    assert d["cap"]["acc"][0][0] == "Брокерский счёт" and d["cap"]["hold"][0][0] == "AAPL"
    assert d["cap"]["wallet"][0][0] == "AED"


def test_link_is_trimmed_to_limit(db, clock, mid):
    svc = Service(db, clock=clock, fetch=offline)
    from datetime import datetime, timedelta
    for i in range(400):
        clock.set_local(datetime(2026, 5, 1, 12) + timedelta(hours=10 * i))
        svc.process_text(f"покупка номер {i} {10 + i}", mid())
    full = webapp.url(svc, "https://x/app", max_len=100000)
    short = webapp.url(svc, "https://x/app", max_len=3000)
    assert len(short) <= 3000 < len(full)
    assert len(webapp.decode(short.split("#d=")[1])["tx"]) < len(webapp.decode(full.split("#d=")[1])["tx"])


def test_no_url_configured():
    assert webapp.url(None, "") is None

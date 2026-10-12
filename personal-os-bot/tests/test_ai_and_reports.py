"""Optional AI layer (fake client, no network) and analytics images."""
from datetime import datetime

import pytest

from bot.ai import AIError, extract_json, validate
from bot.nlp import CATEGORIES
from bot.service import Service


class FakeAI:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []
        self.cfg = type("C", (), {"provider": "fake", "model": "m", "can_see_images": True})()

    def parse_text(self, text, ctx):
        self.calls.append(("text", text, ctx))
        if self.error:
            raise self.error
        return self.result

    def parse_image(self, image, caption, ctx):
        self.calls.append(("image", caption, ctx))
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def ai_svc(db, clock):
    def make(result=None, error=None):
        ai = FakeAI(result, error)
        return Service(db, clock=clock, ai=ai), ai
    return make


def test_rules_first_ai_not_called_for_simple_messages(ai_svc, mid):
    svc, ai = ai_svc({"items": []})
    svc.process_text("Кофе 18", mid())
    svc.process_text("Завтра в 11 позвонить преподавателю", mid())
    assert ai.calls == []


def test_ai_parses_mixed_message_into_one_undoable_action(ai_svc, mid):
    svc, ai = ai_svc({"items": [
        {"type": "expense", "amount": 30, "currency": None, "category": "Транспорт", "description": "такси",
         "date": "2026-10-11"},
        {"type": "expense", "amount": 85, "category": "Здоровье", "description": "лекарства"},
        {"type": "reminder", "title": "к врачу", "date": "2026-10-13", "time": "10:00"},
    ]})
    r = svc.process_text("вчера на такси ушло тридцатка, лекарства 85, а завтра к врачу к 10 утра", mid())
    assert r.text.startswith("🤖 ")
    assert "−30 AED · Транспорт · такси · вчера" in r.text and "−85 AED · Здоровье" in r.text
    assert "К врачу — завтра 10:00 🔔" in r.text
    assert svc.db.scalar("SELECT COUNT(*) FROM transactions") == 2
    assert svc.db.scalar("SELECT COUNT(*) FROM actions") == 1
    svc.handle_callback(r.buttons[0][0][1])  # "Отменить всё"
    assert svc.db.scalar("SELECT COUNT(*) FROM transactions") == 0
    assert svc.db.scalar("SELECT COUNT(*) FROM tasks") == 0
    assert svc.db.scalar("SELECT COUNT(*) FROM reminders") == 0


def test_bank_sms_ambiguous_numbers_go_to_ai(ai_svc, mid):
    svc, ai = ai_svc({"items": [{"type": "expense", "amount": 45.5, "currency": "AED", "category": "Продукты",
                                 "description": "Carrefour"}]})
    r = svc.process_text("Purchase of AED 45.50 at CARREFOUR with card ending 1234. Avl bal AED 2,300.00", mid())
    assert "−45.50 AED · Продукты · Carrefour" in r.text
    assert len(ai.calls) == 1


def test_ai_invented_or_invalid_data_is_dropped(ai_svc, mid):
    svc, _ = ai_svc({"items": [
        {"type": "expense", "amount": None, "description": "что-то"},      # no amount -> dropped
        {"type": "hack", "amount": 5},                                     # unknown type -> dropped
        {"type": "expense", "amount": -10, "description": "минус"},        # non-positive -> dropped
    ], "question": "Это расход или задача?"})
    r = svc.process_text("бла бла непонятно", mid())
    assert "🤖 Это расход или задача?" in r.text and "Inbox" in r.text
    assert svc.db.scalar("SELECT COUNT(*) FROM transactions") == 0
    assert svc.db.scalar("SELECT COUNT(*) FROM inbox") == 1


def test_ai_failure_falls_back_to_inbox(ai_svc, mid):
    svc, _ = ai_svc(error=AIError("лимит бесплатных запросов исчерпан, попробуйте позже"))
    r = svc.process_text("бла бла непонятно", mid())
    assert "AI недоступен" in r.text and "Inbox" in r.text
    assert svc.db.scalar("SELECT COUNT(*) FROM inbox") == 1


def test_ai_failure_on_amount_question_keeps_asking(ai_svc, mid):
    svc, _ = ai_svc(error=AIError("нет связи"))
    r = svc.process_text("кофе 18 20", mid())
    assert r.text == "Какое число — сумма?"


def test_ai_partial_failure_saves_nothing(ai_svc, mid, monkeypatch):
    svc, _ = ai_svc({"items": [
        {"type": "expense", "amount": 30, "description": "такси"},
        {"type": "task", "title": "позвонить"},
    ]})
    monkeypatch.setattr(svc, "_create_task", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    r = svc.process_text("бла бла непонятно", mid())
    assert "Записал" not in r.text
    assert svc.db.scalar("SELECT COUNT(*) FROM transactions") == 0
    assert svc.db.scalar("SELECT COUNT(*) FROM inbox") == 1


def test_ai_can_be_switched_off(ai_svc, mid):
    svc, ai = ai_svc({"items": [{"type": "note", "title": "x"}]})
    svc.handle_callback("set:tog:ai_enabled")
    svc.process_text("бла бла непонятно", mid())
    assert ai.calls == []


def test_inbox_item_can_be_parsed_by_ai(ai_svc, mid):
    svc, ai = ai_svc({"items": [{"type": "task", "title": "Купить подарок Саше", "date": "2026-10-16"}]})
    svc.ai_backup = svc.ai
    svc.ai = None
    svc.process_text("подарок саше что-нибудь придумать", mid())   # no AI at that moment -> Inbox
    svc.ai = svc.ai_backup
    iid = svc.db.scalar("SELECT id FROM inbox")
    assert any(d == f"ib:{iid}:ai" for row in svc.view_inbox().buttons for _, d in row)
    r = svc.handle_callback(f"ib:{iid}:ai")
    assert "Купить подарок Саше" in r.text
    assert svc.db.scalar("SELECT status FROM inbox") == "processed"


def test_photo_receipt(ai_svc, mid):
    svc, ai = ai_svc({"items": [{"type": "expense", "amount": 132.4, "category": "Продукты",
                                 "description": "Lulu Hypermarket"}]})
    r = svc.process_photo(b"\xff\xd8fakejpeg", "", mid())
    assert "−132.40 AED · Продукты · Lulu Hypermarket" in r.text
    assert ai.calls[0][0] == "image"


def test_photo_without_ai_explains(svc, mid):
    r = svc.process_photo(b"x", "", mid())
    assert "AI" in r.text and svc.db.scalar("SELECT COUNT(*) FROM transactions") == 0


def test_ai_context_has_local_date_and_categories(ai_svc, mid):
    svc, ai = ai_svc({"items": []})
    svc.process_text("бла бла непонятно", mid())
    ctx = ai.calls[0][2]
    assert ctx["now"] == datetime(2026, 10, 12, 14, 0) and ctx["currency"] == "AED"
    assert ctx["categories"] == CATEGORIES


def test_extract_json_and_validate():
    assert extract_json('```json\n{"items": []}\n```') == {"items": []}
    assert extract_json('Вот: {"items": [], "question": null} готово')["items"] == []
    with pytest.raises(AIError):
        extract_json("не json")
    items, q = validate({"items": [{"type": "event", "title": "Пара", "date": "2026-10-15", "time": "8:30",
                                    "category": "Выдумка"}]}, datetime(2026, 10, 12).date(), CATEGORIES)
    assert items[0].time == (8, 30) and items[0].category is None and q is None


def test_config_from_env():
    from bot.ai import config_from_env
    assert config_from_env({}) is None
    assert config_from_env({"AI_PROVIDER": "gemini"}) is None  # no key -> off
    c = config_from_env({"AI_PROVIDER": "gemini", "AI_API_KEY": "k"})
    assert c.base_url.startswith("https://generativelanguage.googleapis.com") and c.can_see_images
    o = config_from_env({"AI_PROVIDER": "ollama"})
    assert o is not None and o.base_url == "http://localhost:11434/v1"


# ---------------------------------------------------------------- reports


def _png_size(data: bytes):
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(data))
    return img.format, img.size


@pytest.mark.parametrize("period", ["m", "w", "pm", "6"])
def test_report_images_render(svc, mid, period):
    for t in ["Кофе 18", "Такси 25, продукты 60", "вчера обед 45", "Получил зарплату 6500", "лимит кафе 50",
              "аптека 120", "подарок маме 300"]:
        svc.process_text(t, mid())
    r = svc.analytics(period)
    fmt_, (w, h) = _png_size(r.photo[1])
    assert fmt_ == "PNG" and w == 1080 and h > 1000
    assert r.text.startswith("📊")
    assert [d for row in r.buttons for _, d in row] == ["st:w", "st:m", "st:pm", "st:6"]


def test_report_empty_period_renders(svc):
    r = svc.analytics("m")
    assert r.photo and "0 AED" in r.text


def test_category_colors_are_stable(svc, mid):
    svc.process_text("продукты 100", mid())
    svc.analytics("m")
    first = svc.db.get_setting("category_colors")
    svc.process_text("такси 500", mid())   # transport becomes the biggest category
    svc.analytics("m")
    import json
    colors = json.loads(svc.db.get_setting("category_colors"))
    assert colors["Продукты"] == json.loads(first)["Продукты"]   # not repainted by rank
    assert "Транспорт" in colors


def test_monthly_report_sent_on_first_day(svc, mid, clock):
    clock.set_local(datetime(2026, 10, 20, 12, 0))
    svc.process_text("Кофе 18", mid())
    clock.set_local(datetime(2026, 11, 1, 8, 5))
    notes = svc.collect_due()
    photos = [n for n in notes if n.reply.photo]
    assert len(photos) == 1 and photos[0].reply.text.startswith("📊 Итоги прошлого месяца")
    for n in notes:
        n.on_sent()
    assert not [n for n in svc.collect_due() if n.reply.photo]


def test_money_view_links_to_analytics(svc):
    assert any(d == "st:m" for row in svc.view_money().buttons for _, d in row)

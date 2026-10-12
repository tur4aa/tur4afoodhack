"""Bank-app style report cards rendered to PNG with Pillow (no browser, no matplotlib).

Everything is drawn at 2x and downsampled, so arcs and rounded corners are smooth.
Colors: validated categorical palette (dark mode), fixed category -> color mapping,
so a category keeps its color in every report.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import formatting as fmt

FONT_PATH = Path(__file__).parent / "assets" / "fonts" / "Inter-Variable.ttf"

W = 1080            # final width in px (Telegram shows photos up to ~1280)
S = 2               # supersampling factor
PAD = 56

# --- theme (dark, validated) -------------------------------------------------
BG = "#0d0d0d"          # page plane
CARD = "#1a1a19"        # chart surface
INK = "#f0efec"
INK2 = "#c3c2b7"
MUTED = "#898781"
GRID = "#2c2c2a"
BASE = "#383835"
GOOD = "#0ca30c"
CRITICAL = "#d03b3b"
TRACK = "#262624"
OTHER = "#6b6a66"       # neutral gray for "Другое"

SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
ACCENT = SERIES[0]
ACCENT_SOFT = "#1c5cab"  # blue ramp step 550, for past bars

# Entity -> palette slot. The service assigns slots permanently, first come first served,
# so a category keeps its color in every report (color follows the category, never its rank).
# Categories beyond the 8 validated slots are drawn gray as part of "Другое".
def color_of(category: str, colors: dict[str, int] | None = None) -> str:
    if colors is not None and category in colors:
        return SERIES[colors[category]]
    return OTHER


_font_cache: dict[tuple[int, int], ImageFont.FreeTypeFont] = {}


def font(size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    key = (size, weight)
    if key not in _font_cache:
        f = ImageFont.truetype(str(FONT_PATH), size * S)
        f.set_variation_by_axes([min(max(size, 14), 32), weight])
        _font_cache[key] = f
    return _font_cache[key]


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def compact(minor: int) -> str:
    """Axis-style compact numbers: 950, 1.2K, 12K."""
    v = minor / 100
    if abs(v) >= 1000:
        k = v / 1000
        return f"{k:.1f}K".replace(".0K", "K") if abs(k) < 10 else f"{k:.0f}K"
    return f"{v:.0f}"


@dataclass
class CategoryRow:
    name: str
    amount: int          # minor units
    limit: int | None = None


@dataclass
class Report:
    title: str                       # "Октябрь 2026"
    subtitle: str                    # "Расходы · 1–12 окт"
    currency: str
    total: int                       # net expenses, minor
    compare_label: str | None        # "к сентябрю за те же дни"
    compare_total: int | None
    income: int
    kpis: list[tuple[str, str]]      # [(label, value)]
    categories: list[CategoryRow]
    bars: list[tuple[str, int, bool]]   # (label, amount, is_current)
    bars_title: str
    bar_reference: tuple[str, int] | None = None   # ("бюджет/день", minor)
    top: list[tuple[str, str, int]] = field(default_factory=list)  # (date label, description, amount)
    footer: str = "Kompas · по записям в боте, не банковские данные"
    colors: dict[str, int] = field(default_factory=dict)   # category -> palette slot


class Canvas:
    def __init__(self, height: int):
        self.img = Image.new("RGB", (W * S, height * S), BG)
        self.d = ImageDraw.Draw(self.img)

    def rect(self, x0, y0, x1, y1, fill, r=0, corners=None):
        self.d.rounded_rectangle([x0 * S, y0 * S, x1 * S, y1 * S], radius=r * S, fill=fill, corners=corners)

    def text(self, x, y, s, size, weight=400, fill=INK, anchor="la"):
        self.d.text((x * S, y * S), s, font=font(size, weight), fill=fill, anchor=anchor)

    def width(self, s, size, weight=400) -> float:
        return self.d.textlength(s, font=font(size, weight)) / S

    def line(self, x0, y0, x1, y1, fill, w=1):
        self.d.line([x0 * S, y0 * S, x1 * S, y1 * S], fill=fill, width=max(1, int(w * S)))

    def circle(self, cx, cy, r, fill):
        self.d.ellipse([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], fill=fill)

    def png(self) -> bytes:
        out = self.img.resize((self.img.width // S, self.img.height // S), Image.LANCZOS)
        buf = io.BytesIO()
        out.save(buf, "PNG", optimize=True)
        return buf.getvalue()


def _fit(c: Canvas, s: str, size: int, weight: int, max_w: float) -> str:
    if c.width(s, size, weight) <= max_w:
        return s
    while s and c.width(s + "…", size, weight) > max_w:
        s = s[:-1]
    return s + "…"


def _donut(c: Canvas, cx: float, cy: float, r_out: float, r_in: float, parts: list[tuple[str, int]]) -> None:
    total = sum(v for _, v in parts) or 1
    box = [(cx - r_out) * S, (cy - r_out) * S, (cx + r_out) * S, (cy + r_out) * S]
    if len(parts) == 1:
        c.d.ellipse(box, fill=parts[0][0])
    else:
        a = -90.0
        for col, v in parts:
            sweep = 360 * v / total
            c.d.pieslice(box, a, a + sweep, fill=col)
            a += sweep
        # 2px surface gaps between segments
        a = -90.0
        for _, v in parts:
            rad = math.radians(a)
            c.line(cx + r_in * 0.9 * math.cos(rad), cy + r_in * 0.9 * math.sin(rad),
                   cx + (r_out + 2) * math.cos(rad), cy + (r_out + 2) * math.sin(rad), CARD, 3)
            a += 360 * v / total
    c.circle(cx, cy, r_in, CARD)


def render_report(rep: Report) -> bytes:
    cur = rep.currency
    cats = [r for r in rep.categories if r.amount > 0]
    n_list = min(len(cats), 8)
    has_top = bool(rep.top)
    height = (PAD + 300 + 24 + 150 + 24 + (110 + max(n_list, 1) * 78 + 40) + 24 + 420
              + (24 + 90 + 64 * len(rep.top) if has_top else 0) + 90)
    c = Canvas(height)
    x0, x1 = PAD, W - PAD
    y = PAD

    # ---- hero card ------------------------------------------------------
    c.rect(x0, y, x1, y + 300, CARD, 28)
    c.text(x0 + 40, y + 40, rep.title, 30, 700)
    c.text(x0 + 40, y + 84, rep.subtitle, 22, 400, INK2)
    c.text(x0 + 40, y + 132, fmt.money(rep.total), 84, 700)
    tw = c.width(fmt.money(rep.total), 84, 700)
    c.text(x0 + 52 + tw, y + 176, cur, 32, 500, INK2)
    if rep.compare_total is not None and rep.compare_label:
        if rep.compare_total > 0:
            pct = round((rep.total - rep.compare_total) * 100 / rep.compare_total)
            up = pct > 0
            arrow = "▲" if up else ("▼" if pct < 0 else "•")
            col = CRITICAL if up else GOOD   # spending more is the bad direction
            chip = f"{arrow} {abs(pct)}%"
            cw = c.width(chip, 22, 600) + 32
            c.rect(x0 + 40, y + 236, x0 + 40 + cw, y + 274, _tint(col), 19)
            c.text(x0 + 56, y + 242, chip, 22, 600, INK)
            c.text(x0 + 56 + cw, y + 242, rep.compare_label, 22, 400, INK2)
        else:
            c.text(x0 + 40, y + 242, f"{rep.compare_label}: расходов не было", 22, 400, INK2)
    y += 300 + 24

    # ---- KPI row ----------------------------------------------------------
    kpis = rep.kpis[:3]
    gap = 20
    kw = (x1 - x0 - gap * (len(kpis) - 1)) / max(len(kpis), 1)
    for i, (label, value) in enumerate(kpis):
        kx = x0 + i * (kw + gap)
        c.rect(kx, y, kx + kw, y + 150, CARD, 24)
        c.text(kx + 28, y + 30, _fit(c, label, 20, 400, kw - 56), 20, 400, MUTED)
        c.text(kx + 28, y + 70, _fit(c, value, 36, 700, kw - 56), 36, 700)
    y += 150 + 24

    # ---- categories: donut + ranked list ------------------------------------
    block_h = 110 + max(n_list, 1) * 78 + 40
    c.rect(x0, y, x1, y + block_h, CARD, 28)
    c.text(x0 + 40, y + 40, "Категории", 28, 700)
    total = sum(r.amount for r in cats) or 1
    if cats:
        # donut: up to 5 named segments in fixed palette order + gray "Другое"
        colors = rep.colors
        named = [r for r in cats if r.name in colors][:5]
        rest = total - sum(r.amount for r in named)
        named.sort(key=lambda r: colors[r.name])   # palette order -> validated adjacent pairs
        parts = [(color_of(r.name, colors), r.amount) for r in named]
        if rest > 0:
            parts.append((OTHER, rest))
        r_out = min(150, (block_h - 150) / 2)
        cx, cy = x1 - 40 - r_out, y + 110 + r_out
        _donut(c, cx, cy, r_out, r_out * 0.66, parts)
        c.text(cx, cy - 6, f"{len(cats)}", 40, 700, INK, anchor="ms")
        c.text(cx, cy + 30, "категорий" if len(cats) % 10 in (0, 5, 6, 7, 8, 9) or 11 <= len(cats) % 100 <= 14
               else ("категория" if len(cats) % 10 == 1 else "категории"), 20, 400, MUTED, anchor="ms")
        list_x1 = cx - r_out - 48
        ly = y + 110
        top_amount = cats[0].amount or 1
        for r in cats[:n_list]:
            c.circle(x0 + 50, ly + 14, 8, color_of(r.name, rep.colors))
            pct = r.amount * 100 / total
            right = f"{fmt.money(r.amount)}"
            rw = c.width(right, 24, 600)
            c.text(list_x1, ly, right, 24, 600, INK, anchor="ra")
            name = _fit(c, r.name, 24, 500, list_x1 - (x0 + 72) - rw - 70)
            c.text(x0 + 72, ly, name, 24, 500, INK)
            c.text(list_x1 - rw - 16, ly + 2, f"{pct:.0f}%", 20, 400, MUTED, anchor="ra")
            # thin magnitude bar; limit turns it into a meter
            bx0, bx1 = x0 + 72, list_x1
            by = ly + 42
            c.rect(bx0, by, bx1, by + 8, TRACK, 4)
            if r.limit:
                frac = min(r.amount / r.limit, 1)
                col = CRITICAL if r.amount > r.limit else color_of(r.name, rep.colors)
                lbl = f"лимит {fmt.money(r.limit)}" + (" — превышен" if r.amount > r.limit else "")
                c.text(bx1, by + 14, lbl, 16, 400, MUTED, anchor="ra")
            else:
                frac = r.amount / top_amount
                col = color_of(r.name, rep.colors)
            c.rect(bx0, by, bx0 + max((bx1 - bx0) * frac, 8), by + 8, col, 4)
            ly += 78
        if len(cats) > n_list:
            c.text(x0 + 72, ly - 8, f"и ещё {len(cats) - n_list}", 20, 400, MUTED)
    else:
        c.text(x0 + 40, y + 110, "Расходов за период нет", 24, 400, INK2)
    y += block_h + 24

    # ---- columns (single series) --------------------------------------------
    ch = 420
    c.rect(x0, y, x1, y + ch, CARD, 28)
    c.text(x0 + 40, y + 40, rep.bars_title, 28, 700)
    px0, px1 = x0 + 96, x1 - 40
    py0, py1 = y + 110, y + ch - 70
    vals = [v for _, v, _ in rep.bars]
    ref = rep.bar_reference[1] if rep.bar_reference else 0
    vmax = max(vals + [ref, 1])
    step = _nice_step(vmax / 100) * 100
    top_tick = math.ceil(vmax / step) * step if step else vmax
    for k in range(0, 4):
        val = top_tick * k / 3
        ty = py1 - (py1 - py0) * k / 3
        c.line(px0, ty, px1, ty, GRID if k else BASE, 1)
        c.text(px0 - 14, ty - 11, compact(int(val)), 18, 400, MUTED, anchor="ra")
    n = max(len(rep.bars), 1)
    slot = (px1 - px0) / n
    bw = min(24, slot * 0.62)
    label_every = 1 if n <= 12 else (5 if n > 20 else 3)
    cur_i = next((i for i, b in enumerate(rep.bars) if b[2]), -1)
    for i, (label, v, current) in enumerate(rep.bars):
        bx = px0 + slot * i + (slot - bw) / 2
        if v > 0:
            h = max((py1 - py0) * v / top_tick, 4)
            c.rect(bx, py1 - h, bx + bw, py1, ACCENT if current else ACCENT_SOFT, 4, corners=(True, True, False, False))
        near_current = cur_i >= 0 and not current and abs(i - cur_i) <= (1 if label_every > 1 else 0)
        if current or ((i % label_every == 0 or i == n - 1) and not near_current):
            c.text(bx + bw / 2, py1 + 16, label, 18, 600 if current else 400, INK if current else MUTED, anchor="ma")
    if rep.bar_reference and ref > 0:
        ry = py1 - (py1 - py0) * ref / top_tick
        c.line(px0, ry, px1, ry, INK2, 1)
        lbl = f"{rep.bar_reference[0]} {fmt.money(ref)}"
        c.text(px1, ry - 30, lbl, 18, 500, INK2, anchor="ra")
    y += ch + 24

    # ---- biggest expenses -----------------------------------------------------
    if has_top:
        th = 90 + 64 * len(rep.top)
        c.rect(x0, y, x1, y + th, CARD, 28)
        c.text(x0 + 40, y + 40, "Крупные траты", 28, 700)
        ty = y + 100
        for dl, desc, amount in rep.top:
            c.text(x0 + 40, ty, dl, 22, 400, MUTED)
            c.text(x1 - 40, ty, f"−{fmt.money(amount)}", 24, 600, INK, anchor="ra")
            c.text(x0 + 150, ty, _fit(c, desc, 24, 500, x1 - x0 - 380), 24, 500, INK)
            ty += 64
        y += th + 24

    c.text(W / 2, y + 16, rep.footer, 18, 400, MUTED, anchor="ma")
    return c.png()


def _tint(hex_color: str, alpha: float = 0.28) -> tuple[int, int, int]:
    r, g, b = hex_rgb(hex_color)
    br, bg, bb = hex_rgb(CARD)
    return (round(br + (r - br) * alpha), round(bg + (g - bg) * alpha), round(bb + (b - bb) * alpha))


def _nice_step(raw: float) -> float:
    """A clean tick step (1, 2, 5 x 10^n) so that 3 steps cover ``raw``."""
    if raw <= 0:
        return 1
    target = raw / 3
    mag = 10 ** math.floor(math.log10(target))
    for m in (1, 2, 2.5, 5, 10):
        if m * mag >= target:
            return m * mag
    return 10 * mag


def day_label(d: date) -> str:
    return str(d.day)


# ------------------------------------------------------------------ capital card


@dataclass
class CapitalReport:
    currency: str
    total: int
    change: tuple[int, str] | None            # (diff minor, since day ISO)
    wallet: int
    invested: int
    capital: int
    parts: list[tuple[str, str, int]]          # (name, kind label, value minor)
    colors: dict[str, int]
    history: list[tuple[str, int]]             # (day ISO, value minor)
    holdings: list[tuple[str, str, int, float | None]]   # (symbol, qty, value minor, pnl %)
    footer: str = "Kompas · оценка по последним известным ценам и курсам"


def _line_chart(c: Canvas, x0, y0, x1, y1, points: list[tuple[str, int]], cur: str) -> None:
    vals = [v for _, v in points]
    lo, hi = min(vals), max(vals)
    min_span = max(abs(hi) * 0.04, 3000)   # flat history should look flat, not like a crash
    if hi - lo < min_span:
        mid = (hi + lo) / 2
        lo, hi = mid - min_span / 2, mid + min_span / 2
    pad = (hi - lo) * 0.12
    lo, hi = lo - pad, hi + pad
    px0, px1, py0, py1 = x0 + 96, x1, y0, y1 - 40
    step = (hi - lo) / 3
    labels = [compact(int(lo + step * k)) for k in range(4)]
    if len(set(labels)) < 4:   # narrow range: compact labels would repeat ("19K, 19K") - show full numbers
        labels = [fmt.money(round((lo + step * k) / 100) * 100) for k in range(4)]
    for k in range(4):
        ty = py1 - (py1 - py0) * k / 3
        c.line(px0, ty, px1, ty, GRID if k else BASE, 1)
        c.text(px0 - 14, ty - 11, labels[k], 18, 400, MUTED, anchor="ra")
    n = len(points)

    def xy(i, v):
        return px0 + (px1 - px0) * (i / max(n - 1, 1)), py1 - (py1 - py0) * (v - lo) / (hi - lo)

    pts = [xy(i, v) for i, (_, v) in enumerate(points)]
    # area wash
    poly = [(px * S, py * S) for px, py in pts] + [(pts[-1][0] * S, py1 * S), (pts[0][0] * S, py1 * S)]
    overlay = Image.new("RGBA", c.img.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).polygon(poly, fill=hex_rgb(ACCENT) + (26,))
    c.img.paste(overlay, (0, 0), overlay)
    c.d = ImageDraw.Draw(c.img)
    c.d.line([(px * S, py * S) for px, py in pts], fill=ACCENT, width=2 * S, joint="curve")
    ex, ey = pts[-1]
    c.circle(ex, ey, 7, CARD)
    c.circle(ex, ey, 5, ACCENT)
    first, last = points[0][0], points[-1][0]
    c.text(px0, py1 + 14, f"{int(first[8:])}.{first[5:7]}", 18, 400, MUTED)
    c.text(px1, py1 + 14, f"{int(last[8:])}.{last[5:7]}", 18, 600, INK, anchor="ra")


def render_capital(rep: CapitalReport) -> bytes:
    cur = rep.currency
    parts = sorted(rep.parts, key=lambda p: -p[2])
    n_parts = min(len(parts), 7)
    has_hold = bool(rep.holdings)
    height = (PAD + 300 + 24 + 150 + 24 + (110 + max(n_parts, 1) * 78 + 40) + 24 + 400
              + (24 + 100 + 64 * len(rep.holdings) if has_hold else 0) + 90)
    c = Canvas(height)
    x0, x1 = PAD, W - PAD
    y = PAD

    c.rect(x0, y, x1, y + 300, CARD, 28)
    c.text(x0 + 40, y + 40, "Капитал", 30, 700)
    c.text(x0 + 40, y + 84, "счета, инвестиции, имущество и кошелёк", 22, 400, INK2)
    c.text(x0 + 40, y + 132, fmt.money(rep.total), 84, 700)
    tw = c.width(fmt.money(rep.total), 84, 700)
    c.text(x0 + 52 + tw, y + 176, cur, 32, 500, INK2)
    if rep.change:
        diff, since = rep.change
        base = rep.total - diff
        pct = diff * 100 / base if base else 0
        up = diff >= 0
        chip = f"{'▲' if up else '▼'} {abs(pct):.1f}%"
        cw = c.width(chip, 22, 600) + 32
        c.rect(x0 + 40, y + 236, x0 + 40 + cw, y + 274, _tint(GOOD if up else CRITICAL), 19)
        c.text(x0 + 56, y + 242, chip, 22, 600, INK)
        c.text(x0 + 56 + cw, y + 242, f"{'+' if up else '−'}{fmt.money(abs(diff))} с {int(since[8:])}.{since[5:7]}",
               22, 400, INK2)
    y += 324

    pnl = rep.capital - rep.invested
    kpis = [("Вложено", fmt.money(round(rep.invested / 100) * 100)),
            ("Результат", ("+" if pnl >= 0 else "−") + fmt.money(round(abs(pnl) / 100) * 100)),
            ("Кошелёк", fmt.money(round(rep.wallet / 100) * 100))]
    kw = (x1 - x0 - 40) / 3
    for i, (label, value) in enumerate(kpis):
        kx = x0 + i * (kw + 20)
        c.rect(kx, y, kx + kw, y + 150, CARD, 24)
        c.text(kx + 28, y + 30, label, 20, 400, MUTED)
        c.text(kx + 28, y + 70, _fit(c, value, 36, 700, kw - 56), 36, 700)
    y += 174

    block_h = 110 + max(n_parts, 1) * 78 + 40
    c.rect(x0, y, x1, y + block_h, CARD, 28)
    c.text(x0 + 40, y + 40, "Где деньги", 28, 700)
    total = sum(p[2] for p in parts) or 1
    if parts:
        slot = lambda name: SERIES[rep.colors[name]] if name in rep.colors else OTHER  # noqa: E731
        donut_parts = sorted(parts[:6], key=lambda p: rep.colors.get(p[0], 99))
        rest = total - sum(p[2] for p in donut_parts)
        segs = [(slot(p[0]), p[2]) for p in donut_parts] + ([(OTHER, rest)] if rest > 0 else [])
        r_out = min(150, (block_h - 150) / 2)
        cx, cy = x1 - 40 - r_out, y + 110 + r_out
        _donut(c, cx, cy, r_out, r_out * 0.66, segs)
        top_share = parts[0][2] * 100 / total
        c.text(cx, cy - 6, f"{top_share:.0f}%", 40, 700, INK, anchor="ms")
        c.text(cx, cy + 30, _fit(c, parts[0][0], 18, 400, r_out * 1.1), 18, 400, MUTED, anchor="ms")
        list_x1 = cx - r_out - 48
        ly = y + 110
        for name, label, v in parts[:n_parts]:
            c.circle(x0 + 50, ly + 14, 8, slot(name))
            right = fmt.money(v)
            rw = c.width(right, 24, 600)
            c.text(list_x1, ly, right, 24, 600, INK, anchor="ra")
            c.text(x0 + 72, ly, _fit(c, name, 24, 500, list_x1 - x0 - 72 - rw - 80), 24, 500, INK)
            c.text(list_x1 - rw - 16, ly + 2, f"{v * 100 / total:.0f}%", 20, 400, MUTED, anchor="ra")
            c.text(x0 + 72, ly + 36, label, 18, 400, MUTED)
            ly += 78
    else:
        c.text(x0 + 40, y + 110, "Счетов пока нет", 24, 400, INK2)
    y += block_h + 24

    c.rect(x0, y, x1, y + 400, CARD, 28)
    c.text(x0 + 40, y + 40, "Динамика", 28, 700)
    if len(rep.history) >= 2:
        _line_chart(c, x0 + 40, y + 110, x1 - 40, y + 380, rep.history, cur)
    else:
        c.text(x0 + 40, y + 120, "График появится через пару дней —", 24, 400, INK2)
        c.text(x0 + 40, y + 158, "бот сохраняет стоимость капитала раз в день.", 24, 400, INK2)
    y += 424

    if has_hold:
        th = 100 + 64 * len(rep.holdings)
        c.rect(x0, y, x1, y + th, CARD, 28)
        c.text(x0 + 40, y + 40, "Позиции", 28, 700)
        ty = y + 104
        for sym, qty, value, pct in rep.holdings:
            c.text(x0 + 40, ty, sym, 24, 600, INK)
            c.text(x0 + 180, ty + 2, qty, 22, 400, MUTED)
            c.text(x1 - 200, ty, fmt.money(value), 24, 600, INK, anchor="ra")
            if pct is not None:
                up = pct >= 0
                chip = f"{'▲' if up else '▼'} {abs(pct):.1f}%"
                cw = c.width(chip, 20, 600) + 24
                c.rect(x1 - 40 - cw, ty - 4, x1 - 40, ty + 30, _tint(GOOD if up else CRITICAL), 17)
                c.text(x1 - 40 - cw / 2, ty, chip, 20, 600, INK, anchor="ma")
            ty += 64
        y += th + 24

    c.text(W / 2, y + 16, rep.footer, 18, 400, MUTED, anchor="ma")
    return c.png()

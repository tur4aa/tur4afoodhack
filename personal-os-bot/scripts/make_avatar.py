"""Draws branding/avatar.png (bot profile photo) and branding/menu-icon.png. Run: python scripts/make_avatar.py"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "branding"
N = 1024
S = 3  # supersampling


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def avatar(size=N) -> Image.Image:
    W = size * S
    img = Image.new("RGB", (W, W))
    top, bottom = (16, 30, 58), (31, 98, 196)          # deep navy -> brand blue
    px = img.load()
    for y in range(W):
        for x in range(0, W, 1):
            t = min(max((x * 0.35 + y * 0.65) / W, 0), 1)
            px[x, y] = lerp(top, bottom, t)
    d = ImageDraw.Draw(img, "RGBA")
    c = W / 2
    # soft glow behind the rose
    glow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([c - W * .30, c - W * .30, c + W * .30, c + W * .30], fill=(120, 180, 255, 70))
    img.paste(glow.filter(ImageFilter.GaussianBlur(W * .06)), (0, 0), glow.filter(ImageFilter.GaussianBlur(W * .06)))
    d = ImageDraw.Draw(img, "RGBA")
    # ring with tick marks
    r = W * .34
    d.ellipse([c - r, c - r, c + r, c + r], outline=(255, 255, 255, 60), width=int(W * .012))
    for i in range(12):
        a = math.radians(i * 30)
        r1, r2 = r * (0.86 if i % 3 else 0.80), r * 0.93
        d.line([c + r1 * math.sin(a), c - r1 * math.cos(a), c + r2 * math.sin(a), c - r2 * math.cos(a)],
               fill=(255, 255, 255, 110 if i % 3 else 200), width=int(W * (.008 if i % 3 else .012)))
    # four-point rose: long north-south needle, short east-west
    L, w, s = W * .30, W * .072, W * .16

    def diamond(angle, length, width, color):
        a = math.radians(angle)
        tip = (c + length * math.sin(a), c - length * math.cos(a))
        left = (c + width * math.sin(a - math.pi / 2), c - width * math.cos(a - math.pi / 2))
        right = (c + width * math.sin(a + math.pi / 2), c - width * math.cos(a + math.pi / 2))
        d.polygon([tip, left, (c, c), right], fill=color)

    diamond(90, s, w * .8, (255, 255, 255, 120))
    diamond(270, s, w * .8, (255, 255, 255, 120))
    diamond(180, L, w, (255, 255, 255, 150))
    diamond(0, L, w, (255, 255, 255, 255))
    # warm north tip
    a = 0
    d.polygon([(c, c - L), (c - w * .55, c - L * .45), (c + w * .55, c - L * .45)], fill=(255, 140, 80, 255))
    d.ellipse([c - W * .028, c - W * .028, c + W * .028, c + W * .028], fill=(16, 30, 58, 255))
    d.ellipse([c - W * .014, c - W * .014, c + W * .014, c + W * .014], fill=(255, 255, 255, 255))
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    a = avatar()
    a.save(OUT / "avatar.png", optimize=True)
    a.resize((512, 512), Image.LANCZOS).save(OUT / "avatar-512.png", optimize=True)
    # preview as Telegram shows it (circle, small)
    prev = Image.new("RGB", (560, 200), (23, 33, 43))
    for i, sz in enumerate((160, 96, 48)):
        m = Image.new("L", (sz, sz), 0)
        ImageDraw.Draw(m).ellipse([0, 0, sz - 1, sz - 1], fill=255)
        prev.paste(a.resize((sz, sz), Image.LANCZOS), (20 + i * 200, (200 - sz) // 2), m)
    prev.save(OUT / "avatar-preview.png")
    print("saved to", OUT)

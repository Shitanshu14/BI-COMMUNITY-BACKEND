"""
Generates the icon (circular badge) + cover (banner) PNGs used by
`seed_communities` for every default community, entirely with Pillow —
no external image files or network access needed, so this works the same
in dev, CI, and on Render at deploy time.

Each community gets a themed, original glyph (play button, camera, robot,
DNA helix, ...) on a gradient made from its brand-ish `color`, rather than
a literal reproduction of any platform's real logo.
"""

from io import BytesIO

from PIL import Image, ImageDraw


def hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _mix(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def lighten(c, amt=0.35):
    return _mix(c, (255, 255, 255), amt)


def darken(c, amt=0.35):
    return _mix(c, (0, 0, 0), amt)


def diagonal_gradient(size, color1, color2):
    """A soft diagonal gradient between two RGB colors, built from Pillow's
    built-in linear_gradient (no numpy needed)."""
    w, h = size
    base = Image.linear_gradient("L").rotate(40, expand=True, resample=Image.BICUBIC)
    bw, bh = base.size
    scale = max(w / bw, h / bh) * 1.4
    base = base.resize((int(bw * scale) + 1, int(bh * scale) + 1), Image.BICUBIC)
    bw, bh = base.size
    left, top = (bw - w) // 2, (bh - h) // 2
    base = base.crop((left, top, left + w, top + h))
    layer1 = Image.new("RGB", size, color1)
    layer2 = Image.new("RGB", size, color2)
    return Image.composite(layer2, layer1, base)


def _white(alpha):
    return (255, 255, 255, alpha)


def draw_glyph(draw, cx, cy, r, key, alpha=235):
    """Draws a simple, original glyph centered at (cx, cy) with 'radius' r."""
    w = max(3, r * 0.16)
    col = _white(alpha)

    if key == "youtube":
        pts = [(cx - r * 0.35, cy - r * 0.55), (cx - r * 0.35, cy + r * 0.55), (cx + r * 0.6, cy)]
        draw.polygon(pts, fill=col)

    elif key == "code":
        draw.line([(cx - r * 0.1, cy - r * 0.45), (cx - r * 0.55, cy), (cx - r * 0.1, cy + r * 0.45)],
                   fill=col, width=int(w), joint="curve")
        draw.line([(cx + r * 0.1, cy - r * 0.45), (cx + r * 0.55, cy), (cx + r * 0.1, cy + r * 0.45)],
                   fill=col, width=int(w), joint="curve")

    elif key == "robot":
        head = (cx - r * 0.5, cy - r * 0.4, cx + r * 0.5, cy + r * 0.5)
        draw.rounded_rectangle(head, radius=r * 0.18, outline=col, width=int(w))
        eye_r = r * 0.09
        draw.ellipse((cx - r * 0.25 - eye_r, cy - eye_r, cx - r * 0.25 + eye_r, cy + eye_r), fill=col)
        draw.ellipse((cx + r * 0.25 - eye_r, cy - eye_r, cx + r * 0.25 + eye_r, cy + eye_r), fill=col)
        draw.line([(cx - r * 0.18, cy + r * 0.25), (cx + r * 0.18, cy + r * 0.25)], fill=col, width=int(w * 0.8))
        draw.line([(cx, cy - r * 0.4), (cx, cy - r * 0.58)], fill=col, width=int(w * 0.6))
        draw.ellipse((cx - r * 0.06, cy - r * 0.66, cx + r * 0.06, cy - r * 0.54), fill=col)

    elif key == "gaming":
        body = (cx - r * 0.7, cy - r * 0.24, cx + r * 0.7, cy + r * 0.26)
        draw.rounded_rectangle(body, radius=r * 0.32, outline=col, width=int(w))
        grip_r = r * 0.16
        draw.ellipse((cx - r * 0.68 - grip_r * 0.4, cy + r * 0.08, cx - r * 0.68 + grip_r * 1.4,
                       cy + r * 0.5), outline=col, width=int(w * 0.8))
        draw.ellipse((cx + r * 0.68 - grip_r * 1.4, cy + r * 0.08, cx + r * 0.68 + grip_r * 0.4,
                       cy + r * 0.5), outline=col, width=int(w * 0.8))
        s = r * 0.13
        draw.line([(cx - r * 0.32 - s, cy), (cx - r * 0.32 + s, cy)], fill=col, width=int(w * 0.8))
        draw.line([(cx - r * 0.32, cy - s), (cx - r * 0.32, cy + s)], fill=col, width=int(w * 0.8))
        for dx, dy in [(-s, 0), (s, 0), (0, -s), (0, s)]:
            dot_r = r * 0.045
            draw.ellipse((cx + r * 0.32 + dx - dot_r, cy + dy - dot_r, cx + r * 0.32 + dx + dot_r,
                           cy + dy + dot_r), fill=col)

    elif key == "instagram":
        body = (cx - r * 0.5, cy - r * 0.5, cx + r * 0.5, cy + r * 0.5)
        draw.rounded_rectangle(body, radius=r * 0.28, outline=col, width=int(w))
        lens_r = r * 0.28
        draw.ellipse((cx - lens_r, cy - lens_r, cx + lens_r, cy + lens_r), outline=col, width=int(w))
        dot_r = r * 0.06
        draw.ellipse((cx + r * 0.28 - dot_r, cy - r * 0.28 - dot_r, cx + r * 0.28 + dot_r, cy - r * 0.28 + dot_r),
                      fill=col)

    elif key == "facebook":
        body = (cx - r * 0.55, cy - r * 0.48, cx + r * 0.55, cy + r * 0.3)
        draw.rounded_rectangle(body, radius=r * 0.3, outline=col, width=int(w))
        draw.polygon([(cx - r * 0.15, cy + r * 0.3), (cx + r * 0.1, cy + r * 0.3), (cx - r * 0.05, cy + r * 0.62)],
                      fill=col)
        eye_r = r * 0.07
        for ex in (-0.2, 0.2):
            draw.ellipse((cx + r * ex - eye_r, cy - r * 0.08 - eye_r, cx + r * ex + eye_r, cy - r * 0.08 + eye_r),
                          fill=col)

    elif key == "biology":
        top_y, bot_y = cy - r * 0.55, cy + r * 0.55
        steps = 6
        for i in range(steps + 1):
            t = i / steps
            y = top_y + (bot_y - top_y) * t
            import math
            spread = math.sin(t * math.pi * 2.2) * r * 0.32
            lx, rx = cx - spread, cx + spread
            dot_r = r * 0.06
            draw.ellipse((lx - dot_r, y - dot_r, lx + dot_r, y + dot_r), fill=col)
            draw.ellipse((rx - dot_r, y - dot_r, rx + dot_r, y + dot_r), fill=col)
            if i % 2 == 0:
                draw.line([(lx, y), (rx, y)], fill=col, width=int(w * 0.6))

    elif key == "teacher":
        draw.polygon([(cx, cy - r * 0.45), (cx + r * 0.55, cy - r * 0.08), (cx, cy + r * 0.28),
                       (cx - r * 0.55, cy - r * 0.08)], outline=col, width=int(w))
        draw.rectangle((cx - r * 0.22, cy + r * 0.28, cx + r * 0.22, cy + r * 0.44), outline=col, width=int(w * 0.8))
        draw.line([(cx + r * 0.5, cy - r * 0.02), (cx + r * 0.5, cy + r * 0.35)], fill=col, width=int(w * 0.6))
        draw.ellipse((cx + r * 0.5 - r * 0.06, cy + r * 0.35 - r * 0.06, cx + r * 0.5 + r * 0.06,
                       cy + r * 0.35 + r * 0.06), fill=col)

    elif key == "star":
        import math
        pts = []
        for i in range(10):
            ang = -math.pi / 2 + i * math.pi / 5
            rad = r * (0.62 if i % 2 == 0 else 0.26)
            pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
        draw.polygon(pts, fill=col)

    elif key == "business":
        base_y = cy + r * 0.45
        bars = [(-0.4, 0.25), (-0.05, 0.5), (0.3, 0.7)]
        bw = r * 0.24
        for bx, bh in bars:
            x0, x1 = cx + r * bx - bw / 2, cx + r * bx + bw / 2
            y0 = base_y - r * bh
            draw.rounded_rectangle((x0, y0, x1, base_y), radius=bw * 0.25, fill=col)
        draw.line([(cx - r * 0.5, cy - r * 0.05), (cx - r * 0.1, cy - r * 0.4), (cx + r * 0.15, cy - r * 0.2),
                    (cx + r * 0.55, cy - r * 0.55)], fill=col, width=int(w * 0.7), joint="curve")

    else:
        draw.ellipse((cx - r * 0.4, cy - r * 0.4, cx + r * 0.4, cy + r * 0.4), fill=col)


def build_icon_png(color_hex, icon_key, size=240):
    c = hex_to_rgb(color_hex)
    grad = diagonal_gradient((size, size), lighten(c, 0.1), darken(c, 0.3))

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)

    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)

    draw = ImageDraw.Draw(out)
    draw_glyph(draw, size / 2, size / 2, size * 0.32, icon_key)

    buf = BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def build_cover_png(color_hex, icon_key, size=(900, 280)):
    c = hex_to_rgb(color_hex)
    grad = diagonal_gradient(size, lighten(c, 0.06), darken(c, 0.34)).convert("RGBA")

    glyph_layer = Image.new("RGBA", size, (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glyph_layer)
    gw, gh = size
    draw_glyph(gdraw, gw * 0.8, gh * 0.5, gh * 0.6, icon_key, alpha=45)

    out = Image.alpha_composite(grad, glyph_layer).convert("RGB")
    buf = BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()

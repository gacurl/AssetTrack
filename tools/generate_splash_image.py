# file: tools/generate_splash_image.py
# Generates a deterministic AssetTrack splash PNG via Pillow.
# Usage: python3 tools/generate_splash_image.py

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


# Canvas / output
CANVAS_WIDTH = 2200
CANVAS_HEIGHT = 650
OUTPUT_PATH = Path("assettrack/intake/static/img/assettrack-splash.png")

# Palette
BACKGROUND = "#fefefe"
CARD_BG = "#ffffff"
CARD_BORDER = "#dedede"
TEXT_DARK = "#15161a"
TEXT_MID = "#33363b"
TEXT_LIGHT = "#a2a2a2"
ORANGE = "#ff4b1f"
SHADOW = (0, 0, 0, 14)

# Layout (easy tuning)
TITLE_CENTER_X = 1100
TITLE_Y = 54
LOGIN_LABEL_Y = 130

CARD_X = 750
CARD_Y = 182
CARD_W = 700
CARD_H = 260
CARD_RADIUS = 12

BOTTOM_ORANGE_X = 0
BOTTOM_ORANGE_Y = 542
BOTTOM_ORANGE_W = 335
BOTTOM_ORANGE_H = 68

BRAND_X = 118
BRAND_BASELINE_Y = 588
FINGERPRINT_CENTER = (1915, 562)
FINGERPRINT_RADIUS = 150


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    heavy_candidates = [
        "Arial Black.ttf",
        "Arial Black",
        "/System/Library/Fonts/Supplemental/Arial Black.ttf",
        "/Library/Fonts/Arial Black.ttf",
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    ]
    regular_candidates = [
        "Arial.ttf",
        "Arial",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]
    candidates = heavy_candidates if bold else regular_candidates
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_tracked_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: str,
    tracking: int,
) -> tuple[int, int, int, int]:
    x, y = xy
    left = x
    top = None
    bottom = None
    for i, ch in enumerate(text):
        bbox = draw.textbbox((x, y), ch, font=font)
        draw.text((x, y), ch, font=font, fill=fill)
        top = bbox[1] if top is None else min(top, bbox[1])
        bottom = bbox[3] if bottom is None else max(bottom, bbox[3])
        x = bbox[2] + (tracking if i < len(text) - 1 else 0)
    return (left, top or y, x, bottom or y)


def _tracked_text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, tracking: int) -> int:
    x = 0
    for i, ch in enumerate(text):
        bbox = draw.textbbox((x, 0), ch, font=font)
        x = bbox[2] + (tracking if i < len(text) - 1 else 0)
    return x


def _center_tracked_text(
    draw: ImageDraw.ImageDraw,
    center_x: int,
    y: int,
    text: str,
    font: ImageFont.ImageFont,
    fill: str,
    tracking: int,
) -> None:
    width = _tracked_text_width(draw, text, font, tracking)
    _draw_tracked_text(draw, (center_x - width // 2, y), text, font, fill, tracking)


def _draw_rounded_rect(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    radius: int,
    fill: str,
    outline: str | None = None,
    width: int = 1,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _draw_card_shadow(base: Image.Image, box: tuple[int, int, int, int], radius: int) -> None:
    # Lightweight faux shadow using layered translucent rounded rectangles (no blur dependency).
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    x0, y0, x1, y1 = box
    for i, alpha in enumerate([18, 14, 10, 7]):
        odraw.rounded_rectangle(
            (x0 - 2 - i * 2, y0 + 6 + i * 4, x1 + 2 + i * 2, y1 + 12 + i * 4),
            radius=radius + i * 2,
            fill=(0, 0, 0, alpha),
        )
    base.alpha_composite(overlay)


def _draw_user_icon(draw: ImageDraw.ImageDraw, x: int, y: int, color: str) -> None:
    draw.ellipse((x + 7, y + 4, x + 19, y + 16), outline=color, width=2)
    draw.arc((x + 2, y + 14, x + 24, y + 30), start=200, end=340, fill=color, width=2)


def _draw_lock_icon(draw: ImageDraw.ImageDraw, x: int, y: int, color: str) -> None:
    draw.rounded_rectangle((x + 4, y + 12, x + 22, y + 28), radius=2, outline=color, width=2)
    draw.arc((x + 6, y + 4, x + 20, y + 18), start=200, end=340, fill=color, width=2)
    draw.line((x + 13, y + 18, x + 13, y + 24), fill=color, width=2)


def _draw_eye_off_icon(draw: ImageDraw.ImageDraw, x: int, y: int, color: str) -> None:
    draw.arc((x + 2, y + 10, x + 30, y + 26), start=200, end=340, fill=color, width=2)
    draw.arc((x + 2, y + 8, x + 30, y + 24), start=20, end=160, fill=color, width=2)
    draw.ellipse((x + 13, y + 13, x + 19, y + 19), outline=color, width=2)
    draw.line((x + 4, y + 6, x + 28, y + 28), fill=color, width=2)


def _draw_fingerprint(draw: ImageDraw.ImageDraw, center: tuple[int, int], max_radius: int) -> None:
    cx, cy = center
    # Dense, thin arcs resembling the mock's lower-right fingerprint.
    for i in range(34):
        rx = max_radius - i * 4
        ry = int(max_radius * 0.88) - i * 3
        if rx < 24 or ry < 20:
            break

        box = (cx - rx + (i // 6), cy - ry - (i // 10), cx + rx + (i // 9), cy + ry)
        width = 1 if i > 2 else 2
        start = 206 + (i % 4) * 3
        end = 522 - (i % 6) * 5
        draw.arc(box, start=start, end=end, fill=TEXT_DARK, width=width)

        # Deterministic white gaps for a fingerprint-ridge look.
        if i % 2 == 0:
            draw.arc(box, start=291, end=318, fill=BACKGROUND, width=width + 1)
        if i % 3 == 1:
            draw.arc(box, start=110, end=130, fill=BACKGROUND, width=width + 1)
        if i % 5 == 2:
            draw.arc(box, start=436, end=452, fill=BACKGROUND, width=width + 1)

    # Inner swirl / off-center core.
    for i in range(18):
        r = 54 - i * 2
        if r < 12:
            break
        dx = i // 2
        dy = -(i // 6)
        draw.arc(
            (cx - r + dx, cy - r + dy, cx + r + dx, cy + r + dy),
            start=210 + i * 2,
            end=468 - i * 4,
            fill=TEXT_DARK,
            width=1 if i > 4 else 2,
        )


def _draw_login_card(draw: ImageDraw.ImageDraw, image: Image.Image) -> None:
    card_box = (CARD_X, CARD_Y, CARD_X + CARD_W, CARD_Y + CARD_H)
    _draw_card_shadow(image.convert("RGBA"), card_box, CARD_RADIUS)


def _draw_login_card_elements(draw: ImageDraw.ImageDraw, image: Image.Image) -> None:
    # Shadow drawn on RGBA base and merged back.
    rgba = image.convert("RGBA")
    _draw_card_shadow(rgba, (CARD_X, CARD_Y, CARD_X + CARD_W, CARD_Y + CARD_H), CARD_RADIUS)
    image.paste(rgba.convert("RGB"))

    _draw_rounded_rect(
        draw,
        (CARD_X, CARD_Y, CARD_X + CARD_W, CARD_Y + CARD_H),
        radius=CARD_RADIUS,
        fill=CARD_BG,
        outline=CARD_BORDER,
        width=2,
    )

    label_font = _load_font(18, bold=True)
    input_font = _load_font(17, bold=False)
    button_font = _load_font(24, bold=True)

    field_left = CARD_X + 58
    field_right = CARD_X + CARD_W - 58
    input_h = 34

    # NAME label
    _center_tracked_text(draw, CARD_X + CARD_W // 2, CARD_Y + 22, "NAME", label_font, TEXT_DARK, tracking=7)
    draw.line((CARD_X + 280, CARD_Y + 43, CARD_X + 420, CARD_Y + 43), fill=ORANGE, width=2)

    # Name input
    name_y = CARD_Y + 49
    _draw_rounded_rect(draw, (field_left, name_y, field_right, name_y + input_h), radius=5, fill="#f8f8f8", outline="#d9d9de")
    _draw_user_icon(draw, field_left + 10, name_y + 2, "#4f4f54")
    draw.text((field_left + 44, name_y + 8), "Enter your name", font=input_font, fill=TEXT_LIGHT)

    # PASSWORD label
    _center_tracked_text(draw, CARD_X + CARD_W // 2, CARD_Y + 100, "PASSWORD", label_font, TEXT_DARK, tracking=6)
    draw.line((CARD_X + 245, CARD_Y + 121, CARD_X + 455, CARD_Y + 121), fill=ORANGE, width=2)

    # Password input
    pwd_y = CARD_Y + 127
    _draw_rounded_rect(draw, (field_left, pwd_y, field_right, pwd_y + input_h), radius=5, fill="#f8f8f8", outline="#d9d9de")
    _draw_lock_icon(draw, field_left + 9, pwd_y + 1, "#4f4f54")
    draw.text((field_left + 44, pwd_y + 8), "Enter your password", font=input_font, fill=TEXT_LIGHT)
    _draw_eye_off_icon(draw, field_right - 40, pwd_y + 2, "#2f2f33")

    # Button
    btn_y = CARD_Y + 179
    _draw_rounded_rect(draw, (field_left, btn_y, field_right, btn_y + 42), radius=5, fill=ORANGE)
    _center_tracked_text(draw, CARD_X + CARD_W // 2 - 10, btn_y + 7, "LOGIN", button_font, "#ffffff", tracking=8)
    # Arrow icon
    ax = field_right - 38
    ay = btn_y + 21
    draw.line((ax - 18, ay, ax + 6, ay), fill="#ffffff", width=3)
    draw.line((ax - 2, ay - 8, ax + 6, ay), fill="#ffffff", width=3)
    draw.line((ax - 2, ay + 8, ax + 6, ay), fill="#ffffff", width=3)


def _draw_bottom_brand(draw: ImageDraw.ImageDraw) -> None:
    # Orange block with a soft stepped fade to mimic the mock's left accent.
    for x in range(BOTTOM_ORANGE_W):
        alpha_mix = max(0.0, min(1.0, 1.0 - max(0, x - (BOTTOM_ORANGE_W - 70)) / 70))
        if x < BOTTOM_ORANGE_W - 70:
            color = ORANGE
        else:
            # Blend toward background using line primitives only.
            r0, g0, b0 = (255, 75, 31)
            r1, g1, b1 = (254, 254, 254)
            t = 1.0 - alpha_mix
            color = (int(r0 * alpha_mix + r1 * t), int(g0 * alpha_mix + g1 * t), int(b0 * alpha_mix + b1 * t))
        draw.line((BOTTOM_ORANGE_X + x, BOTTOM_ORANGE_Y, BOTTOM_ORANGE_X + x, BOTTOM_ORANGE_Y + BOTTOM_ORANGE_H), fill=color)

    brand_bold = _load_font(50, bold=True)
    brand_regular = _load_font(50, bold=False)
    asset_text = "ASSET"
    track_text = "TRACK"

    asset_bbox = draw.textbbox((0, 0), asset_text, font=brand_bold)
    track_bbox = draw.textbbox((0, 0), track_text, font=brand_regular)
    top_y = BRAND_BASELINE_Y - (asset_bbox[3] - asset_bbox[1])

    draw.text((BRAND_X, top_y), asset_text, font=brand_bold, fill=TEXT_DARK)
    track_x = BRAND_X + (asset_bbox[2] - asset_bbox[0]) + 6
    draw.text((track_x, top_y), track_text, font=brand_regular, fill=TEXT_MID)

    underline_y = BRAND_BASELINE_Y + 6
    underline_x0 = BRAND_X
    underline_x1 = track_x + (track_bbox[2] - track_bbox[0]) - 6
    draw.line((underline_x0, underline_y, underline_x1, underline_y), fill=ORANGE, width=3)

    # Chevron accent before the fingerprint.
    chevron_x = underline_x1 + 34
    chevron_y = top_y + 26
    draw.polygon([(chevron_x, chevron_y), (chevron_x + 18, chevron_y + 12), (chevron_x, chevron_y + 24)], fill=ORANGE)

    # Subtle dot grid near the footer to echo the mock.
    dot_color = "#ececec"
    for y in range(CANVAS_HEIGHT - 36, CANVAS_HEIGHT - 6, 7):
        for x in range(18, 1550, 12):
            if 980 < x < 1180:
                continue
            draw.point((x, y), fill=dot_color)

    # Thin footer rule with orange segment.
    rule_y = CANVAS_HEIGHT - 2
    draw.line((80, rule_y, 1540, rule_y), fill="#e8e8e8", width=1)
    draw.line((260, rule_y, 1080, rule_y), fill=ORANGE, width=1)


def generate() -> Path:
    image = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)

    title_font = _load_font(60, bold=True)
    login_font = _load_font(24, bold=True)

    title_text = "BOLD QUEST"
    title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
    draw.text((TITLE_CENTER_X - (title_bbox[2] - title_bbox[0]) // 2, TITLE_Y), title_text, font=title_font, fill=TEXT_DARK)

    _center_tracked_text(draw, TITLE_CENTER_X, LOGIN_LABEL_Y, "LOGIN", login_font, TEXT_DARK, tracking=7)

    _draw_login_card_elements(draw, image)
    _draw_bottom_brand(draw)
    _draw_fingerprint(draw, FINGERPRINT_CENTER, FINGERPRINT_RADIUS)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        dir=str(OUTPUT_PATH.parent), prefix=".assettrack-splash-", suffix=".png", delete=False
    ) as tmp:
        tmp_path = Path(tmp.name)

    try:
        image.save(tmp_path, format="PNG", optimize=True)
        os.replace(tmp_path, OUTPUT_PATH)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    return OUTPUT_PATH


if __name__ == "__main__":
    output = generate()
    print(f"Generated {output}")

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


SIZE = 1024
OUTPUT = Path("mnt_v7_0_red_avatar.png")


def _hex(rgb: str) -> tuple[int, int, int]:
    rgb = rgb.lstrip("#")
    return tuple(int(rgb[i : i + 2], 16) for i in (0, 2, 4))


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        Path(r"C:\Windows\Fonts\arialbd.ttf"),
        Path(r"C:\Windows\Fonts\Arialbd.ttf"),
        Path(r"C:\Windows\Fonts\segoeuib.ttf"),
        Path(r"C:\Windows\Fonts\seguisb.ttf"),
        Path(r"C:\Windows\Fonts\bahnschrift.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _red_gradient(size: int) -> Image.Image:
    dark = _hex("#31040d")
    red = _hex("#b70c26")
    bright = _hex("#ff3048")
    ember = _hex("#ff7a3d")
    img = Image.new("RGB", (size, size))
    px = img.load()
    cx, cy = size * 0.36, size * 0.30
    max_r = math.hypot(size, size)

    for y in range(size):
        for x in range(size):
            linear = (x * 0.72 + y * 1.05) / (size * 1.77)
            radial = math.hypot(x - cx, y - cy) / max_r
            if linear < 0.44:
                color = _lerp(dark, red, linear / 0.44)
            else:
                color = _lerp(red, bright, (linear - 0.44) / 0.56)
            if radial < 0.23:
                color = _lerp(color, ember, (0.23 - radial) / 0.23 * 0.55)
            vignette = math.hypot(x - size / 2, y - size / 2) / (size * 0.72)
            color = _lerp(color, dark, max(0.0, vignette - 0.48) * 0.55)
            px[x, y] = color
    return img


def _draw_market_texture(base: Image.Image) -> None:
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    for x in range(-220, SIZE + 240, 72):
        draw.line((x, 0, x + 420, SIZE), fill=(255, 190, 190, 23), width=2)
    for y in range(138, SIZE, 108):
        draw.line((0, y, SIZE, y - 90), fill=(65, 0, 20, 34), width=2)

    candle_x = 152
    heights = [62, 116, 84, 142, 96, 176, 128, 210, 154]
    for i, h in enumerate(heights):
        x = candle_x + i * 86
        top = 760 - h
        bottom = 760
        color = (255, 228, 220, 44) if i % 2 else (90, 0, 24, 70)
        draw.line((x + 12, top - 34, x + 12, bottom + 28), fill=color, width=4)
        draw.rounded_rectangle((x, top, x + 24, bottom), radius=6, fill=color)

    points = [(130, 692), (244, 640), (348, 665), (462, 570), (590, 592), (730, 486), (884, 524)]
    draw.line(points, fill=(255, 246, 235, 86), width=8, joint="curve")
    draw.line(points, fill=(255, 77, 79, 150), width=3, joint="curve")

    layer = layer.filter(ImageFilter.GaussianBlur(radius=0.35))
    base.alpha_composite(layer)


def _draw_glass_panel(base: Image.Image) -> None:
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.rounded_rectangle((132, 276, 892, 688), radius=58, fill=(38, 0, 12, 152))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=26))
    base.alpha_composite(shadow)

    panel = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(panel)
    draw.rounded_rectangle((128, 260, 896, 676), radius=58, fill=(255, 240, 235, 42))
    draw.rounded_rectangle((128, 260, 896, 676), radius=58, outline=(255, 224, 216, 120), width=3)
    draw.rounded_rectangle((158, 292, 866, 392), radius=34, fill=(255, 255, 255, 31))
    panel = panel.filter(ImageFilter.GaussianBlur(radius=0.2))
    base.alpha_composite(panel)


def _draw_centered_text(
    base: Image.Image,
    text: str,
    font: ImageFont.FreeTypeFont,
    y_center: int,
    fill: tuple[int, int, int],
    shadow: tuple[int, int, int],
    shadow_blur: int,
    stroke: tuple[int, int, int] | None = None,
    stroke_width: int = 0,
) -> None:
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    x = (base.width - (bbox[2] - bbox[0])) / 2
    y = y_center - (bbox[3] - bbox[1]) / 2 - bbox[1]

    draw.text((x + 16, y + 22), text, font=font, fill=shadow + (210,), stroke_width=stroke_width)
    layer = layer.filter(ImageFilter.GaussianBlur(radius=shadow_blur))
    base.alpha_composite(layer)

    draw = ImageDraw.Draw(base)
    kwargs = {}
    if stroke is not None and stroke_width:
        kwargs = {"stroke_width": stroke_width, "stroke_fill": stroke + (255,)}
    draw.text((x, y), text, font=font, fill=fill + (255,), **kwargs)


def _draw_corner_marks(base: Image.Image) -> None:
    draw = ImageDraw.Draw(base)
    accent = (255, 224, 210, 205)
    dark = (81, 0, 22, 150)
    for offset in (0, 20):
        draw.line((180 + offset, 202, 308 + offset, 202), fill=accent if offset == 0 else dark, width=8)
        draw.line((180, 202 + offset, 180, 330 + offset), fill=accent if offset == 0 else dark, width=8)
        draw.line((844 - offset, 824, 716 - offset, 824), fill=accent if offset == 0 else dark, width=8)
        draw.line((844, 824 - offset, 844, 696 - offset), fill=accent if offset == 0 else dark, width=8)


def main() -> None:
    bg = _red_gradient(SIZE).convert("RGBA")
    _draw_market_texture(bg)
    _draw_glass_panel(bg)
    _draw_corner_marks(bg)

    title_font = _load_font(330)
    label_font = _load_font(80)
    small_font = _load_font(36)

    _draw_centered_text(
        bg,
        "7.0",
        title_font,
        y_center=474,
        fill=_hex("#fff4ec"),
        shadow=_hex("#4b0014"),
        shadow_blur=13,
        stroke=_hex("#8d061d"),
        stroke_width=4,
    )
    _draw_centered_text(
        bg,
        "MNT",
        label_font,
        y_center=742,
        fill=_hex("#ffe1d3"),
        shadow=_hex("#510015"),
        shadow_blur=6,
        stroke=_hex("#8d061d"),
        stroke_width=1,
    )
    _draw_centered_text(
        bg,
        "STRATEGY SIGNAL",
        small_font,
        y_center=826,
        fill=_hex("#ffc4b6"),
        shadow=_hex("#510015"),
        shadow_blur=4,
    )

    bg.convert("RGB").save(OUTPUT, quality=95)
    print(OUTPUT.resolve())


if __name__ == "__main__":
    main()

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


SIZE = 1024
OUTPUT = Path("mnt_v7_1_blue_avatar.png")


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


def _blue_gradient(size: int) -> Image.Image:
    dark = _hex("#2a5f9f")
    navy = _hex("#4e8fda")
    cobalt = _hex("#6eb8ff")
    cyan = _hex("#8fe9ff")
    ice = _hex("#f0feff")
    img = Image.new("RGB", (size, size))
    px = img.load()
    cx, cy = size * 0.66, size * 0.24
    max_r = math.hypot(size, size)

    for y in range(size):
        for x in range(size):
            linear = (x * 0.82 + y * 1.04) / (size * 1.86)
            radial = math.hypot(x - cx, y - cy) / max_r
            if linear < 0.38:
                color = _lerp(dark, navy, linear / 0.38)
            elif linear < 0.72:
                color = _lerp(navy, cobalt, (linear - 0.38) / 0.34)
            else:
                color = _lerp(cobalt, cyan, (linear - 0.72) / 0.28)
            if radial < 0.21:
                color = _lerp(color, ice, (0.21 - radial) / 0.21 * 0.48)
            vignette = math.hypot(x - size / 2, y - size / 2) / (size * 0.71)
            color = _lerp(color, dark, max(0.0, vignette - 0.46) * 0.58)
            px[x, y] = color
    return img


def _draw_market_texture(base: Image.Image) -> None:
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    for x in range(-180, SIZE + 260, 76):
        draw.line((x, 80, x + 360, SIZE - 40), fill=(180, 244, 255, 24), width=2)
    for y in range(160, SIZE, 104):
        draw.line((0, y, SIZE, y - 70), fill=(5, 20, 44, 44), width=2)

    candle_x = 160
    heights = [74, 108, 92, 156, 118, 184, 146, 220, 168]
    for i, h in enumerate(heights):
        x = candle_x + i * 84
        top = 768 - h
        bottom = 768
        color = (214, 251, 255, 52) if i % 2 else (9, 28, 58, 82)
        draw.line((x + 12, top - 32, x + 12, bottom + 24), fill=color, width=4)
        draw.rounded_rectangle((x, top, x + 24, bottom), radius=6, fill=color)

    mix_lines = [
        ((132, 696), (240, 660), (350, 646), (458, 600), (582, 552), (718, 498), (874, 470)),
        ((132, 726), (244, 706), (352, 682), (468, 646), (596, 606), (730, 570), (878, 544)),
        ((132, 760), (244, 750), (356, 734), (478, 710), (612, 684), (748, 658), (888, 642)),
    ]
    colors = [(199, 244, 255, 88), (71, 213, 255, 128), (9, 54, 112, 140)]
    widths = [8, 6, 4]
    for points, color, width in zip(mix_lines, colors, widths):
        draw.line(points, fill=color, width=width, joint="curve")

    layer = layer.filter(ImageFilter.GaussianBlur(radius=0.4))
    base.alpha_composite(layer)


def _draw_glass_panel(base: Image.Image) -> None:
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.rounded_rectangle((124, 270, 900, 686), radius=58, fill=(6, 18, 40, 132))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=24))
    base.alpha_composite(shadow)

    panel = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(panel)
    draw.rounded_rectangle((120, 254, 904, 674), radius=58, fill=(236, 250, 255, 34))
    draw.rounded_rectangle((120, 254, 904, 674), radius=58, outline=(220, 249, 255, 118), width=3)
    draw.rounded_rectangle((154, 286, 870, 392), radius=34, fill=(255, 255, 255, 28))
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
    accent = (216, 248, 255, 205)
    dark = (8, 29, 60, 160)
    for offset in (0, 20):
        draw.line((178 + offset, 198, 306 + offset, 198), fill=accent if offset == 0 else dark, width=8)
        draw.line((178, 198 + offset, 178, 326 + offset), fill=accent if offset == 0 else dark, width=8)
        draw.line((846 - offset, 826, 718 - offset, 826), fill=accent if offset == 0 else dark, width=8)
        draw.line((846, 826 - offset, 846, 698 - offset), fill=accent if offset == 0 else dark, width=8)


def main() -> None:
    bg = _blue_gradient(SIZE).convert("RGBA")
    _draw_market_texture(bg)
    _draw_glass_panel(bg)
    _draw_corner_marks(bg)

    title_font = _load_font(322)
    label_font = _load_font(78)
    small_font = _load_font(34)

    _draw_centered_text(
        bg,
        "7.1",
        title_font,
        y_center=474,
        fill=_hex("#eefcff"),
        shadow=_hex("#07152f"),
        shadow_blur=13,
        stroke=_hex("#1a64c5"),
        stroke_width=4,
    )
    _draw_centered_text(
        bg,
        "MNT",
        label_font,
        y_center=742,
        fill=_hex("#d4f7ff"),
        shadow=_hex("#081b3e"),
        shadow_blur=6,
        stroke=_hex("#134e9f"),
        stroke_width=1,
    )
    _draw_centered_text(
        bg,
        "MIX SIGNAL",
        small_font,
        y_center=822,
        fill=_hex("#9beaff"),
        shadow=_hex("#081b3e"),
        shadow_blur=4,
    )

    bg.convert("RGB").save(OUTPUT, quality=95)
    print(OUTPUT.resolve())


if __name__ == "__main__":
    main()

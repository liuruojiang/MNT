from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


SIZE = 1024
OUTPUT = Path("mnt_v6_5_gold_avatar.png")


def _hex(rgb: str) -> tuple[int, int, int]:
    rgb = rgb.lstrip("#")
    return tuple(int(rgb[i : i + 2], 16) for i in (0, 2, 4))


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def _radial_gold_background(size: int) -> Image.Image:
    center = _hex("#ffd867")
    mid = _hex("#e1af2d")
    edge = _hex("#aa6f08")
    img = Image.new("RGB", (size, size))
    px = img.load()
    cx = cy = size / 2
    max_r = (2 * (cx**2)) ** 0.5
    for y in range(size):
        for x in range(size):
            dx = x - cx
            dy = y - cy
            r = (dx * dx + dy * dy) ** 0.5 / max_r
            if r < 0.42:
                color = _lerp(center, mid, r / 0.42)
            else:
                color = _lerp(mid, edge, min(1.0, (r - 0.42) / 0.58))
            px[x, y] = color
    return img


def _load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        Path(r"C:\Windows\Fonts\arialbd.ttf"),
        Path(r"C:\Windows\Fonts\Arialbd.ttf"),
        Path(r"C:\Windows\Fonts\seguisb.ttf"),
        Path(r"C:\Windows\Fonts\segoeuib.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _draw_centered_text(
    base: Image.Image,
    text: str,
    font: ImageFont.FreeTypeFont,
    y_center: int,
    fill: tuple[int, int, int],
    shadow: tuple[int, int, int],
    blur: int,
    shadow_offset: tuple[int, int],
) -> None:
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    bbox = draw.textbbox((0, 0), text, font=font)
    x = (base.width - (bbox[2] - bbox[0])) / 2
    y = y_center - (bbox[3] - bbox[1]) / 2
    draw.text((x + shadow_offset[0], y + shadow_offset[1]), text, font=font, fill=shadow + (180,))
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=blur))
    Image.Image.alpha_composite(base, overlay)
    draw = ImageDraw.Draw(base)
    draw.text((x, y), text, font=font, fill=fill + (255,))


def _draw_arc_rings(base: Image.Image) -> None:
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    bbox = (146, 116, 878, 906)
    for width in (8, 4):
        sdraw.arc(bbox, start=200, end=340, fill=(60, 30, 0, 170), width=width)
        sdraw.arc(bbox, start=20, end=160, fill=(60, 30, 0, 170), width=width)
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=6))
    Image.Image.alpha_composite(base, shadow)

    draw = ImageDraw.Draw(base)
    outer_dark = _hex("#8d5f0b") + (255,)
    inner_light = _hex("#f4d26a") + (255,)
    outer_bbox = (148, 118, 876, 904)
    inner_bbox = (154, 124, 870, 898)
    for start, end in ((200, 340), (20, 160)):
        draw.arc(outer_bbox, start=start, end=end, fill=outer_dark, width=6)
        draw.arc(inner_bbox, start=start, end=end, fill=inner_light, width=3)


def main() -> None:
    bg = _radial_gold_background(SIZE).convert("RGBA")

    vignette = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    vdraw = ImageDraw.Draw(vignette)
    vdraw.ellipse((54, 54, 970, 970), fill=(255, 220, 120, 32))
    vignette = vignette.filter(ImageFilter.GaussianBlur(radius=42))
    bg = Image.alpha_composite(bg, vignette)

    _draw_arc_rings(bg)

    title_font = _load_font("title", 246)
    subtitle_font = _load_font("subtitle", 92)
    main_fill = _hex("#fff9df")
    shadow = _hex("#7b5811")

    _draw_centered_text(
        bg,
        "V6.5",
        title_font,
        y_center=468,
        fill=main_fill,
        shadow=shadow,
        blur=8,
        shadow_offset=(10, 12),
    )
    _draw_centered_text(
        bg,
        "MNT",
        subtitle_font,
        y_center=694,
        fill=main_fill,
        shadow=shadow,
        blur=5,
        shadow_offset=(6, 8),
    )

    bg.convert("RGB").save(OUTPUT, quality=95)
    print(OUTPUT.resolve())


if __name__ == "__main__":
    main()

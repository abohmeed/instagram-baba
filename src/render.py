"""Compose the post image: text laid over a darkened photograph.

Arabic shaping is handled by libraqm (bundled in Pillow's wheels), which does
the bidi reordering and contextual letter forms correctly, including the dense
Uthmani diacritics. If Pillow was built without Raqm we fall back to manual
reshaping via arabic-reshaper + python-bidi.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

from .arabic import shape_fallback, strip_waqf

ROOT = Path(__file__).resolve().parents[1]
HAS_RAQM = features.check("raqm")


def _hex_to_rgb(value: str) -> tuple:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _prepare(text: str, direction: str) -> str:
    """Raqm shapes in place; without it we must pre-shape and pre-reorder."""
    if HAS_RAQM or direction != "rtl":
        return text
    return shape_fallback(text)


def _text_kwargs(direction: str, language: str) -> dict:
    if not HAS_RAQM:
        return {}
    return {"direction": direction, "language": language}


def _fit_background(image: Image.Image, width: int, height: int) -> Image.Image:
    """Center-crop to the target aspect ratio, then resize."""
    target = width / height
    w, h = image.size
    current = w / h
    if current > target:
        new_w = int(h * target)
        left = (w - new_w) // 2
        image = image.crop((left, 0, left + new_w, h))
    elif current < target:
        new_h = int(w / target)
        top = (h - new_h) // 2
        image = image.crop((0, top, w, top + new_h))
    return image.resize((width, height), Image.LANCZOS)


def _darken(image: Image.Image, cfg: dict) -> Image.Image:
    blur = float(cfg.get("blur_radius", 0) or 0)
    if blur > 0:
        image = image.filter(ImageFilter.GaussianBlur(blur))

    opacity = float(cfg.get("overlay_opacity", 0.45))
    if opacity > 0:
        overlay = Image.new("RGB", image.size, (0, 0, 0))
        image = Image.blend(image, overlay, min(max(opacity, 0.0), 1.0))

    strength = float(cfg.get("vignette", 0) or 0)
    if strength > 0:
        w, h = image.size
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).ellipse(
            (-w * 0.18, -h * 0.18, w * 1.18, h * 1.18), fill=255
        )
        mask = mask.filter(ImageFilter.GaussianBlur(min(w, h) / 7))
        shade = Image.new("RGB", (w, h), (0, 0, 0))
        faded = Image.blend(image, shade, min(max(strength, 0.0), 1.0))
        image = Image.composite(image, faded, mask)

    return image


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int, tk: dict) -> list:
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if font.getlength(candidate, **tk) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _balance(text: str, font: ImageFont.FreeTypeFont, max_width: int, tk: dict) -> list:
    """Re-wrap at the narrowest width that still yields the same line count.

    Greedy wrapping leaves a lone short word on the last line; shrinking the
    measuring width until the count would change spreads the words evenly.
    """
    lines = _wrap(text, font, max_width, tk)
    if len(lines) < 2:
        return lines

    target = len(lines)
    lo, hi = int(max_width * 0.5), max_width
    best = lines
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = _wrap(text, font, mid, tk)
        if len(candidate) <= target and all(
            font.getlength(line, **tk) <= max_width for line in candidate
        ):
            best = candidate
            hi = mid - 1
        else:
            lo = mid + 1
    return best


def _layout(text: str, cfg: dict, box: tuple, direction: str, language: str):
    """Find the largest font size whose wrapped text fits the box."""
    font_path = ROOT / cfg["font"]
    if not font_path.exists():
        raise RuntimeError(f"Font not found: {font_path}")

    max_w, max_h = box
    spacing = float(cfg.get("line_spacing", 1.5))
    tk = _text_kwargs(direction, language)
    shaped = _prepare(text, direction)

    size = int(cfg.get("max_font_size", 92))
    floor = int(cfg.get("min_font_size", 30))
    while size >= floor:
        font = ImageFont.truetype(str(font_path), size)
        lines = _wrap(shaped, font, max_w, tk)
        line_height = size * spacing
        if len(lines) * line_height <= max_h and all(
            font.getlength(line, **tk) <= max_w for line in lines
        ):
            return font, _balance(shaped, font, max_w, tk), line_height
        size -= 2

    font = ImageFont.truetype(str(font_path), floor)
    return font, _balance(shaped, font, max_w, tk), floor * spacing


def _draw_block(base, lines, font, line_height, top, center_x, colour, tk, shadow):
    if shadow:
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        drawer = ImageDraw.Draw(layer)
        for i, line in enumerate(lines):
            drawer.text(
                (center_x, top + i * line_height + line_height / 2),
                line, font=font, fill=(0, 0, 0, 170), anchor="mm", **tk,
            )
        base.alpha_composite(layer.filter(ImageFilter.GaussianBlur(7)))

    draw = ImageDraw.Draw(base)
    for i, line in enumerate(lines):
        draw.text(
            (center_x, top + i * line_height + line_height / 2),
            line, font=font, fill=colour, anchor="mm", **tk,
        )


def compose(profile, item: dict, background: Image.Image, reference: str) -> Image.Image:
    cfg = profile["image"]
    direction = profile["content"].get("direction", "rtl")
    language = profile["content"].get("language", "ar")
    width, height = int(cfg["width"]), int(cfg["height"])

    canvas = _darken(_fit_background(background, width, height), cfg).convert("RGBA")

    box_cfg = cfg.get("text_box", {})
    box = (
        int(width * float(box_cfg.get("width_pct", 0.84))),
        int(height * float(box_cfg.get("height_pct", 0.58))),
    )
    verse = item["text"]
    if profile["content"].get("strip_waqf", True):
        verse = strip_waqf(verse)
    font, lines, line_height = _layout(verse, cfg, box, direction, language)

    tk = _text_kwargs(direction, language)
    ref_size = int(cfg.get("reference_size", 36))
    ref_font = ImageFont.truetype(
        str(ROOT / cfg.get("reference_font", cfg["font"])), ref_size
    )
    ref_line_height = ref_size * 1.4
    gap = height * float(cfg.get("reference_gap_pct", 0.05))

    # Centre the verse and its reference as one group, so the composition sits
    # on the optical centre rather than the verse alone sitting high.
    block_height = len(lines) * line_height
    group_height = block_height + gap + ref_line_height
    top = (height - group_height) / 2

    _draw_block(
        canvas, lines, font, line_height, top, width / 2,
        _hex_to_rgb(cfg.get("text_color", "#FFFFFF")) + (255,),
        tk, bool(cfg.get("shadow", True)),
    )
    _draw_block(
        canvas, [_prepare(reference, direction)], ref_font, ref_line_height,
        top + block_height + gap, width / 2,
        _hex_to_rgb(cfg.get("reference_color", "#E9E2D2")) + (235,),
        tk, bool(cfg.get("shadow", True)),
    )

    # Optional handle in the bottom margin.
    signature = cfg.get("signature") or ""
    if signature:
        sig_font = ImageFont.truetype(
            str(ROOT / cfg.get("reference_font", cfg["font"])),
            int(cfg.get("signature_size", 24)),
        )
        alpha = int(255 * float(cfg.get("signature_opacity", 0.5)))
        ImageDraw.Draw(canvas).text(
            (width / 2, height - height * 0.055),
            signature, font=sig_font, anchor="mm",
            fill=_hex_to_rgb(cfg.get("signature_color", "#FFFFFF")) + (alpha,),
        )

    return canvas.convert("RGB")


def save(image: Image.Image, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "JPEG", quality=92, optimize=True, progressive=True)
    return path

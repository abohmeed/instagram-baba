"""Caption assembly from the profile's template."""
import random

from .arabic import to_arabic_digits

MAX_CAPTION = 2200  # Instagram's hard limit
MAX_HASHTAGS = 30


def reference_text(profile, item: dict) -> str:
    cfg = profile["caption"]
    fmt = cfg.get("reference_format", "{surah_name} {ayah_ref}")
    return fmt.format(**_fields(item, cfg.get("numerals", "latin")))


def _fields(item: dict, numerals: str = "latin") -> dict:
    start, end = item.get("ayah_start"), item.get("ayah_end")
    single = start == end
    digits = to_arabic_digits if numerals == "arabic" else str

    ayah_ref = digits(start) if single else f"{digits(start)}-{digits(end)}"
    fields = dict(item)
    fields.setdefault("surah_name", "")
    fields["ayah_ref"] = ayah_ref
    fields["ayah_label"] = (
        f"{'الآية' if single else 'الآيات'} {ayah_ref}" if numerals == "arabic"
        else f"{'v.' if single else 'vv.'} {ayah_ref}"
    )
    # These are supplied separately by build(); never let a pool record shadow them.
    fields.pop("reference", None)
    fields.pop("hashtags", None)
    return fields


def build(profile, item: dict, rng: random.Random | None = None) -> str:
    rng = rng or random.Random()
    cfg = profile["caption"]

    tags = list(cfg.get("hashtags") or [])
    limit = min(int(cfg.get("hashtag_count", len(tags)) or len(tags)), MAX_HASHTAGS)
    if len(tags) > limit:
        tags = rng.sample(tags, limit)
        rng.shuffle(tags)

    fields = _fields(item, cfg.get("numerals", "latin"))
    caption = cfg.get("template", "{text}\n\n{reference}\n\n{hashtags}").format(
        **fields,
        reference=reference_text(profile, item),
        hashtags=" ".join(tags),
    )

    if len(caption) > MAX_CAPTION:
        caption = caption[:MAX_CAPTION - 1].rstrip() + "…"
    return caption

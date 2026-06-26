"""Alt-text generation for images found in a document.

The Remediation Agent must produce *context-aware* alt text, not a generic
"image" placeholder. ClarityDesk supports pluggable providers:

* HeuristicProvider (default, offline, zero-egress): infers a description from
  the image's own pixels (orientation, palette, whether it looks like a chart,
  photo, logo or diagram) fused with the surrounding page caption/heading.
* VisionProvider (opt-in): sends the image to a vision LLM for a richer
  description. Network egress is explicit and must be allow-listed by the
  security guard, so confidential documents never leave silently.

Both implement `describe(ImageContext) -> str`.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from typing import Optional, Protocol

from PIL import Image


@dataclass
class ImageContext:
    """Everything we know about an image when writing its alt text."""
    image_bytes: bytes
    page: int
    xref: int
    caption: str = ""          # nearby "Figure N: ..." text
    heading: str = ""          # nearest preceding heading
    surrounding_text: str = ""  # body text near the image


class AltTextProvider(Protocol):
    name: str
    def describe(self, ctx: ImageContext) -> str: ...


# --------------------------------------------------------------------------- #
# Heuristic, fully-local provider
# --------------------------------------------------------------------------- #
@dataclass
class HeuristicProvider:
    name: str = "heuristic"
    max_len: int = 160

    def _analyze(self, data: bytes) -> dict:
        info: dict = {"kind": "image", "w": 0, "h": 0}
        try:
            img = Image.open(io.BytesIO(data))
            img.load()
        except Exception:
            return info
        info["w"], info["h"] = img.size
        rgb = img.convert("RGB")
        small = rgb.resize((48, 48))
        px = list(small.getdata())
        n = len(px)
        # unique-ish colours -> photos have many, charts/logos few
        uniq = len({(r // 16, g // 16, b // 16) for r, g, b in px})
        # saturation / brightness
        def sat(p):
            r, g, b = p
            mx, mn = max(p), min(p)
            return 0 if mx == 0 else (mx - mn) / mx
        avg_sat = sum(sat(p) for p in px) / n
        avg_bri = sum(sum(p) for p in px) / (n * 3) / 255.0
        w, h = info["w"], info["h"]
        aspect = (w / h) if h else 1.0

        if uniq <= 12 and avg_sat < 0.25:
            kind = "logo or icon"
        elif uniq <= 40 and avg_bri > 0.6:
            kind = "chart or diagram"
        elif avg_sat > 0.25 and uniq > 60:
            kind = "photograph"
        else:
            kind = "graphic"
        info.update(kind=kind, aspect=round(aspect, 2),
                    brightness=round(avg_bri, 2), saturation=round(avg_sat, 2),
                    palette=uniq)
        return info

    def describe(self, ctx: ImageContext) -> str:
        a = self._analyze(ctx.image_bytes)
        caption = _clean(ctx.caption)
        heading = _clean(ctx.heading)
        kind = a.get("kind", "image")

        if caption:
            # Caption is the strongest human-authored signal.
            base = caption
            if not _looks_complete(caption):
                base = f"{kind.capitalize()}: {caption}"
        elif heading:
            base = f"{kind.capitalize()} in section '{heading}'"
        else:
            base = kind.capitalize()
            if a.get("w"):
                base += f" ({a['w']}x{a['h']} px)"
        return _truncate(base, self.max_len)


# --------------------------------------------------------------------------- #
# Optional cloud vision provider (opt-in, audited egress)
# --------------------------------------------------------------------------- #
@dataclass
class VisionProvider:
    name: str = "vision"
    model: str = "gpt-4o-mini"
    api_key_env: str = "OPENAI_API_KEY"
    fallback: AltTextProvider = field(default_factory=HeuristicProvider)

    def describe(self, ctx: ImageContext) -> str:
        key = os.getenv(self.api_key_env)
        if not key:
            return self.fallback.describe(ctx)
        try:
            import base64
            from openai import OpenAI

            client = OpenAI(api_key=key)
            b64 = base64.b64encode(ctx.image_bytes).decode()
            hint = " ".join(x for x in (ctx.heading, ctx.caption) if x)
            prompt = (
                "Write a concise, factual alt text (max 160 chars) for this "
                "image in a business document. Do not start with 'image of'. "
                f"Document context: {hint or 'n/a'}."
            )
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                }],
                max_tokens=80,
            )
            text = (resp.choices[0].message.content or "").strip()
            return _truncate(text, 160) if text else self.fallback.describe(ctx)
        except Exception:
            return self.fallback.describe(ctx)


# --------------------------------------------------------------------------- #
def _clean(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _looks_complete(text: str) -> bool:
    return len(text.split()) >= 4


def _truncate(text: str, n: int) -> str:
    text = _clean(text)
    return text if len(text) <= n else text[: n - 1].rstrip() + "\u2026"


def default_provider() -> AltTextProvider:
    """Vision if a key is configured AND explicitly enabled, else heuristic."""
    if os.getenv("CLARITYDESK_VISION") == "1" and os.getenv("OPENAI_API_KEY"):
        return VisionProvider()
    return HeuristicProvider()

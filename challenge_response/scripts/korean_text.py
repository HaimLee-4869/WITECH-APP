"""OpenCV 화면에 한글을 그린다.

cv2.putText는 한글을 못 그려서 네모로 나온다. 사용자에게 보여줄 안내 문구는
PIL로 그려 프레임에 얹는다. 한글 글꼴이 없으면 호출자가 준 영문 대체 문구를 쓴다.
"""
from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np

_CANDIDATES = ("malgun.ttf", "NanumGothic.ttf", "AppleGothic.ttf", "gulim.ttc")
_cache: dict[int, object] = {}
_available: bool | None = None


def _font_path() -> Path | None:
    directories = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
                   Path("/usr/share/fonts"), Path("/Library/Fonts")]
    for directory in directories:
        for name in _CANDIDATES:
            candidate = directory / name
            if candidate.exists():
                return candidate
    return None


def available() -> bool:
    global _available
    if _available is None:
        try:
            import PIL  # noqa: F401
            _available = _font_path() is not None
        except ImportError:
            _available = False
    return _available


def _font(size: int):
    if size not in _cache:
        from PIL import ImageFont
        _cache[size] = ImageFont.truetype(str(_font_path()), size)
    return _cache[size]


def text_size(text: str, size: int) -> tuple[int, int]:
    if not available():
        return (0, 0)
    from PIL import ImageDraw, Image
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    box = draw.textbbox((0, 0), text, font=_font(size))
    return box[2] - box[0], box[3] - box[1]


def put_text(frame: np.ndarray, text: str, origin, size: int = 20,
             colour=(255, 255, 255), fallback: str | None = None) -> None:
    """frame에 한글 문구를 그린다. origin은 좌측 상단 (x, y).

    한글을 그릴 수 없는 환경이면 fallback(영문)을 cv2로 그린다.
    """
    if not available():
        if fallback:
            cv2.putText(frame, fallback, (origin[0], origin[1] + size),
                        cv2.FONT_HERSHEY_SIMPLEX, size / 32.0, colour, 1, cv2.LINE_AA)
        return

    from PIL import Image, ImageDraw
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image)
    draw.text(origin, text, font=_font(size), fill=(colour[2], colour[1], colour[0]))
    frame[:] = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def put_text_centred(frame: np.ndarray, text: str, centre_x: int, top: int,
                     size: int = 20, colour=(255, 255, 255),
                     fallback: str | None = None) -> None:
    width, _ = text_size(text, size)
    if width:
        put_text(frame, text, (centre_x - width // 2, top), size, colour, fallback)
    else:
        put_text(frame, text, (centre_x - 120, top), size, colour, fallback)

"""테스트용 앱 payload 생성기. 같은 seed → 같은 payload."""

from __future__ import annotations

import copy

import numpy as np


def make_frames(seed: int = 0, n: int = 40, span_ms: int = 2000) -> list[dict]:
    rng = np.random.default_rng(seed)
    base = rng.uniform(0.2, 0.8, size=(21, 3))
    frames = []
    for i in range(n):
        t = round(i * span_ms / max(n - 1, 1))
        lm = (base + rng.normal(0, 0.01, size=(21, 3))).round(5).tolist()
        frames.append({"tMs": t, "handedness": "Right", "score": 0.98, "lm": lm})
    return frames


def camera() -> dict:
    return {"width": 720, "height": 1280}


def verify_body(user_id: str = "kim", seed: int = 0, gesture_id: str | None = None, **kw) -> dict:
    body = {
        "userId": user_id,
        "capturedAt": "2026-09-16T10:39:01+09:00",
        "camera": camera(),
        "nominalFps": 30,
        "durationMs": 2000,
        "frames": make_frames(seed),
    }
    if gesture_id is not None:
        body["gestureId"] = gesture_id
    body.update(kw)
    return body


def enroll_body(user_id: str = "kim", gesture_id: str = "G1", seeds=(0, 1, 2)) -> dict:
    return {
        "userId": user_id,
        "gestureId": gesture_id,
        "camera": camera(),
        "takes": [
            {
                "takeNo": i + 1,
                "capturedAt": "2026-09-16T10:30:00+09:00",
                "nominalFps": 30,
                "durationMs": 2000,
                "frames": make_frames(seed),
            }
            for i, seed in enumerate(seeds)
        ],
    }


def ai_input(frames: list[dict], cam: dict | None = None) -> dict:
    """AI 모듈에 직접 넘길 형태 (단위 테스트용)."""
    return {"camera": copy.deepcopy(cam if cam is not None else camera()), "frames": copy.deepcopy(frames)}

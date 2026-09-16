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
    """AI 모듈에 직접 넘길 payload. 백엔드와 같은 변환 경로를 쓴다."""
    from app import schemas
    from app.services.ai_gateway import to_ai_input

    cam = camera() if cam is None else cam
    return to_ai_input(
        None if cam is None else schemas.Camera.model_validate(cam),
        [schemas.Frame.model_validate(f) for f in copy.deepcopy(frames)],
    )


def enroll_same_body(user_id: str = "kim", gesture_id: str = "G1", seed: int = 0) -> dict:
    """3회 모두 같은 프레임. 스텁에서는 centroid = 해당 입력의 임베딩 → 같은 입력 인증 시 유사도 1.0."""
    return enroll_body(user_id, gesture_id, seeds=(seed, seed, seed))


def predicted_gesture(seed: int = 0) -> str:
    """verify_body(seed=seed)에 대해 제스처 모델이 예측하는 제스처.

    USE_GESTURE_CLASSIFIER=true 모드 테스트에서만 필요하다.
    """
    from ai import encoder
    from app import schemas
    from app.services.ai_gateway import to_ai_input

    req = schemas.VerifyRequest.model_validate(verify_body(seed=seed))
    return encoder.classify_gesture(to_ai_input(req.camera, req.frames))[0]


def left_hand(frames: list[dict]) -> list[dict]:
    return [{**f, "handedness": "Left"} for f in frames]


def other_gesture(gesture_id: str) -> str:
    return "G2" if gesture_id == "G1" else "G1"

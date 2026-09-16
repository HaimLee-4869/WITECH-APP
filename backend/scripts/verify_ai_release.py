"""ai_release 교체 후 검증 (명세 14장 4번).

    cd backend
    python scripts/verify_ai_release.py

backend/ai/encoder.py가 명세 1장 계약과 맞는지 확인한다. 하나라도 FAIL이면 종료 코드 1.
MODEL_VERSION에 stub이 들어 있으면 아직 교체 전이라는 WARN이 뜬다.

입력은 백엔드가 실제로 넘기는 형태(app/services/ai_gateway.to_ai_input)로 만든다.
embed 단계부터 줄줄이 실패하면 **입력 형태 가정이 실제 모듈과 다른 것**이다.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import math
import sys
import traceback
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import numpy as np  # noqa: E402

from app.schemas import Camera, Frame  # noqa: E402
from app.services.ai_gateway import (  # noqa: E402
    REASON_MESSAGES,
    InvalidSequenceError,
    reason_of,
    to_ai_input,
)

EXPECTED_DIM = 128
GESTURES = {f"G{i}" for i in range(1, 6)}


def make_frames(seed: int, n: int = 40, span_ms: int = 2000) -> list[dict]:
    rng = np.random.default_rng(seed)
    base = rng.uniform(0.3, 0.7, size=(21, 3))
    base[:, 2] = rng.normal(0, 0.02, size=21)
    frames = []
    for i in range(n):
        drift = np.array([0.1 * math.sin(i / 6), 0.05 * math.cos(i / 5), 0.0])
        lm = (base + drift + rng.normal(0, 0.003, size=(21, 3))).tolist()
        frames.append({"tMs": round(i * span_ms / max(n - 1, 1)), "handedness": "Right", "score": 0.97, "lm": lm})
    return frames


def build(frames: list[dict], camera: dict | None = None) -> dict:
    cam = {"width": 720, "height": 1280} if camera is None else camera
    return to_ai_input(
        Camera.model_validate(cam) if cam else None,
        [Frame.model_validate(f) for f in frames],
    )


class Report:
    def __init__(self):
        self.rows: list[tuple[str, str, str]] = []

    def add(self, status: str, name: str, detail: str = "") -> None:
        self.rows.append((status, name, detail))
        print(f"[{status:4}] {name}" + (f" — {detail}" if detail else ""))

    def check(self, name: str, fn) -> object:
        try:
            result = fn()
        except AssertionError as exc:
            self.add("FAIL", name, str(exc))
            return None
        except Exception as exc:
            self.add("FAIL", name, f"{type(exc).__name__}: {exc}")
            traceback.print_exc(limit=2)
            return None
        self.add("PASS", name, result if isinstance(result, str) else "")
        return result

    @property
    def failed(self) -> int:
        return sum(1 for s, _, _ in self.rows if s == "FAIL")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ai_release 계약 검증")
    parser.add_argument("--encoder-module", default="ai.encoder")
    args = parser.parse_args(argv)

    r = Report()
    try:
        encoder = importlib.import_module(args.encoder_module)
    except Exception as exc:
        r.add("FAIL", f"import {args.encoder_module}", f"{type(exc).__name__}: {exc}")
        return 1

    # --- 1. 공개 API ---
    def api():
        for name in ("MODEL_VERSION", "GESTURE_MODEL_VERSION",
                     "load_model", "embed", "embed_batch", "classify_gesture"):
            assert hasattr(encoder, name), f"{name} 없음"
        assert isinstance(encoder.MODEL_VERSION, str) and encoder.MODEL_VERSION
        assert isinstance(encoder.GESTURE_MODEL_VERSION, str) and encoder.GESTURE_MODEL_VERSION
        # InvalidSequenceError는 encoder 또는 features 어디에 있어도 된다 (백엔드는 게이트웨이로 받는다)
        assert issubclass(InvalidSequenceError, ValueError), "InvalidSequenceError는 ValueError 하위여야 함"
        params = inspect.signature(encoder.load_model).parameters
        assert "device" in params, "load_model(device=...) 인자 없음"
        return f"MODEL_VERSION={encoder.MODEL_VERSION}, GESTURE_MODEL_VERSION={encoder.GESTURE_MODEL_VERSION}"

    r.check("공개 API와 버전 상수", api)
    if "stub" in str(getattr(encoder, "MODEL_VERSION", "")):
        r.add("WARN", "MODEL_VERSION", "아직 스텁이다")

    r.check("load_model(device='cpu')", lambda: encoder.load_model(device="cpu"))

    sample = build(make_frames(0))
    other = build(make_frames(1))

    # --- 2. 임베딩 ---
    def embed_contract():
        v = encoder.embed(sample)
        assert isinstance(v, np.ndarray), f"np.ndarray가 아님: {type(v)}  ← 입력 형태 가정(to_ai_input) 확인"
        assert v.shape == (EXPECTED_DIM,), f"shape {v.shape} != ({EXPECTED_DIM},)"
        assert v.dtype == np.float32, f"dtype {v.dtype} != float32"
        assert np.all(np.isfinite(v)), "NaN/Inf 포함"
        norm = float(np.linalg.norm(v))
        assert abs(norm - 1.0) < 1e-4, f"L2 norm {norm:.6f} != 1"
        return f"norm={norm:.6f}"

    r.check("embed: (128,) float32, L2 norm=1", embed_contract)

    def deterministic():
        a, b = encoder.embed(sample), encoder.embed(sample)
        assert np.allclose(a, b, atol=1e-6), "같은 입력에 다른 벡터 (eval 모드/dropout 확인)"
        cos = float(encoder.embed(sample) @ encoder.embed(other))
        return f"다른 입력과의 코사인={cos:.4f}"

    r.check("embed: 같은 입력 → 같은 벡터", deterministic)

    def batch():
        out = encoder.embed_batch([sample, other])
        assert out.shape == (2, EXPECTED_DIM), f"shape {out.shape}"
        assert out.dtype == np.float32, f"dtype {out.dtype}"
        assert np.allclose(out[0], encoder.embed(sample), atol=1e-5), "embed_batch[0] != embed"
        empty = encoder.embed_batch([])
        assert np.asarray(empty).shape[0] == 0, "빈 입력 처리"

    r.check("embed_batch: (N,128), embed와 일치", batch)

    def classify():
        label, conf = encoder.classify_gesture(sample)
        assert isinstance(label, str), f"label 타입 {type(label)}"
        assert label in GESTURES, f"label {label!r} 가 G1~G5가 아님 (gestures 테이블과 불일치)"
        assert isinstance(conf, float) and 0.0 <= conf <= 1.0, f"confidence {conf!r}"
        return f"{label}, {conf:.3f}"

    r.check("classify_gesture: (G1~G5, 0~1)", classify)

    def min_accepted():
        encoder.embed(build(make_frames(2, n=8, span_ms=760)))
        return "8프레임/760ms 허용 (보간은 AI 모듈 몫)"

    r.check("최소 조건 입력 허용", min_accepted)

    # --- 3. 거절 조건 6종 ---
    def no_hand(frames, k):
        for f in frames[:k]:
            f["lm"] = None
        return frames

    def dup_t(frames):
        frames[5]["tMs"] = frames[4]["tMs"]
        return frames

    def bad_shape(frames):
        frames[3]["lm"] = frames[3]["lm"][:20]
        return frames

    def nan(frames):
        frames[3]["lm"][0][0] = float("nan")
        return frames

    def left(frames):
        return [{**f, "handedness": "Left"} for f in frames]

    cases = [
        ("too_few_frames", lambda: build(make_frames(3, n=7))),
        ("insufficient_valid_frames", lambda: build(no_hand(make_frames(3, n=12), 5))),
        ("duration_too_short", lambda: build(make_frames(3, n=20, span_ms=700))),
        ("non_monotonic_timestamps", lambda: build(dup_t(make_frames(3)))),
        ("missing_camera_size", lambda: build(make_frames(3), camera={"width": 720})),
        ("malformed_landmarks", lambda: build(bad_shape(make_frames(3)))),
        ("malformed_landmarks", lambda: build(nan(make_frames(3)))),
        # 명세 1장에는 없지만 hand-only 모델이 거절한다. 앱 안내 문구가 갈린다.
        ("wrong_hand", lambda: build(left(make_frames(3)))),
    ]
    for expected, make in cases:
        def rejection(expected=expected, make=make):
            try:
                encoder.embed(make())
            except InvalidSequenceError as exc:
                got = reason_of(exc)
                if got != expected:
                    r.add("WARN", f"사유 코드 {expected}",
                          f"백엔드 추정={got}, 메시지={exc!s}  ← ai_gateway._REASON_PATTERNS 조정")
                return f"InvalidSequenceError: {exc}"
            raise AssertionError("InvalidSequenceError가 발생하지 않음")

        r.check(f"거절: {expected}", rejection)

    assert set(REASON_MESSAGES) >= {c[0] for c in cases}

    print()
    print(f"FAIL {r.failed}건 / 전체 {len(r.rows)}건")
    return 1 if r.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

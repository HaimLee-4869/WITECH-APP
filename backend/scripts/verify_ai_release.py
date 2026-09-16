"""ai_release 교체 후 검증 (명세 14장 4번, dual-head v1.1.x 계약).

    cd backend
    python scripts/verify_ai_release.py
    python scripts/verify_ai_release.py --encoder-module brokenai.encoder   # 다른 패키지 검사

backend/ai/가 백엔드가 기대하는 계약과 맞는지 확인한다. 하나라도 FAIL이면 종료 코드 1.

입력은 백엔드가 실제로 넘기는 형태(app/services/ai_gateway.to_ai_input)로 만든다.
embed 단계부터 줄줄이 실패하면 **입력 형태 가정이 실제 모듈과 다른 것**이다.

manifest.json이 있으면 파일 해시도 검증한다.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import inspect
import json
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
REQUIRED_API = (
    "MODEL_VERSION",
    "EMBEDDING_DIM",
    "load_model",
    "embed_user",
    "embed_gesture",
    "embed_user_batch",
    "embed_gesture_batch",
    "embed_both",
    "embed_both_batch",
    "get_thresholds",
)


def make_frames(seed: int, n: int = 40, span_ms: int = 4000) -> list[dict]:
    rng = np.random.default_rng(seed)
    base = rng.uniform(0.3, 0.7, size=(21, 3))
    base[:, 2] = rng.normal(0, 0.02, size=21)
    frames = []
    for i in range(n):
        drift = np.array([0.1 * math.sin(i / 6), 0.05 * math.cos(i / 5), 0.0])
        lm = (base + drift + rng.normal(0, 0.003, size=(21, 3))).tolist()
        frames.append(
            {
                "tMs": round(i * span_ms / max(n - 1, 1)),
                "handedness": "Right",
                "score": 0.97,
                "lm": lm,
            }
        )
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
    parser = argparse.ArgumentParser(description="ai_release 계약 검증 (dual-head)")
    parser.add_argument("--encoder-module", default="ai.encoder")
    args = parser.parse_args(argv)

    r = Report()
    try:
        encoder = importlib.import_module(args.encoder_module)
    except Exception as exc:
        r.add("FAIL", f"import {args.encoder_module}", f"{type(exc).__name__}: {exc}")
        return 1

    release_dir = Path(getattr(encoder, "__file__", str(BACKEND_DIR / "ai"))).resolve().parent

    # --- 0. manifest 무결성 ---
    manifest_path = release_dir / "manifest.json"
    if manifest_path.exists():

        def manifest_check():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            status = manifest.get("status")
            assert status in (None, "FINALIZED"), f"status={status} (빌드 전 템플릿이다)"
            files = manifest.get("files", [])
            assert files, "manifest에 파일 목록이 없다"
            bad = []
            for item in files:
                path = release_dir / item["path"]
                if not path.exists():
                    bad.append(f"{item['path']}: 없음")
                    continue
                if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                    bad.append(f"{item['path']}: 해시 불일치")
            assert not bad, "; ".join(bad)
            return f"{len(files)}개 파일 해시 일치 ({manifest.get('release')})"

        r.check("manifest 무결성", manifest_check)
    else:
        r.add("WARN", "manifest.json", "없음 — 파일 무결성을 확인할 수 없다")

    # --- 1. 공개 API ---
    def api():
        missing = [name for name in REQUIRED_API if not hasattr(encoder, name)]
        assert not missing, f"없는 항목: {missing}"
        assert isinstance(encoder.MODEL_VERSION, str) and encoder.MODEL_VERSION
        assert int(encoder.EMBEDDING_DIM) == EXPECTED_DIM
        # InvalidSequenceError는 encoder/features 어디에 있어도 된다 (게이트웨이가 흡수한다).
        assert issubclass(InvalidSequenceError, ValueError), "ValueError 하위여야 함"
        params = inspect.signature(encoder.load_model).parameters
        assert "device" in params, "load_model(device=...) 인자 없음"
        return f"MODEL_VERSION={encoder.MODEL_VERSION}"

    r.check("공개 API와 버전 상수", api)
    if "stub" in str(getattr(encoder, "MODEL_VERSION", "")):
        r.add("WARN", "MODEL_VERSION", "아직 스텁이다")

    r.check("load_model(device='cpu')", lambda: encoder.load_model(device="cpu"))

    def lock_check():
        source = (release_dir / "encoder.py").read_text(encoding="utf-8")
        assert "threading" in source, "encoder.py에 threading 락이 없다 (백엔드 락 필요)"
        return "threading.RLock 있음 — 백엔드는 락을 걸지 않는다"

    r.check("내부 스레드 락", lock_check)

    sample = build(make_frames(0))
    other = build(make_frames(1))

    # --- 2. 두 헤드 임베딩 ---
    def head(name: str, fn):
        def run():
            v = fn(sample)
            assert isinstance(v, np.ndarray), f"np.ndarray가 아님: {type(v)}  ← 입력 형태 확인"
            assert v.shape == (EXPECTED_DIM,), f"shape {v.shape}"
            assert v.dtype == np.float32, f"dtype {v.dtype}"
            assert np.all(np.isfinite(v)), "NaN/Inf 포함"
            norm = float(np.linalg.norm(v))
            assert abs(norm - 1.0) < 1e-4, f"L2 norm {norm:.6f} != 1"
            return f"norm={norm:.6f}"

        r.check(f"{name}: (128,) float32, L2 norm=1", run)

    head("embed_user", encoder.embed_user)
    head("embed_gesture", encoder.embed_gesture)

    def both():
        result = encoder.embed_both(sample)
        assert set(result) >= {"user_embedding", "gesture_embedding"}, f"키: {list(result)}"
        user = result["user_embedding"]
        gesture = result["gesture_embedding"]
        assert np.allclose(user, encoder.embed_user(sample), atol=1e-5)
        assert np.allclose(gesture, encoder.embed_gesture(sample), atol=1e-5)
        assert not np.allclose(user, gesture), "두 헤드가 같은 벡터다. 관문 하나가 무의미해진다"
        return f"두 헤드 상호 코사인={float(user @ gesture):+.4f}"

    r.check("embed_both: 두 헤드가 단건 호출과 일치", both)

    def deterministic():
        a = encoder.embed_user(sample)
        b = encoder.embed_user(sample)
        assert np.allclose(a, b, atol=1e-6), "같은 입력에 다른 벡터 (eval 모드/dropout 확인)"
        return f"다른 입력과의 user 코사인={float(a @ encoder.embed_user(other)):.4f}"

    r.check("같은 입력 → 같은 벡터", deterministic)

    def batch():
        result = encoder.embed_both_batch([sample, other])
        users = result["user_embeddings"]
        gestures = result["gesture_embeddings"]
        assert users.shape == gestures.shape == (2, EXPECTED_DIM), f"{users.shape}/{gestures.shape}"
        assert users.dtype == np.float32
        assert np.allclose(users[0], encoder.embed_user(sample), atol=1e-5)
        assert np.allclose(gestures[0], encoder.embed_gesture(sample), atol=1e-5)

    r.check("embed_both_batch: (N,128) 두 벌, 단건과 일치", batch)

    def thresholds():
        data = encoder.get_thresholds()
        points = data.get("operating_points", {})
        assert points, "operating_points가 없다"
        selected = data.get("selected_operating_point")
        assert selected in points, f"선택 운영점 {selected!r}이 목록에 없다"
        for name, point in points.items():
            assert "user_threshold" in point and "gesture_threshold" in point, (
                f"운영점 {name}에 두 관문 임계값이 모두 있어야 한다"
            )
        chosen = points[selected]
        return (
            f"{len(points)}개 운영점, 기본={selected} "
            f"Tu={chosen['user_threshold']:.6f} Tg={chosen['gesture_threshold']:.6f}"
        )

    r.check("thresholds: 운영점마다 Tu/Tg", thresholds)

    r.check(
        "최소 조건 입력 허용",
        lambda: (
            encoder.embed_both(build(make_frames(2, n=8, span_ms=760))),
            "8프레임/760ms 허용 (보간은 AI 모듈 몫)",
        )[1],
    )
    r.check(
        "긴 캡처 허용",
        lambda: (
            encoder.embed_both(build(make_frames(2, n=80, span_ms=4000))),
            "4초/80프레임 허용 (현재 앱 촬영 길이)",
        )[1],
    )

    # --- 3. 거절 조건 ---
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
                encoder.embed_both(make())
            except InvalidSequenceError as exc:
                got = reason_of(exc)
                if got != expected:
                    r.add(
                        "WARN",
                        f"사유 코드 {expected}",
                        f"백엔드 추정={got}, 메시지={exc!s}  ← ai_gateway._REASON_PATTERNS 조정",
                    )
                return f"InvalidSequenceError: {exc}"
            raise AssertionError("InvalidSequenceError가 발생하지 않음")

        r.check(f"거절: {expected}", rejection)

    assert set(REASON_MESSAGES) >= {c[0] for c in cases}

    print()
    print(f"FAIL {r.failed}건 / 전체 {len(r.rows)}건")
    return 1 if r.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

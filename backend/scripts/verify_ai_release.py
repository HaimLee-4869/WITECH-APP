"""ai_release 교체 후 검증 (명세 14장 4번, v1.0.0 mobile dual-head 계약).

    cd backend
    python scripts/verify_ai_release.py
    python scripts/verify_ai_release.py --encoder-module brokenai.encoder   # 다른 패키지 검사

backend/ai/가 백엔드가 기대하는 계약과 맞는지 확인한다. 하나라도 FAIL이면 종료 코드 1.

입력은 백엔드가 실제로 넘기는 형태(app/services/ai_gateway.to_ai_input)로 만든다.
embed 단계부터 줄줄이 실패하면 **입력 형태 가정이 실제 모듈과 다른 것**이다.

공개 API: `embed(payload) -> (gesture, user)`, `embed_batch(list) -> (gesture[N], user[N])`.
**순서가 gesture 먼저다.** 백엔드는 ai_gateway에서 (user, gesture)로 뒤집어 쓴다.

manifest.json에 파일별 sha256이 있으면 해시도 검증한다. 없으면 WARN
(v1.0.0 mobile 릴리스는 파일 목록이 없다. 릴리스 ZIP 해시로 따로 확인할 것).
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
    check_sequence,
    reason_of,
    to_ai_input,
)

EXPECTED_DIM = 128
REQUIRED_API = (
    "MODEL_VERSION",
    "EMBEDDING_DIM",
    "load_model",
    "embed",
    "embed_batch",
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


def build(frames: list[dict], camera: dict | None = None, duration_ms: int | None = 4000) -> dict:
    """앱과 같은 조건: nominalFps=30, durationMs=촬영 길이."""
    cam = {"width": 720, "height": 1280} if camera is None else camera
    return to_ai_input(
        Camera.model_validate(cam) if cam else None,
        [Frame.model_validate(f) for f in frames],
        nominal_fps=30.0,
        duration_ms=duration_ms,
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
    features = importlib.import_module(args.encoder_module.rsplit(".", 1)[0] + ".features") \
        if (release_dir / "features.py").exists() else importlib.import_module("ai.features")

    # --- 0. manifest 무결성 ---
    manifest_path = release_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    if manifest is None:
        r.add("WARN", "manifest 무결성", "manifest.json 없음 — 파일 무결성을 확인할 수 없다")
    elif not manifest.get("files"):
        r.add("WARN", "manifest 무결성", "파일별 sha256이 없다 — 릴리스 ZIP 해시로 확인할 것")
    else:

        def manifest_check():
            status = manifest.get("status")
            assert status in (None, "FINALIZED"), f"status={status} (빌드 전 템플릿이다)"
            bad = []
            for item in manifest["files"]:
                path = release_dir / item["path"]
                if not path.exists():
                    bad.append(f"{item['path']}: 없음")
                    continue
                if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                    bad.append(f"{item['path']}: 해시 불일치")
            assert not bad, "; ".join(bad)
            version = manifest.get("release") or manifest.get("model_version")
            return f"{len(manifest['files'])}개 파일 해시 일치 ({version})"

        r.check("manifest 무결성", manifest_check)

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

    def pair(payload):
        """백엔드와 같은 경로: 앞단 거절 → 모듈. (user, gesture)로 돌려준다."""
        check_sequence(payload)
        gesture, user = encoder.embed(payload)
        return user, gesture

    # --- 2. 두 헤드 임베딩 ---
    def head(name: str, index: int):
        def run():
            result = encoder.embed(sample)
            assert isinstance(result, tuple) and len(result) == 2, (
                f"embed()가 (gesture, user) 튜플이 아님: {type(result)}"
            )
            v = result[index]
            assert isinstance(v, np.ndarray), f"np.ndarray가 아님: {type(v)}  ← 입력 형태 확인"
            assert v.shape == (EXPECTED_DIM,), f"shape {v.shape}"
            assert v.dtype == np.float32, f"dtype {v.dtype}"
            assert np.all(np.isfinite(v)), "NaN/Inf 포함"
            norm = float(np.linalg.norm(v))
            assert abs(norm - 1.0) < 1e-4, f"L2 norm {norm:.6f} != 1"
            return f"norm={norm:.6f}"

        r.check(f"{name}: (128,) float32, L2 norm=1", run)

    head("gesture head embed()[0]", 0)
    head("user head embed()[1]", 1)

    def heads_differ():
        user, gesture = pair(sample)
        assert not np.allclose(user, gesture), "두 헤드가 같은 벡터다. 관문 하나가 무의미해진다"
        return f"두 헤드 상호 코사인={float(user @ gesture):+.4f}"

    r.check("두 헤드가 서로 다른 벡터", heads_differ)

    def deterministic():
        a = encoder.embed(sample)[1]
        b = encoder.embed(sample)[1]
        assert np.allclose(a, b, atol=1e-6), "같은 입력에 다른 벡터 (eval 모드/dropout 확인)"
        return f"다른 입력과의 user 코사인={float(a @ encoder.embed(other)[1]):.4f}"

    r.check("같은 입력 → 같은 벡터", deterministic)

    def batch():
        gestures, users = encoder.embed_batch([sample, other])
        assert users.shape == gestures.shape == (2, EXPECTED_DIM), f"{users.shape}/{gestures.shape}"
        assert users.dtype == np.float32
        gesture, user = encoder.embed(sample)
        assert np.allclose(gestures[0], gesture, atol=1e-5), "batch[0]이 단건 gesture와 다르다 (순서 확인)"
        assert np.allclose(users[0], user, atol=1e-5), "batch[1]이 단건 user와 다르다 (순서 확인)"

    r.check("embed_batch: (gesture, user) 두 벌, 단건과 일치", batch)

    def thresholds():
        data = json.loads((release_dir / "thresholds.json").read_text(encoding="utf-8"))
        if "operating_points" in data:
            chosen = data["operating_points"][data.get("selected_operating_point", "default")]
        else:
            chosen = data
        tu, tg = float(chosen["user_threshold"]), float(chosen["gesture_threshold"])
        seed = json.loads((BACKEND_DIR / "app" / "default_thresholds.json").read_text(encoding="utf-8"))
        default = next(p for p in seed["operatingPoints"] if p["basis"] == seed["defaultBasis"])
        assert (default["userThreshold"], default["gestureThreshold"]) == (tu, tg), (
            "app/default_thresholds.json이 릴리스와 다르다 — scripts/import_thresholds.py 실행"
        )
        assert seed.get("modelVersion") == encoder.MODEL_VERSION, (
            f"default_thresholds.json modelVersion={seed.get('modelVersion')}"
        )
        return f"Tu={tu} Tg={tg} (app/default_thresholds.json과 일치)"

    r.check("thresholds: 릴리스 = 백엔드 시드", thresholds)

    def duration():
        slow = make_frames(4, n=56, span_ms=3930)  # 4초 동안 14fps
        _, got = features.build_hand_features(build(slow))
        assert abs(got - 4.0) < 1e-6, (
            f"duration {got:.3f}s != 4.0s ← to_ai_input의 fps/totalFrames 확인"
        )
        return "14fps 4초 캡처 → 4.00s (totalFrames / fps)"

    r.check("duration = 촬영 길이", duration)

    r.check(
        "최소 조건 입력 허용",
        lambda: (
            pair(build(make_frames(2, n=8, span_ms=760), duration_ms=760)),
            "8프레임/760ms 허용 (보간은 AI 모듈 몫)",
        )[1],
    )
    r.check(
        "긴 캡처 허용",
        lambda: (
            pair(build(make_frames(2, n=80, span_ms=4000))),
            "4초/80프레임 허용 (현재 앱 촬영 길이)",
        )[1],
    )

    # --- 3. 거절 조건 (앞단 check_sequence + 모듈) ---
    def no_hand(frames, k):
        for f in frames[:k]:
            f["lm"] = None
        return frames

    def dup_t(frames):
        frames[5]["tMs"] = frames[4]["tMs"]
        return frames

    def swap_t(frames):
        frames[5], frames[6] = frames[6], frames[5]
        return frames

    def bad_shape(frames):
        frames[3]["lm"] = frames[3]["lm"][:20]
        return frames

    def nan(frames):
        frames[3]["lm"][0][0] = float("nan")
        return frames

    cases = [
        ("too_few_frames", lambda: build(make_frames(3, n=7))),
        ("insufficient_valid_frames", lambda: build(no_hand(make_frames(3, n=12), 5))),
        ("duration_too_short", lambda: build(make_frames(3, n=20, span_ms=700))),
        ("non_monotonic_timestamps", lambda: build(dup_t(make_frames(3)))),
        ("non_monotonic_timestamps", lambda: build(swap_t(make_frames(3)))),
        ("missing_camera_size", lambda: build(make_frames(3), camera={"width": 720})),
        ("malformed_landmarks", lambda: build(bad_shape(make_frames(3)))),
        ("malformed_landmarks", lambda: build(nan(make_frames(3)))),
    ]
    for expected, make in cases:

        def rejection(expected=expected, make=make):
            try:
                pair(make())
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

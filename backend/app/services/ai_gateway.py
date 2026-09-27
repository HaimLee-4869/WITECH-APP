"""백엔드 ↔ AI 모듈 경계.

ai_release의 입력 형태·예외 형태가 바뀌면 **이 파일만** 고친다.
여기서 전처리(정규화·리샘플링·feature)는 하지 않는다. 형태 변환과 입력 거절만 한다.

입력 형태는 ai/README.md "입력 payload 필수 항목" 기준 (2026-09-27 실측 확인):

    {
      "width": 720, "height": 1280,
      "fps": 30.0, "totalFrames": 120,
      "frames": [{"frameIndex": 0, "tMs": 0.0, "landmarks": [[x, y, z], ...21개],
                  "handedness": "Right", "valid": true}, ...]
    }

- 카메라 크기는 **최상위** width/height (`camera` 중첩이 아니다)
- 프레임 좌표 키는 **`landmarks`** (`lm`이 아니다). [x,y,z] 배열과 {"x","y","z"} 둘 다 허용
- `valid`: 손 좌표가 없는 프레임은 false. 모듈이 건너뛴다
- **`fps`·`totalFrames`**: 모듈은 `duration_sec = totalFrames / fps`를 모델 입력으로 쓴다.
  둘 다 없으면 조용히 fps=30, totalFrames=검출 프레임 수로 채워서, 실기기 13~16fps에서는
  4초 촬영이 2초로 들어가고 본인 user 점수가 0.73까지 떨어진다(Tu 0.824 아래).
  앱이 보내는 `nominalFps`·`durationMs`로 채운다.
- `frameIndex`: 모듈이 valid mask를 전체 타임라인에 복원할 때만 쓴다. 이 체크포인트는
  valid mask 열을 입력으로 쓰지 않으므로(임베딩 영향 0) tMs에서 환산해 채운다.

반환 순서 주의: `encoder.embed()`는 **(gesture, user)** 다. 이 파일의 `embed_both*`는
예전과 같이 **(user, gesture)** 를 돌려준다. 순서를 뒤집는 곳은 여기 한 곳뿐이다.
"""

from __future__ import annotations

import logging
import math
import re
import numpy as np

from ai import encoder
from app.errors import ApiError
from app.schemas import Camera, Frame

try:  # ai_release는 features.py에만 정의한다. 다른 구성도 견디게 둘 다 본다.
    from ai.encoder import InvalidSequenceError
except ImportError:  # pragma: no cover - 릴리스 구성에 따라 갈린다
    from ai.features import InvalidSequenceError

log = logging.getLogger(__name__)

__all__ = [
    "InvalidSequenceError",
    "REASON_MESSAGES",
    "to_ai_input",
    "check_sequence",
    "reason_of",
    "invalid_sequence_error",
    "embed_both",
    "embed_both_batch",
]

# 명세 1장 거절 조건 중 v1.0.0 mobile 모듈이 검사하지 않는 것. 백엔드가 직접 막는다.
MIN_INPUT_FRAMES = 8
MIN_DURATION_MS = 750.0
# nominalFps가 없거나 이상할 때. 모듈의 기본값과 같다.
DEFAULT_FPS = 30.0

# 거절 사유 코드 → 앱이 그대로 보여줄 안내 문구
REASON_MESSAGES: dict[str, str] = {
    "too_few_frames": "촬영된 프레임이 너무 적습니다. 다시 시도해주세요.",
    "insufficient_valid_frames": "손이 충분히 인식되지 않았습니다. 다시 시도해주세요.",
    "duration_too_short": "동작이 너무 짧습니다. 조금 더 천천히 해주세요.",
    "non_monotonic_timestamps": "촬영 시간 정보가 올바르지 않습니다. 다시 시도해주세요.",
    "missing_camera_size": "카메라 해상도 정보가 없습니다. 앱을 최신 버전으로 업데이트해주세요.",
    "malformed_landmarks": "손 좌표 형식이 올바르지 않습니다. 다시 시도해주세요.",
    "invalid_sequence": "입력을 처리할 수 없습니다. 다시 시도해주세요.",
}

# InvalidSequenceError에 사유 코드 속성이 없으면 메시지로 추정한다. 위에서부터 먼저 맞는 것.
# 실제 ai_release 메시지로 검증했다 (tests/test_ai_contract.py).
_REASON_PATTERNS: list[tuple[str, str]] = [
    (r"camera|width|height", "missing_camera_size"),
    # "tMs must be finite and strictly increasing"와 겹치므로 finite 단독은 쓰지 않는다
    (r"\b(nan|inf|infinity)\b|21|landmark|shape", "malformed_landmarks"),
    (r"valid|hand", "insufficient_valid_frames"),
    (r"\btms\b|timestamp|increas|monoton", "non_monotonic_timestamps"),
    (r"750|duration|span|short", "duration_too_short"),
    (r"frame", "too_few_frames"),
]


class _RejectedSequence(InvalidSequenceError):
    """백엔드가 직접 거절한 입력. 사유 코드를 속성으로 들고 있어 메시지 추정이 필요 없다."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def _fps(nominal_fps: float | None) -> float:
    if nominal_fps is None or not math.isfinite(nominal_fps) or nominal_fps <= 0:
        return DEFAULT_FPS
    return float(nominal_fps)


def to_ai_input(
    camera: Camera | None,
    frames: list[Frame],
    *,
    nominal_fps: float | None = None,
    duration_ms: float | None = None,
) -> dict:
    """스키마 객체 → AI 모듈 입력 payload.

    등록·인증·재색인이 모두 이 함수를 거친다. 같은 원본이면 항상 같은 payload가 나와야
    같은 임베딩이 나온다.

    `duration_ms`는 앱의 촬영 길이(`durationMs`)다. 모듈은 `totalFrames / fps`를 촬영 길이로
    보므로 `totalFrames = round(durationMs × fps / 1000)`으로 맞춘다. 없으면 첫~끝 tMs
    간격에 한 칸을 더한 값으로 대신한다 (검출 프레임 수를 쓰는 모듈 기본값보다 정확하다).
    """
    fps = _fps(nominal_fps)
    payload: dict = {"fps": fps, "frames": []}
    if camera is not None:
        # 누락은 AI 모듈이 missing_camera_size로 거절한다. 여기서 막지 않는다.
        if camera.width is not None:
            payload["width"] = camera.width
        if camera.height is not None:
            payload["height"] = camera.height

    finite = [f.t_ms for f in frames if math.isfinite(f.t_ms)]
    t0 = finite[0] if finite else 0.0
    max_index = -1
    for f in frames:
        has_hand = bool(f.lm)
        # tMs가 깨진 입력은 check_sequence가 거절한다. 여기서는 형태만 만든다.
        index = max(0, round((f.t_ms - t0) * fps / 1000.0)) if math.isfinite(f.t_ms) else 0
        max_index = max(max_index, index)
        frame: dict = {"frameIndex": index, "tMs": f.t_ms, "landmarks": f.lm, "valid": has_hand}
        if f.handedness is not None:
            frame["handedness"] = f.handedness  # 왼손이면 AI 모듈이 오른손으로 미러링한다
        if f.score is not None:
            frame["score"] = f.score
        payload["frames"].append(frame)

    if duration_ms is not None and math.isfinite(duration_ms) and duration_ms > 0:
        total = round(duration_ms * fps / 1000.0)
    else:
        total = max_index + 1  # tMs 간격 + 한 칸
    # 선언한 촬영 길이보다 프레임이 넓게 퍼져 있으면 프레임 쪽을 믿는다
    payload["totalFrames"] = max(total, max_index + 1, 1)
    return payload


def check_sequence(payload: dict) -> None:
    """명세 1장 거절 조건 중 AI 모듈이 하지 않는 것: 프레임 수, tMs 단조 증가, 750ms.

    v1.0.0 mobile 모듈은 tMs를 **정렬한 뒤** 중복만 거절하고, 길이 하한이 없다(8프레임
    0.27초도 받는다). 그대로 두면 뒤섞인 시간이나 너무 짧은 캡처가 조용히 임베딩된다.
    """
    frames = payload.get("frames") or []
    if len(frames) < MIN_INPUT_FRAMES:
        raise _RejectedSequence(
            "too_few_frames",
            f"at least {MIN_INPUT_FRAMES} captured frames are required; got {len(frames)}",
        )
    times = np.asarray([f.get("tMs", math.nan) for f in frames], dtype=np.float64)
    if not np.all(np.isfinite(times)) or np.any(np.diff(times) <= 0):
        raise _RejectedSequence(
            "non_monotonic_timestamps", "tMs must be finite and strictly increasing"
        )
    span = float(times[-1] - times[0])
    if span < MIN_DURATION_MS:
        raise _RejectedSequence(
            "duration_too_short",
            f"capture duration must be at least {MIN_DURATION_MS:.0f} ms; got {span:.1f} ms",
        )


def embed_both(payload: dict) -> tuple[np.ndarray, np.ndarray]:
    """(user, gesture) 임베딩. 한 번의 forward로 둘 다 계산한다."""
    check_sequence(payload)
    gesture, user = encoder.embed(payload)  # ⚠️ 모듈은 (gesture, user) 순서
    return user, gesture


def embed_both_batch(payloads: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """(user[N,128], gesture[N,128]). 등록·재색인에서 쓴다."""
    for payload in payloads:
        check_sequence(payload)
    gestures, users = encoder.embed_batch(payloads)  # ⚠️ 모듈은 (gesture, user) 순서
    return users, gestures


def reason_of(exc: Exception) -> str:
    reason = getattr(exc, "reason", None) or getattr(exc, "code", None)
    if isinstance(reason, str) and reason in REASON_MESSAGES:
        return reason
    text = str(exc).lower()
    for pattern, code in _REASON_PATTERNS:
        if re.search(pattern, text):
            return code
    return "invalid_sequence"


def invalid_sequence_error(exc: Exception, take_no: int | None = None) -> ApiError:
    reason = reason_of(exc)
    log.info("invalid sequence: reason=%s take=%s detail=%s", reason, take_no, exc)
    return ApiError(422, "invalid_sequence", reason, REASON_MESSAGES[reason], take_no=take_no)

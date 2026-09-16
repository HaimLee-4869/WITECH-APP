"""백엔드 ↔ AI 모듈 경계.

ai_release의 입력 형태·예외 형태가 바뀌면 **이 파일만** 고친다.
여기서 전처리(정규화·리샘플링·feature)는 하지 않는다. 형태 변환만 한다.

입력 형태는 ai/AI_RELEASE_README.md "Input contract" 기준 (2026-09-16 실측 확인):

    {
      "width": 720, "height": 1280,
      "frames": [{"tMs": 0.0, "landmarks": [[x, y, z], ...21개],
                  "handedness": "Right", "valid": true}, ...]
    }

- 카메라 크기는 **최상위** width/height (`camera` 중첩이 아니다)
- 프레임 좌표 키는 **`landmarks`** (`lm`이 아니다). [x,y,z] 배열과 {"x","y","z"} 둘 다 허용
- `valid`: 손 좌표가 있는 프레임에 true를 명시한다. 이걸 붙여야 21×3 위반·NaN을
  조용히 무시하지 않고 InvalidSequenceError로 거절한다 (명세 1장 거절 조건에 맞추기 위함)
"""

from __future__ import annotations

import logging
import re

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
    "reason_of",
    "invalid_sequence_error",
]

# 거절 사유 코드 → 앱이 그대로 보여줄 안내 문구
REASON_MESSAGES: dict[str, str] = {
    "too_few_frames": "촬영된 프레임이 너무 적습니다. 다시 시도해주세요.",
    "insufficient_valid_frames": "손이 충분히 인식되지 않았습니다. 다시 시도해주세요.",
    "duration_too_short": "동작이 너무 짧습니다. 조금 더 천천히 해주세요.",
    "non_monotonic_timestamps": "촬영 시간 정보가 올바르지 않습니다. 다시 시도해주세요.",
    "missing_camera_size": "카메라 해상도 정보가 없습니다. 앱을 최신 버전으로 업데이트해주세요.",
    "malformed_landmarks": "손 좌표 형식이 올바르지 않습니다. 다시 시도해주세요.",
    # 명세 1장 거절 조건에는 없지만 실제 모듈이 거절한다 (오른손 전용 모델)
    "wrong_hand": "오른손을 사용해주세요. 이 모델은 오른손 동작만 인식합니다.",
    "invalid_sequence": "입력을 처리할 수 없습니다. 다시 시도해주세요.",
}

# InvalidSequenceError에 사유 코드 속성이 없으면 메시지로 추정한다. 위에서부터 먼저 맞는 것.
# 실제 ai_release 메시지로 검증했다 (tests/test_invalid_input.py).
_REASON_PATTERNS: list[tuple[str, str]] = [
    # "right-hand captures only"가 아래 valid|hand 패턴에 걸리지 않도록 먼저 본다
    (r"right[- ]hand|left[- ]hand|handedness", "wrong_hand"),
    (r"camera|width|height", "missing_camera_size"),
    # "tMs must be finite and strictly increasing"와 겹치므로 finite 단독은 쓰지 않는다
    (r"\b(nan|inf|infinity)\b|21|landmark|shape", "malformed_landmarks"),
    (r"valid|hand", "insufficient_valid_frames"),
    (r"\btms\b|timestamp|increas|monoton", "non_monotonic_timestamps"),
    (r"750|duration|span|short", "duration_too_short"),
    (r"frame", "too_few_frames"),
]


def to_ai_input(camera: Camera | None, frames: list[Frame]) -> dict:
    """스키마 객체 → AI 모듈 입력 payload.

    등록·인증·재색인이 모두 이 함수를 거친다. 같은 원본이면 항상 같은 payload가 나와야
    같은 임베딩이 나온다.
    """
    payload: dict = {"frames": []}
    if camera is not None:
        # 누락은 AI 모듈이 missing_camera_size로 거절한다. 여기서 막지 않는다.
        if camera.width is not None:
            payload["width"] = camera.width
        if camera.height is not None:
            payload["height"] = camera.height

    for f in frames:
        has_hand = bool(f.lm)
        frame: dict = {"tMs": f.t_ms, "landmarks": f.lm, "valid": has_hand}
        if f.handedness is not None:
            frame["handedness"] = f.handedness  # 왼손이면 AI 모듈이 거절한다
        if f.score is not None:
            frame["score"] = f.score
        payload["frames"].append(frame)
    return payload


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

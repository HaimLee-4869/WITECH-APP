"""백엔드 ↔ AI 모듈 경계.

ai_release로 교체할 때 입력 형태나 예외 형태가 스텁 가정과 다르면 **이 파일만** 고친다.
여기서 전처리(정규화·리샘플링·feature)는 하지 않는다. 형태 변환만 한다.
"""

from __future__ import annotations

import logging
import re

from ai import encoder
from app.errors import ApiError
from app.schemas import Camera, Frame

log = logging.getLogger(__name__)

# 명세 1장 거절 조건 → 앱이 재촬영 안내를 고를 수 있는 사유 코드
REASON_MESSAGES: dict[str, str] = {
    "too_few_frames": "촬영된 프레임이 너무 적습니다. 다시 시도해주세요.",
    "insufficient_valid_frames": "손이 충분히 인식되지 않았습니다. 다시 시도해주세요.",
    "duration_too_short": "동작이 너무 짧습니다. 조금 더 천천히 해주세요.",
    "non_monotonic_timestamps": "촬영 시간 정보가 올바르지 않습니다. 다시 시도해주세요.",
    "missing_camera_size": "카메라 해상도 정보가 없습니다. 앱을 최신 버전으로 업데이트해주세요.",
    "malformed_landmarks": "손 좌표 형식이 올바르지 않습니다. 다시 시도해주세요.",
    "invalid_sequence": "입력을 처리할 수 없습니다. 다시 시도해주세요.",
}

# 실제 모듈의 예외에 reason 속성이 없을 때 메시지로 추정한다. 위에서부터 먼저 맞는 것.
_REASON_PATTERNS: list[tuple[str, str]] = [
    (r"camera|width|height", "missing_camera_size"),
    (r"\b(nan|inf|infinity)\b|21|landmark|shape", "malformed_landmarks"),
    (r"valid|hand", "insufficient_valid_frames"),
    (r"\btms\b|timestamp|increas|monoton", "non_monotonic_timestamps"),
    (r"750|duration|span|short", "duration_too_short"),
    (r"frame", "too_few_frames"),
]


def to_ai_input(camera: Camera | None, frames: list[Frame]) -> dict:
    """스키마 객체 → AI 모듈 입력 dict.

    등록·인증·재색인이 모두 이 함수를 거친다. 같은 원본이면 항상 같은 dict가 나와야
    같은 임베딩이 나온다 (스텁은 repr 해시를 쓴다).
    """
    return {
        "camera": None if camera is None else {"width": camera.width, "height": camera.height},
        "frames": [
            {"tMs": f.t_ms, "lm": f.lm, "handedness": f.handedness, "score": f.score}
            for f in frames
        ],
    }


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

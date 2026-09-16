"""인증 로직 (명세 7장 POST /verify).

1. 입력 검증 → 실패 시 422 (로그에 invalid_input)
2. classify_gesture(frames) → 제스처 판정
3. 템플릿 조회에 쓸 제스처 결정 (USE_GESTURE_CLASSIFIER)
     true  : 예측 제스처. gestureId가 왔는데 예측과 다르면 gesture_mismatch로 거부
     false : 앱이 보낸 gestureId. 예측은 기록만 하고 판정에 쓰지 않는다
4. embed(frames) → query 임베딩
5. (user, 제스처, 활성 model_version) 템플릿 조회 → 없으면 no_template
6. 코사인 유사도 = query @ template
7. 활성 threshold와 비교
8. auth_logs 기록 (성공·실패 모두, 랜드마크 원본 포함)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ai import encoder
from app.config import Settings
from app.errors import ApiError, invalid_request, not_found
from app.models import AuthLog, User
from app.schemas import VerifyRequest, VerifyResponse
from app.services import app_config_service as cfg
from app.services import template_service, threshold_service
from app.services.ai_gateway import (
    InvalidSequenceError,
    invalid_sequence_error,
    to_ai_input,
)

log = logging.getLogger(__name__)

BELOW_THRESHOLD = "below_threshold"
NO_TEMPLATE = "no_template"
INVALID_INPUT = "invalid_input"
GESTURE_MISMATCH = "gesture_mismatch"
MODEL_VERSION_MISMATCH = "model_version_mismatch"


@dataclass
class _Attempt:
    """한 번의 인증 시도에서 로그와 응답에 들어갈 값."""

    user_id: str
    claimed: str | None
    raw_body: str
    started: float = field(default_factory=time.perf_counter)
    predicted: str | None = None
    confidence: float | None = None
    lookup_gesture: str | None = None
    score: float | None = None
    threshold: float | None = None
    passed: bool = False
    fail_reason: str | None = None

    def latency_ms(self) -> int:
        return int(round((time.perf_counter() - self.started) * 1000))


def _write_log(session: Session, a: _Attempt, model_version: str | None, latency_ms: int) -> None:
    session.add(
        AuthLog(
            user_id=a.user_id,
            claimed_gesture_id=a.claimed,
            predicted_gesture_id=a.predicted,
            gesture_confidence=a.confidence,
            score=a.score,
            threshold=a.threshold,
            passed=a.passed,
            fail_reason=a.fail_reason,
            auth_model_version=model_version,
            gesture_model_version=encoder.GESTURE_MODEL_VERSION,
            landmarks_json=a.raw_body,
            latency_ms=latency_ms,
        )
    )
    session.commit()


def verify(session: Session, settings: Settings, req: VerifyRequest, raw_body: str) -> VerifyResponse:
    a = _Attempt(user_id=req.user_id, claimed=req.gesture_id, raw_body=raw_body)

    if session.get(User, req.user_id) is None:
        raise not_found("user_not_found", "등록되지 않은 사용자입니다.")
    if not settings.use_gesture_classifier and not req.gesture_id:
        raise invalid_request(
            "gesture_id_required", "gestureId가 필요합니다. (USE_GESTURE_CLASSIFIER=false)"
        )

    active_version = cfg.get_active_model_version(session)
    active_threshold = threshold_service.get_active(session, active_version) if active_version else None
    a.threshold = active_threshold.value if active_threshold else None

    def fail(reason: str) -> None:
        a.passed = False
        a.fail_reason = reason

    def finish() -> VerifyResponse:
        latency = a.latency_ms()
        _write_log(session, a, active_version, latency)
        return VerifyResponse(
            score=a.score,
            threshold=a.threshold,
            passed=a.passed,
            reason=a.fail_reason,
            predicted_gesture=a.predicted,
            gesture_confidence=a.confidence,
            gesture_id=a.lookup_gesture,
            model_version=active_version or encoder.MODEL_VERSION,
            latency_ms=latency,
        )

    ai_input = to_ai_input(req.camera, req.frames)

    # 1-2. 검증 겸 제스처 분류 (두 모드 모두 호출해서 기록한다)
    try:
        predicted, confidence = encoder.classify_gesture(ai_input)
    except InvalidSequenceError as exc:
        fail(INVALID_INPUT)
        _write_log(session, a, active_version, a.latency_ms())
        raise invalid_sequence_error(exc) from exc
    a.predicted, a.confidence = str(predicted), float(confidence)

    # 3. 템플릿 조회에 쓸 제스처
    if settings.use_gesture_classifier:
        a.lookup_gesture = a.predicted
        if req.gesture_id and req.gesture_id != a.predicted:
            fail(GESTURE_MISMATCH)
            return finish()
    else:
        a.lookup_gesture = req.gesture_id

    # 로드된 인코더와 템플릿의 벡터 공간이 다르면 비교 자체가 무의미하다 (조용히 틀림).
    if active_version != encoder.MODEL_VERSION:
        fail(MODEL_VERSION_MISMATCH)
        _write_log(session, a, active_version, a.latency_ms())
        log.error("active model %s != loaded encoder %s", active_version, encoder.MODEL_VERSION)
        raise ApiError(
            503, "service_unavailable", MODEL_VERSION_MISMATCH,
            "인증 모델 교체 중입니다. 잠시 후 다시 시도해주세요.",
        )
    if active_threshold is None:
        raise ApiError(
            503, "service_unavailable", "no_active_threshold",
            "인증 기준값이 설정되지 않았습니다. 관리자에게 문의해주세요.",
        )

    # 4. query 임베딩
    try:
        query = encoder.embed(ai_input)
    except InvalidSequenceError as exc:
        fail(INVALID_INPUT)
        _write_log(session, a, active_version, a.latency_ms())
        raise invalid_sequence_error(exc) from exc

    # 5. 템플릿
    template = template_service.get_template(session, req.user_id, a.lookup_gesture, active_version)
    if template is None:
        fail(NO_TEMPLATE)
        return finish()

    # 6-7. 유사도와 판정
    a.score = template_service.cosine_score(query, template)
    a.passed = a.score >= active_threshold.value
    if not a.passed:
        a.fail_reason = BELOW_THRESHOLD
    return finish()

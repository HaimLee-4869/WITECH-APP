"""인증 로직 (dual-head, 명세 7장 + AI 릴리스 v1.1.1).

1. 입력 검증 → 실패 시 422 (로그에 invalid_input)
2. embed_both(frames) → user·gesture 임베딩 (한 번의 forward)
3. (user, gestureId, 활성 model_version) 템플릿 2개 조회 → 없으면 no_template
4. 코사인 유사도 두 개 = query @ template
5. **gesture_score >= Tg AND user_score >= Tu** 일 때만 통과
6. auth_logs에 두 점수·두 임계값 기록 (성공·실패 모두, 랜드마크 원본 포함)

왜 관문이 둘인가. 이전 모델(v1.0.0)은 user 임베딩만 봤고, 제스처 분류기는 닫힌 집합이라
판정에서 뺐다. 그래서 본인이 등록과 **다른 동작**을 해도 통과했다(2026-09-17 실기기 실측:
본인의 다른 동작이 0.81~0.99로 전부 통과). gesture 관문이 그것을 막는다.
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
    embed_both,
    invalid_sequence_error,
    to_ai_input,
)

log = logging.getLogger(__name__)

BELOW_THRESHOLD = "below_threshold"   # user 관문 미달 = 본인이 아니다
GESTURE_GATE = "gesture_gate"         # gesture 관문 미달 = 등록한 동작이 아니다
NO_TEMPLATE = "no_template"
INVALID_INPUT = "invalid_input"
MODEL_VERSION_MISMATCH = "model_version_mismatch"


@dataclass
class _Attempt:
    """한 번의 인증 시도에서 로그와 응답에 들어갈 값."""

    user_id: str
    gesture_id: str
    raw_body: str
    started: float = field(default_factory=time.perf_counter)
    score: float | None = None            # user 관문
    threshold: float | None = None
    gesture_score: float | None = None    # gesture 관문
    gesture_threshold: float | None = None
    passed: bool = False
    fail_reason: str | None = None

    def latency_ms(self) -> int:
        return int(round((time.perf_counter() - self.started) * 1000))


def _write_log(session: Session, a: _Attempt, model_version: str | None, latency_ms: int) -> None:
    session.add(
        AuthLog(
            user_id=a.user_id,
            claimed_gesture_id=a.gesture_id,
            score=a.score,
            threshold=a.threshold,
            gesture_score=a.gesture_score,
            gesture_threshold=a.gesture_threshold,
            passed=a.passed,
            fail_reason=a.fail_reason,
            auth_model_version=model_version,
            # dual-head는 한 모델이 두 임베딩을 낸다. 별도 제스처 모델이 없다.
            gesture_model_version=model_version,
            landmarks_json=a.raw_body,
            latency_ms=latency_ms,
        )
    )
    session.commit()


def _summary(req: VerifyRequest, a: _Attempt, status: int, reason: str | None) -> str:
    """요청 1건을 한 줄로. 실기기 테스트에서 무슨 일이 있었는지 서버 로그만으로 보이게 한다.

    랜드마크 본문은 찍지 않는다 (auth_logs.landmarks_json에 이미 남는다).
    """
    cam = req.camera
    camera = f"{cam.width}x{cam.height}" if cam is not None else "none"
    hand_frames = sum(1 for f in req.frames if f.lm)
    span = f"{req.frames[-1].t_ms - req.frames[0].t_ms:.0f}" if req.frames else "-"

    def num(v: float | None) -> str:
        return "-" if v is None else f"{v:.4f}"

    return (
        f"verify status={status} user={req.user_id} gesture={req.gesture_id} "
        f"camera={camera} frames={len(req.frames)} handFrames={hand_frames} "
        f"durationMs={req.duration_ms} spanMs={span} "
        f"score={num(a.score)} threshold={num(a.threshold)} "
        f"gestureScore={num(a.gesture_score)} gestureThreshold={num(a.gesture_threshold)} "
        f"passed={a.passed} reason={reason or '-'} latencyMs={a.latency_ms()}"
    )


def verify(session: Session, settings: Settings, req: VerifyRequest, raw_body: str) -> VerifyResponse:
    a = _Attempt(user_id=req.user_id, gesture_id=req.gesture_id or "", raw_body=raw_body)
    try:
        res = _verify(session, settings, req, a)
    except ApiError as exc:
        log.info(_summary(req, a, exc.status_code, exc.reason))
        raise
    log.info(_summary(req, a, 200, res.reason))
    return res


def _verify(session: Session, settings: Settings, req: VerifyRequest, a: _Attempt) -> VerifyResponse:
    if session.get(User, req.user_id) is None:
        raise not_found("user_not_found", "등록되지 않은 사용자입니다.")
    if not req.gesture_id:
        # dual-head는 gesture 템플릿을 gestureId로 찾는다. 서버가 추측하지 않는다.
        raise invalid_request("gesture_id_required", "수어 암호(gestureId)가 필요합니다.")

    active_version = cfg.get_active_model_version(session)
    pair = threshold_service.get_active_pair(session, active_version) if active_version else None
    if pair is not None:
        a.threshold, a.gesture_threshold = pair.user, pair.gesture

    def fail(reason: str) -> None:
        a.passed = False
        a.fail_reason = reason

    def finish() -> VerifyResponse:
        latency = a.latency_ms()
        _write_log(session, a, active_version, latency)
        return VerifyResponse(
            score=a.score,
            threshold=a.threshold,
            gesture_score=a.gesture_score,
            gesture_threshold=a.gesture_threshold,
            passed=a.passed,
            reason=a.fail_reason,
            gesture_id=req.gesture_id,
            model_version=active_version or encoder.MODEL_VERSION,
            latency_ms=latency,
        )

    # 로드된 인코더와 템플릿의 벡터 공간이 다르면 비교 자체가 무의미하다 (조용히 틀림).
    if active_version != encoder.MODEL_VERSION:
        fail(MODEL_VERSION_MISMATCH)
        _write_log(session, a, active_version, a.latency_ms())
        log.error("active model %s != loaded encoder %s", active_version, encoder.MODEL_VERSION)
        raise ApiError(
            503, "service_unavailable", MODEL_VERSION_MISMATCH,
            "인증 모델 교체 중입니다. 잠시 후 다시 시도해주세요.",
        )
    if pair is None:
        raise ApiError(
            503, "service_unavailable", "no_active_threshold",
            "인증 기준값이 설정되지 않았습니다. 관리자에게 문의해주세요.",
        )

    # 2. 검증 겸 임베딩
    try:
        user_embedding, gesture_embedding = embed_both(to_ai_input(req.camera, req.frames))
    except InvalidSequenceError as exc:
        fail(INVALID_INPUT)
        _write_log(session, a, active_version, a.latency_ms())
        raise invalid_sequence_error(exc) from exc

    # 3. 템플릿 두 개. 하나라도 없으면 비교할 수 없다.
    user_template = template_service.get_template(
        session, req.user_id, req.gesture_id, active_version, kind="user"
    )
    gesture_template = template_service.get_template(
        session, req.user_id, req.gesture_id, active_version, kind="gesture"
    )
    if user_template is None or gesture_template is None:
        fail(NO_TEMPLATE)
        return finish()

    # 4-5. 두 관문. 둘 다 넘어야 통과한다.
    a.score = template_service.cosine_score(user_embedding, user_template)
    a.gesture_score = template_service.cosine_score(gesture_embedding, gesture_template)
    a.passed = pair.passes(a.score, a.gesture_score)
    if not a.passed:
        # 먼저 막힌 관문을 사유로 쓴다. 동작이 다르면 본인이어도 gesture_gate다.
        fail(GESTURE_GATE if a.gesture_score < pair.gesture else BELOW_THRESHOLD)
    return finish()

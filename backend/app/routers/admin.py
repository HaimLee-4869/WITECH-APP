"""운영 조정: threshold 전환, 재색인, app_config 변경. 전부 재시작 없이 반영된다."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.deps import get_db
from app.errors import ApiError, not_found
from app.routers.config import get_config
from app.schemas import (
    ChallengeConfigOut,
    ConfigOut,
    ConfigPatch,
    ReindexRequest,
    ReindexResponse,
    ThresholdOut,
    ThresholdSwitchRequest,
)
from app.services import app_config_service as cfg
from app.services import reindex_service, threshold_service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def _threshold_out(row) -> ThresholdOut:
    return ThresholdOut(
        basis=row.basis, gate=row.gate, value=row.value, far=row.far, frr=row.frr,
        model_version=row.model_version, is_active=row.is_active,
    )


def _active_version(session: Session) -> str:
    version = cfg.get_active_model_version(session)
    if version is None:
        raise ApiError(503, "service_unavailable", "no_active_model", "활성 모델 버전이 없습니다.")
    return version


@router.get("/thresholds", response_model=list[ThresholdOut])
def list_thresholds(session: Session = Depends(get_db)) -> list[ThresholdOut]:
    return [_threshold_out(r) for r in threshold_service.list_for_version(session, _active_version(session))]


@router.post("/threshold", response_model=list[ThresholdOut])
def switch_threshold(
    body: ThresholdSwitchRequest, session: Session = Depends(get_db)
) -> list[ThresholdOut]:
    """운영점을 통째로 바꾼다. dual-head는 한 운영점이 두 관문 값을 갖는다."""
    version = _active_version(session)
    pair = threshold_service.switch(session, version, body.basis)
    if pair is None:
        raise not_found(
            "threshold_not_found",
            f"'{body.basis}' 운영점이 없거나 두 관문(user/gesture) 중 하나가 빠졌습니다.",
        )
    log.info(
        "threshold 전환: basis=%s user=%.6f gesture=%.6f", pair.basis, pair.user, pair.gesture
    )
    return [
        _threshold_out(r)
        for r in threshold_service.list_for_version(session, version)
        if r.is_active
    ]


@router.post("/reindex", response_model=ReindexResponse)
async def reindex(body: ReindexRequest, request: Request) -> ReindexResponse:
    def work():
        with request.app.state.db.session() as session:
            return reindex_service.reindex(session, body)

    return await run_in_threadpool(work)


def _deep_merge(base: dict, patch: dict) -> dict:
    """patch의 키만 base 위에 덮는다. dict는 재귀, 그 외(리스트 포함)는 통째 교체.

    directionMap이나 shapePool을 부분 병합하면 중간 상태(방향 하나만 바뀐 표)가
    생기므로 리스트·표는 통째로 바꾼다.
    """
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _patch_challenge(session: Session, patch: dict) -> None:
    """Challenge 설정을 깊은 병합 후 검증해 저장한다. 실패하면 아무것도 바꾸지 않는다."""
    current = cfg.get_challenge_config(session)
    merged = _deep_merge(current, patch)
    try:
        validated = ChallengeConfigOut.model_validate(merged)
    except ValidationError as exc:
        raise ApiError(
            422, "invalid_request", "invalid_challenge_config",
            f"Challenge 설정이 올바르지 않습니다: {exc.errors()[0]['msg']}",
        ) from exc

    # 앱은 프레임 수를 frameReferenceFps 기준 시간으로 바꿔 쓴다. 바뀐 값이
    # 실기기에서 몇 ms가 되는지 로그에 같이 남긴다. 안 보이면 감이 안 잡힌다.
    frame_ms = 1000.0 / validated.frame_reference_fps
    for path, before, after in _changed_leaves(current, merged):
        note = ""
        if path.endswith("Frames"):
            note = f"  ({after}프레임 = {float(after) * frame_ms:.0f}ms @ {validated.frame_reference_fps}fps)"
        log.warning("challenge.%s %s → %s%s", path, before, after, note)

    steps = validated.steps.num_shapes + validated.steps.num_moves
    if validated.timing.total_timeout_ms < validated.timing.per_action_timeout_ms * steps:
        log.warning(
            "challenge.timing: totalTimeoutMs=%s가 perActionTimeoutMs(%s) × 단계 %d = %s보다 "
            "작다. 마지막 단계가 TOTAL_TIMEOUT으로 죽을 수 있다.",
            validated.timing.total_timeout_ms, validated.timing.per_action_timeout_ms,
            steps, validated.timing.per_action_timeout_ms * steps,
        )

    cfg.set_value(session, cfg.CHALLENGE, merged)


def _changed_leaves(before: dict, after: dict, prefix: str = "") -> list[tuple[str, object, object]]:
    """실제로 값이 바뀐 잎만 (경로, 이전, 이후)로 모은다."""
    changed: list[tuple[str, object, object]] = []
    for key, new in after.items():
        if key.startswith("_"):
            continue
        old = before.get(key)
        path = f"{prefix}{key}"
        if isinstance(new, dict) and isinstance(old, dict):
            changed.extend(_changed_leaves(old, new, f"{path}."))
        elif old != new:
            changed.append((path, old, new))
    return changed


@router.patch("/config", response_model=ConfigOut)
def patch_config(body: ConfigPatch, session: Session = Depends(get_db)) -> ConfigOut:
    if body.challenge is not None:
        _patch_challenge(session, body.challenge)
    for field, key in (
        ("enrollment_takes", cfg.ENROLLMENT_TAKES),
        ("enrollment_gestures", cfg.ENROLLMENT_GESTURES),
        ("capture_duration_ms", cfg.CAPTURE_DURATION_MS),
        ("hand_required", cfg.HAND_REQUIRED),
    ):
        value = getattr(body, field)
        if value is None:
            continue
        previous = cfg.get_value(session, key)
        cfg.set_value(session, key, value)
        if key == cfg.CAPTURE_DURATION_MS and previous != value:
            # 촬영 길이는 AI 모델의 입력 feature다. 길이가 다르면 같은 사람·같은 동작도
            # 유사도가 크게 떨어진다(2초 등록분을 5초로 인증하면 0.51, 임계값 0.63 미만).
            # 조용히 바뀌면 원인 모를 인증 실패로 나타나므로 반드시 남긴다.
            log.warning(
                "captureDurationMs %s → %s: 기존 등록 템플릿이 무효가 된다. "
                "scripts/clear_enrollments.py로 정리하고 전원 재등록할 것.",
                previous, value,
            )
    session.commit()
    return get_config(session)

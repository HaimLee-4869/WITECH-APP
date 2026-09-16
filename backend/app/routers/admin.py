"""운영 조정: threshold 전환, 재색인, app_config 변경. 전부 재시작 없이 반영된다."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.deps import get_db
from app.errors import ApiError, not_found
from app.routers.config import get_config
from app.schemas import (
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


@router.patch("/config", response_model=ConfigOut)
def patch_config(body: ConfigPatch, session: Session = Depends(get_db)) -> ConfigOut:
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

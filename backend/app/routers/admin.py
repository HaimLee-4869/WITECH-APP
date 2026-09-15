"""운영 조정: threshold 전환, 재색인, app_config 변경. 전부 재시작 없이 반영된다."""

from __future__ import annotations

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

router = APIRouter(prefix="/admin", tags=["admin"])


def _threshold_out(row) -> ThresholdOut:
    return ThresholdOut(
        basis=row.basis, value=row.value, far=row.far, frr=row.frr,
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


@router.post("/threshold", response_model=ThresholdOut)
def switch_threshold(body: ThresholdSwitchRequest, session: Session = Depends(get_db)) -> ThresholdOut:
    row = threshold_service.switch(session, _active_version(session), body.basis)
    if row is None:
        raise not_found("threshold_not_found", f"'{body.basis}' 기준 threshold가 없습니다.")
    return _threshold_out(row)


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
        if value is not None:
            cfg.set_value(session, key, value)
    session.commit()
    return get_config(session)

"""GET /config (앱이 등록 화면을 그릴 때), GET /health."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ai import encoder
from app.database import Database
from app.deps import get_database, get_db
from app.schemas import ChallengeConfigOut, ConfigOut, HealthOut
from app.services import app_config_service as cfg
from app.services import threshold_service

router = APIRouter(tags=["config"])


@router.get("/config", response_model=ConfigOut)
def get_config(session: Session = Depends(get_db)) -> ConfigOut:
    return ConfigOut(
        enrollment_takes=int(cfg.get_value(session, cfg.ENROLLMENT_TAKES)),
        enrollment_gestures=int(cfg.get_value(session, cfg.ENROLLMENT_GESTURES)),
        capture_duration_ms=int(cfg.get_value(session, cfg.CAPTURE_DURATION_MS)),
        hand_required=str(cfg.get_value(session, cfg.HAND_REQUIRED)),
        model_version=cfg.get_active_model_version(session) or encoder.MODEL_VERSION,
        # Challenge 판정은 앱이 하지만 임계값은 여기서 내려준다. 앱에 상수가 없다.
        challenge=ChallengeConfigOut.model_validate(cfg.get_challenge_config(session)),
    )


@router.get("/health", response_model=HealthOut)
def health(database: Database = Depends(get_database)) -> HealthOut:
    db_ok = database.ping()
    active_version = None
    pair = None
    if db_ok:
        with database.session() as session:
            active_version = cfg.get_active_model_version(session)
            if active_version:
                pair = threshold_service.get_active_pair(session, active_version)
    healthy = db_ok and pair is not None and active_version == encoder.MODEL_VERSION
    return HealthOut(
        status="ok" if healthy else "degraded",
        model_version=active_version,
        loaded_model_version=encoder.MODEL_VERSION,
        active_threshold=pair.user if pair else None,
        active_gesture_threshold=pair.gesture if pair else None,
        active_threshold_basis=pair.basis if pair else None,
        db_ok=db_ok,
    )

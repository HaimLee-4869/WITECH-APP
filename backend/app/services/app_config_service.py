"""app_config 테이블 (운영 중 바뀌는 설정). 값은 JSON으로 저장한다."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import AppConfig
from app.timeutil import utcnow

ENROLLMENT_TAKES = "enrollmentTakes"
ENROLLMENT_GESTURES = "enrollmentGestures"
CAPTURE_DURATION_MS = "captureDurationMs"
HAND_REQUIRED = "handRequired"
# templates/embeddings 조회에 쓰는 활성 인증 모델 버전. 재색인이 끝나야 바뀐다.
ACTIVE_MODEL_VERSION = "activeModelVersion"

DEFAULTS: dict[str, Any] = {
    ENROLLMENT_TAKES: 3,
    ENROLLMENT_GESTURES: 1,  # AI팀 확인 대기 (명세 7장). 1 또는 5.
    CAPTURE_DURATION_MS: 2000,
    HAND_REQUIRED: "right",
}


def get_value(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(AppConfig, key)
    if row is None or row.value is None:
        return DEFAULTS.get(key, default)
    return json.loads(row.value)


def set_value(session: Session, key: str, value: Any) -> None:
    row = session.get(AppConfig, key)
    if row is None:
        row = AppConfig(key=key)
        session.add(row)
    row.value = json.dumps(value, ensure_ascii=False)
    row.updated_at = utcnow()


def get_active_model_version(session: Session) -> str | None:
    return get_value(session, ACTIVE_MODEL_VERSION)

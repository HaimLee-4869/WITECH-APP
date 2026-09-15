"""threshold 조회·전환. 값은 항상 DB에서 읽는다 (코드 상수 금지, 명세 원칙 D).

요청마다 DB에서 활성 행을 읽으므로 전환 즉시 다음 요청부터 반영된다 (재시작 불필요).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Threshold

GLOBAL = "global"


def get_active(session: Session, model_version: str) -> Threshold | None:
    return session.scalar(
        select(Threshold)
        .where(
            Threshold.model_version == model_version,
            Threshold.scheme == GLOBAL,
            Threshold.gesture_id.is_(None),
            Threshold.is_active.is_(True),
        )
        .order_by(Threshold.id.desc())
    )


def list_for_version(session: Session, model_version: str) -> list[Threshold]:
    return list(
        session.scalars(
            select(Threshold)
            .where(Threshold.model_version == model_version, Threshold.scheme == GLOBAL)
            .order_by(Threshold.value.desc())
        )
    )


def switch(session: Session, model_version: str, basis: str) -> Threshold | None:
    """basis 행 하나만 활성으로 만든다. 해당 basis가 없으면 아무것도 바꾸지 않고 None."""
    rows = list_for_version(session, model_version)
    target = next((r for r in rows if r.basis == basis), None)
    if target is None:
        return None
    for r in rows:
        r.is_active = r is target
    session.commit()
    return target

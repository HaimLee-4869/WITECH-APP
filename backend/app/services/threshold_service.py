"""threshold 조회·전환. 값은 항상 DB에서 읽는다 (코드 상수 금지, 명세 원칙 D).

dual-head는 관문이 둘이라 운영점 하나가 **두 행**(user/gesture)으로 저장된다.
`basis`가 운영점 이름(default | demo_relaxed)이고 `gate`가 관문이다.
전환은 같은 basis의 두 행을 함께 활성으로 바꾼다.

요청마다 DB에서 활성 행을 읽으므로 전환 즉시 다음 요청부터 반영된다 (재시작 불필요).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Threshold

GLOBAL = "global"
USER = "user"
GESTURE = "gesture"


@dataclass(frozen=True)
class ThresholdPair:
    """한 운영점의 두 관문 임계값."""

    basis: str | None
    user: float
    gesture: float

    def passes(self, user_score: float, gesture_score: float) -> bool:
        return gesture_score >= self.gesture and user_score >= self.user


def _rows(session: Session, model_version: str, active_only: bool = False) -> list[Threshold]:
    conditions = [
        Threshold.model_version == model_version,
        Threshold.scheme == GLOBAL,
        Threshold.gesture_id.is_(None),
    ]
    if active_only:
        conditions.append(Threshold.is_active.is_(True))
    return list(session.scalars(select(Threshold).where(*conditions).order_by(Threshold.id)))


def get_active_pair(session: Session, model_version: str) -> ThresholdPair | None:
    """활성 운영점. 두 관문이 모두 있어야 유효하다."""
    rows = _rows(session, model_version, active_only=True)
    user = next((r for r in rows if r.gate == USER), None)
    gesture = next((r for r in rows if r.gate == GESTURE), None)
    if user is None or gesture is None:
        return None
    return ThresholdPair(basis=user.basis, user=user.value, gesture=gesture.value)


def list_for_version(session: Session, model_version: str) -> list[Threshold]:
    return _rows(session, model_version)


def switch(session: Session, model_version: str, basis: str) -> ThresholdPair | None:
    """basis의 두 행만 활성으로 만든다. 한쪽이라도 없으면 아무것도 바꾸지 않는다."""
    rows = _rows(session, model_version)
    target = [r for r in rows if r.basis == basis]
    gates = {r.gate for r in target}
    if not {USER, GESTURE} <= gates:
        return None
    for row in rows:
        row.is_active = row.basis == basis
    session.commit()
    return get_active_pair(session, model_version)

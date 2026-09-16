"""관리자 화면: 인증 이력, 월별 통계."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.deps import get_db, get_settings
from app.models import AuthLog, User
from app.schemas import AuthLogOut, AuthLogPage, MonthlyStat

router = APIRouter(tags=["logs"])


@router.get("/logs", response_model=AuthLogPage)
def list_logs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user_id: str | None = Query(None, alias="userId"),
    passed: bool | None = Query(None),
    session: Session = Depends(get_db),
) -> AuthLogPage:
    filters = []
    if user_id is not None:
        filters.append(AuthLog.user_id == user_id)
    if passed is not None:
        filters.append(AuthLog.passed.is_(passed))

    total = session.scalar(select(func.count(AuthLog.id)).where(*filters)) or 0
    rows = session.execute(
        select(AuthLog, User.name, User.department)
        .outerjoin(User, User.id == AuthLog.user_id)
        .where(*filters)
        .order_by(AuthLog.created_at.desc(), AuthLog.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        AuthLogOut(
            id=log.id,
            user_id=log.user_id,
            user_name=name,
            department=department,
            claimed_gesture_id=log.claimed_gesture_id,
            score=log.score,
            threshold=log.threshold,
            gesture_score=log.gesture_score,
            gesture_threshold=log.gesture_threshold,
            passed=log.passed,
            fail_reason=log.fail_reason,
            auth_model_version=log.auth_model_version,
            gesture_model_version=log.gesture_model_version,
            latency_ms=log.latency_ms,
            created_at=log.created_at,
        )
        for log, name, department in rows
    ]
    return AuthLogPage(items=items, total=total, limit=limit, offset=offset)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)  # 테스트에서 고정한다


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


@router.get("/stats/monthly", response_model=list[MonthlyStat])
def monthly_stats(
    months: int = Query(5, ge=1, le=24),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[MonthlyStat]:
    """최근 N개월(이번 달 포함) 인증 건수. 월 경계는 KST. 건수가 0인 달도 포함한다."""
    tz = timezone(timedelta(hours=settings.stats_utc_offset_hours))
    now_local = _now_utc().astimezone(tz)
    keys = [_shift_month(now_local.year, now_local.month, -i) for i in range(months - 1, -1, -1)]
    start_local = datetime(keys[0][0], keys[0][1], 1, tzinfo=tz)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)

    buckets = {k: [0, 0] for k in keys}  # [total, passed]
    # DB 종류에 묶이지 않게 월 계산은 파이썬에서 한다.
    for created_at, passed in session.execute(
        select(AuthLog.created_at, AuthLog.passed).where(AuthLog.created_at >= start_utc)
    ):
        local = created_at.replace(tzinfo=timezone.utc).astimezone(tz)
        bucket = buckets.get((local.year, local.month))
        if bucket is not None:
            bucket[0] += 1
            bucket[1] += 1 if passed else 0

    return [
        MonthlyStat(month=f"{y:04d}-{m:02d}", total=t, passed=p, failed=t - p)
        for (y, m), (t, p) in buckets.items()
    ]

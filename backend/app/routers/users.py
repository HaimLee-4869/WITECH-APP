"""사용자 목록·생성·삭제.

DELETE /users/{id}는 랜드마크 원본을 포함한 관련 데이터를 전부 지운다 (명세 6장 개인정보).
enrollments 영구 보관 원칙의 유일한 예외다.
"""

from __future__ import annotations

import secrets
from collections import defaultdict

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.deps import get_db
from app.errors import ApiError, not_found
from app.models import AuthLog, Embedding, Enrollment, Template, User
from app.schemas import UserCreate, UserOut
from app.services import app_config_service as cfg

router = APIRouter(tags=["users"])


def _enrolled_gestures(session: Session, user_ids: list[str]) -> dict[str, list[str]]:
    version = cfg.get_active_model_version(session)
    rows = session.execute(
        select(Template.user_id, Template.gesture_id)
        .where(Template.user_id.in_(user_ids), Template.model_version == version)
        .order_by(Template.gesture_id)
    ).all()
    result: dict[str, list[str]] = defaultdict(list)
    for user_id, gesture_id in rows:
        result[user_id].append(gesture_id)
    return result


def _out(user: User, gestures: list[str]) -> UserOut:
    return UserOut(
        id=user.id, name=user.name, department=user.department,
        created_at=user.created_at, enrolled_gestures=gestures,
    )


@router.get("/users", response_model=list[UserOut])
def list_users(session: Session = Depends(get_db)) -> list[UserOut]:
    users = session.scalars(select(User).order_by(User.created_at, User.id)).all()
    gestures = _enrolled_gestures(session, [u.id for u in users])
    return [_out(u, gestures.get(u.id, [])) for u in users]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, session: Session = Depends(get_db)) -> UserOut:
    user_id = body.id or f"u_{secrets.token_hex(4)}"
    if session.get(User, user_id) is not None:
        raise ApiError(409, "conflict", "user_exists", "이미 존재하는 사용자 ID입니다.")
    user = User(id=user_id, name=body.name, department=body.department)
    session.add(user)
    session.commit()
    return _out(user, [])


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: str, session: Session = Depends(get_db)) -> Response:
    if session.get(User, user_id) is None:
        raise not_found("user_not_found", "등록되지 않은 사용자입니다.")
    # FK CASCADE에 기대지 않고 명시적으로 지운다 (DB 종류·PRAGMA와 무관하게 확실히).
    enrollment_ids = select(Enrollment.id).where(Enrollment.user_id == user_id)
    session.execute(delete(Embedding).where(Embedding.enrollment_id.in_(enrollment_ids)))
    session.execute(delete(Enrollment).where(Enrollment.user_id == user_id))
    session.execute(delete(Template).where(Template.user_id == user_id))
    session.execute(delete(AuthLog).where(AuthLog.user_id == user_id))
    session.execute(delete(User).where(User.id == user_id))
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""의존성 주입. 설정과 DB는 app.state에서 꺼낸다 (테스트마다 별도 DB를 쓰기 위해)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import Database


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_database(request: Request) -> Database:
    return request.app.state.db


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.db.session() as session:
        yield session

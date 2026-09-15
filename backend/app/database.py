"""DB 엔진과 세션.

SQLite 파일 기반으로 시작하지만 URL만 바꾸면 Postgres로 옮길 수 있게
SQLite 전용 설정은 `_configure_sqlite`에만 둔다.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def _configure_sqlite(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")  # 인증 로그 쓰기와 조회가 동시에 일어난다
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()


class Database:
    def __init__(self, url: str):
        self.url = url
        is_sqlite = url.startswith("sqlite")
        connect_args = {"check_same_thread": False} if is_sqlite else {}
        self.engine = create_engine(url, connect_args=connect_args)
        if is_sqlite:
            _configure_sqlite(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )

    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self.session_factory()
        try:
            yield s
        finally:
            s.close()

    def ping(self) -> bool:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def dispose(self) -> None:
        self.engine.dispose()

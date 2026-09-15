"""2단계: 모델과 Alembic 마이그레이션."""

from __future__ import annotations

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError

from app import models
from app.database import Base, Database
from app.migrations import upgrade_to_head


@pytest.fixture
def db(settings) -> Database:
    upgrade_to_head(settings.database_url)
    database = Database(settings.database_url)
    yield database
    database.dispose()


def test_migration_creates_all_tables(db):
    tables = set(inspect(db.engine).get_table_names())
    assert {
        "users", "gestures", "enrollments", "embeddings", "templates",
        "thresholds", "auth_logs", "app_config", "alembic_version",
    } <= tables


def test_migration_matches_models(settings):
    """모델을 고치고 마이그레이션을 빠뜨리면 여기서 걸린다."""
    upgrade_to_head(settings.database_url)
    engine = create_engine(settings.database_url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == []


def _user_and_gesture(session):
    session.add(models.User(id="kim", name="김길동"))
    session.add(models.Gesture(id="G1", label="G1"))
    session.flush()


def _enrollment(take_no=1):
    return models.Enrollment(
        user_id="kim", gesture_id="G1", take_no=take_no, landmarks_json="{}",
        camera_width=720, camera_height=1280,
    )


def test_enrollment_unique_per_take(db):
    with db.session() as s:
        _user_and_gesture(s)
        s.add(_enrollment(1))
        s.flush()
        s.add(_enrollment(1))
        with pytest.raises(IntegrityError):
            s.flush()


def test_embedding_unique_per_model_version(db):
    with db.session() as s:
        _user_and_gesture(s)
        e = _enrollment()
        s.add(e)
        s.flush()
        s.add(models.Embedding(enrollment_id=e.id, model_version="v1", vector=b"x"))
        s.add(models.Embedding(enrollment_id=e.id, model_version="v2", vector=b"x"))
        s.flush()
        s.add(models.Embedding(enrollment_id=e.id, model_version="v1", vector=b"y"))
        with pytest.raises(IntegrityError):
            s.flush()


def test_deleting_user_cascades(db):
    with db.session() as s:
        _user_and_gesture(s)
        e = _enrollment()
        s.add(e)
        s.flush()
        s.add(models.Embedding(enrollment_id=e.id, model_version="v1", vector=b"x"))
        s.add(models.Template(user_id="kim", gesture_id="G1", model_version="v1", centroid=b"x"))
        s.add(models.AuthLog(user_id="kim", passed=True))
        s.commit()

        s.delete(s.get(models.User, "kim"))
        s.commit()
        for model in (models.Enrollment, models.Embedding, models.Template, models.AuthLog):
            assert s.query(model).count() == 0


def test_app_startup_runs_migrations(client):
    assert "templates" in inspect(client.app.state.db.engine).get_table_names()

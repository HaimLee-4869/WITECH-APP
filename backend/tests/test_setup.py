from app.config import Settings


def test_settings_defaults(monkeypatch):
    """기본값은 운영 설정(2026-09-16 팀 결정): gestureId로 템플릿 조회."""
    monkeypatch.delenv("USE_GESTURE_CLASSIFIER", raising=False)
    s = Settings(_env_file=None)
    assert s.use_gesture_classifier is False
    assert s.ai_device == "cpu"


def test_use_gesture_classifier_from_env(monkeypatch):
    monkeypatch.setenv("USE_GESTURE_CLASSIFIER", "true")
    assert Settings(_env_file=None).use_gesture_classifier is True


def test_cors_origin_list():
    s = Settings(cors_origins="http://a, http://b", _env_file=None)
    assert s.cors_origin_list == ["http://a", "http://b"]


def test_database_connects(client):
    db = client.app.state.db
    assert db.ping()
    with db.engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_load_model_called_once_at_startup(settings, monkeypatch):
    """요청마다 load_model()을 부르면 매번 수백 ms 낭비 (명세 8장)."""
    from fastapi.testclient import TestClient

    from ai import encoder
    from app.main import create_app
    from tests.conftest import post_json
    from tests.payloads import enroll_body

    calls = []
    monkeypatch.setattr(encoder, "load_model", lambda device="cpu": calls.append(device))
    with TestClient(create_app(settings)) as c:
        assert calls == ["cpu"]
        for _ in range(3):
            post_json(c, "/enroll", enroll_body())
        assert calls == ["cpu"]


def test_startup_seeds_gestures_thresholds_config(client):
    from sqlalchemy import select

    from ai import encoder
    from app import models
    from app.services import app_config_service as cfg

    with client.app.state.db.session() as s:
        assert s.scalars(select(models.Gesture.id)).all() == ["G1", "G2", "G3", "G4", "G5"]
        rows = s.scalars(select(models.Threshold)).all()
        assert {(r.basis, r.value, r.is_active) for r in rows} == {
            ("far1", 0.6275163888931274, True),
            ("eer", 0.4360462427139282, False),
            ("far5", 0.27212807536125183, False),
        }
        assert all(r.scheme == "global" and r.gesture_id is None for r in rows)
        assert cfg.get_active_model_version(s) == encoder.MODEL_VERSION
        assert cfg.get_value(s, cfg.ENROLLMENT_TAKES) == 3
        assert cfg.get_value(s, cfg.ENROLLMENT_GESTURES) == 1


def test_startup_seed_is_idempotent(settings):
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app import models
    from app.main import create_app

    for _ in range(2):
        with TestClient(create_app(settings)) as c:
            with c.app.state.db.session() as s:
                assert len(s.scalars(select(models.Threshold)).all()) == 3

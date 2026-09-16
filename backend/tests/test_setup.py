from app.config import Settings


def test_settings_defaults():
    s = Settings(_env_file=None)
    assert s.ai_device == "cpu"
    assert s.database_url.startswith("sqlite")
    # 분류기 전환 설정은 dual-head(v1.1.1)에서 사라졌다. 제스처는 항상 임베딩으로 본다.
    assert not hasattr(s, "use_gesture_classifier")


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
        # dual-head: 운영점 2개 × 관문 2개 = 4행
        assert {(r.basis, r.gate, r.value, r.is_active) for r in rows} == {
            ("default", "user", 0.3423501253128052, True),
            ("default", "gesture", 0.9020317792892456, True),
            ("demo_relaxed", "user", 0.2933087944984436, False),
            ("demo_relaxed", "gesture", 0.9020317792892456, False),
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
                assert len(s.scalars(select(models.Threshold)).all()) == 4

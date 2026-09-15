from app.config import Settings


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("USE_GESTURE_CLASSIFIER", raising=False)
    s = Settings(_env_file=None)
    assert s.use_gesture_classifier is True
    assert s.ai_device == "cpu"


def test_use_gesture_classifier_from_env(monkeypatch):
    monkeypatch.setenv("USE_GESTURE_CLASSIFIER", "false")
    assert Settings(_env_file=None).use_gesture_classifier is False


def test_cors_origin_list():
    s = Settings(cors_origins="http://a, http://b", _env_file=None)
    assert s.cors_origin_list == ["http://a", "http://b"]


def test_database_connects(client):
    db = client.app.state.db
    assert db.ping()
    with db.engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1

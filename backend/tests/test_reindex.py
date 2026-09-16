"""재색인과 실패 시 롤백 (명세 7장, 10장).

인코더 교체(다음 릴리스)는 encoder.MODEL_VERSION과 벡터 생성 방식을 바꿔서 흉내 낸다.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ai import encoder
from app import models
from app.main import create_app
from app.schemas import SequencePayload
from app.services import template_service
from app.services.ai_gateway import to_ai_input
from tests.conftest import post_json
from tests.payloads import enroll_body, enroll_same_body, verify_body

OLD, NEW = encoder.MODEL_VERSION, "handonly-supcon-v1.1.0"
GESTURE, SECOND_GESTURE = "G3", "G5"


def _swap_encoder(monkeypatch, fail_on=None):
    """새 인증 인코더: 버전 문자열이 바뀌고 벡터 공간도 달라진다 (기존 벡터에 고정 회전).

    제스처 모델은 그대로 둔다. fail_on: 이 camera width를 가진 입력에서 실패.
    """
    rotation = np.linalg.qr(np.random.default_rng(99).normal(size=(128, 128)))[0].astype(np.float32)
    original_embed = encoder.embed
    original_batch = encoder.embed_batch

    def rotate(vectors):
        out = np.atleast_2d(vectors) @ rotation.T
        out /= np.linalg.norm(out, axis=1, keepdims=True)
        return out.astype(np.float32)

    def check(payload):
        if fail_on is not None and payload.get("width") == fail_on:
            raise RuntimeError("weights corrupted")

    def new_embed(frames):
        check(frames)
        return rotate(original_embed(frames))[0]

    def new_embed_batch(list_of_frames):
        for payload in list_of_frames:
            check(payload)
        result = original_batch(list_of_frames)
        return rotate(result) if len(result) else result

    monkeypatch.setattr(encoder, "MODEL_VERSION", NEW)
    # 실제 모듈의 embed_batch는 embed를 호출하지 않으므로 둘 다 바꾼다
    monkeypatch.setattr(encoder, "embed", new_embed)
    monkeypatch.setattr(encoder, "embed_batch", new_embed_batch)


def _enroll_users(client):
    for uid in ("kim", "lee", "oh"):
        client.post("/users", json={"id": uid, "name": uid})
        assert post_json(client, "/enroll", enroll_same_body(uid, GESTURE, 0)).status_code == 200
    body = enroll_body("kim", SECOND_GESTURE, seeds=(3, 4, 5))
    assert post_json(client, "/enroll", body).status_code == 200
    return GESTURE  # 템플릿 4개, enrollments 12개


def _snapshot(db):
    with db.session() as s:
        return {
            "templates": sorted((t.user_id, t.gesture_id, t.model_version, t.centroid)
                                for t in s.scalars(select(models.Template))),
            "embeddings": sorted((e.enrollment_id, e.model_version, e.vector)
                                 for e in s.scalars(select(models.Embedding))),
            "enrollments": sorted((e.id, e.landmarks_json) for e in s.scalars(select(models.Enrollment))),
            "active": s.scalar(select(models.AppConfig.value).where(models.AppConfig.key == "activeModelVersion")),
        }


def _restart(settings):
    """새 인코더를 로드한 상태로 서버 재시작 (startup 시드가 새 버전 threshold를 넣는다)."""
    return TestClient(create_app(settings))


def test_version_must_match_loaded_encoder(client):
    res = client.post("/admin/reindex", json={"modelVersion": "handonly-supcon-v9"})
    assert res.status_code == 400
    assert res.json()["detail"]["reason"] == "model_version_mismatch"


def test_reindex_updates_all_templates(settings, monkeypatch):
    with TestClient(create_app(settings)) as c:
        gesture = _enroll_users(c)

    _swap_encoder(monkeypatch)
    with _restart(settings) as c:
        db = c.app.state.db
        assert c.get("/health").json()["status"] == "degraded"
        assert post_json(c, "/verify", verify_body("kim", 0, gesture_id=GESTURE)).status_code == 503

        res = c.post("/admin/reindex", json={"modelVersion": NEW, "dryRun": False})
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["fromVersion"] == OLD and data["toVersion"] == NEW
        assert data["enrollmentsProcessed"] == 12
        assert data["templatesRebuilt"] == 4
        assert data["failed"] == 0 and data["switched"] is True and data["failures"] == []

        with db.session() as s:
            keys_new = {(t.user_id, t.gesture_id) for t in s.scalars(
                select(models.Template).where(models.Template.model_version == NEW))}
            keys_old = {(t.user_id, t.gesture_id) for t in s.scalars(
                select(models.Template).where(models.Template.model_version == OLD))}
            assert keys_new == keys_old and len(keys_new) == 4   # 모든 템플릿이 새 버전으로
            assert s.query(models.Embedding).filter_by(model_version=NEW).count() == 12
            for t in s.scalars(select(models.Template).where(models.Template.model_version == NEW)):
                assert np.linalg.norm(template_service.from_blob(t.centroid)) == pytest.approx(1.0, abs=1e-6)

        health = c.get("/health").json()
        assert health["status"] == "ok" and health["modelVersion"] == NEW

        res = post_json(c, "/verify", verify_body("kim", 0, gesture_id=GESTURE)).json()
        assert res["passed"] is True and res["score"] == pytest.approx(1.0, abs=1e-5)
        assert res["modelVersion"] == NEW
        assert c.get("/logs").json()["items"][0]["authModelVersion"] == NEW
        assert gesture in c.get("/users").json()[0]["enrolledGestures"]


def test_reindex_new_centroid_matches_new_space(settings, monkeypatch):
    """새 템플릿은 새 인코더로 다시 계산한 값이어야 한다 (옛 벡터 복사가 아님)."""
    with TestClient(create_app(settings)) as c:
        _enroll_users(c)
    _swap_encoder(monkeypatch)
    with _restart(settings) as c:
        c.post("/admin/reindex", json={"modelVersion": NEW})
        with c.app.state.db.session() as s:
            old = template_service.get_template(s, "kim", SECOND_GESTURE, OLD)
            new = template_service.get_template(s, "kim", SECOND_GESTURE, NEW)
            group = s.scalars(
                select(models.Enrollment)
                .where(models.Enrollment.user_id == "kim", models.Enrollment.gesture_id == SECOND_GESTURE)
                .order_by(models.Enrollment.take_no)
            ).all()
        inputs = []
        for r in group:
            p = SequencePayload.model_validate(json.loads(r.landmarks_json))
            inputs.append(to_ai_input(p.camera, p.frames))
        expected = template_service.build_centroid(encoder.embed_batch(inputs))
        assert np.allclose(new, expected, atol=1e-6)
        assert not np.allclose(new, old, atol=1e-3)


def test_reindex_failure_keeps_old_version(settings, monkeypatch):
    with TestClient(create_app(settings)) as c:
        _enroll_users(c)
        # oh의 원본만 camera width를 다르게 저장해 두고, 새 인코더가 그 입력에서 실패하게 한다
        with c.app.state.db.session() as s:
            for e in s.scalars(select(models.Enrollment).where(models.Enrollment.user_id == "oh")):
                payload = json.loads(e.landmarks_json)
                payload["camera"]["width"] = 721  # _swap_encoder(fail_on=721)이 이 입력에서 실패한다
                e.landmarks_json = json.dumps(payload)
            s.commit()
        before = _snapshot(c.app.state.db)

    _swap_encoder(monkeypatch, fail_on=721)
    with _restart(settings) as c:
        res = c.post("/admin/reindex", json={"modelVersion": NEW}).json()
        assert res["failed"] == 3
        assert res["switched"] is False
        assert res["templatesRebuilt"] == 0
        assert {f["userId"] for f in res["failures"]} == {"oh"}
        assert all("weights corrupted" in f["error"] for f in res["failures"])

        after = _snapshot(c.app.state.db)
        assert after == before  # 새 버전 행이 하나도 남지 않고, 활성 버전도 그대로
        assert json.loads(after["active"]) == OLD


def test_failed_same_version_reindex_keeps_auth_working(client, db, monkeypatch):
    """같은 버전 재색인이 중간에 실패해도 기존 템플릿으로 인증이 계속된다."""
    gesture = _enroll_users(client)
    before = _snapshot(db)
    calls = {"n": 0}
    original = encoder.embed_batch

    def flaky(items):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("OOM")
        return original(items)

    monkeypatch.setattr(encoder, "embed_batch", flaky)
    monkeypatch.setattr(encoder, "embed", lambda f: (_ for _ in ()).throw(RuntimeError("OOM")))
    res = client.post("/admin/reindex", json={"modelVersion": OLD}).json()
    assert res["failed"] > 0 and res["switched"] is False
    monkeypatch.undo()

    assert _snapshot(db) == before
    verify = post_json(client, "/verify", verify_body("kim", 0, gesture_id=GESTURE)).json()
    assert verify["passed"] is True and verify["gestureId"] == gesture


def test_corrupted_stored_payload_is_reported(client, db):
    _enroll_users(client)
    with db.session() as s:
        e = s.scalar(select(models.Enrollment).where(models.Enrollment.user_id == "lee"))
        e.landmarks_json = "{broken"
        bad_id = e.id
        s.commit()
    res = client.post("/admin/reindex", json={"modelVersion": OLD}).json()
    assert res["switched"] is False
    assert [f["enrollmentId"] for f in res["failures"]] == [bad_id]


def test_dry_run_writes_nothing(settings, monkeypatch):
    with TestClient(create_app(settings)) as c:
        _enroll_users(c)
        before = _snapshot(c.app.state.db)
    _swap_encoder(monkeypatch)
    with _restart(settings) as c:
        res = c.post("/admin/reindex", json={"modelVersion": NEW, "dryRun": True}).json()
        assert res["dryRun"] is True and res["switched"] is False
        assert res["templatesRebuilt"] == 4 and res["failed"] == 0
        assert _snapshot(c.app.state.db) == before


def test_reindex_refuses_without_threshold_for_target(client, db, monkeypatch):
    _enroll_users(client)
    monkeypatch.setattr(encoder, "MODEL_VERSION", NEW)  # 재시작 없이 버전만 바뀐 상황 → threshold 없음
    res = client.post("/admin/reindex", json={"modelVersion": NEW})
    assert res.status_code == 409
    assert res.json()["detail"]["reason"] == "no_active_threshold"


def test_reindex_same_version_is_idempotent(client, db):
    _enroll_users(client)
    before = _snapshot(db)
    res = client.post("/admin/reindex", json={"modelVersion": OLD}).json()
    assert res["switched"] is True and res["failed"] == 0
    after = _snapshot(db)
    assert after["embeddings"] == before["embeddings"]
    assert [t[:4] for t in after["templates"]] == [t[:4] for t in before["templates"]]

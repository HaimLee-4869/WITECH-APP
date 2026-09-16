"""5단계: POST /enroll + 템플릿 생성."""

from __future__ import annotations

import json

import numpy as np
import pytest
from sqlalchemy import select

from ai import encoder
from app import models, schemas
from app.services import template_service
from app.services.ai_gateway import to_ai_input
from tests.conftest import post_json
from tests.payloads import enroll_body, make_frames


def _count(db, model):
    with db.session() as s:
        return s.query(model).count()


def _expected_vectors(body):
    """백엔드와 같은 경로로 다시 계산한 등록 임베딩."""
    req = schemas.EnrollRequest.model_validate(body)
    return encoder.embed_batch([to_ai_input(req.camera, t.frames) for t in req.takes])


# --- centroid 재정규화 --------------------------------------------------------------

def test_build_centroid_is_renormalized():
    vectors = np.stack([_unit(1), _unit(2), _unit(3)])
    raw_mean = vectors.mean(axis=0)
    assert np.linalg.norm(raw_mean) < 0.9  # 평균만 하면 norm이 1이 아니다
    centroid = template_service.build_centroid(vectors)
    assert centroid.dtype == np.float32
    assert np.linalg.norm(centroid) == pytest.approx(1.0, abs=1e-6)
    assert np.allclose(centroid, raw_mean / np.linalg.norm(raw_mean), atol=1e-6)


def _unit(seed):
    v = np.random.default_rng(seed).normal(size=128).astype(np.float32)
    return v / np.linalg.norm(v)


def test_build_centroid_rejects_empty():
    with pytest.raises(ValueError):
        template_service.build_centroid(np.zeros((0, 128)))


def test_blob_roundtrip():
    v = _unit(7)
    blob = template_service.to_blob(v)
    assert len(blob) == 128 * 4
    assert np.array_equal(template_service.from_blob(blob), v)


# --- POST /enroll ---------------------------------------------------------------

def test_enroll_success(client, db, make_user):
    make_user()
    body = enroll_body()
    res = post_json(client, "/enroll", body)
    assert res.status_code == 200, res.text
    assert res.json() == {
        "enrolled": True, "userId": "kim", "gestureId": "G1",
        "takeCount": 3, "required": 3, "modelVersion": encoder.MODEL_VERSION,
    }
    assert _count(db, models.Enrollment) == 3
    assert _count(db, models.Embedding) == 3
    assert _count(db, models.Template) == 1


def test_enroll_stores_raw_landmarks_losslessly(client, db, make_user):
    make_user()
    body = enroll_body()
    body["takes"][0]["frames"][0]["extraField"] = "앱이 추가한 필드도 보존"
    post_json(client, "/enroll", body)
    with db.session() as s:
        rows = s.scalars(select(models.Enrollment).order_by(models.Enrollment.take_no)).all()
    for row, take in zip(rows, body["takes"]):
        stored = json.loads(row.landmarks_json)
        assert stored["camera"] == body["camera"]
        assert stored["frames"] == take["frames"]
        assert stored["takeNo"] == take["takeNo"]
        assert (row.camera_width, row.camera_height) == (720, 1280)
        assert row.nominal_fps == 30 and row.duration_ms == 2000
    # 앱 capturedAt(+09:00)은 UTC로 저장
    assert rows[0].captured_at.hour == 1


def test_enroll_template_is_renormalized_centroid(client, db, make_user):
    """저장된 템플릿 = 3개 임베딩 평균을 재정규화한 것. 이게 깨지면 조용히 틀린다."""
    make_user()
    body = enroll_body()
    post_json(client, "/enroll", body)
    vectors = _expected_vectors(body)
    with db.session() as s:
        tpl = s.scalar(select(models.Template))
        stored_embeddings = s.scalars(select(models.Embedding).order_by(models.Embedding.id)).all()
    centroid = template_service.from_blob(tpl.centroid)
    assert np.linalg.norm(centroid) == pytest.approx(1.0, abs=1e-6)
    assert np.linalg.norm(vectors.mean(axis=0)) < 0.9
    expected = vectors.mean(axis=0)
    expected /= np.linalg.norm(expected)
    assert np.allclose(centroid, expected, atol=1e-6)
    assert tpl.take_count == 3 and tpl.model_version == encoder.MODEL_VERSION
    for emb, vec in zip(stored_embeddings, vectors):
        assert emb.model_version == encoder.MODEL_VERSION
        # 배치 forward와 단건 forward는 마지막 자리에서 미세하게 다를 수 있다
        assert np.allclose(template_service.from_blob(emb.vector), vec, atol=1e-6)


def test_reenroll_replaces_existing(client, db, make_user):
    make_user()
    post_json(client, "/enroll", enroll_body(seeds=(0, 1, 2)))
    with db.session() as s:
        before = s.scalar(select(models.Template.centroid))
    res = post_json(client, "/enroll", enroll_body(seeds=(10, 11, 12)))
    assert res.status_code == 200
    assert _count(db, models.Enrollment) == 3
    assert _count(db, models.Embedding) == 3
    assert _count(db, models.Template) == 1
    with db.session() as s:
        assert s.scalar(select(models.Template.centroid)) != before


def test_multiple_gestures_have_separate_templates(client, db, make_user):
    make_user()
    assert post_json(client, "/enroll", enroll_body(gesture_id="G1")).status_code == 200
    assert post_json(client, "/enroll", enroll_body(gesture_id="G2", seeds=(5, 6, 7))).status_code == 200
    with db.session() as s:
        gestures = sorted(s.scalars(select(models.Template.gesture_id)).all())
    assert gestures == ["G1", "G2"]
    assert _count(db, models.Enrollment) == 6


def test_enroll_unknown_user(client):
    res = post_json(client, "/enroll", enroll_body(user_id="nobody"))
    assert res.status_code == 404
    assert res.json()["detail"]["reason"] == "user_not_found"


def test_enroll_unknown_gesture(client, make_user):
    make_user()
    res = post_json(client, "/enroll", enroll_body(gesture_id="G9"))
    assert res.status_code == 422
    assert res.json()["detail"]["reason"] == "unknown_gesture"


@pytest.mark.parametrize("take_nos", [[1, 2], [1, 2, 2], [1, 2, 4], [1, 2, 3, 4]])
def test_enroll_requires_all_takes(client, db, make_user, take_nos):
    make_user()
    body = enroll_body(seeds=range(len(take_nos)))
    for take, no in zip(body["takes"], take_nos):
        take["takeNo"] = no
    res = post_json(client, "/enroll", body)
    assert res.status_code == 422
    assert res.json()["detail"]["reason"] == "take_count_mismatch"
    assert _count(db, models.Enrollment) == 0


def test_enroll_required_takes_follow_app_config(client, db, make_user):
    from app.services import app_config_service as cfg

    make_user()
    with db.session() as s:
        cfg.set_value(s, cfg.ENROLLMENT_TAKES, 2)
        s.commit()
    res = post_json(client, "/enroll", enroll_body(seeds=(0, 1)))
    assert res.status_code == 200
    assert res.json()["required"] == 2


# --- 부분 등록 금지 -----------------------------------------------------------------

def test_partial_enrollment_forbidden(client, db, make_user):
    make_user()
    body = enroll_body()
    body["takes"][1]["frames"] = make_frames(1, n=5)  # take 2만 불량
    res = post_json(client, "/enroll", body)
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert detail["code"] == "invalid_sequence"
    assert detail["reason"] == "too_few_frames"
    assert detail["takeNo"] == 2
    for model in (models.Enrollment, models.Embedding, models.Template):
        assert _count(db, model) == 0


def test_failed_reenroll_keeps_previous_enrollment(client, db, make_user):
    make_user()
    post_json(client, "/enroll", enroll_body())
    with db.session() as s:
        before = s.scalar(select(models.Template.centroid))
    bad = enroll_body(seeds=(10, 11, 12))
    bad["takes"][2]["frames"][3]["lm"] = [[0.1, 0.2, 0.3]]
    assert post_json(client, "/enroll", bad).status_code == 422
    assert _count(db, models.Enrollment) == 3
    with db.session() as s:
        assert s.scalar(select(models.Template.centroid)) == before


def test_db_failure_mid_enroll_rolls_back(client, db, make_user, monkeypatch):
    """임베딩은 성공했는데 템플릿 저장에서 터지면 원본도 남지 않아야 한다."""
    make_user()

    def boom(*a, **kw):
        raise RuntimeError("disk full")

    monkeypatch.setattr(template_service, "upsert_template", boom)
    with pytest.raises(RuntimeError):
        post_json(client, "/enroll", enroll_body())
    assert _count(db, models.Enrollment) == 0
    assert _count(db, models.Embedding) == 0

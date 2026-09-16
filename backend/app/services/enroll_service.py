"""등록 로직 (명세 7장 POST /enroll).

1. 각 take 검증 → 하나라도 실패하면 전체 422 (부분 등록 금지)
2. enrollments에 랜드마크 원본 저장
3. embed_both_batch → user·gesture 임베딩 (한 번의 forward)
4. embeddings 저장 (kind별로 2배)
5. 각각 평균 → 재정규화 → templates 2개 저장

AI 검증(embed_batch)을 DB 쓰기보다 먼저 하고, 쓰기는 한 트랜잭션으로 묶는다.
그래서 어느 단계에서 실패해도 기존 등록분이 그대로 남는다.
"""

from __future__ import annotations

import json

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ai import encoder
from app.errors import invalid_request, not_found
from app.models import Embedding, Enrollment, Gesture, Template, User
from app.schemas import EnrollRequest, EnrollResponse
from app.services import app_config_service as cfg
from app.services import template_service
from app.services.ai_gateway import (
    InvalidSequenceError,
    embed_both_batch,
    invalid_sequence_error,
    to_ai_input,
)
from app.timeutil import to_utc_naive


def _check_takes(req: EnrollRequest, required: int) -> None:
    take_nos = sorted(t.take_no for t in req.takes)
    if take_nos != list(range(1, required + 1)):
        raise invalid_request(
            "take_count_mismatch",
            f"등록 동작을 {required}회 모두 촬영해주세요. (takeNo 1..{required})",
        )


def _embed_all(inputs: list[dict], take_nos: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """(user, gesture) 임베딩. 검증도 이 호출이 겸한다."""
    try:
        user_vectors, gesture_vectors = embed_both_batch(inputs)
    except InvalidSequenceError as exc:
        # 어느 take가 문제인지 찾아 앱에 알려준다
        for take_no, item in zip(take_nos, inputs):
            try:
                encoder.embed_both(item)
            except InvalidSequenceError as take_exc:
                raise invalid_sequence_error(take_exc, take_no=take_no) from exc
        raise invalid_sequence_error(exc) from exc
    expected = (len(inputs), encoder.EMBEDDING_DIM)
    user_vectors = np.asarray(user_vectors, dtype=np.float32)
    gesture_vectors = np.asarray(gesture_vectors, dtype=np.float32)
    if user_vectors.shape != expected or gesture_vectors.shape != expected:
        raise RuntimeError(
            f"embed_both_batch returned {user_vectors.shape} / {gesture_vectors.shape}"
        )
    return user_vectors, gesture_vectors


def enroll(session: Session, req: EnrollRequest, raw_body: dict) -> EnrollResponse:
    if session.get(User, req.user_id) is None:
        raise not_found("user_not_found", "등록되지 않은 사용자입니다.")
    if session.get(Gesture, req.gesture_id) is None:
        raise invalid_request("unknown_gesture", "알 수 없는 제스처입니다.")

    required = int(cfg.get_value(session, cfg.ENROLLMENT_TAKES))
    _check_takes(req, required)

    takes = sorted(req.takes, key=lambda t: t.take_no)
    raw_takes = {int(t["takeNo"]): t for t in raw_body["takes"]}
    inputs = [to_ai_input(req.camera, t.frames) for t in takes]

    # 1, 3. 검증 겸 임베딩. 여기서 실패하면 DB는 건드리지 않았다.
    user_vectors, gesture_vectors = _embed_all(inputs, [t.take_no for t in takes])
    model_version = encoder.MODEL_VERSION

    try:
        # 재등록: 같은 (user, gesture)의 기존 원본·캐시·템플릿을 대체
        old_ids = select(Enrollment.id).where(
            Enrollment.user_id == req.user_id, Enrollment.gesture_id == req.gesture_id
        )
        session.execute(delete(Embedding).where(Embedding.enrollment_id.in_(old_ids)))
        session.execute(
            delete(Enrollment).where(
                Enrollment.user_id == req.user_id, Enrollment.gesture_id == req.gesture_id
            )
        )
        session.execute(
            delete(Template).where(
                Template.user_id == req.user_id, Template.gesture_id == req.gesture_id
            )
        )

        # 2. 원본 저장 (앱이 보낸 JSON 그대로 + 재색인에 필요한 camera)
        rows = []
        for take in takes:
            stored = {
                "userId": raw_body.get("userId"),
                "gestureId": raw_body.get("gestureId"),
                "camera": raw_body.get("camera"),
                **raw_takes[take.take_no],
            }
            row = Enrollment(
                user_id=req.user_id,
                gesture_id=req.gesture_id,
                take_no=take.take_no,
                landmarks_json=json.dumps(stored, ensure_ascii=False),
                nominal_fps=take.nominal_fps,
                duration_ms=take.duration_ms,
                camera_width=req.camera.width,
                camera_height=req.camera.height,
                captured_at=to_utc_naive(take.captured_at),
            )
            session.add(row)
            rows.append(row)
        session.flush()

        # 4. 임베딩 캐시 (kind별로 저장)
        for kind, vectors in (("user", user_vectors), ("gesture", gesture_vectors)):
            for row, vec in zip(rows, vectors):
                session.add(
                    Embedding(
                        enrollment_id=row.id,
                        model_version=model_version,
                        kind=kind,
                        vector=template_service.to_blob(vec),
                    )
                )

        # 5. centroid 2개. 각각 평균 후 재정규화한다 (build_centroid 안에서).
        for kind, vectors in (("user", user_vectors), ("gesture", gesture_vectors)):
            template_service.upsert_template(
                session, req.user_id, req.gesture_id, model_version, vectors, kind=kind
            )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return EnrollResponse(
        enrolled=True,
        user_id=req.user_id,
        gesture_id=req.gesture_id,
        take_count=len(takes),
        required=required,
        model_version=model_version,
    )

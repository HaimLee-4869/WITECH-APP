"""재색인 (명세 7장 POST /admin/reindex).

인코더가 바뀌면 기존 임베딩은 다른 벡터 공간의 값이라 전부 무효다.
enrollments의 랜드마크 원본을 새 인코더에 다시 통과시켜 embeddings·templates를 만든다.

1단계 (읽기 + 임베딩): DB에 쓰지 않는다. 실패 건을 모은다.
2단계 (쓰기 + 전환): 실패가 0건일 때만, 한 트랜잭션으로 저장하고 활성 버전을 바꾼다.

그래서 중간에 실패하면 DB는 재색인 전과 완전히 같다. 쓰기 락도 2단계에서만 잡으므로
재색인 중에도 인증 로그 쓰기가 오래 막히지 않는다.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ai import encoder
from app.errors import ApiError
from app.models import Embedding, Enrollment
from app.schemas import ReindexFailure, ReindexRequest, ReindexResponse, SequencePayload
from app.services import app_config_service as cfg
from app.services import template_service, threshold_service
from app.services.ai_gateway import to_ai_input

log = logging.getLogger(__name__)


@dataclass
class _Row:
    enrollment_id: int
    user_id: str
    gesture_id: str
    landmarks_json: str


def _failure(row: _Row, error: Exception | str) -> ReindexFailure:
    return ReindexFailure(
        enrollment_id=row.enrollment_id, user_id=row.user_id, gesture_id=row.gesture_id,
        error=str(error)[:500],
    )


def _embed_group(rows: list[_Row]) -> tuple[np.ndarray | None, list[ReindexFailure]]:
    """(user, gesture) 한 묶음. 하나라도 실패하면 그 묶음의 템플릿은 만들 수 없다."""
    inputs, failures = [], []
    for row in rows:
        try:
            payload = SequencePayload.model_validate(json.loads(row.landmarks_json))
            inputs.append(to_ai_input(payload.camera, payload.frames))
        except Exception as exc:  # 저장된 원본이 깨진 경우
            failures.append(_failure(row, f"stored payload unreadable: {exc}"))
    if failures:
        return None, failures

    try:
        vectors = np.asarray(encoder.embed_batch(inputs), dtype=np.float32)
        if vectors.shape != (len(rows), encoder.EMBEDDING_DIM):
            raise RuntimeError(f"embed_batch returned shape {vectors.shape}")
        return vectors, []
    except Exception as batch_exc:
        # 어느 건이 문제인지 하나씩 찾는다
        for row, item in zip(rows, inputs):
            try:
                encoder.embed(item)
            except Exception as exc:
                failures.append(_failure(row, exc))
        if not failures:
            failures = [_failure(row, batch_exc) for row in rows]
        return None, failures


def reindex(session: Session, req: ReindexRequest) -> ReindexResponse:
    started = time.perf_counter()
    to_version = req.model_version
    if to_version != encoder.MODEL_VERSION:
        raise ApiError(
            400, "bad_request", "model_version_mismatch",
            f"로드된 인코더 버전은 {encoder.MODEL_VERSION}입니다. 요청한 버전({to_version})과 다릅니다.",
        )
    if threshold_service.get_active(session, to_version) is None:
        raise ApiError(
            409, "conflict", "no_active_threshold",
            f"{to_version}의 활성 threshold가 없습니다. 전환하면 인증이 불가능해지므로 중단합니다.",
        )
    from_version = cfg.get_active_model_version(session)

    # --- 1단계: 읽기 + 임베딩 (DB 쓰기 없음) ---
    rows = [
        _Row(e.id, e.user_id, e.gesture_id, e.landmarks_json)
        for e in session.scalars(
            select(Enrollment).order_by(Enrollment.user_id, Enrollment.gesture_id, Enrollment.take_no)
        )
    ]
    session.rollback()  # 읽기 트랜잭션을 닫는다

    groups: dict[tuple[str, str], list[_Row]] = defaultdict(list)
    for row in rows:
        groups[(row.user_id, row.gesture_id)].append(row)

    results: dict[tuple[str, str], np.ndarray] = {}
    failures: list[ReindexFailure] = []
    for key, group in groups.items():
        vectors, group_failures = _embed_group(group)
        if group_failures:
            failures.extend(group_failures)
        else:
            results[key] = vectors

    switched = False
    if not failures and not req.dry_run:
        # --- 2단계: 쓰기 + 전환 (한 트랜잭션) ---
        try:
            ids = [r.enrollment_id for r in rows]
            if ids:
                session.execute(
                    delete(Embedding).where(
                        Embedding.enrollment_id.in_(ids), Embedding.model_version == to_version
                    )
                )
            for key, vectors in results.items():
                for row, vec in zip(groups[key], vectors):
                    session.add(
                        Embedding(
                            enrollment_id=row.enrollment_id,
                            model_version=to_version,
                            vector=template_service.to_blob(vec),
                        )
                    )
                template_service.upsert_template(session, key[0], key[1], to_version, vectors)
            cfg.set_value(session, cfg.ACTIVE_MODEL_VERSION, to_version)  # 전부 성공한 뒤에만
            session.commit()
            switched = True
        except Exception:
            session.rollback()
            raise

    if failures:
        log.warning("reindex %s → %s: %d건 실패, 전환하지 않음", from_version, to_version, len(failures))

    return ReindexResponse(
        from_version=from_version,
        to_version=to_version,
        enrollments_processed=len(rows),
        templates_rebuilt=len(results) if not failures else 0,
        failed=len(failures),
        elapsed_ms=int(round((time.perf_counter() - started) * 1000)),
        dry_run=req.dry_run,
        switched=switched,
        failures=failures,
    )

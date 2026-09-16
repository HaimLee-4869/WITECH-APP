"""centroid 생성·재정규화, 벡터 직렬화.

⚠️ 임베딩 여러 개를 평균하면 norm이 1보다 작아진다. 재정규화를 빠뜨리면
유사도가 전부 조금씩 낮게 나오고 threshold가 어긋나는데, 에러는 나지 않는다.
centroid는 반드시 `build_centroid()`로만 만든다.
"""

from __future__ import annotations

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Template
from app.timeutil import utcnow

_DTYPE = np.dtype("<f4")  # float32 little-endian 고정


def build_centroid(vectors) -> np.ndarray:
    arr = np.asarray(vectors, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[0] == 0:
        raise ValueError(f"centroid needs a non-empty (N, dim) array, got shape {arr.shape}")
    template = np.mean(arr, axis=0)
    template /= np.linalg.norm(template) + 1e-12  # 재정규화 (명세 1장)
    return template.astype(np.float32)


def cosine_score(query: np.ndarray, template: np.ndarray) -> float:
    """둘 다 L2 정규화 상태이므로 내적이 곧 코사인 유사도."""
    return float(np.asarray(query, dtype=np.float32) @ np.asarray(template, dtype=np.float32))


def to_blob(vector) -> bytes:
    return np.asarray(vector, dtype=_DTYPE).tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    if len(blob) % _DTYPE.itemsize:
        raise ValueError(f"vector blob length {len(blob)} is not a multiple of 4")
    return np.frombuffer(blob, dtype=_DTYPE).astype(np.float32)


def upsert_template(
    session: Session,
    user_id: str,
    gesture_id: str,
    model_version: str,
    vectors,
    kind: str = "user",
) -> Template:
    """(user, gesture, model_version, kind) centroid를 만든다. kind는 user | gesture."""
    centroid = build_centroid(vectors)
    tpl = session.scalar(
        select(Template).where(
            Template.user_id == user_id,
            Template.gesture_id == gesture_id,
            Template.model_version == model_version,
            Template.kind == kind,
        )
    )
    if tpl is None:
        tpl = Template(
            user_id=user_id,
            gesture_id=gesture_id,
            model_version=model_version,
            kind=kind,
        )
        session.add(tpl)
    tpl.centroid = to_blob(centroid)
    tpl.take_count = len(vectors)
    tpl.updated_at = utcnow()
    return tpl


def get_template(
    session: Session,
    user_id: str,
    gesture_id: str,
    model_version: str,
    kind: str = "user",
) -> np.ndarray | None:
    blob = session.scalar(
        select(Template.centroid).where(
            Template.user_id == user_id,
            Template.gesture_id == gesture_id,
            Template.model_version == model_version,
            Template.kind == kind,
        )
    )
    return None if blob is None else from_blob(blob)

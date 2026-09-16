"""startup 기본 데이터. 이미 있는 값은 덮어쓰지 않는다.

시연용 사용자·이력은 여기가 아니라 scripts/seed_demo_data.py.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai import encoder
from app.models import AppConfig, Gesture, Threshold
from app.services import app_config_service as cfg

log = logging.getLogger(__name__)

DEFAULT_THRESHOLDS_PATH = Path(__file__).with_name("default_thresholds.json")
GESTURES = [(f"G{i}", f"제스처 {i}") for i in range(1, 6)]


def load_thresholds(
    session: Session, model_version: str, path: Path = DEFAULT_THRESHOLDS_PATH
) -> int:
    """thresholds 파일의 운영점을 model_version에 대해 넣는다. 이미 있으면 건너뛴다.

    defaultBasis만 활성. 넣은 행 수를 돌려준다.
    """
    exists = session.scalar(select(Threshold.id).where(Threshold.model_version == model_version))
    if exists is not None:
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("modelVersion") and data["modelVersion"] != model_version:
        log.warning(
            "%s는 %s용 값인데 %s에 넣는다. scripts/import_thresholds.py로 갱신했는지 확인할 것.",
            path.name, data["modelVersion"], model_version,
        )
    default_basis = data.get("defaultBasis", "default")
    rows = 0
    for point in data["operatingPoints"]:
        # dual-head: 운영점 하나가 user/gesture 두 행이 된다.
        for gate in ("user", "gesture"):
            session.add(
                Threshold(
                    scheme=data.get("scheme", "global"),
                    gate=gate,
                    gesture_id=None,
                    model_version=model_version,
                    value=float(point[f"{gate}Threshold"]),
                    far=point.get(f"{gate}Far"),
                    frr=point.get(f"{gate}Frr"),
                    basis=point["basis"],
                    is_active=point["basis"] == default_basis,
                )
            )
            rows += 1
    log.info("thresholds %d행을 model_version=%s 로 추가 (%s)", rows, model_version, path.name)
    return rows


def ensure_seed_data(session: Session) -> None:
    for gid, label in GESTURES:
        if session.get(Gesture, gid) is None:
            session.add(Gesture(id=gid, label=label))

    for key, value in cfg.DEFAULTS.items():
        if session.get(AppConfig, key) is None:
            cfg.set_value(session, key, value)

    active = cfg.get_active_model_version(session)
    if active is None:
        cfg.set_value(session, cfg.ACTIVE_MODEL_VERSION, encoder.MODEL_VERSION)
        active = encoder.MODEL_VERSION
    elif active != encoder.MODEL_VERSION:
        log.warning(
            "로드된 인코더(%s)와 활성 모델 버전(%s)이 다르다. POST /admin/reindex 필요.",
            encoder.MODEL_VERSION, active,
        )

    # 로드된 인코더 버전의 threshold가 없으면 기본 운영점을 넣는다 (재색인 대상 버전 대비).
    load_thresholds(session, encoder.MODEL_VERSION)
    session.commit()

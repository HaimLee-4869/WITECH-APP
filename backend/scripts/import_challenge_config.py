"""challenge_response/configs/challenge_config.json → DB app_config['challenge'].

    cd backend
    python scripts/import_challenge_config.py --dry-run
    python scripts/import_challenge_config.py

04_derive_thresholds.py가 영상에서 임계값을 다시 뽑으면(자유 제스처 데이터 등)
이 스크립트로 서버에 반영한다. 앱은 GET /config로 받아 쓰므로 앱 재배포가 필요 없다.
서버 재시작도 필요 없다 (요청마다 DB를 읽는다).

키 대응은 **명시적으로** 적는다. 자동 snake→camel 변환을 쓰면 AI팀 쪽에서 키 이름이
바뀌었을 때 조용히 빈 설정이 들어간다. 여기서는 없는 키를 만나면 즉시 실패한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy.exc import OperationalError  # noqa: E402

from app.config import Settings  # noqa: E402
from app.database import Database  # noqa: E402
from app.schemas import ChallengeConfigOut  # noqa: E402
from app.services import app_config_service as cfg  # noqa: E402

DEFAULT_SOURCE = BACKEND_DIR.parent / "challenge_response" / "configs" / "challenge_config.json"

# (원본 경로, 대상 경로). 원본에 없으면 실패한다.
SCALARS: tuple[tuple[str, str], ...] = (
    ("angle_space", "angleSpace"),
    ("coordinate_frame", "coordinateFrame"),
    ("frame_reference_fps", "frameReferenceFps"),
    ("shape_hold_frames", "shapeHoldFrames"),
    ("shape_confidence_margin_deg", "shapeConfidenceMarginDeg"),
    ("escape_frames", "escapeFrames"),
    ("finger_extended_angle.thumb", "fingerExtendedAngle.thumb"),
    ("finger_extended_angle.others", "fingerExtendedAngle.others"),
    ("movement.window_ms", "movement.windowMs"),
    ("movement.min_displacement_ratio", "movement.minDisplacementRatio"),
    ("movement.axis_dominance_ratio", "movement.axisDominanceRatio"),
    ("movement.max_duration_ms", "movement.maxDurationMs"),
    ("movement.rest_displacement_ratio", "movement.restDisplacementRatio"),
    ("movement.direction_map", "movement.directionMap"),
    ("timing.per_action_timeout_ms", "timing.perActionTimeoutMs"),
    ("timing.total_timeout_ms", "timing.totalTimeoutMs"),
    ("timing.max_retries", "timing.maxRetries"),
    ("tracking.max_lost_frames", "tracking.maxLostFrames"),
    ("tracking.min_detection_score", "tracking.minDetectionScore"),
)

# null이 '게이트를 끈다'는 뜻이라 없어도 되는 값들.
OPTIONAL: tuple[tuple[str, str], ...] = (
    ("fist_max_tip_wrist_ratio", "fistMaxTipWristRatio"),
    ("shape_confidence_min", "shapeConfidenceMin"),
)


def _get(data: dict, path: str) -> Any:
    node: Any = data
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(path)
        node = node[part]
    return node


def _set(data: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    node = data
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def convert(source: dict, previous: dict) -> dict:
    """원본 config → 서버가 저장할 camelCase 설정.

    단계 구성(steps)과 풀(shapePool/movePool), ruleVersion은 원본에 없다.
    판정 임계값이 아니라 프로토콜 정의라서 challenge_response 쪽 코드 상수이기 때문이다.
    기존 DB 값(없으면 번들 기본값)을 그대로 이어받는다.
    """
    out: dict[str, Any] = {
        "_note": f"scripts/import_challenge_config.py가 {DEFAULT_SOURCE.name}에서 넣음",
        "ruleVersion": previous.get("ruleVersion", ""),
        "steps": previous["steps"],
        "shapePool": previous["shapePool"],
        "movePool": previous["movePool"],
        # 연속성 임계값은 앱 세션에서 재는 값이라 안티스푸핑 원본에 없다.
        "continuity": previous.get("continuity", {"enabled": False}),
    }
    missing = []
    for src, dst in SCALARS:
        try:
            _set(out, dst, _get(source, src))
        except KeyError:
            missing.append(src)
    if missing:
        raise SystemExit(
            f"원본에 없는 키: {missing}\n"
            "AI팀/안티스푸핑 쪽에서 키 이름이 바뀌었을 수 있다. "
            "SCALARS 표를 확인하고 고칠 것 (조용히 넘기지 않는다)."
        )
    for src, dst in OPTIONAL:
        _set(out, dst, source.get(src))

    # 원본(challenge_response)에 없는 앱 운영값은 기존 값을 이어받는다.
    # 판정 임계값이 아니라 앱이 프레임을 다루는 방식이라 도출 대상이 아니다.
    tracking = previous.get("tracking", {})
    for key in ("frameStaleFactor", "frameStaleMinMs", "frameStaleMaxMs"):
        if key in tracking:
            _set(out, f"tracking.{key}", tracking[key])
    timing = previous.get("timing", {})
    for key in ("waitHandReadyMs", "waitHandTimeoutMs", "stepPrepareMs", "stepResultHoldMs"):
        if key in timing:
            _set(out, f"timing.{key}", timing[key])
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Challenge 설정을 DB에 넣는다")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--dry-run", action="store_true", help="저장하지 않고 결과만 출력")
    args = parser.parse_args(argv)

    if not args.source.exists():
        raise SystemExit(f"원본이 없다: {args.source}")
    source = json.loads(args.source.read_text(encoding="utf-8"))

    settings = Settings()
    if args.database_url:
        settings.database_url = args.database_url
    database = Database(settings.database_url)

    with database.session() as session:
        # 서버를 한 번도 안 띄운 DB에는 app_config 테이블이 없다. 그때는 번들
        # 기본값을 기준으로 비교만 한다(저장은 서버가 스키마를 만든 뒤에 된다).
        try:
            previous = cfg.get_challenge_config(session)
        except OperationalError:
            if not args.dry_run:
                raise SystemExit(
                    "DB에 스키마가 없다. 서버를 한 번 띄워 마이그레이션을 돌린 뒤 다시 실행할 것."
                )
            print("(DB에 스키마가 없어 번들 기본값과 비교한다)")
            previous = cfg.default_challenge_config()
        converted = convert(source, previous)
        validated = ChallengeConfigOut.model_validate(converted)

        changed = [
            (path, before, after)
            for path, before, after in _diff(previous, converted)
        ]
        if not changed:
            print("바뀐 값 없음")
        for path, before, after in changed:
            print(f"  {path}: {before} → {after}")

        if args.dry_run:
            print("\n--dry-run: 저장하지 않았다")
        else:
            cfg.set_value(session, cfg.CHALLENGE, converted)
            session.commit()
            print(f"\n저장 완료 → {settings.database_url}")

    steps = validated.steps.num_shapes + validated.steps.num_moves
    print(f"단계 {steps}개 (손 모양 {validated.steps.num_shapes} + 이동 {validated.steps.num_moves}), "
          f"규칙 {validated.rule_version or '(미지정)'}")
    print("앱은 GET /config로 받는다. 서버 재시작 불필요.")
    return 0


def _diff(before: dict, after: dict, prefix: str = ""):
    for key, new in after.items():
        if key.startswith("_"):
            continue
        old = before.get(key)
        path = f"{prefix}{key}"
        if isinstance(new, dict) and isinstance(old, dict):
            yield from _diff(old, new, f"{path}.")
        elif old != new:
            yield path, old, new


if __name__ == "__main__":
    raise SystemExit(main())

"""시연용 데이터 생성 (명세 9장). 관리자 화면 표·차트가 비어 있지 않게 한다.

    cd backend
    python scripts/seed_demo_data.py            # 없으면 생성, 있으면 건너뜀
    python scripts/seed_demo_data.py --reset    # 데모 사용자 ID(hong, kim, ...)의 데이터를 지우고 다시 생성

- 사용자 6명 (홍길동/김길동/오박사/둘리/또치/고길동)
- 제스처 G1~G5, threshold 3종(far1 활성), app_config 기본값 (startup 시드와 동일)
- 최근 5개월 auth_logs

⚠️ 생성되는 인증 이력은 가짜다. 실제 시도와 구분할 수 있게 landmarks_json을 비워 둔다
   (AI팀에 추가 학습 데이터로 넘길 때 landmarks_json이 NULL인 행은 제외).
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import delete, select  # noqa: E402

from ai import encoder  # noqa: E402
from app.config import Settings  # noqa: E402
from app.database import Database  # noqa: E402
from app.migrations import upgrade_to_head  # noqa: E402
from app.models import AuthLog, Embedding, Enrollment, Template, User  # noqa: E402
from app.seed import ensure_seed_data  # noqa: E402
from app.services import app_config_service as cfg  # noqa: E402
from app.services import threshold_service  # noqa: E402

DEMO_USERS = [
    ("hong", "홍길동", "개발팀"),
    ("kim", "김길동", "인사팀"),
    ("oh", "오박사", "영업팀"),
    ("dooly", "둘리", "개발팀"),
    ("ddochi", "또치", "인사팀"),
    ("go", "고길동", "영업팀"),
]
GESTURES = ["G1", "G2", "G3", "G4", "G5"]
KST = timezone(timedelta(hours=9))


def _month_start_utc(now_utc: datetime, months_back: int) -> datetime:
    local = now_utc.astimezone(KST)
    index = local.year * 12 + (local.month - 1) - months_back
    start = datetime(index // 12, index % 12 + 1, 1, tzinfo=KST)
    return start.astimezone(timezone.utc)


def _fake_log(rng: random.Random, user_id: str, when: datetime, threshold: float, version: str) -> AuthLog:
    claimed = rng.choice(GESTURES)
    roll = rng.random()
    predicted, score, reason = claimed, None, None
    if roll < 0.78:                         # 통과
        score = rng.uniform(threshold + 0.01, 0.95)
    elif roll < 0.92:                       # 유사도 미달
        score = rng.uniform(0.15, threshold - 0.01)
        reason = "below_threshold"
    elif roll < 0.97:                       # 제스처 오분류
        predicted = rng.choice([g for g in GESTURES if g != claimed])
        reason = "gesture_mismatch"
    else:                                   # 손 인식 실패
        predicted = None
        reason = "invalid_input"
    return AuthLog(
        user_id=user_id,
        claimed_gesture_id=claimed,
        predicted_gesture_id=predicted,
        gesture_confidence=None if predicted is None else round(rng.uniform(0.6, 0.99), 3),
        score=None if score is None else round(score, 6),
        threshold=threshold,
        passed=reason is None,
        fail_reason=reason,
        auth_model_version=version,
        gesture_model_version=encoder.GESTURE_MODEL_VERSION,
        landmarks_json=None,  # 가짜 데이터 표시
        latency_ms=rng.randint(25, 140),
        created_at=when.replace(tzinfo=None),
    )


def _delete_demo_users(session) -> None:
    ids = [u[0] for u in DEMO_USERS]
    enrollment_ids = select(Enrollment.id).where(Enrollment.user_id.in_(ids))
    session.execute(delete(Embedding).where(Embedding.enrollment_id.in_(enrollment_ids)))
    for model in (Enrollment, Template, AuthLog):
        session.execute(delete(model).where(model.user_id.in_(ids)))
    session.execute(delete(User).where(User.id.in_(ids)))
    session.commit()


def seed(database_url: str, reset: bool = False, months: int = 5, seed_value: int = 42,
         now_utc: datetime | None = None) -> dict:
    upgrade_to_head(database_url)
    db = Database(database_url)
    rng = random.Random(seed_value)
    now_utc = now_utc or datetime.now(timezone.utc)
    try:
        with db.session() as session:
            ensure_seed_data(session)
            if reset:
                _delete_demo_users(session)
            if session.get(User, DEMO_USERS[0][0]) is not None:
                return {"skipped": True, "users": 0, "logs": 0}

            version = cfg.get_active_model_version(session)
            active = threshold_service.get_active(session, version)
            if active is None:
                raise SystemExit(f"{version}의 활성 threshold가 없습니다.")
            threshold = active.value

            start = _month_start_utc(now_utc, months - 1)
            for i, (uid, name, dept) in enumerate(DEMO_USERS):
                session.add(User(id=uid, name=name, department=dept,
                                 created_at=(start - timedelta(days=7 - i)).replace(tzinfo=None)))
            session.flush()  # 관계 매핑이 없어 INSERT 순서가 보장되지 않는다 (FK)

            logs = 0
            for m in range(months - 1, -1, -1):
                month_start = _month_start_utc(now_utc, m)
                month_end = min(_month_start_utc(now_utc, m - 1), now_utc) if m > 0 else now_utc
                span = (month_end - month_start).total_seconds()
                count = rng.randint(35, 70) if m > 0 else max(8, int(rng.randint(35, 70) * span / (30 * 86400)))
                for _ in range(count):
                    when = month_start + timedelta(seconds=rng.uniform(0, span))
                    session.add(_fake_log(rng, rng.choice(DEMO_USERS)[0], when, threshold, version))
                    logs += 1
            session.commit()
            return {"skipped": False, "users": len(DEMO_USERS), "logs": logs}
    finally:
        db.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=None, help="기본: DATABASE_URL 환경변수 / .env")
    parser.add_argument("--reset", action="store_true", help="데모 사용자와 그 데이터를 지우고 다시 생성")
    parser.add_argument("--months", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    url = args.database_url or Settings().database_url
    result = seed(url, reset=args.reset, months=args.months, seed_value=args.seed)
    if result["skipped"]:
        print("데모 사용자가 이미 있어 건너뜀 (--reset으로 재생성)")
    else:
        print(f"사용자 {result['users']}명, 인증 이력 {result['logs']}건 생성 → {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

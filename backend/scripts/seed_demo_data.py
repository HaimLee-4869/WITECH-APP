"""시연용 사용자 생성 (명세 9장).

    cd backend
    python scripts/seed_demo_data.py            # 없으면 생성, 있으면 건너뜀
    python scripts/seed_demo_data.py --reset    # 팀 사용자 ID의 데이터를 지우고 다시 생성

- 팀원 5명
- 제스처 G1~G5, threshold(기본 운영점 활성), app_config 기본값 (startup 시드와 동일)

**인증 이력은 만들지 않는다.** 예전에는 관리자 화면 표·차트를 채우려고 가짜 이력을
넣었지만, 실제 테스트로 쌓인 것과 섞이면 화면 숫자를 믿을 수 없다. 화면이 비어 보이는
편이 정확하다. 이력은 앱으로 실제 인증을 해야 쌓인다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import delete, select  # noqa: E402

from app.config import Settings  # noqa: E402
from app.database import Database  # noqa: E402
from app.migrations import upgrade_to_head  # noqa: E402
from app.models import AuthLog, Embedding, Enrollment, Template, User  # noqa: E402
from app.seed import ensure_seed_data  # noqa: E402
from app.timeutil import utcnow  # noqa: E402

# (id, 이름, 부서). id는 앱이 요청에 싣는 값이고 이름은 화면 표시용이다.
TEAM_USERS = [
    ("geonju", "김건주", "개발팀"),
    ("taerin", "김태린", "AI팀"),
    ("seungyeon", "승연", "AI팀"),
    ("hyemin", "황혜민", "개발팀"),
    ("eunjung", "이은정", "개발팀"),
]


def _delete_team_users(session) -> None:
    """팀 사용자와 그들의 등록·임베딩·템플릿·인증 이력을 지운다.

    --reset 전용. 여기 나열된 ID만 지우므로 다른 사용자 데이터는 남는다.
    """
    ids = [u[0] for u in TEAM_USERS]
    enrollment_ids = select(Enrollment.id).where(Enrollment.user_id.in_(ids))
    session.execute(delete(Embedding).where(Embedding.enrollment_id.in_(enrollment_ids)))
    for model in (Enrollment, Template, AuthLog):
        session.execute(delete(model).where(model.user_id.in_(ids)))
    session.execute(delete(User).where(User.id.in_(ids)))
    session.commit()


def seed(database_url: str, reset: bool = False) -> dict:
    upgrade_to_head(database_url)
    db = Database(database_url)
    try:
        with db.session() as session:
            ensure_seed_data(session)
            if reset:
                _delete_team_users(session)

            created = 0
            now = utcnow()
            for uid, name, dept in TEAM_USERS:
                if session.get(User, uid) is not None:
                    continue  # 이미 있으면 이름·부서를 덮어쓰지 않는다
                session.add(User(id=uid, name=name, department=dept, created_at=now))
                created += 1
            session.commit()

            present = session.scalars(
                select(User.id).where(User.id.in_([u[0] for u in TEAM_USERS]))
            ).all()
            return {"created": created, "present": sorted(present)}
    finally:
        db.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--database-url", default=None, help="기본: DATABASE_URL 환경변수 / .env")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="팀 사용자와 그 등록·이력을 지우고 다시 생성",
    )
    args = parser.parse_args(argv)

    url = args.database_url or Settings().database_url
    result = seed(url, reset=args.reset)
    print(f"사용자 {len(result['present'])}명 (신규 {result['created']}명) → {url}")
    for uid, name, dept in TEAM_USERS:
        mark = "+" if uid in result["present"] else "!"
        print(f"  {mark} {uid:10} {name:5} {dept}")
    print("인증 이력은 만들지 않는다. 앱으로 실제 인증해야 쌓인다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

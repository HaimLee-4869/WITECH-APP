"""등록 데이터(원본·임베딩·템플릿)를 지운다. 사용자와 인증 이력은 남긴다.

    cd backend
    python scripts/clear_enrollments.py --dry-run          # 무엇이 지워질지만 본다
    python scripts/clear_enrollments.py                    # 전체 삭제
    python scripts/clear_enrollments.py --user eunjung     # 한 사람만
    python scripts/clear_enrollments.py --gesture G5       # 한 제스처만

**언제 쓰나.** 등록과 인증의 조건이 달라져 기존 템플릿이 무효가 됐을 때.

- `captureDurationMs`를 바꿨을 때 (촬영 길이는 AI 모델의 입력 feature다)
- 카메라·전처리 조건이 바뀌었을 때

인코더 교체는 여기가 아니라 `POST /admin/reindex`다. 재색인은 저장된 원본을 다시
임베딩하므로 재등록이 필요 없다. 이 스크립트는 **원본 자체가 못 쓰게 됐을 때** 쓴다.

서버를 멈추지 않아도 된다. 백엔드는 요청마다 DB에서 템플릿을 읽으므로 캐시가 없다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import delete, func, select  # noqa: E402

from app.config import Settings  # noqa: E402
from app.database import Database  # noqa: E402
from app.models import Embedding, Enrollment, Template  # noqa: E402


def clear(database_url: str, user_id: str | None = None, gesture_id: str | None = None,
          dry_run: bool = False) -> dict:
    db = Database(database_url)
    try:
        with db.session() as session:
            filters = []
            if user_id:
                filters.append(Enrollment.user_id == user_id)
            if gesture_id:
                filters.append(Enrollment.gesture_id == gesture_id)

            rows = session.execute(
                select(Enrollment.user_id, Enrollment.gesture_id, func.count(Enrollment.id))
                .where(*filters)
                .group_by(Enrollment.user_id, Enrollment.gesture_id)
                .order_by(Enrollment.user_id, Enrollment.gesture_id)
            ).all()

            template_filters = []
            if user_id:
                template_filters.append(Template.user_id == user_id)
            if gesture_id:
                template_filters.append(Template.gesture_id == gesture_id)
            templates = session.scalar(
                select(func.count(Template.id)).where(*template_filters)
            ) or 0

            enrollment_ids = select(Enrollment.id).where(*filters)
            embeddings = session.scalar(
                select(func.count(Embedding.id)).where(Embedding.enrollment_id.in_(enrollment_ids))
            ) or 0

            result = {
                "groups": [(u, g, int(n)) for u, g, n in rows],
                "enrollments": sum(int(n) for _, _, n in rows),
                "embeddings": int(embeddings),
                "templates": int(templates),
                "dry_run": dry_run,
            }
            if dry_run:
                return result

            session.execute(
                delete(Embedding).where(Embedding.enrollment_id.in_(enrollment_ids))
            )
            session.execute(delete(Enrollment).where(*filters))
            session.execute(delete(Template).where(*template_filters))
            session.commit()
            return result
    finally:
        db.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--database-url", default=None, help="기본: DATABASE_URL 환경변수 / .env")
    parser.add_argument("--user", default=None, help="이 사용자만")
    parser.add_argument("--gesture", default=None, help="이 제스처만")
    parser.add_argument("--dry-run", action="store_true", help="지우지 않고 대상만 출력")
    args = parser.parse_args(argv)

    url = args.database_url or Settings().database_url
    result = clear(url, user_id=args.user, gesture_id=args.gesture, dry_run=args.dry_run)

    head = "지울 대상" if args.dry_run else "삭제함"
    print(f"{head}: 원본 {result['enrollments']}건, 임베딩 {result['embeddings']}건, "
          f"템플릿 {result['templates']}건 → {url}")
    for user, gesture, count in result["groups"]:
        print(f"  {user:12} {gesture:4} 원본 {count}건")
    if not result["groups"]:
        print("  (대상 없음)")
    if not args.dry_run and result["enrollments"]:
        print("사용자와 인증 이력은 남아 있다. 앱에서 다시 등록하면 새 조건으로 만들어진다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

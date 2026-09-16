"""dual-head(v1.1.1): 임베딩·템플릿 kind, threshold gate, 인증 로그 제스처 점수

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-17

dual-head는 한 번의 촬영에서 user·gesture 임베딩을 각각 낸다. 그래서
  embeddings  (enrollment_id, model_version) → (enrollment_id, model_version, kind)
  templates   (user_id, gesture_id, model_version) → (..., kind)
로 유일 키가 늘어난다. **옛 유일 키가 남아 있으면 같은 enrollment에 user/gesture 두 행을
넣을 수 없으므로**, SQLite에서 제약을 확실히 갈아 끼우려고 `copy_from`으로 테이블을
다시 만든다(자동 생성본은 반영된 제약을 그대로 옮겨 옛 제약이 남는다).

auth_logs는 컬럼 추가만 한다. 기존 행의 gesture_score/threshold는 NULL로 남는다
(v1.0.0 시절 기록이라 제스처 관문이 없었다는 뜻이다).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

metadata = sa.MetaData()

# 0001 시점의 테이블 정의에서 **옛 UNIQUE 제약만 뺀 것**. copy_from에 넘겨
# 재생성될 테이블의 출발점으로 쓴다.
embeddings_without_uc = sa.Table(
    "embeddings",
    metadata,
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("enrollment_id", sa.Integer(), nullable=False),
    sa.Column("model_version", sa.String(), nullable=False),
    sa.Column("vector", sa.LargeBinary(), nullable=False),
    sa.Column("created_at", sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(["enrollment_id"], ["enrollments.id"], ondelete="CASCADE"),
)

templates_without_uc = sa.Table(
    "templates",
    metadata,
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("user_id", sa.String(), nullable=False),
    sa.Column("gesture_id", sa.String(), nullable=False),
    sa.Column("model_version", sa.String(), nullable=False),
    sa.Column("centroid", sa.LargeBinary(), nullable=False),
    sa.Column("take_count", sa.Integer(), nullable=True),
    sa.Column("updated_at", sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(["gesture_id"], ["gestures.id"]),
    sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
)


def upgrade() -> None:
    with op.batch_alter_table(
        "embeddings", copy_from=embeddings_without_uc, recreate="always"
    ) as batch_op:
        batch_op.add_column(
            sa.Column("kind", sa.String(), server_default="user", nullable=False)
        )
        batch_op.create_unique_constraint(
            "uq_embeddings_enrollment_version_kind",
            ["enrollment_id", "model_version", "kind"],
        )
        batch_op.create_index(
            "ix_embeddings_enrollment_id", ["enrollment_id"], unique=False
        )

    with op.batch_alter_table(
        "templates", copy_from=templates_without_uc, recreate="always"
    ) as batch_op:
        batch_op.add_column(
            sa.Column("kind", sa.String(), server_default="user", nullable=False)
        )
        batch_op.create_unique_constraint(
            "uq_templates_user_gesture_version_kind",
            ["user_id", "gesture_id", "model_version", "kind"],
        )
        batch_op.create_index("ix_templates_user_id", ["user_id"], unique=False)

    with op.batch_alter_table("thresholds", schema=None) as batch_op:
        # 어느 관문의 임계값인지. 기존 행은 user 관문으로 본다.
        batch_op.add_column(
            sa.Column("gate", sa.String(), server_default="user", nullable=False)
        )

    with op.batch_alter_table("auth_logs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("gesture_score", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("gesture_threshold", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("auth_logs", schema=None) as batch_op:
        batch_op.drop_column("gesture_threshold")
        batch_op.drop_column("gesture_score")

    with op.batch_alter_table("thresholds", schema=None) as batch_op:
        batch_op.drop_column("gate")

    # kind가 사라지면 user/gesture 행이 옛 유일 키와 충돌한다. 되돌리기 전에
    # gesture 행을 먼저 지운다 (어차피 dual-head 이전 코드는 쓰지 않는다).
    op.execute("DELETE FROM templates WHERE kind = 'gesture'")
    op.execute("DELETE FROM embeddings WHERE kind = 'gesture'")

    with op.batch_alter_table("templates", schema=None) as batch_op:
        batch_op.drop_constraint("uq_templates_user_gesture_version_kind", type_="unique")
        batch_op.drop_column("kind")
        batch_op.create_unique_constraint(
            "uq_templates_user_gesture_version", ["user_id", "gesture_id", "model_version"]
        )

    with op.batch_alter_table("embeddings", schema=None) as batch_op:
        batch_op.drop_constraint("uq_embeddings_enrollment_version_kind", type_="unique")
        batch_op.drop_column("kind")
        batch_op.create_unique_constraint(
            "uq_embeddings_enrollment_version", ["enrollment_id", "model_version"]
        )

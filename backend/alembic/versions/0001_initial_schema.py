"""초기 스키마 (명세 6장)

Revision ID: 0001
Revises: 
Create Date: 2026-09-16 05:16:44.940006
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('app_config',
    sa.Column('key', sa.String(), nullable=False),
    sa.Column('value', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('gestures',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('label', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('users',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('department', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('auth_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('claimed_gesture_id', sa.String(), nullable=True),
    sa.Column('predicted_gesture_id', sa.String(), nullable=True),
    sa.Column('gesture_confidence', sa.Float(), nullable=True),
    sa.Column('score', sa.Float(), nullable=True),
    sa.Column('threshold', sa.Float(), nullable=True),
    sa.Column('passed', sa.Boolean(), nullable=True),
    sa.Column('fail_reason', sa.String(), nullable=True),
    sa.Column('auth_model_version', sa.String(), nullable=True),
    sa.Column('gesture_model_version', sa.String(), nullable=True),
    sa.Column('landmarks_json', sa.Text(), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('auth_logs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_auth_logs_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_auth_logs_user_id'), ['user_id'], unique=False)

    op.create_table('enrollments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('gesture_id', sa.String(), nullable=False),
    sa.Column('take_no', sa.Integer(), nullable=False),
    sa.Column('landmarks_json', sa.Text(), nullable=False),
    sa.Column('nominal_fps', sa.Float(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('camera_width', sa.Integer(), nullable=False),
    sa.Column('camera_height', sa.Integer(), nullable=False),
    sa.Column('captured_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['gesture_id'], ['gestures.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'gesture_id', 'take_no')
    )
    with op.batch_alter_table('enrollments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_enrollments_user_id'), ['user_id'], unique=False)

    op.create_table('templates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('gesture_id', sa.String(), nullable=False),
    sa.Column('model_version', sa.String(), nullable=False),
    sa.Column('centroid', sa.LargeBinary(), nullable=False),
    sa.Column('take_count', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['gesture_id'], ['gestures.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'gesture_id', 'model_version')
    )
    with op.batch_alter_table('templates', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_templates_user_id'), ['user_id'], unique=False)

    op.create_table('thresholds',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('scheme', sa.String(), nullable=False),
    sa.Column('gesture_id', sa.String(), nullable=True),
    sa.Column('model_version', sa.String(), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('far', sa.Float(), nullable=True),
    sa.Column('frr', sa.Float(), nullable=True),
    sa.Column('basis', sa.String(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['gesture_id'], ['gestures.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('embeddings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('enrollment_id', sa.Integer(), nullable=False),
    sa.Column('model_version', sa.String(), nullable=False),
    sa.Column('vector', sa.LargeBinary(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['enrollment_id'], ['enrollments.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('enrollment_id', 'model_version')
    )
    with op.batch_alter_table('embeddings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_embeddings_enrollment_id'), ['enrollment_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('embeddings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_embeddings_enrollment_id'))

    op.drop_table('embeddings')
    op.drop_table('thresholds')
    with op.batch_alter_table('templates', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_templates_user_id'))

    op.drop_table('templates')
    with op.batch_alter_table('enrollments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_enrollments_user_id'))

    op.drop_table('enrollments')
    with op.batch_alter_table('auth_logs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_auth_logs_user_id'))
        batch_op.drop_index(batch_op.f('ix_auth_logs_created_at'))

    op.drop_table('auth_logs')
    op.drop_table('users')
    op.drop_table('gestures')
    op.drop_table('app_config')

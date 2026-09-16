"""SQLAlchemy 모델 (명세 6장).

enrollments  : 랜드마크 원본. 진실의 원천. 영구 보관.
embeddings   : enrollments에서 파생된 캐시. model_version × kind로 재생성 가능.
templates    : embeddings의 centroid. **재정규화된 상태로** 저장.

dual-head(v1.1.1)부터 임베딩이 두 종류다 (`kind`):
  user    : 누구인지. threshold Tu와 비교.
  gesture : 무슨 동작인지. threshold Tg와 비교.
인증은 두 관문을 모두 넘어야 통과한다.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.timeutil import utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    department: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Gesture(Base):
    __tablename__ = "gestures"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # G1 ~ G5
    label: Mapped[str | None] = mapped_column(String)


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("user_id", "gesture_id", "take_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    gesture_id: Mapped[str] = mapped_column(ForeignKey("gestures.id"), nullable=False)
    take_no: Mapped[int] = mapped_column(Integer, nullable=False)
    # 앱이 보낸 raw payload 전체. 가공·압축하지 않는다.
    landmarks_json: Mapped[str] = mapped_column(Text, nullable=False)
    nominal_fps: Mapped[float | None] = mapped_column(Float)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    camera_width: Mapped[int] = mapped_column(Integer, nullable=False)
    camera_height: Mapped[int] = mapped_column(Integer, nullable=False)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Embedding(Base):
    __tablename__ = "embeddings"
    __table_args__ = (UniqueConstraint("enrollment_id", "model_version", "kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enrollment_id: Mapped[int] = mapped_column(
        ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    # user | gesture (dual-head)
    kind: Mapped[str] = mapped_column(String, nullable=False, server_default="user")
    vector: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)  # float32 LE x128
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Template(Base):
    __tablename__ = "templates"
    __table_args__ = (
        UniqueConstraint("user_id", "gesture_id", "model_version", "kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    gesture_id: Mapped[str] = mapped_column(ForeignKey("gestures.id"), nullable=False)
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    # user | gesture. 한 (user, gesture)에 두 행이 생긴다.
    kind: Mapped[str] = mapped_column(String, nullable=False, server_default="user")
    centroid: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)  # 재정규화 완료
    take_count: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Threshold(Base):
    __tablename__ = "thresholds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scheme: Mapped[str] = mapped_column(String, nullable=False)  # global | gesture
    # 어느 관문의 임계값인지. user | gesture (dual-head)
    gate: Mapped[str] = mapped_column(String, nullable=False, server_default="user")
    gesture_id: Mapped[str | None] = mapped_column(ForeignKey("gestures.id"))
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    far: Mapped[float | None] = mapped_column(Float)
    frr: Mapped[float | None] = mapped_column(Float)
    basis: Mapped[str | None] = mapped_column(String)  # default | demo_relaxed
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuthLog(Base):
    __tablename__ = "auth_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    claimed_gesture_id: Mapped[str | None] = mapped_column(String)
    predicted_gesture_id: Mapped[str | None] = mapped_column(String)
    gesture_confidence: Mapped[float | None] = mapped_column(Float)
    # user 관문 (dual-head 이전에는 이 둘만 있었다)
    score: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    # gesture 관문
    gesture_score: Mapped[float | None] = mapped_column(Float)
    gesture_threshold: Mapped[float | None] = mapped_column(Float)
    passed: Mapped[bool | None] = mapped_column(Boolean)
    # below_threshold | gesture_gate | no_template | invalid_input | model_version_mismatch
    fail_reason: Mapped[str | None] = mapped_column(String)
    auth_model_version: Mapped[str | None] = mapped_column(String)
    gesture_model_version: Mapped[str | None] = mapped_column(String)
    landmarks_json: Mapped[str | None] = mapped_column(Text)  # 추가 학습 데이터
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AppConfig(Base):
    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)  # JSON 인코딩된 값
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

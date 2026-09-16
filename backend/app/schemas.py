"""Pydantic 요청/응답 스키마 (명세 7장). JSON 필드는 camelCase.

랜드마크 내용(21x3, NaN, 프레임 수, tMs 증가)은 여기서 검사하지 않는다.
그건 AI 모듈의 거절 조건이고, 사유 코드와 함께 422로 내려가야 하기 때문이다.
여기서는 JSON 타입만 본다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_serializer
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ResponseModel(CamelModel):
    @field_serializer("*", when_used="json", check_fields=False)
    def _utc(self, v):
        # DB는 UTC naive로 저장한다. 응답에서는 오프셋을 붙인다.
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc).isoformat()
        return v


# --- 공통: 캡처 시퀀스 -------------------------------------------------------------

class Camera(CamelModel):
    # 누락 자체는 AI 모듈이 missing_camera_size로 거절한다.
    width: int | None = None
    height: int | None = None


class Frame(CamelModel):
    t_ms: float = Field(alias="tMs")
    # None 또는 []: 손이 검출되지 않은 프레임
    lm: list[list[float]] | None = None
    handedness: str | None = None
    score: float | None = None


class SequencePayload(CamelModel):
    """AI 모듈에 넘기는 단위. 인증 요청 1건, 등록 take 1건이 각각 하나."""

    camera: Camera | None = None
    frames: list[Frame] = Field(default_factory=list)


# --- /verify --------------------------------------------------------------------

UserId = Annotated[str, Field(min_length=1, max_length=64)]
GestureId = Annotated[str, Field(min_length=1, max_length=32)]


class VerifyRequest(SequencePayload):
    user_id: UserId
    gesture_id: GestureId | None = None
    captured_at: datetime | None = None
    nominal_fps: float | None = None
    duration_ms: int | None = None


class VerifyResponse(ResponseModel):
    # user 관문: 본인인지
    score: float | None
    threshold: float | None
    # gesture 관문: 등록한 동작인지 (dual-head)
    gesture_score: float | None = None
    gesture_threshold: float | None = None
    passed: bool
    # below_threshold | gesture_gate | no_template. 통과 시 null.
    reason: str | None = None
    # 템플릿 조회에 쓴 제스처 (앱이 보낸 gestureId)
    gesture_id: str | None
    model_version: str
    latency_ms: int


class ErrorDetail(BaseModel):
    code: str       # invalid_sequence | invalid_request | not_found | ...
    reason: str     # 세부 사유 코드
    message: str    # 사용자 안내 문구
    take_no: int | None = Field(default=None, serialization_alias="takeNo")


# --- /enroll --------------------------------------------------------------------

class EnrollTake(CamelModel):
    take_no: int = Field(ge=1)
    captured_at: datetime | None = None
    nominal_fps: float | None = None
    duration_ms: int | None = None
    frames: list[Frame] = Field(default_factory=list)


class EnrollRequest(CamelModel):
    user_id: UserId
    gesture_id: GestureId
    camera: Camera | None = None
    takes: list[EnrollTake] = Field(min_length=1)


class EnrollResponse(ResponseModel):
    enrolled: bool
    user_id: str
    gesture_id: str
    take_count: int
    required: int
    model_version: str


# --- /users ---------------------------------------------------------------------

class UserCreate(CamelModel):
    id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.\-]{1,64}$")
    name: str = Field(min_length=1, max_length=100)
    department: str | None = Field(default=None, max_length=100)


class UserOut(ResponseModel):
    id: str
    name: str
    department: str | None
    created_at: datetime
    enrolled_gestures: list[str]


# --- /logs, /stats --------------------------------------------------------------

class AuthLogOut(ResponseModel):
    id: int
    user_id: str | None
    user_name: str | None
    department: str | None
    claimed_gesture_id: str | None
    score: float | None
    threshold: float | None
    gesture_score: float | None
    gesture_threshold: float | None
    passed: bool | None
    fail_reason: str | None
    auth_model_version: str | None
    gesture_model_version: str | None
    latency_ms: int | None
    created_at: datetime


class AuthLogPage(ResponseModel):
    items: list[AuthLogOut]
    total: int
    limit: int
    offset: int


class MonthlyStat(ResponseModel):
    month: str  # YYYY-MM (KST)
    total: int
    passed: int
    failed: int


# --- /config, /health -----------------------------------------------------------

class ConfigOut(ResponseModel):
    enrollment_takes: int
    enrollment_gestures: int
    capture_duration_ms: int
    hand_required: str
    model_version: str


class ConfigPatch(CamelModel):
    enrollment_takes: int | None = Field(default=None, ge=1, le=10)
    enrollment_gestures: int | None = Field(default=None, ge=1, le=5)
    capture_duration_ms: int | None = Field(default=None, ge=750, le=10000)
    hand_required: str | None = Field(default=None, pattern=r"^(right|left|any)$")


class HealthOut(ResponseModel):
    status: str
    model_version: str | None            # DB의 활성 모델 버전
    loaded_model_version: str             # 프로세스에 로드된 ai.encoder.MODEL_VERSION
    active_threshold: float | None        # user 관문 (Tu)
    active_gesture_threshold: float | None  # gesture 관문 (Tg)
    active_threshold_basis: str | None
    db_ok: bool


# --- /admin ---------------------------------------------------------------------

class ThresholdSwitchRequest(CamelModel):
    basis: str = Field(min_length=1)  # default | demo_relaxed


class ThresholdOut(ResponseModel):
    basis: str | None
    gate: str  # user | gesture
    value: float
    far: float | None
    frr: float | None
    model_version: str
    is_active: bool


class ReindexRequest(CamelModel):
    model_version: str = Field(min_length=1)
    dry_run: bool = False


class ReindexFailure(ResponseModel):
    enrollment_id: int
    user_id: str
    gesture_id: str
    error: str


class ReindexResponse(ResponseModel):
    from_version: str | None
    to_version: str
    enrollments_processed: int
    templates_rebuilt: int
    failed: int
    elapsed_ms: int
    dry_run: bool
    switched: bool
    failures: list[ReindexFailure]

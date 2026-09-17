"""Pydantic 요청/응답 스키마 (명세 7장). JSON 필드는 camelCase.

랜드마크 내용(21x3, NaN, 프레임 수, tMs 증가)은 여기서 검사하지 않는다.
그건 AI 모듈의 거절 조건이고, 사유 코드와 함께 422로 내려가야 하기 때문이다.
여기서는 JSON 타입만 본다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator
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

# --- 안티스푸핑 Challenge 설정 -----------------------------------------------------
#
# 판정은 앱이 하지만 임계값은 전부 서버가 소유한다. 앱에 상수로 박으면 자유 제스처
# 데이터로 재도출했을 때 앱을 다시 배포해야 한다.
# 원본은 challenge_response/configs/challenge_config.json (도출 근거 _source 포함).

class FingerExtendedAngleOut(ResponseModel):
    """손가락이 '펴졌다'고 볼 최소 관절 각도(도)."""
    thumb: float = Field(gt=0.0, lt=180.0)
    others: float = Field(gt=0.0, lt=180.0)


class ChallengeMovementOut(ResponseModel):
    window_ms: float = Field(gt=0.0, le=5000.0)
    min_displacement_ratio: float = Field(gt=0.0, le=10.0)
    axis_dominance_ratio: float = Field(gt=1.0, le=50.0)
    max_duration_ms: float = Field(gt=0.0, le=30000.0)
    rest_displacement_ratio: float = Field(ge=0.0, le=10.0)
    # {"MOVE_LEFT": ["x", -1], ...}. 축→방향 대응도 추측이 아니라 영상에서 도출했다.
    direction_map: dict[str, tuple[str, int]]


class ChallengeTimingOut(ResponseModel):
    per_action_timeout_ms: float = Field(gt=0.0, le=30000.0)
    total_timeout_ms: float = Field(gt=0.0, le=60000.0)
    max_retries: int = Field(ge=0, le=5)

    # 손이 이만큼 연속으로 잡혀야 1단계를 시작한다. 그 전에는 제한 시간이 흐르지
    # 않고 재시도도 차감되지 않는다. 앱 인증 화면의 kHandReadyDuration과 같은 값이다.
    wait_hand_ready_ms: float = Field(default=400.0, ge=0.0, le=5000.0)

    # 손을 아예 들지 않을 때 대기를 끝내는 시간. 판정 제한이 아니라 화면이
    # 영원히 멈춰 있지 않게 하는 안전장치다.
    wait_hand_timeout_ms: float = Field(default=15000.0, gt=0.0, le=120000.0)

    # 단계가 넘어간 뒤 다음 판정을 시작하기까지 주는 시간.
    #
    # 요청 동작 그림을 보고 손을 준비할 시간이다. 이 동안에는 perActionTimeoutMs가
    # 흐르지 않는다. 실기기에서 각 단계가 순식간에 지나가 무엇을 했는지 인지가
    # 안 된다는 피드백으로 넣었다. 0이면 바로 다음 판정으로 간다.
    step_prepare_ms: float = Field(default=1500.0, ge=0.0, le=10000.0)

    # 단계 결과(PASS/FAIL)를 보여주는 시간.
    #
    # 동작을 맞게 해도 순식간에 넘어가 제대로 한 건지 인지가 안 된다는 피드백으로
    # 넣었다. 이 동안에도 제한 시간이 흐르지 않는다. 0이면 바로 넘어간다.
    #
    # 순서: 동작 통과 → PASS 표시 → 다음 동작 준비 → 판정
    step_result_hold_ms: float = Field(default=1500.0, ge=0.0, le=10000.0)


class ChallengeTrackingOut(ResponseModel):
    max_lost_frames: int = Field(ge=1, le=300)
    min_detection_score: float = Field(ge=0.0, le=1.0)

    # 앱이 '손 없음'을 만들어 넣기까지 기다리는 시간. 프레임이 이보다 오래 안 오면
    # 손이 사라진 것으로 보고, 이동 판정 윈도우를 비운다.
    #
    # 고정 상수(100ms)를 쓰다가 실기기에서 터졌다. 14fps면 프레임 간격이 71ms라
    # 여유가 29ms뿐이고, 한 프레임만 늦어도(110~170ms 관측) 윈도우가 비워져
    # 550ms를 채울 기회가 없었다. 최근 프레임 간격의 중앙값 × factor로 유도한다.
    #
    # factor는 측정값이 아니라 정책값이다. 실기기 체감으로 조정한다.
    frame_stale_factor: float = Field(default=3.0, gt=1.0, le=20.0)
    frame_stale_min_ms: int = Field(default=150, ge=30, le=5000)
    frame_stale_max_ms: int = Field(default=800, ge=50, le=10000)

    @model_validator(mode="after")
    def _check_bounds(self):
        if self.frame_stale_min_ms > self.frame_stale_max_ms:
            raise ValueError("frameStaleMinMs가 frameStaleMaxMs보다 크다")
        return self


class ChallengeStepsOut(ResponseModel):
    """단계 구성. 3단계(손 모양 2 + 이동 1)가 기본이다."""
    num_shapes: int = Field(ge=0, le=4)
    num_moves: int = Field(ge=0, le=4)


class ChallengeContinuityOut(ResponseModel):
    """연속 세션에서 손이 바뀌었는지 보는 검사.

    Challenge와 제스처 인증을 한 번의 촬영으로 묶으면 "Challenge는 본인 손,
    인증은 피해자 영상"을 막을 수 있다. 다만 손을 빼지 않고 화면을 들이미는
    경우가 남는데, 그때는 손 크기와 손목 위치가 한 프레임 사이에 튄다.

    ⚠️ **기본은 꺼져 있다.** 정상 세션의 프레임 간 변화량을 아직 재지 않았다.
    임계값을 추측해서 넣으면 정상 사용자를 막거나 아무것도 막지 못한다.
    앱이 측정값을 디버그 로그에 남기므로, 세션이 쌓이면 분포에서 도출한다.
    """

    enabled: bool = False

    # 프레임 간 손 크기 변화 허용치(배수). null이면 미도출.
    max_scale_jump_ratio: float | None = Field(default=None, gt=0.0, le=100.0)

    # 프레임 간 손목 이동 허용치(손 크기 배수). null이면 미도출.
    max_wrist_jump_ratio: float | None = Field(default=None, gt=0.0, le=100.0)

    @model_validator(mode="after")
    def _needs_thresholds(self):
        if self.enabled and (
            self.max_scale_jump_ratio is None or self.max_wrist_jump_ratio is None
        ):
            raise ValueError(
                "연속성 검사를 켜려면 maxScaleJumpRatio와 maxWristJumpRatio가 모두 필요하다. "
                "근거 없이 켤 수 없다."
            )
        return self


class ChallengeConfigOut(ResponseModel):
    rule_version: str
    angle_space: str = Field(pattern=r"^(image_iso|world)$")
    coordinate_frame: str = Field(pattern=r"^(raw|mirrored)$")
    # shapeHoldFrames 등 '프레임 수' 값은 이 fps의 파일럿 영상에서 센 것이다.
    # 앱은 이 fps 기준 시간(ms)으로 바꿔 판정한다. 실기기는 13~16fps다.
    frame_reference_fps: float = Field(gt=0.0, le=240.0)
    finger_extended_angle: FingerExtendedAngleOut
    # null이면 FIST 게이트를 끈다(도출 실패 시). 임의의 값을 넣지 않는다.
    fist_max_tip_wrist_ratio: float | None = Field(default=None, gt=0.0, le=10.0)
    shape_hold_frames: int = Field(ge=1, le=120)
    shape_confidence_margin_deg: float = Field(gt=0.0, le=180.0)
    # null이면 신뢰도 게이트를 끈다. 04가 '신뢰도로는 더 못 거른다'를 측정으로 확인했다.
    shape_confidence_min: float | None = Field(default=None, ge=0.0, le=1.0)
    # 0이면 이탈 관문을 끈다.
    escape_frames: int = Field(ge=0, le=120)
    movement: ChallengeMovementOut
    timing: ChallengeTimingOut
    tracking: ChallengeTrackingOut
    steps: ChallengeStepsOut
    continuity: ChallengeContinuityOut = Field(
        default_factory=ChallengeContinuityOut
    )
    shape_pool: list[str] = Field(min_length=1)
    move_pool: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_pools(self):
        if self.steps.num_shapes > len(self.shape_pool):
            raise ValueError("numShapes가 shapePool보다 많다. 서로 다른 모양을 뽑을 수 없다")
        if self.steps.num_moves > len(self.move_pool):
            raise ValueError("numMoves가 movePool보다 많다")
        if self.steps.num_shapes + self.steps.num_moves < 1:
            raise ValueError("단계가 0개인 Challenge는 만들 수 없다")
        missing = set(self.move_pool) - set(self.movement.direction_map)
        if missing:
            raise ValueError(f"directionMap에 없는 이동: {sorted(missing)}")
        return self


class ConfigOut(ResponseModel):
    enrollment_takes: int
    enrollment_gestures: int
    capture_duration_ms: int
    hand_required: str
    model_version: str
    # 인증 성공 후 "계속하기"로 여는 주소. 2차 인증 시연용.
    post_auth_url: str
    challenge: ChallengeConfigOut


class ConfigPatch(CamelModel):
    enrollment_takes: int | None = Field(default=None, ge=1, le=10)
    enrollment_gestures: int | None = Field(default=None, ge=1, le=5)
    capture_duration_ms: int | None = Field(default=None, ge=750, le=10000)
    hand_required: str | None = Field(default=None, pattern=r"^(right|left|any)$")
    # https만 받는다. 앱이 외부 브라우저로 열기 때문이다.
    post_auth_url: str | None = Field(default=None, pattern=r"^https://\S+$", max_length=500)
    # 일부 키만 보내면 저장된 값에 깊은 병합 후 ChallengeConfigOut으로 검증한다.
    # 예: {"challenge": {"timing": {"perActionTimeoutMs": 2500}}}
    challenge: dict | None = None


# --- 디버그 로그 -------------------------------------------------------------------

class DebugLogBatch(CamelModel):
    """앱이 모아 보내는 Challenge 판정 로그.

    프레임마다 한 번씩 보내면 14fps에서 초당 14번 왕복한다. 앱이 모아서 보낸다.
    """
    session_id: str = Field(min_length=1, max_length=64)
    lines: list[str] = Field(min_length=1, max_length=200)


class DebugLogOut(ResponseModel):
    written: int
    path: str
    client: str


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

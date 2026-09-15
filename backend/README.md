# Sign-ID 백엔드

수어 제스처 기반 비접촉 인증 시스템의 FastAPI 백엔드. Flutter 앱과 AI 모델 사이를 연결하고
사용자·등록·인증 이력을 관리한다. 설계 근거는 [`../BACKEND_SPEC.md`](../BACKEND_SPEC.md).

> ⚠️ **현재 `ai/`는 스텁이다.** 임베딩과 제스처 분류가 가짜 값이다. 흐름(등록 → 인증 → 재색인)은
> 진짜처럼 동작하지만 실제 사람의 동작 인식 성능과는 무관하다. [`ai/stub_notice.md`](ai/stub_notice.md)

목차

1. [실행](#1-실행)
2. [설정](#2-설정)
3. [API 목록](#3-api-목록)
4. [앱팀 전달: 요청·응답 규격](#4-앱팀-전달-요청응답-규격)
5. [사유 코드 목록](#5-사유-코드-목록)
6. [threshold 운영](#6-threshold-운영)
7. [ai_release 교체 절차](#7-ai_release-교체-절차)
8. [데이터 보관과 개인정보](#8-데이터-보관과-개인정보)
9. [알려진 한계](#9-알려진-한계)
10. [구조](#10-구조)

---

## 1. 실행

Python 3.11.

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

uvicorn app.main:app --reload     # http://127.0.0.1:8000/docs
```

startup에서 자동으로 한다:

- `alembic upgrade head` (스키마 생성·마이그레이션)
- `ai.encoder.load_model()` **1회**
- 기본 데이터: 제스처 G1~G5, threshold 3종(far1 활성), `app_config` 기본값. 이미 있으면 덮어쓰지 않는다.

시연용 사용자·이력 (관리자 화면이 비어 보이지 않게):

```bash
python scripts/seed_demo_data.py            # 사용자 6명 + 최근 5개월 인증 이력
python scripts/seed_demo_data.py --reset    # 데모 사용자 ID(hong, kim, oh, dooly, ddochi, go)만 지우고 재생성
```

테스트:

```bash
pytest                                      # 테스트마다 임시 SQLite
```

휴대폰 실기기에서 붙을 때는 `uvicorn app.main:app --host 0.0.0.0 --port 8000`.

---

## 2. 설정

### 환경변수 (`.env`) — 프로세스 시작 시 정해지는 값

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./signid.db` | Postgres로 옮길 때 URL만 바꾼다 |
| `AI_DEVICE` | `cpu` | `load_model(device=...)` |
| `LOG_LEVEL` | `INFO` | |
| `CORS_ORIGINS` | `*` | 쉼표 구분 |
| `USE_GESTURE_CLASSIFIER` | `true` | `/verify`에서 템플릿을 고르는 방식. 아래 참고 |

#### `USE_GESTURE_CLASSIFIER`

| | `true` (기본, 명세 7장) | `false` |
|---|---|---|
| 템플릿 조회 키 | `classify_gesture()` 예측 제스처 | 앱이 보낸 `gestureId` |
| `gestureId` | 선택. 보냈는데 예측과 다르면 `gesture_mismatch`로 거부 | **필수**. 없으면 422 `gesture_id_required` |
| `classify_gesture()` 호출 | 함 | 함 (결과를 `predictedGesture`·`auth_logs.predicted_gesture_id`에 기록만, 판정에 안 씀) |

응답의 `gestureId`는 실제로 템플릿 조회에 쓴 제스처다. 바꾸려면 `.env` 수정 후 서버 재시작.

### `app_config` 테이블 — 운영 중 바꾸는 값 (재시작 불필요)

| 키 | 기본값 | 설명 |
|---|---|---|
| `enrollmentTakes` | 3 | 제스처당 등록 횟수. `/enroll`은 takeNo 1..N을 모두 요구 |
| `enrollmentGestures` | 1 | 등록할 제스처 수. ⚠️ AI팀 확인 대기 (1 또는 5) |
| `captureDurationMs` | 2000 | 앱 촬영 시간 |
| `handRequired` | `right` | 앱 안내용 |
| `activeModelVersion` | 로드된 인코더 버전 | 재색인이 바꾼다. 직접 수정 금지 |

```bash
curl -X PATCH localhost:8000/admin/config -H 'Content-Type: application/json' -d '{"enrollmentGestures": 5}'
```

---

## 3. API 목록

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/verify` | 인증 |
| POST | `/enroll` | 제스처 등록 (take 전부 한 번에) |
| GET | `/config` | 앱 등록 화면 구성값 |
| GET | `/users` | 사용자 목록 (활성 모델 기준 등록된 제스처 포함) |
| POST | `/users` | 사용자 생성 `{id?, name, department?}`. id 생략 시 `u_xxxxxxxx` |
| DELETE | `/users/{id}` | 사용자와 관련 데이터 **전부** 삭제 (랜드마크 원본 포함) |
| GET | `/logs?limit&offset&userId&passed` | 인증 이력, 최신순. 랜드마크는 싣지 않음 |
| GET | `/stats/monthly?months=5` | 월별 인증 건수 (KST, 0건인 달 포함) |
| GET | `/health` | 상태, 모델 버전, 활성 threshold |
| GET | `/admin/thresholds` | 활성 모델의 threshold 운영점 목록 |
| POST | `/admin/threshold` | 활성 threshold 전환 `{basis: "far1" \| "eer" \| "far5"}` |
| POST | `/admin/reindex` | 재색인 `{modelVersion, dryRun}` |
| PATCH | `/admin/config` | `app_config` 변경 |

전체 스키마는 `/docs`.

---

## 4. 앱팀 전달: 요청·응답 규격

**백엔드가 AI팀 계약 기준이다. 앱이 이 규격에 맞춘다.**
그대로 보내면 통과하는 완전한 예시 파일이 있다 (테스트로 검증됨):

- [`examples/verify_request.json`](examples/verify_request.json)
- [`examples/enroll_request.json`](examples/enroll_request.json)

### 4.1 공통 규칙

- JSON 필드는 camelCase.
- **`camera.width` / `camera.height` 필수** (새 항목). 없으면 422 `missing_camera_size`.
  카메라 프레임의 실제 픽셀 크기 (세로 촬영이면 `720x1280`처럼 세로가 큼).
- `frames[].tMs`: 캡처 시작부터의 **실제** 경과 ms. 반드시 증가. 인덱스×33 같은 가정 금지.
- `frames[].lm`: MediaPipe Hand 21점 `[x, y, z]`, 가공하지 않은 원본.
  손이 검출되지 않은 프레임은 `"lm": null`로 보내도 된다 (보내지 않아도 된다).
- 최소 조건: 프레임 8개 이상, 손 검출 프레임 8개 이상, 첫–마지막 `tMs` 간격 750ms 이상.
  8~31프레임은 AI 모듈이 보간한다. **앱이 패딩하지 말 것.**
- 오른손만 허용 (화면 안내). `handedness`, `score`는 선택 필드로 그대로 보내면 된다.
- `capturedAt`은 **오프셋 포함** ISO-8601 (`2026-09-16T10:39:01+09:00`). 오프셋이 없으면 UTC로 간주한다.
- 실패 응답은 모두 `{"detail": {"code", "reason", "message"}}`. 앱은 `reason`으로 분기하고 `message`를 그대로 보여줘도 된다.
- threshold는 **응답에서 읽는다.** 앱에 넣지 않는다.

### 4.2 `POST /verify`

요청 (프레임 1개만 펼침, 전체는 [`examples/verify_request.json`](examples/verify_request.json)):

```json
{
  "userId": "kim",
  "gestureId": "G3",
  "capturedAt": "2026-09-16T10:39:01+09:00",
  "camera": { "width": 720, "height": 1280 },
  "nominalFps": 30,
  "durationMs": 2000,
  "frames": [
    {
      "tMs": 0,
      "handedness": "Right",
      "score": 0.98,
      "lm": [
        [0.5371, 0.6569, 0.0025], [0.4167, 0.4824, -0.0224], [0.3515, 0.6377, -0.0123],
        [0.4925, 0.4809, -0.0028], [0.4239, 0.5242, 0.0146], [0.512, 0.688, 0.0211],
        [0.537, 0.6912, -0.0281], [0.3968, 0.5742, -0.0149], [0.3604, 0.5441, 0.0143],
        [0.6262, 0.5767, -0.04], [0.4991, 0.4621, -0.0087], [0.406, 0.5996, -0.0016],
        [0.461, 0.3899, 0.0249], [0.3923, 0.468, 0.0145], [0.4987, 0.6458, -0.01],
        [0.574, 0.4158, -0.0058], [0.5026, 0.6483, -0.0025], [0.5323, 0.4076, 0.0299],
        [0.4466, 0.4331, -0.0064], [0.4627, 0.6835, -0.0077], [0.5303, 0.5788, 0.0096]
      ]
    },
    { "tMs": 103, "lm": null }
  ]
}
```

| 필드 | 필수 | 설명 |
|---|---|---|
| `userId` | ✅ | |
| `gestureId` | 선택 | `USE_GESTURE_CLASSIFIER=false`면 필수 |
| `camera.width`, `camera.height` | ✅ | |
| `frames` | ✅ | |
| `capturedAt`, `nominalFps`, `durationMs` | 선택 | 기록용 |

응답 200 — 통과:

```json
{
  "score": 0.7134,
  "threshold": 0.627516,
  "passed": true,
  "reason": null,
  "predictedGesture": "G3",
  "gestureConfidence": 0.93,
  "gestureId": "G3",
  "modelVersion": "handonly-supcon-v1.0.0",
  "latencyMs": 42
}
```

응답 200 — 거부 (비교를 하지 않은 경우):

```json
{
  "score": null,
  "threshold": 0.627516,
  "passed": false,
  "reason": "gesture_mismatch",
  "predictedGesture": "G2",
  "gestureConfidence": 0.9,
  "gestureId": "G2",
  "modelVersion": "handonly-supcon-v1.0.0",
  "latencyMs": 7
}
```

> **⚠️ `score`는 nullable이다.** `gesture_mismatch`, `no_template`처럼 유사도 비교를 하지 않았으면 `null`.
> 0.0으로 채우지 않는 이유: "비교를 안 했다"와 "유사도가 0이다"가 구분되지 않는다.
> 앱은 `score`를 `double?`로 받고, 결과 화면에서 `null`이면 점수를 표시하지 않는다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `score` | `number \| null` | 코사인 유사도 |
| `threshold` | `number \| null` | 이번 판정에 쓴 값 (서버 활성 threshold) |
| `passed` | `bool` | |
| `reason` | `string \| null` | 거부 사유 ([5.1](#51-인증-거부-사유-auth_logsfail_reason)). 통과 시 `null` |
| `predictedGesture` | `string \| null` | 분류 모델 결과 |
| `gestureConfidence` | `number \| null` | |
| `gestureId` | `string \| null` | 템플릿 조회에 실제로 쓴 제스처 |
| `modelVersion` | `string` | |
| `latencyMs` | `int` | 서버 처리 시간 |

응답 422 — 재촬영 필요:

```json
{
  "detail": {
    "code": "invalid_sequence",
    "reason": "insufficient_valid_frames",
    "message": "손이 충분히 인식되지 않았습니다. 다시 시도해주세요."
  }
}
```

### 4.3 `POST /enroll`

요청 (take당 프레임 1개만 펼침, 전체는 [`examples/enroll_request.json`](examples/enroll_request.json)):

```json
{
  "userId": "kim",
  "gestureId": "G3",
  "camera": { "width": 720, "height": 1280 },
  "takes": [
    {
      "takeNo": 1,
      "capturedAt": "2026-09-16T10:31:00+09:00",
      "nominalFps": 30,
      "durationMs": 2000,
      "frames": [
        { "tMs": 0, "handedness": "Right", "score": 0.97, "lm": [[0.53, 0.65, 0.0], "... 21개"] }
      ]
    },
    { "takeNo": 2, "capturedAt": "2026-09-16T10:32:00+09:00", "nominalFps": 30, "durationMs": 2000, "frames": [] },
    { "takeNo": 3, "capturedAt": "2026-09-16T10:33:00+09:00", "nominalFps": 30, "durationMs": 2000, "frames": [] }
  ]
}
```

(위 블록의 `"... 21개"`와 빈 `frames`는 지면상 생략. 실제로는 예시 파일처럼 채운다.)

- `takes`는 `GET /config`의 `enrollmentTakes`개, `takeNo`는 1..N 전부. 모자라거나 중복이면 422 `take_count_mismatch`.
- `camera`는 요청 최상위에 한 번 (take 공통).
- **take 하나라도 불량이면 전체 거부, 아무것도 저장되지 않는다.** 422에 `takeNo`가 붙으니 그 회차만 다시 찍게 안내할 수 있다. 단, 재전송은 3회 전부 보내야 한다.
- 같은 `(userId, gestureId)`로 다시 보내면 기존 등록을 대체한다.
- 사용자는 먼저 `POST /users`로 만들어야 한다 (없으면 404 `user_not_found`).

응답 200:

```json
{
  "enrolled": true,
  "userId": "kim",
  "gestureId": "G3",
  "takeCount": 3,
  "required": 3,
  "modelVersion": "handonly-supcon-v1.0.0"
}
```

응답 422:

```json
{
  "detail": {
    "code": "invalid_sequence",
    "reason": "too_few_frames",
    "message": "촬영된 프레임이 너무 적습니다. 다시 시도해주세요.",
    "takeNo": 2
  }
}
```

### 4.4 `GET /config`

앱 시작 시 호출해 등록 화면을 그린다.

```json
{
  "enrollmentTakes": 3,
  "enrollmentGestures": 1,
  "captureDurationMs": 2000,
  "handRequired": "right",
  "modelVersion": "handonly-supcon-v1.0.0"
}
```

### 4.5 관리자 화면

`GET /logs?limit=50&offset=0` (선택: `userId`, `passed=true|false`):

```json
{
  "items": [
    {
      "id": 3,
      "userId": "kim",
      "userName": "김길동",
      "department": "개발팀",
      "claimedGestureId": "G3",
      "predictedGestureId": "G3",
      "gestureConfidence": 0.93,
      "score": 0.7134,
      "threshold": 0.627516,
      "passed": true,
      "failReason": null,
      "authModelVersion": "handonly-supcon-v1.0.0",
      "gestureModelVersion": "handonly-gesture-1dcnn-v1.0.0",
      "latencyMs": 42,
      "createdAt": "2026-09-16T01:39:01.123456+00:00"
    }
  ],
  "total": 214,
  "limit": 50,
  "offset": 0
}
```

`createdAt`은 UTC(`+00:00`). 화면에는 로컬 시각으로 변환해 표시한다.

`GET /stats/monthly?months=5` (오래된 달 → 최근 달, 이번 달 포함):

```json
[
  { "month": "2026-05", "total": 52, "passed": 41, "failed": 11 },
  { "month": "2026-06", "total": 0,  "passed": 0,  "failed": 0 },
  { "month": "2026-09", "total": 23, "passed": 19, "failed": 4 }
]
```

`GET /users`:

```json
[
  {
    "id": "kim",
    "name": "김길동",
    "department": "개발팀",
    "createdAt": "2026-09-15T20:52:33.950331+00:00",
    "enrolledGestures": ["G3"]
  }
]
```

### 4.6 현재 앱 코드와 다른 점 (앱 수정 체크리스트)

| 항목 | 현재 앱 (`lib/`) | 백엔드 규격 |
|---|---|---|
| 경로 | `/v1/verify`, `/v1/enroll`, `/v1/auth-logs`, `/v1/stats/monthly` | `/verify`, `/enroll`, `/logs`, `/stats/monthly` (접두사 없음) |
| `VerifyRequest` | `camera` 없음, `gestureId` 없음 | `camera: {width, height}` **필수**, `gestureId` 선택 |
| `VerifyResponse.score` | `double` 필수 | **`double?`** |
| `VerifyResponse` 추가 필드 | — | `predictedGesture`, `gestureConfidence`, `gestureId`, `modelVersion` |
| `EnrollRequest` | `{userId, capturedAt, nominalFps, takeCount, takes: [[frame]]}` | `{userId, gestureId, camera, takes: [{takeNo, capturedAt, nominalFps, durationMs, frames}]}` |
| `EnrollRequest.capturedAt` | `toIso8601String()` (오프셋 없음) | take별, 오프셋 포함 |
| `EnrollResponse` | `acceptedTakes`, `templateId`, 실패 시 `enrolled: false` | `takeCount`, `required`, `modelVersion`. 실패는 **422** |
| 인증 이력 | `List<AuthLog{userName, department, timestamp, passed}>` | `{items: [...], total, limit, offset}`, 시각은 `createdAt` |
| 월별 통계 | `{month: 1~12, count}` | `{month: "YYYY-MM", total, passed, failed}` |
| 에러 | 미정 | `detail.reason` 코드별 재촬영 안내 ([5.2](#52-http-에러-사유-detailreason)) |
| 등록 화면 | 고정 | `GET /config`로 회차·제스처 수 구성 |

---

## 5. 사유 코드 목록

### 5.1 인증 거부 사유 (`auth_logs.fail_reason`)

`/verify` 응답의 `reason`, `/logs`의 `failReason`도 같은 값.

| 코드 | 명세 | HTTP | `score` | 의미 |
|---|---|---|---|---|
| `below_threshold` | 명세 | 200 | 숫자 | 유사도가 활성 threshold 미만 |
| `no_template` | 명세 | 200 | `null` | 해당 (사용자, 제스처, 활성 모델 버전) 템플릿 없음 |
| `gesture_mismatch` | 명세 | 200 | `null` | `gestureId`가 분류 결과와 다름 (`USE_GESTURE_CLASSIFIER=true`에서만) |
| `invalid_input` | 명세 | 422 | `null` | AI 모듈이 입력 거절. 세부 사유는 응답 `detail.reason` |
| **`model_version_mismatch`** | **명세 외 추가** | **503** | `null` | 로드된 인코더와 활성 모델 버전이 다름 (인코더 교체 후 재색인 전). 벡터 공간이 달라 비교하면 조용히 틀리므로 비교하지 않고 거부 |

로그에 남지 않는 요청: 없는 사용자(404), 요청 형식 오류(422 `schema_validation`, `gesture_id_required`),
활성 threshold 없음(503 `no_active_threshold`).

### 5.2 HTTP 에러 사유 (`detail.reason`)

**입력 거절 (`code: invalid_sequence`, 422)** — 앱이 재촬영 안내에 사용

| `reason` | 조건 | 기본 `message` |
|---|---|---|
| `too_few_frames` | 전체 프레임 8개 미만 | 촬영된 프레임이 너무 적습니다. 다시 시도해주세요. |
| `insufficient_valid_frames` | 손 검출 프레임 8개 미만 | 손이 충분히 인식되지 않았습니다. 다시 시도해주세요. |
| `duration_too_short` | 첫–마지막 `tMs` 750ms 미만 | 동작이 너무 짧습니다. 조금 더 천천히 해주세요. |
| `non_monotonic_timestamps` | `tMs`가 증가하지 않음 | 촬영 시간 정보가 올바르지 않습니다. 다시 시도해주세요. |
| `missing_camera_size` | `camera.width`/`height` 누락 | 카메라 해상도 정보가 없습니다. 앱을 최신 버전으로 업데이트해주세요. |
| `malformed_landmarks` | 21×3이 아니거나 NaN/Inf | 손 좌표 형식이 올바르지 않습니다. 다시 시도해주세요. |
| `invalid_sequence` | 위로 분류되지 않은 AI 모듈 거절 | 입력을 처리할 수 없습니다. 다시 시도해주세요. |

**그 외**

| HTTP | `code` | `reason` | 발생 |
|---|---|---|---|
| 422 | `invalid_request` | `schema_validation` | JSON 타입·필수 필드 오류 (`detail.errors`에 위치) |
| 422 | `invalid_request` | `gesture_id_required` | `/verify`, `USE_GESTURE_CLASSIFIER=false`인데 `gestureId` 없음 |
| 422 | `invalid_request` | `take_count_mismatch` | `/enroll` take 개수·번호 불일치 |
| 422 | `invalid_request` | `unknown_gesture` | `/enroll` 없는 제스처 ID |
| 404 | `not_found` | `user_not_found` | `/verify`, `/enroll`, `DELETE /users/{id}` |
| 404 | `not_found` | `threshold_not_found` | `/admin/threshold` 없는 basis |
| 409 | `conflict` | `user_exists` | `POST /users` 중복 ID |
| 409 | `conflict` | `no_active_threshold` | `/admin/reindex` 대상 버전 threshold 없음 |
| 400 | `bad_request` | `model_version_mismatch` | `/admin/reindex` 요청 버전 ≠ 로드된 인코더 |
| 503 | `service_unavailable` | `model_version_mismatch` | `/verify` 재색인 전 (5.1 참고) |
| 503 | `service_unavailable` | `no_active_threshold` | `/verify` 활성 threshold 없음 |

---

## 6. threshold 운영

threshold는 DB `thresholds` 테이블에만 있다 (코드·앱에 없음). 요청마다 활성 행을 읽으므로 **전환 즉시 반영, 재시작 불필요.**

| basis | threshold | Val FAR | Val FRR |
|---|---|---|---|
| `far1` (기본) | 0.627516 | 0.95% | 4.29% |
| `eer` | 0.436046 | 2.86% | 2.86% |
| `far5` | 0.272128 | 5.00% | 2.14% |

```bash
curl localhost:8000/admin/thresholds
curl -X POST localhost:8000/admin/threshold -H 'Content-Type: application/json' -d '{"basis": "eer"}'
```

시연 리허설에서 거부가 잦으면 `eer`로 내린다. `auth_logs.threshold`에 시도마다 쓴 값이 남는다.

기본값은 `app/default_thresholds.json`에서 들어간다. startup 시 **로드된 인코더 버전**에 threshold가 없으면 이 파일로 채운다.

---

## 7. ai_release 교체 절차

### 7.0 가장 먼저: AI 입력 형태 확인 ⚠️ 미확정

> **⚠️ 미확정 — 실제 모듈과 다를 수 있음.**
> 백엔드가 `embed(frames)` / `classify_gesture(frames)`에 넘기는 `frames` 인자의 형태는
> 명세에 없어서 **백엔드가 가정한 것**이다. 카메라 크기를 함께 넘길 방법이 시그니처에 없어 dict 하나로 묶었다.
>
> ```python
> {
>   "camera": {"width": 720, "height": 1280},
>   "frames": [{"tMs": 0.0, "lm": [[x, y, z], ...21개] | None, "handedness": "Right", "score": 0.98}, ...]
> }
> ```
>
> 이 변환은 **`app/services/ai_gateway.py`의 `to_ai_input()` 한 곳**에만 있다.
> 등록·인증·재색인·검증 스크립트가 모두 이 함수를 거친다. 실제 모듈과 다르면 이 함수만 고친다.
> 함께 확인할 것:
> - `InvalidSequenceError`에 사유 코드 속성(`reason`)이 있는지. 없으면 메시지 문구로 추정하므로
>   `ai_gateway.py`의 `_REASON_PATTERNS`가 실제 메시지와 맞는지 (7.4 스크립트가 WARN으로 알려준다)
> - `classify_gesture()` 라벨이 `G1`~`G5` 문자열인지 (`gestures` 테이블 ID와 같아야 함)

### 7.1 절차

1. **입력 형태 확인** (7.0). AI팀 문서·`encoder.py` docstring과 `to_ai_input()`을 비교한다.
2. **파일 복사**: `ai_release/`의 `encoder.py`, `features.py`, `model_defs.py`, `weights/`, `preprocess.json`을
   `backend/ai/`에 복사 (기존 스텁 덮어쓰기). `ai/stub_notice.md`는 삭제.
   - 실제 `encoder.py`가 `from features import ...`처럼 패키지 밖 import를 쓰면 `from ai.features import ...`로 맞추거나
     `ai/__init__.py`에서 경로를 잡는다. 가중치 경로가 CWD 기준이면 `Path(__file__).parent` 기준인지 확인.
3. **의존성 병합**: `ai_release/requirements.txt`의 `torch` 등을 `backend/requirements.txt`에 추가.
   `numpy==1.26.4`가 양쪽에서 같은지 확인. `pip install -r requirements.txt`.
4. **가중치 확인**: `python ai_release/smoke_test.py`
5. **계약 검증**: `python scripts/verify_ai_release.py`
   - 시그니처, 임베딩 `(128,)` `float32`, L2 norm=1, 결정성, `embed_batch` 일치, 분류 라벨, 거절 조건 6종.
   - `FAIL`이 있으면 종료 코드 1. `embed`부터 줄줄이 실패하면 7.0의 입력 형태가 다른 것이다.
   - `[WARN] 사유 코드 ...`가 뜨면 `_REASON_PATTERNS` 조정.
6. **threshold 반영**: `ai_release/thresholds.json`의 값을 `app/default_thresholds.json` 형식으로 옮긴다.
   서버를 띄우면 새 `MODEL_VERSION`에 대해 threshold 3종이 자동으로 들어간다 (이미 그 버전 행이 있으면 건드리지 않는다).
   파일을 고치기 전에 서버를 먼저 띄웠다면 `thresholds` 테이블에서 새 `model_version` 행을 지우고 재시작한다.
   값은 재색인 후 `GET /admin/thresholds`로 확인 (활성 모델 버전 기준으로 보여준다).
7. **서버 재시작 후 재색인**:
   ```bash
   curl localhost:8000/health        # status=degraded, modelVersion=옛 버전, loadedModelVersion=새 버전
   curl -X POST localhost:8000/admin/reindex -H 'Content-Type: application/json' \
        -d '{"modelVersion": "handonly-supcon-v1.0.0", "dryRun": true}'     # 실패 건 먼저 확인
   curl -X POST localhost:8000/admin/reindex -H 'Content-Type: application/json' \
        -d '{"modelVersion": "handonly-supcon-v1.0.0", "dryRun": false}'
   curl localhost:8000/health        # status=ok
   ```
   재색인 전까지 `/verify`는 503 `model_version_mismatch`다.
8. **테스트 재실행**: `pytest`. 스텁 전용 테스트(결정적 벡터로 유사도 1.0, 사유 코드 속성)는 실제 모델에서 실패할 수 있다.
   `tests/test_ai_stub.py`의 시그니처·형태 테스트는 통과해야 한다.

### 7.2 재색인 동작

- `enrollments`의 랜드마크 원본을 새 인코더에 다시 넣어 `embeddings`·`templates`를 새 `model_version`으로 만든다.
- 임베딩을 **전부 먼저 계산**하고, 실패가 0건일 때만 한 트랜잭션으로 저장하면서 `activeModelVersion`을 바꾼다.
- 한 건이라도 실패하면 **아무것도 저장하지 않고** 전환하지 않는다. 응답 `failures`에 enrollment ID와 에러.
- 옛 버전의 embeddings·templates는 지우지 않는다 (되돌릴 때 사용).

---

## 8. 데이터 보관과 개인정보

손 랜드마크는 생체인식정보로 볼 여지가 있다.

| 테이블 | 저장 내용 | 보관 |
|---|---|---|
| `enrollments.landmarks_json` | 등록 시 앱이 보낸 랜드마크 원본 JSON 전체 | 영구 (재색인의 원천). 재등록 시 이전 원본은 대체(삭제)된다 |
| `embeddings`, `templates` | 원본에서 파생된 벡터 | 재생성 가능한 캐시 |
| `auth_logs.landmarks_json` | 인증 시도 요청 원본 (거절된 입력 포함) | AI팀 추가 학습 데이터 |
| `users` | 이름, 부서 | |

- **보관 기한: ⚠️ 팀 결정 필요.** 명세는 README 명시를 요구한다. 결정되면 이 줄을 고친다.
- `DELETE /users/{id}`는 해당 사용자의 원본·임베딩·템플릿·인증 이력을 **전부** 지운다.
- `scripts/seed_demo_data.py`가 만든 인증 이력은 가짜이며 `landmarks_json`이 `NULL`이다.
  AI팀에 넘길 때는 `landmarks_json IS NOT NULL`인 행만 추출한다.

---

## 9. 알려진 한계

**모델 성능 (AI팀 명시)**

| | 검증셋 | 처음 보는 사용자 |
|---|---|---|
| FAR | 0.95% | **7.16%** |
| FRR | 4.29% | **40.54%** |

처음 보는 사용자는 본인도 10번 중 4번 거부될 수 있다. "FAR 1%를 보장하는 출입 통제 수준"으로 표현하면 안 된다.

**백엔드**

- **스텁 상태**: 바이트 단위로 같은 입력만 유사도 1.0이 나온다. 조금만 달라도 무관한 벡터가 된다.
  스텁 분류기는 입력 해시로 G1~G5를 고르므로, `USE_GESTURE_CLASSIFIER=true`에서는 스텁이 예측한 제스처로 등록해야 통과한다.
- **새로운 동작 등록 불가 (true 모드)**: AI팀 제스처 분류기는 G1~G5 닫힌 집합이고 "미분류" 출력이 없다.
  학습에 없는 동작도 G1~G5 중 하나로 분류된다. 사용자별 자유 동작이 필요하면 `USE_GESTURE_CLASSIFIER=false` + AI팀 검증이 필요하다.
- **오른손 강제 안 함**: 명세의 거절 조건에 손 방향이 없어 서버는 검사하지 않는다 (`handedness`는 원본에만 남음).
- **인증 없음**: `/admin/*`, `DELETE /users`에 접근 제어가 없다. 외부에 노출하지 말 것.
- **인코더 교체 중 인증 중단**: 프로세스에 인코더가 하나라서, 새 인코더를 올린 뒤 재색인이 끝날 때까지 `/verify`는 503이다.
- **SQLite**: 쓰기 동시성이 하나다 (WAL + busy_timeout 5초). 시연 규모에는 충분하며, 규모가 커지면 `DATABASE_URL`을 Postgres로.
- **재등록 시 옛 원본 삭제**: `UNIQUE(user_id, gesture_id, take_no)` 때문에 대체한다. 보관이 필요해지면 스키마 변경 필요.
- 재색인 도중 같은 사용자가 재등록하면 재색인 저장 단계가 500으로 실패할 수 있다 (롤백되어 데이터는 안전, 다시 실행하면 됨). 재색인은 트래픽이 없을 때 한다.

---

## 10. 구조

```
backend/
├── app/
│   ├── main.py                  # 앱, startup(마이그레이션·load_model 1회·기본 데이터)
│   ├── config.py                # 환경변수
│   ├── database.py, models.py   # SQLAlchemy
│   ├── schemas.py               # Pydantic (camelCase)
│   ├── errors.py                # {"detail": {code, reason, message}}
│   ├── seed.py, default_thresholds.json
│   ├── routers/                 # verify, enroll, users, logs, config(+health), admin
│   └── services/
│       ├── ai_gateway.py        # ⚠️ AI 입력 형태 변환·사유 코드 (교체 시 여기만)
│       ├── auth_service.py      # /verify
│       ├── enroll_service.py    # /enroll
│       ├── template_service.py  # centroid 평균 → 재정규화
│       ├── reindex_service.py   # 재색인
│       ├── threshold_service.py
│       └── app_config_service.py
├── ai/                          # ⚠️ 스텁. ai_release로 교체
├── alembic/                     # 마이그레이션
├── examples/                    # 앱팀 전달용 완전한 요청 예시
├── scripts/
│   ├── seed_demo_data.py
│   └── verify_ai_release.py
└── tests/
```

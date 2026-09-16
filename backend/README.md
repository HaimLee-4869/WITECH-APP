# Sign-ID 백엔드

수어 제스처 기반 비접촉 인증 시스템의 FastAPI 백엔드. Flutter 앱과 AI 모델 사이를 연결하고
사용자·등록·인증 이력을 관리한다. 설계 근거는 [`../BACKEND_SPEC.md`](../BACKEND_SPEC.md).

> `ai/`에는 AI팀 릴리스 **`shared-dual-head-v1.1.1`**이 들어 있다 (2026-09-17 교체).
> 이전 릴리스는 `ai_v1.0.0_baseline/`에 보관한다(쓰이지 않음).
> 원본 문서는 `ai/README.md`, `ai/manifest.json`. 성능 한계는 [9장](#9-알려진-한계)을 볼 것.
>
> **판정은 관문 두 개다.** `gesture_score >= Tg AND user_score >= Tu`.
> user 관문만 있던 v1.0.0에서는 본인이 등록과 다른 동작을 해도 통과했다.

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
- `ai.encoder.load_model()` **1회** (가중치 로드, 약 1초)
- 기본 데이터: 제스처 G1~G5, threshold 3종(far1 활성), `app_config` 기본값. 이미 있으면 덮어쓰지 않는다.

팀 사용자 (인증 이력은 만들지 않는다. 실제 테스트로만 쌓인다):

```bash
python scripts/seed_demo_data.py            # 팀원 5명
python scripts/seed_demo_data.py --reset    # 팀 사용자 ID의 등록·이력까지 지우고 재생성
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
제스처 분류기 전환 설정(`USE_GESTURE_CLASSIFIER`)은 dual-head 교체로 사라졌다.
제스처는 분류가 아니라 임베딩으로 판정하고, 조회 키는 항상 앱이 보낸 `gestureId`다.

### `app_config` 테이블 — 운영 중 바꾸는 값 (재시작 불필요)

| 키 | 기본값 | 설명 |
|---|---|---|
| `enrollmentTakes` | 3 | 제스처당 등록 횟수. `/enroll`은 takeNo 1..N을 모두 요구 |
| `enrollmentGestures` | 1 | 등록할 제스처 수. ⚠️ AI팀 확인 대기 (1 또는 5) |
| `captureDurationMs` | 4000 | 앱 촬영 시간. ⚠️ 바꾸면 기존 등록이 무효다 (9장) |
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
| POST | `/admin/threshold` | 활성 운영점 전환 `{basis: "default" \| "demo_relaxed"}` (두 관문이 함께 바뀐다) |
| POST | `/admin/reindex` | 재색인 `{modelVersion, dryRun}` |
| PATCH | `/admin/config` | `app_config` 변경 |
| POST/GET/DELETE | `/debug/challenge` | 앱의 Challenge 판정 로그 (개발용, 6.6장) |

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
- **오른손만 허용.** `frames[].handedness`를 MediaPipe 값 그대로 보낼 것. 왼손이 섞이면 422 `wrong_hand`로
  거절된다. handedness를 아예 보내지 않으면 모델이 검사하지 못하므로 앱이 화면에서 강제해야 한다
  (실제 왼손 입력을 `Right`로 위장해 보내면 인식률이 떨어진다).
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
| `gestureId` | ✅ | 운영 설정(`USE_GESTURE_CLASSIFIER=false`)에서 필수 |
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
  "captureDurationMs": 4000,
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
| `below_threshold` | 명세 | 200 | 숫자 | **user 관문 미달.** 동작은 맞지만 본인으로 보이지 않는다 |
| **`gesture_gate`** | **dual-head 추가** | 200 | 숫자 | **gesture 관문 미달.** 등록한 동작이 아니다 (본인이어도 거부) |
| `no_template` | 명세 | 200 | `null` | 해당 (사용자, 제스처, 활성 모델 버전) 템플릿 없음. dual-head는 user·gesture 둘 다 있어야 한다 |
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
| `wrong_hand` | 프레임 `handedness`에 왼손이 있음 (명세 1장에 없던 조건) | 오른손을 사용해주세요. 이 모델은 오른손 동작만 인식합니다. |
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

dual-head는 관문이 둘이라 **운영점 하나가 두 값(Tu, Tg)** 을 갖는다. DB에는 관문마다
한 행씩(`gate` 컬럼) 들어가고, `basis`로 묶어 함께 전환한다. 요청마다 활성 행을 읽으므로
**전환 즉시 반영, 재시작 불필요.**

| basis | Tu (본인) | Tg (동작) | 검증셋 user FAR/FRR |
|---|---|---|---|
| `default` (기본) | 0.342350 | 0.902032 | 4.05% / 4.29% |
| `demo_relaxed` | 0.293309 | 0.902032 | 4.76% / 2.86% |

`demo_relaxed`는 **user 관문만** 낮춘다. 시연에서 본인 거부가 잦을 때 쓴다.
동작이 안 맞아 막히는 경우(`gesture_gate`)는 이 운영점으로 풀리지 않는다.

```bash
curl localhost:8000/admin/thresholds
curl -X POST localhost:8000/admin/threshold \
  -H 'Content-Type: application/json' -d '{"basis": "demo_relaxed"}'
```

`auth_logs`에는 시도마다 두 점수와 두 임계값이 모두 남는다.

### 촬영 길이를 바꿀 때 (`captureDurationMs`)

⚠️ **기존 등록 템플릿이 무효가 된다.** 9장 첫 항목을 먼저 읽을 것. 순서는 이렇다.

```bash
curl -X PATCH localhost:8000/admin/config \
  -H 'Content-Type: application/json' -d '{"captureDurationMs": 4000}'
curl localhost:8000/config                      # 반영 확인

python scripts/clear_enrollments.py --dry-run   # 지울 대상 확인
python scripts/clear_enrollments.py             # 원본·임베딩·템플릿 삭제
```

서버를 멈출 필요는 없다(요청마다 DB에서 읽는다). 사용자와 인증 이력은 남는다.
이후 앱을 다시 시작해 새 길이로 **전원 재등록**한다.

시연 리허설에서 거부가 잦으면 `eer`로 내린다. `auth_logs.threshold`에 시도마다 쓴 값이 남는다.

기본값은 `app/default_thresholds.json`에서 들어간다. startup 시 **로드된 인코더 버전**에 threshold가 없으면 이 파일로 채운다.

---

## 6.5 Challenge 설정 (안티스푸핑)

판정은 **앱이** 한다. 서버는 임계값만 내려준다. 앱에 상수로 박으면 자유 제스처
데이터로 재도출했을 때 앱을 다시 배포해야 하기 때문이다.

- 원본: `challenge_response/configs/challenge_config.json` (도출 근거 `_source` 포함)
- 서버 기본값: `app/default_challenge_config.json` (판정용 값만 camelCase로)
- 저장 위치: `app_config` 테이블의 `challenge` 키
- 앱 전달: `GET /config`의 `challenge` 블록

```bash
# 원본이 갱신되면 DB에 반영 (서버 재시작 불필요)
python scripts/import_challenge_config.py --dry-run
python scripts/import_challenge_config.py

# 실기기 체감에 맞춰 일부만 조정
curl -X PATCH localhost:8000/admin/config -H 'Content-Type: application/json' \
  -d '{"challenge": {"timing": {"perActionTimeoutMs": 2500}}}'
curl -X PATCH localhost:8000/admin/config -H 'Content-Type: application/json' \
  -d '{"challenge": {"escapeFrames": 8, "shapeHoldFrames": 5}}'

# 단계 수 (3단계 → 2단계). 코드 수정 없이 바뀐다
curl -X PATCH localhost:8000/admin/config -H 'Content-Type: application/json' \
  -d '{"challenge": {"steps": {"numShapes": 1, "numMoves": 1}, "timing": {"totalTimeoutMs": 4000}}}'
```

PATCH는 **깊은 병합**이다. 보낸 키만 바뀌고 나머지는 그대로다. 단, `directionMap`은
통째로 바뀐다 — 방향 하나만 바뀐 표가 남으면 나머지가 옛 도출값이 되어 조용히
어긋나기 때문이다. 검증에 실패하면 **아무것도 바꾸지 않는다.**

로그에 남는 것:
- 바뀐 값마다 이전 → 이후. 프레임 수 값은 `frameReferenceFps` 기준 몇 ms인지 함께
- `totalTimeoutMs < perActionTimeoutMs × 단계 수`면 경고 (마지막 단계가 죽는다)

**null은 null로 둔다.** `shapeConfidenceMin`은 "분포가 겹쳐 도출하지 못했다"는 뜻이고
0으로 채우면 게이트가 켜진 것처럼 보인다. `fistMaxTipWristRatio`도 마찬가지다.

### 앱 쪽 제약 (앱 README에도 있다)

- **`minDetectionScore`는 앱에서 작동하지 않는다.** `hand_landmarker` 3.0.1이 검출
  신뢰도를 주지 않는다. 앱은 `score`에 플러그인 하한값(0.6)을 넣는데 이건 측정값이
  아니라 "이 값 이상"이라는 뜻이다. 0.938과 비교하면 매 프레임 미달이 되므로
  (실기기에서 실제로 그랬다) 측정값이 아닌 소스는 관문을 건너뛴다.
  `TRACKING_UNSTABLE`은 앱에서 발생하지 않는다.
- **`maxLostFrames = 38`은 측정값이 아니다.** 근거 부족으로 도출하지 못해 2026-09-16에
  정한 임시값이다. 실사용 세션이 쌓이면 다시 재야 한다.
- 앱 판정이라 **앱을 조작하면 우회된다.** 서버는 Challenge 결과를 받지도 검증하지도
  않는다. 실제 출입 통제에 쓰려면 서버 판정으로 바꿔야 한다.

## 6.6 Challenge 판정 로그 (개발용)

앱이 판정하므로 서버에는 근거가 남지 않는다. 실기기 화면의 진단 패널은 프레임마다
바뀌어 읽을 수 없어서, 앱이 한 줄씩 보내고 여기서 파일과 콘솔에 남긴다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/debug/challenge` | `{sessionId, lines[]}`. 앱이 모아서 보낸다(14fps면 초당 14줄) |
| GET | `/debug/challenge` | 로그 전문. `?lines=50`이면 마지막 50줄 |
| DELETE | `/debug/challenge` | 비운다. 세션 하나만 깨끗이 보려고 |

- 파일: `backend/logs/challenge_debug.log` (git에 올라가지 않는다)
- 콘솔: `challenge.debug` 로거. 모든 줄이 `CHALLENGE `로 시작한다
- 줄바꿈과 제어문자를 지우고 2000바이트로 자른다. 한 줄 형식이 깨지면 grep이
  소용없어지기 때문이다

⚠️ **인증이 없다.** 앱이 보낸 문자열을 그대로 기록한다. 외부에 노출하는 배포에서는
`DEBUG_LOG_ENABLED=false`로 끈다(404).

## 7. ai_release 교체 절차

### 7.0 가장 먼저: AI 입력 형태 확인

> **v1.0.0 교체 시 실제로 틀렸던 부분이다.** 릴리스가 바뀌면 여기부터 확인한다.
>
> 현재 백엔드가 `embed()` / `classify_gesture()`에 넘기는 형태 (v1.0.0 기준, 실측 확인):
>
> ```python
> {
>   "width": 720, "height": 1280,          # 최상위. camera 중첩이 아니다
>   "frames": [{"tMs": 0.0, "landmarks": [[x, y, z], ...21개] | None,
>              "handedness": "Right", "valid": True}, ...]
> }
> ```
>
> 이 변환은 **`app/services/ai_gateway.py`의 `to_ai_input()` 한 곳**에만 있다.
> 등록·인증·재색인·검증 스크립트가 모두 이 함수를 거친다. 모듈이 바뀌면 이 함수만 고친다.
>
> `valid: true`를 붙이는 이유: 이걸 빼면 모듈이 21×3 위반·NaN 프레임을 **에러 없이 무시**해서
> 명세 1장의 거절 조건이 동작하지 않는다.
>
> 함께 확인할 것:
> - `InvalidSequenceError` 위치. v1.0.0은 `encoder.py`가 아니라 **`features.py`에만** 정의한다.
>   백엔드는 `ai_gateway.py`가 양쪽을 다 시도해 받아온다.
> - 예외에 사유 코드 속성(`reason`)이 있는지. v1.0.0은 없어서 메시지 문구로 추정한다
>   (`_REASON_PATTERNS`). 7.1의 검증 스크립트가 추정이 틀리면 WARN으로 알려준다.
> - `classify_gesture()` 라벨이 `G1`~`G5` 문자열인지 (`gestures` 테이블 ID와 같아야 함)

### 7.1 절차

1. **입력 형태 확인** (7.0). AI팀 문서·`encoder.py` docstring과 `to_ai_input()`을 비교한다.
2. **파일 복사**: `ai_release/`의 `encoder.py`, `features.py`, `model_defs.py`, `weights/`, `preprocess.json`,
   `thresholds.json`, `manifest.json`을 `backend/ai/`에 복사한다 (README는 `ai/AI_RELEASE_README.md`로).
   `ai/__init__.py`는 비워 둔다 (릴리스의 `__init__.py`를 덮어쓰지 말 것 — 상대 import가 꼬인다).
   `manifest.json`의 sha256으로 파일 무결성을 확인한다.
3. **의존성 병합**: `ai_release/requirements.txt`의 `torch` 등을 `backend/requirements.txt`에 추가.
   `numpy==1.26.4`가 양쪽에서 같은지 확인. `pip install -r requirements.txt`.
   (v1.0.0: `torch==2.8.0`. CPU 휠로 충분하다.)
4. **가중치 확인**: `python ai_release/smoke_test.py`
5. **계약 검증**: `python scripts/verify_ai_release.py`
   - 시그니처, 임베딩 `(128,)` `float32`, L2 norm=1, 결정성, `embed_batch` 일치, 분류 라벨, 거절 조건 6종.
   - `FAIL`이 있으면 종료 코드 1. `embed`부터 줄줄이 실패하면 7.0의 입력 형태가 다른 것이다.
   - `[WARN] 사유 코드 ...`가 뜨면 `_REASON_PATTERNS` 조정.
6. **threshold 반영**: `python scripts/import_thresholds.py` (`ai/thresholds.json` → `app/default_thresholds.json`).
   운영점 이름을 `far_1_percent`→`far1` 식으로 바꾸고 값은 풀 정밀도로 옮긴다.
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
8. **테스트 재실행**: `pytest`. `tests/test_ai_contract.py`가 AI 모듈 계약(시그니처·형태·거절 조건)을 직접 검사한다.
   테스트의 유사도 기대값은 합성 좌표 기준이므로, 모델이 바뀌면 `tests/test_threshold.py`의
   `UNRELATED_SEED`처럼 두 운영점 사이에 오도록 고른 값은 다시 골라야 할 수 있다.

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

**모델 성능 (AI팀 `ai/calibration_report.md`)**

| 지표 (P08~P10, 신규 사용자 7,275 trial) | 값 |
|---|---|
| Accuracy | 95.77% |
| **Genuine FRR** | **28.04%** |
| Combined Attack FAR | 3.22% |
| Wrong-Gesture FAR | 1.52% |
| **Same-Gesture Impostor FAR** | **17.34%** |
| Random Impostor FAR | 0.13% |

검증셋(학습에 참여한 사용자) 수치는 gesture EER 0%, user EER 4.17%인데, **그대로 인용하면 안 된다.**
AI팀 문서가 "validation Gesture EER 0%를 자유 제스처 성능으로 제시하지 말 것"이라고 명시한다.

신규 사용자 FRR 28.04%는 본인도 10번 중 3번쯤 거부된다는 뜻이다(v1.0.0의 40.54%에서 개선).
주 병목은 같은 동작을 아는 공격자(17.34%)다. 출입 통제 수준으로 표현하면 안 된다.

**P08~P10도 제스처는 G1~G5다.** "Unseen User + Known Gesture"이지 자유 제스처 결과가 아니다.

**백엔드**

- **`encoder.MODEL_VERSION`이 `shared-dual-head-v1.1.0`이다.** 패키지·thresholds·manifest는 `v1.1.1`인데
  코드 상수만 올라가지 않았다(AI팀 확인된 사항). 백엔드는 이 상수를 DB에 기록하므로 `/health`와
  `templates.model_version`에는 **v1.1.0**으로 남는다. 동작에는 영향이 없지만, 다음 릴리스에서
  진짜 v1.1.1이 오면 구분이 안 되므로 그때 AI팀에 상수 갱신을 요청한다.
- **자유 제스처는 아직 미검증**: 체크포인트는 여전히 G1~G5로 학습됐다. 구조적으로는 제스처를
  임베딩으로 보므로 개인 제스처가 가능하지만, AI팀이 "unseen free-gesture generalization is not
  yet validated"라고 명시했다.
- **Challenge는 앱이 판정한다**: 서버는 임계값만 내려주고 결과를 검증하지 않는다.
  앱을 조작하면 동작 없이 통과시킬 수 있다. 시연 범위의 결정이다 (6.5장).
- **Challenge의 검출 신뢰도 관문이 꺼져 있다**: 플러그인이 신뢰도를 주지 않아
  `minDetectionScore`가 앱에서 적용되지 않는다(앱이 넣는 0.6은 측정값이 아닌 하한값이다).
  `TRACKING_UNSTABLE`이 발생하지 않는다.
- **Challenge `maxLostFrames`는 임시값**: 38은 측정으로 도출한 값이 아니다.
- **모델을 바꾸면 등록이 무효다**: v1.0.0 → v1.1.1처럼 벡터 공간이 달라지면 재색인으로 해결되지 않는다
  (재색인은 같은 모델의 임베딩 재생성이다). `scripts/clear_enrollments.py` 후 전원 재등록.
- **등록 정책**: 릴리스 기준 "개인 제스처 1개 × 3회"다 (`enrollmentGestures=1`, `enrollmentTakes=3`).
- **촬영 길이를 바꾸면 기존 등록이 무효가 된다.** `captureDurationMs`는 화면 설정이 아니라
  **AI 모델의 입력 feature**다(학습 분포: 평균 3.29초, 표준편차 1.15초). 등록과 인증의 길이가
  다르면 같은 사람·같은 동작도 유사도가 크게 떨어진다. 합성 입력 실측에서 2초로 등록한
  템플릿에 5초 인증을 하면 **0.51**로, 활성 threshold 0.6275 아래였다(무관한 동작이 0.43).
  에러 없이 인증만 실패하므로 원인을 찾기 어렵다. 값을 바꾸면 `PATCH /admin/config`가 경고를
  로그에 남기고, **`scripts/clear_enrollments.py`로 정리한 뒤 전원 재등록해야 한다.**
  (인코더 교체는 다르다. 그건 원본이 남아 있으므로 `POST /admin/reindex`로 재생성한다.)
- **오른손 전용**: 프레임에 왼손 `handedness`가 있으면 AI 모듈이 거절한다(422 `wrong_hand`).
  handedness를 보내지 않으면 검사되지 않으므로 앱이 화면에서 강제해야 한다.
- **테스트 데이터는 합성 좌표**: 테스트의 유사도 값(같은 입력 1.0 등)은 배선 확인용이며 실제 인식 성능이 아니다.
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
├── ai/                          # AI팀 릴리스 shared-dual-head-v1.1.1
├── ai_v1.0.0_baseline/          # 이전 릴리스 보관 (import되지 않음)
├── alembic/                     # 마이그레이션
├── examples/                    # 앱팀 전달용 완전한 요청 예시
├── scripts/
│   ├── seed_demo_data.py
│   ├── clear_enrollments.py     # 등록 원본·임베딩·템플릿 삭제 (촬영 조건이 바뀐 경우)
│   ├── import_thresholds.py     # ai/thresholds.json → app/default_thresholds.json
│   └── verify_ai_release.py
└── tests/
```

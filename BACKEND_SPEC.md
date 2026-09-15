# Sign-ID 백엔드 구현 명세

> 수어 제스처 기반 비접촉 인증 시스템의 **FastAPI 백엔드**.
> Flutter 앱과 AI 모델 사이를 연결하고, 사용자·등록·인증 이력을 관리한다.

---

## 0. 가장 중요한 원칙

### 원칙 A — AI 모델은 별도 서버가 아니라 import하는 라이브러리다

```
앱 ──HTTP──> 이 서버 (FastAPI)
                 │
                 └── import ai.encoder   ← 같은 파이썬 프로세스 안
                        └── weights/*.pt
```

AI팀 코드를 `backend/ai/`에 두고 함수로 호출한다. HTTP 호출이 아니다.

### 원칙 B — AI팀 결과물 없이 전부 만들 수 있다

`ai_release/`는 아직 도착하지 않았다. **스텁(가짜) 구현으로 시작하고, 나중에 파일만 교체한다.**

스텁은 실제와 같은 시그니처·같은 반환 형태를 갖고, 같은 입력에 항상 같은 값을 돌려줘야 한다. 그래야 등록·인증·유사도·재색인 전체 흐름을 진짜처럼 검증할 수 있다.

### 원칙 C — 랜드마크 원본이 진실의 원천, 임베딩은 캐시다

인코더가 바뀌면 저장된 임베딩은 **전부 무효**가 된다. 다른 벡터 공간의 값이라 코사인 유사도가 의미를 잃는다. 사용자를 다시 불러 등록시킬 수 없으므로:

```
enrollments  → 랜드마크 원본 (영구 보관, 절대 삭제 금지)
embeddings   → 벡터 + model_version (언제든 재생성 가능)
```

모델이 바뀌면 `POST /admin/reindex`로 저장된 랜드마크를 새 인코더에 다시 통과시킨다.

이미 한 번 일어났다: AI팀이 D=169(pose 포함) → D=127(hand only)로 바꾸면서 임베딩 공간이 완전히 달라졌다. 앞으로도 일어난다.

### 원칙 D — threshold와 설정값은 DB에 있고 앱에 없다

앱에 박으면 운영 중 조정이 불가능하다. 시연 리허설에서 거부율이 높으면 값을 바꿔야 할 수 있다.

---

## 1. AI 모델 계약 (AI팀 확정, 2026-09-10)

이 값들은 확정이다. 임의로 바꾸지 말 것.

| 항목 | 값 |
|---|---|
| 인증 모델 버전 | `handonly-supcon-v1.0.0` |
| 제스처 모델 버전 | `handonly-gesture-1dcnn-v1.0.0` |
| 임베딩 차원 | 128, `float32` |
| 임베딩 정규화 | L2 정규화된 상태로 반환됨 |
| 내부 feature | `[T=32, D=127]` |
| threshold 방식 | Global 하나 (사용자별·제스처별 아님) |
| 배포 threshold | `0.627516` |
| 등록 횟수 | 제스처당 3회 |
| 손 | **오른손만 허용** |
| 추론 | CPU 가능, GPU 불필요 |
| 동시 호출 | 안전함 (내부 RLock). 백엔드 락 불필요 |

### 함수 시그니처

```python
MODEL_VERSION = "handonly-supcon-v1.0.0"
GESTURE_MODEL_VERSION = "handonly-gesture-1dcnn-v1.0.0"

load_model(device="cpu")                          # startup 1회
embed(frames) -> np.ndarray                       # (128,) L2 정규화됨
embed_batch(list_of_frames) -> np.ndarray         # (N,128)
classify_gesture(frames) -> tuple[str, float]     # ("G1", 0.93)
```

**코사인 유사도, centroid 생성, threshold 비교는 백엔드 책임이다.** AI 모듈은 임베딩만 만든다.

### 앱이 보내는 입력

MediaPipe Hand 21점 xyz + 프레임별 `tMs` + **카메라 `width`/`height`**.

`width`/`height`는 새로 추가된 필수 항목이다. 학습 시 영상 종횡비를 보정했기 때문에 없으면 거절된다. **앱에도 이 필드를 추가해야 한다** (별도 작업).

### 거절 조건 (`InvalidSequenceError`)

AI 모듈이 다음 경우 `InvalidSequenceError(ValueError)`를 던진다.

- 전체 캡처 프레임 8개 미만
- 유효한 손 랜드마크 프레임 8개 미만
- 첫–마지막 timestamp 간격 750ms 미만
- `tMs`가 증가하지 않음
- 카메라 `width`/`height` 누락
- landmark가 21×3 형식이 아니거나 NaN/Inf 포함

**백엔드는 이를 422로 변환하고, 앱이 재촬영 안내를 띄울 수 있게 사유 코드를 함께 내려준다.**

8~31 프레임은 AI 모듈이 내부에서 선형 보간해 T=32로 맞춘다. 백엔드가 패딩하지 말 것.

### ⚠️ 놓치기 쉬운 것: centroid 재정규화

등록 임베딩 3개를 평균하면 **norm이 1이 아니게 된다.** 재정규화하지 않으면 유사도가 전부 미묘하게 낮아지고, threshold `0.627516`이 안 맞는다. **에러는 나지 않는다.**

```python
template = np.mean(enrollment_embeddings, axis=0)
template /= (np.linalg.norm(template) + 1e-12)
score = float(query_embedding @ template)
```

---

## 2. 성능 한계 (반드시 인지할 것)

AI팀이 명시한 경고다.

| | 검증셋 | 처음 보는 사용자 |
|---|---|---|
| FAR | 0.95% | **7.16%** |
| FRR | 4.29% | **40.54%** |

**처음 보는 사용자의 FRR 40.54%는 본인도 10번 중 4번 거부된다는 뜻이다.**

AI팀 원문: "실제 출입 통제 수준의 FAR 1%를 보장하는 모델로 표현하면 안 된다."

### 백엔드 대응

`thresholds.json`에 세 가지 운영점이 있다. **전부 DB에 넣고, 활성 행만 바꿔서 전환할 수 있게 한다.**

| 기준 | threshold | Val FAR | Val FRR |
|---|---|---|---|
| FAR≤1% (기본) | 0.627516 | 0.95% | 4.29% |
| EER | 0.436046 | 2.86% | 2.86% |
| FAR≤5% | 0.272128 | 5.00% | 2.14% |

시연에서 거부가 잦으면 EER 지점으로 내릴 수 있어야 한다. 서버 재시작 없이 바뀌어야 한다.

---

## 3. 기술 스택

```
Python 3.11
FastAPI
SQLAlchemy 2.x
SQLite (파일 기반, 나중에 Postgres 전환 가능하게)
Alembic (마이그레이션)
Pydantic v2
numpy 1.26.4      ← AI 모듈과 버전 맞출 것
pytest, httpx     ← 테스트
```

`torch`는 실제 `ai_release`가 들어올 때 추가한다. 스텁 단계에서는 numpy만 있으면 된다.

---

## 4. 폴더 구조

```
backend/
├── requirements.txt
├── README.md
├── .env.example
├── app/
│   ├── main.py              # FastAPI 앱, startup에서 load_model()
│   ├── config.py            # 설정, 환경변수
│   ├── database.py          # 세션, 엔진
│   ├── models.py            # SQLAlchemy 모델
│   ├── schemas.py           # Pydantic 요청/응답
│   ├── deps.py              # 의존성 주입
│   ├── routers/
│   │   ├── verify.py
│   │   ├── enroll.py
│   │   ├── users.py
│   │   ├── logs.py
│   │   ├── config.py
│   │   └── admin.py
│   └── services/
│       ├── auth_service.py      # 인증 로직
│       ├── enroll_service.py    # 등록 로직
│       ├── template_service.py  # centroid 생성·재정규화
│       └── reindex_service.py   # 재색인
├── ai/
│   ├── __init__.py
│   ├── encoder.py           # ← ai_release가 오면 교체될 자리
│   ├── features.py          # ← 교체될 자리
│   └── stub_notice.md       # 현재 스텁임을 명시
├── alembic/
├── scripts/
│   ├── seed_demo_data.py    # 시연용 사용자·이력 생성
│   └── verify_ai_release.py # ai_release 교체 후 검증
└── tests/
    ├── test_enroll.py
    ├── test_verify.py
    ├── test_reindex.py
    ├── test_threshold.py
    └── test_invalid_input.py
```

---

## 5. 스텁 AI 모듈

`ai/encoder.py`에 아래를 만든다. **실제 파일이 오면 통째로 덮어쓴다.**

```python
"""
⚠️ 스텁 구현. AI팀의 ai_release/encoder.py로 교체될 예정.
시그니처와 반환 형태는 실제와 동일하게 유지한다.
"""
import hashlib
import numpy as np

MODEL_VERSION = "stub-v0"
GESTURE_MODEL_VERSION = "stub-gesture-v0"
EMBEDDING_DIM = 128

class InvalidSequenceError(ValueError):
    """AI 모듈이 입력을 거절할 때. 실제 모듈과 같은 타입."""

_loaded = False

def load_model(device: str = "cpu") -> None:
    global _loaded
    _loaded = True

def _validate(frames) -> None:
    # 실제 모듈과 같은 거절 조건을 구현할 것 (1장 참고)
    ...

def _deterministic_vector(frames) -> np.ndarray:
    """같은 입력 → 항상 같은 벡터. 테스트 재현성에 필수."""
    key = repr(frames).encode()
    seed = int(hashlib.sha256(key).hexdigest()[:8], 16)
    v = np.random.RandomState(seed).randn(EMBEDDING_DIM).astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-12)

def embed(frames) -> np.ndarray:
    _validate(frames)
    return _deterministic_vector(frames)

def embed_batch(list_of_frames) -> np.ndarray:
    if not list_of_frames:
        return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    return np.stack([embed(f) for f in list_of_frames])

def classify_gesture(frames) -> tuple[str, float]:
    _validate(frames)
    v = _deterministic_vector(frames)
    idx = int(abs(v[0]) * 1000) % 5
    return (f"G{idx + 1}", 0.90)
```

**`_deterministic_vector`가 핵심이다.** 매번 랜덤이면 같은 사람이 같은 동작을 해도 인증이 안 되므로 흐름 검증이 불가능하다.

### 스텁으로 검증 가능한 것

- 등록 → 템플릿 생성 → 인증 통과
- 다른 입력 → 유사도 낮음 → 인증 거부
- threshold 변경 시 판정이 바뀌는지
- 재색인 후 모든 템플릿의 `model_version`이 갱신되는지
- 잘못된 입력이 422로 변환되는지

`hashlib`을 쓰는 이유: 파이썬 `hash()`는 실행마다 값이 달라져서(PYTHONHASHSEED) 재현되지 않는다.

---

## 6. DB 스키마

```sql
users
  id              TEXT PK
  name            TEXT NOT NULL
  department      TEXT
  created_at      TIMESTAMP

gestures
  id              TEXT PK          -- 'G1' ~ 'G5'
  label           TEXT

enrollments                        -- 랜드마크 원본. 영구 보관.
  id              INTEGER PK
  user_id         TEXT FK
  gesture_id      TEXT FK
  take_no         INTEGER          -- 1..3
  landmarks_json  TEXT NOT NULL    -- 앱이 보낸 raw payload 전체
  nominal_fps     REAL
  duration_ms     INTEGER
  camera_width    INTEGER NOT NULL
  camera_height   INTEGER NOT NULL
  captured_at     TIMESTAMP
  created_at      TIMESTAMP
  UNIQUE(user_id, gesture_id, take_no)

embeddings                         -- 파생 캐시. 재생성 가능.
  id              INTEGER PK
  enrollment_id   INTEGER FK
  model_version   TEXT NOT NULL
  vector          BLOB NOT NULL    -- float32 128개
  created_at      TIMESTAMP
  UNIQUE(enrollment_id, model_version)

templates                          -- centroid. 재정규화된 상태로 저장.
  id              INTEGER PK
  user_id         TEXT FK
  gesture_id      TEXT FK
  model_version   TEXT NOT NULL
  centroid        BLOB NOT NULL
  take_count      INTEGER
  updated_at      TIMESTAMP
  UNIQUE(user_id, gesture_id, model_version)

thresholds
  id              INTEGER PK
  scheme          TEXT NOT NULL    -- 'global' | 'gesture'
  gesture_id      TEXT NULL        -- global이면 NULL
  model_version   TEXT NOT NULL
  value           REAL NOT NULL
  far             REAL
  frr             REAL
  basis           TEXT             -- 'far1' | 'eer' | 'far5'
  is_active       BOOLEAN NOT NULL DEFAULT 0
  created_at      TIMESTAMP

auth_logs
  id              INTEGER PK
  user_id         TEXT FK
  claimed_gesture_id   TEXT        -- 앱이 주장한 것 (있으면)
  predicted_gesture_id TEXT        -- 분류 모델이 판정한 것
  gesture_confidence   REAL
  score           REAL
  threshold       REAL
  passed          BOOLEAN
  fail_reason     TEXT             -- 'below_threshold' | 'no_template' | 'invalid_input' | 'gesture_mismatch'
  auth_model_version    TEXT
  gesture_model_version TEXT
  landmarks_json  TEXT             -- 추가 학습 데이터
  latency_ms      INTEGER
  created_at      TIMESTAMP

app_config
  key             TEXT PK
  value           TEXT
  updated_at      TIMESTAMP
```

### 설계 의도

**`claimed`와 `predicted` 제스처를 분리한 이유**: 인증 실패가 제스처 분류 오류 때문인지 임베딩 불일치 때문인지 구분해야 한다. AI팀도 제스처 오분류를 분석 항목으로 두고 있다.

**`auth_logs.landmarks_json`을 저장하는 이유**: 인증 시도 하나하나가 추가 학습 데이터다. 시연 기간에 쌓인 데이터를 AI팀에 넘길 수 있다.

**`thresholds.is_active`**: 여러 운영점을 미리 넣어두고 활성 행만 바꾼다. 서버 재시작 없이 전환되어야 한다.

**`templates`에 `model_version`이 들어가는 이유**: 재색인 중에도 기존 버전으로 인증이 계속 되어야 한다. 새 버전 템플릿이 다 만들어진 뒤 전환한다.

### 개인정보 주의

손 랜드마크는 생체인식정보로 볼 여지가 있다. 저장 사실과 보관 기한을 README에 명시하고, `DELETE /users/{id}`로 관련 데이터를 전부 지울 수 있게 한다.

---

## 7. API

### `POST /verify`

```jsonc
// 요청
{
  "userId": "kim",
  "gestureId": "G3",           // 선택. 없으면 분류 모델 결과만 사용
  "capturedAt": "2026-09-16T10:39:01+09:00",
  "camera": { "width": 720, "height": 1280 },
  "nominalFps": 30,
  "durationMs": 2000,
  "frames": [
    { "tMs": 0,  "lm": [[0.51,0.62,0.0], /* 21개 */] },
    { "tMs": 33, "lm": [ /* ... */ ] }
  ]
}

// 응답 200
{
  "score": 0.7134,
  "threshold": 0.627516,
  "passed": true,
  "predictedGesture": "G3",
  "gestureConfidence": 0.93,
  "modelVersion": "handonly-supcon-v1.0.0",
  "latencyMs": 42
}

// 응답 422 (InvalidSequenceError)
{
  "detail": {
    "code": "invalid_sequence",
    "reason": "insufficient_valid_frames",
    "message": "손이 충분히 인식되지 않았습니다. 다시 시도해주세요."
  }
}
```

**처리 순서**

1. 입력 검증 → 실패 시 422 (로그에 `invalid_input`으로 남김)
2. `classify_gesture(frames)` → 제스처 판정
3. `gestureId`가 왔는데 예측과 다르면 → 거부, `fail_reason='gesture_mismatch'`
4. `embed(frames)` → query 임베딩
5. `(user_id, predicted_gesture, active_model_version)` 템플릿 조회 → 없으면 `no_template`
6. 코사인 유사도 = `query @ template` (둘 다 정규화 상태이므로 내적)
7. 활성 threshold와 비교
8. `auth_logs`에 기록 (성공·실패 모두, 랜드마크 포함)

### `POST /enroll`

```jsonc
{
  "userId": "kim",
  "gestureId": "G3",
  "camera": { "width": 720, "height": 1280 },
  "takes": [
    { "takeNo": 1, "capturedAt": "...", "nominalFps": 30, "durationMs": 2000, "frames": [...] },
    { "takeNo": 2, ... },
    { "takeNo": 3, ... }
  ]
}
```

**처리 순서**

1. 각 take 검증 → 하나라도 실패하면 전체 422 (부분 등록 금지)
2. `enrollments`에 랜드마크 원본 저장
3. `embed_batch([...])` → 임베딩 3개
4. `embeddings`에 저장
5. 평균 → **재정규화** → `templates`에 저장
6. 응답에 `enrolled`, `takeCount`, `required`

같은 `(user, gesture)` 재등록 시 기존 것을 대체한다.

### `GET /config`

```jsonc
{
  "enrollmentTakes": 3,
  "enrollmentGestures": 1,      // ⚠️ AI팀 확인 대기 중. 아래 참고
  "captureDurationMs": 2000,
  "handRequired": "right",      // 오른손만 허용
  "modelVersion": "handonly-supcon-v1.0.0"
}
```

`app_config` 테이블에서 읽는다. **앱은 이 값을 받아서 등록 화면을 그린다.**

> **미확정 항목**: `enrollmentGestures`가 1인지 5인지 AI팀 답변 대기 중이다. DB 구조는 둘 다 지원하므로(`templates`가 `user_id + gesture_id` 키) 백엔드는 영향이 없다. 기본값 1로 두고 `app_config`에서 바꿀 수 있게 한다.

### 나머지

```
GET    /users                → 목록
POST   /users                → 생성 (name, department)
DELETE /users/{id}           → 사용자 및 관련 데이터 전부 삭제
GET    /logs?limit&offset&userId&passed   → 인증 이력 (관리자 화면)
GET    /stats/monthly?months=5            → 월별 인증 건수 (차트)
GET    /health               → { status, modelVersion, activeThreshold, dbOk }
POST   /admin/threshold      → { basis: "eer" } 활성 threshold 전환
POST   /admin/reindex        → 재색인 (아래)
```

### `POST /admin/reindex`

```jsonc
// 요청
{ "modelVersion": "handonly-supcon-v1.1.0", "dryRun": false }

// 응답
{
  "fromVersion": "handonly-supcon-v1.0.0",
  "toVersion": "handonly-supcon-v1.1.0",
  "enrollmentsProcessed": 45,
  "templatesRebuilt": 15,
  "failed": 0,
  "elapsedMs": 1230
}
```

**처리 순서**

1. 현재 `ai.encoder.MODEL_VERSION`이 요청값과 일치하는지 확인 (다르면 400)
2. 모든 `enrollments`의 `landmarks_json`을 읽어 `embed_batch()`에 넣음
3. 새 `model_version`으로 `embeddings` 저장
4. `(user, gesture)`별 centroid 재생성 → 재정규화 → `templates` 저장
5. **전부 성공한 뒤에** 활성 버전을 전환
6. 실패한 건이 있으면 전환하지 않고 목록 보고

중간에 실패해도 기존 버전으로 인증이 계속 되어야 한다.

---

## 8. startup / 설정

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    ai.encoder.load_model(device="cpu")   # 반드시 1회만
    await ensure_seed_data()
    yield
```

요청마다 모델을 로드하면 매번 수백 ms가 낭비된다. **startup에서 한 번만.**

동시 호출은 AI 모듈 내부 RLock으로 처리되므로 백엔드에서 별도 락을 걸지 말 것.

`.env.example`:
```
DATABASE_URL=sqlite:///./signid.db
AI_DEVICE=cpu
LOG_LEVEL=INFO
CORS_ORIGINS=*
```

---

## 9. 시드 데이터

`scripts/seed_demo_data.py`로 시연용 데이터를 만든다. 관리자 화면에 표가 비어 있으면 곤란하다.

- 사용자 6명 (목업 기준: 홍길동/김길동/오박사/둘리/또치/고길동, 부서는 개발팀/인사팀/영업팀)
- 제스처 G1~G5
- `thresholds` 3행 (far1 활성, eer·far5 비활성)
- `auth_logs` 최근 5개월치, 표 스크롤과 차트가 보이게 충분히
- `app_config` 기본값

---

## 10. 테스트

`pytest` + `httpx`. SQLite는 테스트마다 임시 파일 또는 인메모리.

반드시 포함할 것:

- **등록 → 인증 통과**: 같은 입력으로 등록하고 인증하면 유사도 1.0에 가깝고 통과
- **다른 입력 → 거부**: 무관한 입력은 threshold 아래
- **centroid 재정규화**: 평균 후 norm이 1인지 검증. 이게 깨지면 조용히 틀린다
- **threshold 전환**: `POST /admin/threshold`로 바꾸면 같은 입력의 판정이 뒤집히는지
- **재색인**: 버전 바꾸고 재색인하면 모든 템플릿의 `model_version`이 갱신되는지
- **재색인 실패 시 롤백**: 중간 실패 시 기존 버전이 유지되는지
- **입력 거절 6종**: 1장의 각 거절 조건이 422와 올바른 사유 코드로 변환되는지
- **부분 등록 금지**: take 3개 중 하나가 잘못되면 아무것도 저장되지 않는지
- **동시 요청**: 여러 요청을 병렬로 보내도 결과가 일관되는지

---

## 11. 작업 순서

1. 프로젝트 구조, requirements, config, DB 연결
2. SQLAlchemy 모델 + Alembic 초기 마이그레이션
3. **스텁 AI 모듈** (5장) + 단위 테스트
4. Pydantic 스키마 (요청/응답)
5. `POST /enroll` + 템플릿 생성 (**재정규화 주의**)
6. `POST /verify` + threshold 비교 + 로깅
7. `GET /config`, `/users`, `/logs`, `/stats/monthly`, `/health`
8. `POST /admin/threshold`, `POST /admin/reindex`
9. 시드 스크립트
10. 테스트 전체
11. README (실행법, API 목록, ai_release 교체 절차, 알려진 한계)

각 단계마다 테스트를 돌리고 커밋한다.

---

## 12. 완료 기준

- [ ] `uvicorn app.main:app --reload`로 실행되고 `/docs`가 뜬다
- [ ] 스텁 상태에서 등록 → 인증 전체 흐름이 동작한다
- [ ] centroid가 재정규화되어 저장된다 (테스트로 검증)
- [ ] threshold 3종이 DB에 있고 재시작 없이 전환된다
- [ ] 재색인이 동작하고, 실패 시 기존 버전이 유지된다
- [ ] 입력 거절 6종이 422와 사유 코드로 변환된다
- [ ] `auth_logs`에 랜드마크 원본과 두 모델 버전이 남는다
- [ ] 시드 데이터로 관리자 화면 API가 의미 있는 값을 돌려준다
- [ ] `pytest` 전체 통과
- [ ] README에 `ai_release` 교체 절차가 단계별로 적혀 있다
- [ ] 앱이 보내야 할 payload 예시가 README에 있다 (앱팀 전달용)

---

## 13. 하지 말 것

- AI 모델을 별도 HTTP 서버로 만들지 말 것
- 요청마다 `load_model()`을 호출하지 말 것
- centroid 평균 후 재정규화를 빠뜨리지 말 것 (에러 없이 조용히 틀린다)
- threshold를 코드에 상수로 박지 말 것
- `enrollments.landmarks_json`을 삭제하거나 압축 손실 저장하지 말 것
- 백엔드에서 전처리(정규화·리샘플링·feature 생성)를 직접 구현하지 말 것 — `ai/features.py` 사용
- 프레임 부족을 백엔드에서 패딩하지 말 것 — AI 모듈이 보간한다
- AI 모듈 호출에 별도 락을 걸지 말 것 (내부에 RLock 있음)
- `challenge_response/`와 Flutter 코드를 건드리지 말 것

---

## 14. ai_release 도착 후 절차

README에 이 절차를 적어둔다.

1. `ai_release/`의 `encoder.py`, `features.py`, `model_defs.py`, `weights/`, `preprocess.json`을 `backend/ai/`에 복사
2. `ai_release/requirements.txt`의 `torch` 등을 `backend/requirements.txt`에 병합
3. `ai_release/smoke_test.py` 실행 — 가중치 파일이 온전한지 확인
4. `scripts/verify_ai_release.py` 실행 — 시그니처, 임베딩 차원(128), L2 norm(=1), 거절 조건이 명세와 맞는지 검증
5. `thresholds.json`의 값을 DB `thresholds` 테이블에 반영
6. `POST /admin/reindex`로 기존 등록분 재임베딩
7. 테스트 전체 재실행

`scripts/verify_ai_release.py`를 미리 만들어둔다. 교체 후 뭐가 어긋났는지 바로 알 수 있어야 한다.

---

## 15. 앱팀 후속 작업 (이번 범위 아님, 기록용)

- `VerifyRequest`/`EnrollRequest`에 `camera.width`, `camera.height` 추가
- 인증·등록 화면에 "오른손을 사용해주세요" 안내
- `GET /config`를 앱 시작 시 호출해 등록 화면 구성
- `kUseMockApi = false`로 전환해 실제 서버 연동
- 422 응답의 사유 코드별 재촬영 안내 문구

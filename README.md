# Sign-ID — 수어 제스처 기반 비접촉 인증

카드키·지문 대신 **수어 제스처**로 출입을 인증하는 시스템.
사용자가 카메라 앞에서 자신만의 손동작("수어 암호")을 수행하면, 앱이 MediaPipe로
손 랜드마크 21점을 수집해 서버로 보내고, 서버가 AI 모델로 본인 여부를 판정한다.

**앱·백엔드·안티스푸핑이 한 저장소에 있고 전부 실제로 동작한다.**
처음에는 앱만 있는 저장소였고 백엔드와 AI 모델은 목(mock)이었다. 지금은
실서버 연동이 기본값이다(`kUseMockApi = false`).

| 구성 요소 | 위치 | 상태 |
|---|---|---|
| **Flutter 앱** | `lib/` | 화면 UI, 카메라 프리뷰 + 손 뼈대 오버레이, 랜드마크 수집 |
| **안티스푸핑 Challenge** | `lib/challenge/` (판정)<br>`challenge_response/` (원본·임계값 도출) | 무작위 동작 3개를 요청하고 규칙 기반 판정. 인증 앞단 |
| **FastAPI 백엔드** | `backend/` | SQLite + Alembic, 등록·인증·이력·운영 API |
| **AI 인증 모델** | `backend/ai/` | AI팀 릴리스 `shared-dual-head-v1.1.1`. 백엔드가 import해서 쓴다 |

| 아직 없는 것 | 비고 |
|---|---|
| 사용자 계정/비밀번호 인증 | 홈에서 사용자를 고르는 것이 신원이다 |
| `/admin/*` 접근 제어 | 인증이 없다. 외부 노출 금지 |
| 푸시 알림 | |
| 개인 제스처(자유 제스처) | 모델은 임베딩 방식이나 체크포인트는 G1~G5로 학습됐다 |
| Challenge 결과의 서버 검증 | 판정이 앱에서 끝난다. 앱을 조작하면 우회된다 |

### 문서

| 문서 | 내용 |
|---|---|
| 이 파일 | 앱 실행·플래그·구조, 안티스푸핑 Challenge, 알려진 제약 |
| [`PROGRESS.md`](PROGRESS.md) | **전체 진행 현황과 성능 수치.** 먼저 읽을 것 |
| [`backend/README.md`](backend/README.md) | API 규격, 사유 코드, 운영점 전환, ai_release 교체 절차 |
| [`challenge_response/README.md`](challenge_response/README.md) | 안티스푸핑 임계값 도출 근거 |
| `SPEC.md`, `BACKEND_SPEC.md`, `CHALLENGE_SPEC.md` | 초기 구현 명세 (현재 상태와 다를 수 있다) |

---

## 실행 방법

### 준비물

| 항목 | 버전 |
|---|---|
| Flutter SDK | 3.44 이상 (개발 시 3.44.8 / Dart 3.12.2) |
| JDK | 17 이상 |
| Android minSdk | 24 |
| compileSdk | **37** (`permission_handler_android`가 요구. 36으로 두면 빌드 실패) |

**Android 전용이다.** `flutter create` 시 `--platforms android`만 지정했고
`ios/`, `web/`, `windows/` 등의 폴더는 만들지 않는다. `hand_landmarker`
플러그인이 JNI 기반 Android 전용이라 다른 플랫폼에서는 빌드되지 않는다.

### 백엔드 먼저 띄우기

앱이 실서버에 붙는 것이 기본값이라(`kUseMockApi = false`) 백엔드가 떠 있어야 한다.
자세한 것은 [`backend/README.md`](backend/README.md) 1장.

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# 실기기에서 붙으려면 0.0.0.0으로 띄운다 (localhost는 폰 자신을 가리킨다)
uvicorn app.main:app --host 0.0.0.0 --port 8000

python scripts/seed_demo_data.py  # 팀원 5명 (다른 터미널에서)
```

startup에서 마이그레이션, AI 가중치 로드(약 1초), 기본 데이터 삽입이 자동으로 된다.
`http://127.0.0.1:8000/docs`에서 API를 눌러 볼 수 있다.

서버 없이 화면만 보려면 `lib/core/config.dart`의 `kUseMockApi`를 `true`로 바꾼다.

### 내 폰에 설치하기

1. 폰에서 **개발자 옵션 → USB 디버깅**을 켜고 USB로 연결한다.
2. 연결을 확인한다. 폰에 "USB 디버깅을 허용하시겠습니까?" 팝업이 뜨면 허용한다.

```bash
flutter devices          # 폰이 목록에 보여야 한다
```

3. 빌드하고 설치한다.

```bash
flutter pub get
flutter build apk --release --dart-define=SIGNID_API_BASE=http://192.168.0.10:8000
flutter install --release
```

`SIGNID_API_BASE`는 **PC의 LAN IP**다. `ipconfig`(Windows) / `ifconfig`(macOS)로 확인한다.
빼먹으면 앱이 서버를 찾지 못하고 홈 화면 하단에 오류가 뜬다.

기기가 여러 대면 `-d <device-id>`로 지정한다 (`flutter devices`의 두 번째 열).

```bash
flutter install --release -d RFCWB1EH7FN
```

앱을 처음 실행하면 카메라 권한을 묻는다. 허용해야 인증 화면이 동작한다.
거부하면 원 아래에 무엇을 해야 하는지 안내 문구가 뜬다.

개발 중에는 핫 리로드가 되는 `flutter run`이 더 편하다.

```bash
flutter run --release    # 또는 그냥 flutter run (디버그)
```

첫 릴리스 빌드는 MediaPipe 네이티브 라이브러리 때문에 몇 분 걸리고, APK는
약 82MB다. 두 번째부터는 1~2분이면 끝난다.

### 검증

```bash
flutter analyze   # 경고 0개여야 한다
flutter test      # 340개 (상태 머신·오버레이·화면 전환 + 안티스푸핑 Challenge 237개)
```

테스트는 `kUseFakeLandmarks` 값과 무관하게 항상 가짜 소스를 주입한다
(`test/test_helpers.dart`). 플래그를 바꿨다고 테스트가 깨지지 않는다.

백엔드와 안티스푸핑 원본도 각자 테스트가 있다:

```bash
cd backend && pytest                                  # 193개
cd challenge_response && pytest                       # 236개 (test_guide_overlay는 opencv 필요)
```

`challenge_response`의 `tests/test_dart_golden.py`는 **파이썬 규칙과 Dart 이식본이
갈라졌는지** 본다. 규칙을 고쳤으면 `python scripts/export_dart_golden.py`를 먼저 돌린다.

### 에뮬레이터에서 확인하기

에뮬레이터에는 실제 손이 없다. `lib/core/config.dart`의
`kUseFakeLandmarks = true`로 바꾸면 가짜 랜드마크가 흐르면서 인증 흐름 전체가
끝까지 동작한다. 카메라 없이도 상태 머신, 오버레이 렌더링, 카운트다운,
진행률 아크, 결과 화면을 전부 확인할 수 있다.

다만 **안티스푸핑 Challenge는 통과할 수 없다.** 가짜 손은 사인파라 요청하는 손
모양(FIST/INDEX…)을 만들지 못한다. Challenge 흐름 자체는
`test/challenge/flow_test.dart`가 대본 손으로 끝까지 돌려 확인한다.

---

## 플래그

전부 `lib/core/config.dart`에 있다. 컴파일 타임 상수라 값을 바꾸면 다시 빌드해야 한다.

| 플래그 | 기본값 | 설명 |
|---|---|---|
| `kUseMockApi` | **`false`** | `false`면 `HttpApiClient`(실서버). `true`면 `MockApiClient`(지연·랜덤 점수·5% 타임아웃) |
| `kUseFakeLandmarks` | `false` | `false`면 `OnDeviceLandmarkSource`(실제 카메라 + MediaPipe), `true`면 `FakeLandmarkSource`(사인파 가짜 손). 에뮬레이터에서 돌릴 때만 `true`로 바꾼다 |
| `kDefaultEnrollTakes` | `3` | 등록 회차 수의 **기본값**. 실제 값은 서버 `GET /config`의 `enrollmentTakes` |
| `kRecordDuration` | `4000ms` | 캡처 시간의 **기본값**. 실제 값은 서버 `GET /config`의 `captureDurationMs`<br>⚠️ 이 값은 AI 모델의 입력 feature다. 바꾸면 기존 등록이 무효다 |
| `kNominalFps` | `30` | 카메라 명목 fps. 서버로 보내는 `nominalFps` 값 |
| `kMinFramesForVerify` | `20` | 이보다 적게 모이면 서버로 보내지 않고 재시도를 안내 |
| `kHandReadyDuration` | `400ms` | 이만큼 연속 검출되면 카운트다운 시작 |
| `kHandGapTolerance` | `300ms` | 이보다 짧은 공백은 연속이 끊긴 것으로 보지 않는다 |
| `kHandLostDuration` | `700ms` | 이만큼 손이 안 보이면 수집을 버리고 처음부터 |
| `kCountdownSeconds` | `2` | 카운트다운 길이 |
| `kGestureIds` | `G1`~`G5` | 서버가 아는 수어 암호 ID. 홈 화면에서 고른 값이 `gestureId`로 전송된다 |
| `kPluginProvidesHandedness` | `false` | 플러그인이 좌/우를 주지 않아 `handedness`를 보내지 않는다 (아래 "알려진 제약") |
| `kShowChallengeDebug` | `true` | Challenge 진단 패널과 서버 로그 전송. 시연 전에 끈다 (`lib/screens/challenge_screen.dart`) |

원 테두리 색이 의미를 나눈다. **진행률 아크만 보라(`AppColors.progress`)** 다 —
초록으로 두면 차오르는 아크가 "정답/통과"로 읽히는데 실제로는 촬영 진행도일 뿐이다.

| 색 | 뜻 |
|---|---|
| 회색 | 손을 찾는 중 |
| 민트 | 준비됨 / 판정 중 |
| 보라 | **촬영·준비 진행률** (판정 결과가 아니다) |
| 초록 | 통과 |
| 빨강 | 실패 |
| `kApiBaseUrl` | (빌드 시 주입) | `--dart-define=SIGNID_API_BASE=...` |

홈 화면 하단에 현재 모드(목 API / 가짜 랜드마크)가 칩으로 표시된다.

서버 주소는 코드에 넣지 말고 빌드 시 주입한다. 실기기에서는 PC의 LAN IP를 쓴다(localhost는 폰 자신을 가리킨다):

```bash
# 백엔드: cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
flutter run --dart-define=SIGNID_API_BASE=http://192.168.0.10:8000
```

연결만 따로 확인하려면:

```bash
flutter test test/live_backend_test.dart \
  --dart-define=SIGNID_LIVE_TEST=1 \
  --dart-define=SIGNID_API_BASE=http://127.0.0.1:8000
```

요청·응답 규격은 `backend/README.md` 4장, 실패 사유 코드는 5장에 있다.
앱은 사유 코드별 안내 문구를 `lib/models/api_error.dart`에서 고른다.

---

## MediaPipe 버전 (AI팀과 맞춰야 함)

앱이 쓰는 네이티브 MediaPipe 버전이 AI팀의 Python `mediapipe` 버전과 어긋나면
랜드마크 좌표가 미세하게 달라져 인증 정확도가 조용히 깎인다. 그래서 기록해 둔다.

| 항목 | 버전 |
|---|---|
| `hand_landmarker` (pub.dev) | **3.0.1** |
| 네이티브 MediaPipe | **`com.google.mediapipe:tasks-vision:0.10.29`** |
| 모델 | 플러그인에 번들된 `hand_landmarker.task` (별도 설치 불필요) |
| 랜드마크 | 손당 21점, x/y는 [0,1] 정규화, z는 손목 기준 상대 깊이 |

`tasks-vision` 버전은 `hand_landmarker` 3.0.1의 `android/build.gradle`에서 확인했다.
플러그인을 올릴 때 이 값이 바뀌면 AI팀에 알리고 이 표를 갱신할 것.

---

## 설계 원칙

### A. 앱은 원본 좌표만 다룬다

전처리(정규화, 리샘플링, 속도·각도 특징 추출)를 Dart로 구현하지 않는다.
MediaPipe가 뱉는 raw 좌표를 그대로 수집해 서버로 보낸다. AI팀의 Python 전처리
코드와 Dart 구현이 미세하게 어긋나면 인증 정확도가 조용히 깎이고 원인 추적이
매우 어렵기 때문이다. **전처리는 전적으로 서버 책임이다.**

좌표에 가하는 유일한 가공은 화면에 그리기 위한 변환이며, 이 변환은
`HandOverlayPainter` 안에만 있고 결과는 서버로 가지 않는다.

특히 **전면 카메라 프리뷰는 좌우 반전해서 보여주지만, 서버로 보내는 좌표는
반전하지 않은 원본이다.** 실수하기 쉬운 지점이라 코드 주석에도 명시해 두었다.

### B. 랜드마크 추출 방식은 교체 가능

`LandmarkSource` 인터페이스 뒤에 구현체를 숨긴다. 나중에 "서버에서 영상을 받아
추출"하는 방식으로 바뀌어도 UI와 컨트롤러는 손대지 않는다.

- `OnDeviceLandmarkSource` — 카메라 + MediaPipe (실기기)
- `FakeLandmarkSource` — 사인파 기반 가짜 좌표 (에뮬레이터/테스트)

### C. 서버 연동은 스위치 하나로 되돌릴 수 있다

`ApiClient` 인터페이스를 `HttpApiClient`(기본)와 `MockApiClient`가 함께 구현한다.
`kUseMockApi` 하나만 바꾸면 전환된다. 서버 없이 화면만 보거나 목업을 시연할 때 쓴다.

**판정에 쓰는 값은 전부 서버가 소유한다.** 앱에 상수로 박지 않는다.

| 값 | 어디서 오나 |
|---|---|
| 인증 임계값 Tu·Tg | `/verify` 응답에 실려 온다. 앱은 표시만 한다 |
| 등록 회차 수, 촬영 길이 | `GET /config` |
| 안티스푸핑 Challenge 임계값 전부 | `GET /config`의 `challenge` 블록. **못 받으면 시작하지 않는다** |

운영 중 조정이 가능해야 하기 때문이다. 촬영 길이나 Challenge 임계값을 바꿀 때
앱을 다시 배포하지 않는다.

### D. 타임스탬프는 실측값

`HandFrame.tMs`는 캡처 시작 시점부터의 **실제** 경과 시간이다. 폰 부하에 따라
프레임 간격이 흔들리는데, 서버가 고정 길이로 리샘플링하려면 이 값이 정확해야
한다. 인덱스 × 33 같은 균등 간격 가정은 쓰지 않는다.

---

## 폴더 구조

```
lib/
  main.dart                      진입점, 세로 고정, ProviderScope
  core/
    config.dart                  플래그와 튜닝 상수
    theme.dart                   색상/타이포/모양 토큰
    hand_connections.dart        MediaPipe 21점 연결 정의
    screen_rotation.dart         센서 → 화면 회전 (오버레이와 판정이 공유)
  challenge/                     안티스푸핑 판정 (challenge_response 이식)
    challenge_config.dart        서버가 주는 임계값 (앱에 상수 없음)
    geometry.dart                각도·손크기·손끝거리
    window_motion.dart           변위와 주축비
    hand_action_detector.dart    손 모양 패턴 매칭
    movement_detector.dart       이동 방향 (라벨만 거울 반전)
    challenge_generator.dart     무작위 동작 생성 (Random.secure)
    challenge_state_machine.dart 순서·시간·이탈 관문·반대방향 규칙
    hand_sketch.dart             안내 그림 좌표 (판정 규칙에서 생성)
    challenge_debug_format.dart  판정 로그 한 줄 형식
  models/
    landmark.dart                Landmark, HandFrame
    verify.dart                  VerifyRequest, VerifyResponse
    challenge_messages.dart      Challenge 안내·실패 문구
    enroll.dart                  EnrollRequest, EnrollResponse
    auth_log.dart                AuthLog, MonthlyStat
  services/
    landmark_source.dart         추상 인터페이스 + LandmarkTransform
    on_device_landmark_source.dart
    fake_landmark_source.dart
    api_client.dart              추상 인터페이스
    mock_api_client.dart
    http_api_client.dart         실서버 연동 (config/users/verify/enroll/logs/stats/debug)
    challenge_debug_sink.dart    판정 로그를 서버로 (fire and forget)
  state/
    capture_session.dart         손 탐색→카운트다운→수집 공용 절차
    auth_flow_controller.dart
    enroll_controller.dart
    challenge_controller.dart    카메라 스트림 → Observation (판정 규칙은 없다)
    admin_controller.dart
    providers.dart               DI 지점
  screens/
    home_screen.dart             사용자 선택·추가 + 3개 진입점
    challenge_screen.dart        동작 확인 (인증 앞단)
    auth_screen.dart             ★ 가장 중요한 화면
    result_screen.dart
    enroll_screen.dart
    add_user_sheet.dart
    admin_screen.dart
  widgets/
    hand_overlay_painter.dart    좌표 변환이 격리된 곳
    challenge_guide.dart         요청 동작 그림 (손 뼈대 + 화살표)
    challenge_move_debug.dart    이동 판정 진단 패널
    capture_ring.dart
    primary_button.dart
    secondary_button.dart
    status_chip.dart
```

---

## 인증 흐름

홈에서 "인증하기"를 누르면 **동작 확인(Challenge)** 을 먼저 거친다. 통과해야 제스처
인증으로 넘어가고, 실패하면 `/verify`를 호출하지 않는다 (아래 "안티스푸핑 Challenge").

```
HomeScreen → ChallengeScreen → AuthScreen → ResultScreen
             (안티스푸핑)       (제스처 인증)
```

Challenge는 **손이 원 안에 들어올 때까지 기다린 뒤** 시작한다. 대기 중에는
제한 시간이 흐르지 않고 재시도도 차감되지 않는다. 인증 화면의 `handSearching`과
같은 자리다.

```
waitHand   "손을 원 안에 위치시켜 주세요". 테두리 = 회색. **시계 멈춤**
   ↓ 400ms 연속 검출 (timing.waitHandReadyMs)
ACTION 1    perActionTimeoutMs와 totalTimeoutMs가 흐른다
   ↓ 통과
준비 1.5초  "1단계 완료 · 다음: 주먹 쥐기". 테두리 = 초록. **시계 멈춤**
   ↓ timing.stepPrepareMs
ACTION 2    …
```

**시계가 멈추는 구간이 셋이다.** 손을 기다릴 때, 단계 사이 준비 시간, 이탈 관문
대기. 셋 다 사용자가 화면을 읽고 손을 만드는 시간이라 판정 제한으로 재면 안 된다.

### 캡처 상태 머신

`lib/state/auth_flow_controller.dart` + `lib/state/capture_session.dart`.

```
idle          카메라 켜짐. "수어 암호를 입력하세요". 인증 버튼 활성
   ↓ 인증 버튼
handSearching 손을 찾는 중. "손을 원 안에 위치시켜 주세요". 원 테두리 = 회색
   ↓ 400ms 연속 검출 (프레임 수가 아니라 시간)
handReady     "2초 후 시작합니다". 원 테두리 = 민트. 2→1 카운트다운
   ↓ 카운트다운 종료
recording     서버가 정한 시간(기본 4000ms) 수집. 원 테두리 = 진행률 아크
   ↓ 수집 종료
uploading     "확인 중입니다". 원 안에 인디케이터
   ↓ 응답
done          결과 화면으로 전환
```

되돌아가는 경로:

- `recording`/`handReady` 중 손이 15프레임 이상 사라지면 → `handSearching`
  (수집 버퍼를 비우고 "손이 화면을 벗어났습니다" 안내)
- 수집된 프레임이 20개 미만이면 → 서버로 보내지 않고 `idle`로 되돌려 재시도 안내
- 타임아웃 / 그 외 오류 → `idle` + 각각 다른 안내 문구

---

## 전송 JSON 스키마

서버 팀과 합의된 형태. `VerifyRequest.toJson()`이 이 형태를 만든다.

```json
{
  "userId": "eunjung",
  "gestureId": "G1",
  "camera": { "width": 720, "height": 480 },
  "capturedAt": "2026-09-18T10:39:01+09:00",
  "nominalFps": 30,
  "durationMs": 4000,
  "frames": [
    { "tMs": 0,  "score": 0.6,
      "lm": [[0.51,0.62,0.00], [0.53,0.58,-0.01], "...21개..."] },
    { "tMs": 71, "score": 0.6, "lm": ["..."] }
  ]
}
```

- `handedness`는 **보내지 않는다.** 플러그인이 좌/우를 주지 않는다 (아래 "알려진 제약").
- `score`는 측정값이 아니라 플러그인 하한값(0.6)이다. "이 값 이상"이라는 뜻이다.
- `camera`가 없으면 서버가 422 `missing_camera_size`로 거절한다. 종횡비 보정에 필요하다.
- **좌표는 원본 그대로다.** 회전·미러·정규화를 일절 적용하지 않는다.

등록(`EnrollRequest`)은 같은 프레임 구조를 회차 배열(`takes`)로 감싼 형태다.
스키마는 `backend/README.md` 4장에 확정돼 있고 `backend/examples/`에 완전한 예시가 있다.

---

## 알려진 제약

`hand_landmarker` 3.0.1의 `Hand` 클래스는 `landmarks`만 노출하고
**handedness(좌/우)와 검출 신뢰도(score)를 돌려주지 않는다.** 그래서:

- `handedness` — **보내지 않는다.** 서버는 이 값으로 왼손을 거르지만(422 `wrong_hand`),
  모르는 값을 `'Right'`로 채우면 실제 왼손 입력을 오른손으로 위장하게 되고
  AI 릴리스 README가 이를 명시적으로 금지한다. 좌표만으로 좌우를 추정하는 것도
  손바닥이 뒤집히면 틀린다.
- `score` — 플러그인에 설정한 `minHandDetectionConfidence`(0.6)를 하한값으로
  기록한다. 플러그인이 그 미만은 걸러내므로 "이 값 이상"은 참이다.

**결과: 왼손으로 인증해도 서버가 걸러내지 못한다.** 현재 방어선은 인증·등록 화면의
"오른손을 사용해주세요" 안내뿐이다(`HandGuideNotice`, 서버 `handRequired`에 연동).
정확도가 떨어지는 조용한 실패로 이어지므로, 플러그인이 handedness를 주게 되면
`OnDeviceLandmarkSource._toHandFrame()`에서 그 값을 실어 보내고
`kPluginProvidesHandedness`를 `true`로 바꾼다. 그때부터 서버가 왼손을 거른다.

## 안티스푸핑 Challenge (`lib/challenge/`)

인증 화면 **앞에** 붙는 단계다. 서버가 아니라 **앱이 무작위 동작 3개(손 모양 2 +
이동 1)를 내고 앱이 판정한다.** 통과해야 제스처 인증으로 넘어가고, 실패하면
`/verify`를 호출하지 않는다.

판정 규칙은 `challenge_response/`(파이썬 프로토타입)에서 그대로 옮겼다. 두 구현이
갈라지지 않도록 파이썬 실행 결과를 `test/challenge/golden/cross_impl.json`에 남기고
Dart 테스트가 그 파일과 비교한다. 규칙을 고치면 골든을 다시 뽑아야 하고, 안 뽑으면
`challenge_response/tests/test_dart_golden.py`가 실패한다.

```
challenge_response/scripts/export_dart_golden.py   # 규칙을 고친 뒤 다시 실행
```

### ⚠️ 앱에서 판정하는 것의 보안 한계

**앱을 조작하면 Challenge를 하지 않고도 "통과했다"고 만들 수 있다.** 판정이 기기
안에서 끝나고 서버는 그 결과를 받지도, 검증하지도 않는다. 루팅한 기기나 수정한
APK에는 아무 방어가 없다.

그럼에도 앱에서 판정하는 이유는 **실시간 피드백** 때문이다. 남은 시간, 지금 검출된
손 모양, 이탈 관문 진행도를 프레임마다 보여줘야 사용자가 동작을 맞출 수 있는데,
서버 왕복으로는 그 지연을 감당할 수 없다.

시연 범위에서 내린 결정이고, 실제 출입 통제에 쓰려면 **랜드마크를 서버로 보내
서버가 판정하는 구조로 바꿔야 한다.** 그때도 화면 피드백은 앱이 하고, 최종 판정만
서버가 다시 하는 이중 구조가 현실적이다.

### 좌표계 규칙 (이중 반전 주의)

```
MediaPipe 입력      원본 그대로
서버 전송 좌표      원본 그대로          ← /verify, /enroll. 절대 건드리지 않는다
화면 표시·오버레이   회전 + 거울
이동 방향 판정       회전만. 거울은 라벨에만
```

**회전은 판정에도 넣어야 한다.** 센서는 가로(720×480)인데 폰은 세로로 든다.
회전을 빼면 x와 y가 통째로 바뀐다. 각도는 회전에 불변이라 손 모양 판정
(FIST/INDEX…)은 멀쩡하고 **방향만 90도 돌아간다** — 그래서 늦게 드러났다.

회전 규칙은 `lib/core/screen_rotation.dart` 한 곳에 있고 오버레이와 판정이
**같은 함수**를 쓴다. 두 군데에 따로 두었다가 실제로 갈라졌다.

`coordinateFrame: "mirrored"`는 **좌표를 뒤집으라는 뜻이 아니다.** 판정기가 센서
좌표로 방향을 구한 다음 `MOVE_LEFT ↔ MOVE_RIGHT` 라벨만 바꾼다. 사용자는 거울
화면을 보고 있어서, 센서 기준 오른쪽으로 간 손이 화면에서는 왼쪽으로 보이기
때문이다. 상하는 거울에 영향받지 않는다.

**좌표를 미리 뒤집고 라벨도 뒤집으면 반전이 상쇄되어 좌우가 도로 맞아버린다.**
이 프로젝트에서 이중 반전을 두 번 겪었다(안티스푸핑 분석 때, 카메라 프리뷰 때).

`test/challenge/rotation_test.dart`가 sensorOrientation 0/90/180/270 각각에서
"화면 위로 → MOVE_UP", "화면 오른쪽으로 → MOVE_LEFT(거울)"를 확인한다. 회전을
빼먹었을 때 축이 swap되는 것도 회귀 케이스로 남겼다.
`test/challenge/movement_detector_test.dart`의 "좌표계 (거울)" 그룹과
`cross_impl_test.dart`의 거울 대조 4건이 이 규칙을 고정한다.

화살표 안내도 같은 이유로 **라벨 그대로** 그린다. 라벨이 이미 사용자가 화면에서
보는 방향이므로 `directionMap`을 한 번 더 참조하면 화살표만 반대로 간다.

### 임계값은 전부 서버에서 온다

`lib/challenge/`에 임계값 상수가 없다. `GET /config`의 `challenge` 블록을 받아
쓰고, **못 받으면 Challenge를 시작하지 않는다**(대체값을 두면 도출과 다른 기준으로
판정하게 된다). 자유 제스처 데이터로 재도출하면 앱 재배포 없이 서버 값만 바꾼다.

```bash
# 원본(challenge_response/configs/challenge_config.json) → DB
cd backend && python scripts/import_challenge_config.py --dry-run
cd backend && python scripts/import_challenge_config.py

# 실기기 체감에 맞춰 일부만 조정 (서버 재시작 불필요)
curl -X PATCH localhost:8000/admin/config -H 'Content-Type: application/json' \
  -d '{"challenge": {"timing": {"perActionTimeoutMs": 2500}}}'
curl -X PATCH localhost:8000/admin/config -H 'Content-Type: application/json' \
  -d '{"challenge": {"escapeFrames": 8, "shapeHoldFrames": 5}}'

# 3단계 → 2단계 (코드 수정 없이)
curl -X PATCH localhost:8000/admin/config -H 'Content-Type: application/json' \
  -d '{"challenge": {"steps": {"numShapes": 1, "numMoves": 1}, "timing": {"totalTimeoutMs": 4000}}}'
```

### 프레임 수가 아니라 시간으로 잰다

`shapeHoldFrames`·`escapeFrames`·`maxLostFrames`와 이동 윈도우는 **30fps 파일럿
영상에서 센 프레임 수**다. 실기기는 13~16fps라 프레임 수로 세면 같은 조건이 두 배
넘게 긴 시간이 된다. 앱은 `frameReferenceFps` 기준 시간(ms)으로 바꿔 판정한다.

같은 실수를 이미 두 번 했다. `challenge_response`가 웹캠 20fps에서, 앱이
`handReady` 판정에서 겪었다. `test/challenge/time_based_frames_test.dart`가 14fps와
30fps에서 같은 시간이 걸리는지 확인한다.

### 판정 로그를 PC에서 보기

실기기 화면의 진단 패널은 프레임마다 바뀌어 읽을 수 없다. 같은 값을 한 줄씩 서버로
보내고 백엔드가 파일과 콘솔에 남긴다. `kShowChallengeDebug`가 true일 때만 동작하고,
전송이 실패해도 Challenge는 그대로 진행된다(fire and forget).

```bash
# 1) 세션 시작 전에 비운다
curl -X DELETE localhost:8000/debug/challenge

# 2) 폰에서 Challenge를 한 번 수행한다
#    백엔드 터미널에 실시간으로 찍힌다 (로거 이름: challenge.debug)

# 3) 세션이 끝나면 통째로 본다
curl localhost:8000/debug/challenge          # 전체
curl "localhost:8000/debug/challenge?lines=50"   # 마지막 50줄
#    브라우저로 http://localhost:8000/debug/challenge 를 열어 복사해도 된다
#    파일: backend/logs/challenge_debug.log
```

모든 줄이 `CHALLENGE `로 시작하고 `key=value`로만 되어 있다. grep이 쓸모 있으라고
한 줄에 다 넣었다.

```
CHALLENGE begin id=3f2a actions=[FIST,MOVE_LEFT,OPEN_PALM] rule=... fpsRef=30.0 hold=7f escape=14f perAction=2000ms total=6000ms
CHALLENGE shape req=FIST det=UNKNOWN conf=0.00/off hold=0%/7f ang=t151.2+/i172.4+/m168.0+/r63.1-/p61.8- thr=148.9/135.9 tipWrist=1.124/0.909 escape=- lost=0 fps=14.2 gap=71ms
CHALLENGE step 1/3 action=FIST -> PASS elapsed=412ms retries=0
CHALLENGE move req=MOVE_LEFT win=560/550ms(8f)O disp=0.150/0.226(x0.66)X axisRatio=2.10/3.63(x0.58)X axis=x- label=NONE verdict=undetermined blocked=gate1_disp lost=3 fps=14.2 gap=71ms
CHALLENGE result FAIL reason=WRONG_DIRECTION step=2/3 action=MOVE_LEFT steps=1/3 elapsed=4102ms lost=7 fps=13.9
```

무엇부터 볼지:

| grep | 보는 것 |
|---|---|
| `grep 'CHALLENGE move'` | 이동 단계만 |
| `grep -o 'blocked=[a-z0-9_]*' \| sort \| uniq -c` | 어느 관문이 몇 번 막았는지 |
| `grep -o 'verdict=[a-z_]*' \| sort \| uniq -c` | 반대로 잡히는지 아예 확정이 안 되는지 |
| `grep 'blocked=window'` | 윈도우가 안 차는지 (프레임이 늦는 것이다) |
| `grep -o 'lost=[0-9]*' \| tail -1` | 손없음 주입 누적. 손이 보이는데 올라가면 프레임 지연이다 |
| `grep 'CHALLENGE result'` | 세션별 최종 결과와 FailReason |

`disp=0.150/0.226(x0.66)X`는 "실측 0.150, 임계값 0.226, 임계값의 0.66배, 미달"이다.
`×1.0`을 넘겨야 통과한다.

⚠️ `POST /debug/challenge`는 **개발용이고 인증이 없다.** 앱이 보낸 문자열을 그대로
파일에 쓴다. 배포에서는 `DEBUG_LOG_ENABLED=false`로 끈다(404가 된다).

### 겪은 버그: 하한값을 임계값과 비교한 것

실기기에서 Challenge가 매번 `TRACKING_UNSTABLE`로 끝났다. 원인은 null 처리가 아니라
**앱이 측정하지 않은 값을 score에 채워 넣은 것**이었다.

```
OnDeviceLandmarkSource  score = 0.6   ← minHandDetectionConfidence 하한값
challenge 설정          0.938         ← 정상 영상 검출 신뢰도 분포의 p5
0.6 < 0.938 → 매 프레임 미달 → TRACKING_UNSTABLE
```

"0.6 이상"과 "0.6"은 다른 말이다. 서버로 보내는 payload에는 하한값이 유용하지만
(플러그인이 그 미만을 버리므로 참인 정보다), **임계값과 비교하는 자리에 넣으면
거짓이 된다.** `LandmarkSource.providesDetectionScore`로 "이게 측정값인가"를
소스가 직접 선언하게 하고, false면 관문을 건너뛴다.

교차검증 골든은 이걸 못 잡았다. 골든은 상태 머신에 [Observation]을 직접 넣어
파이썬과 대조하는데, 버그는 **프레임 → Observation으로 옮기는 컨트롤러 층**에
있었고 그 층은 골든 범위 밖이다. 게다가 골든의 모든 케이스가 `score=1.0`이라
관문 자체가 한 번도 눌리지 않았다. 지금은 골든에 `score=None`·낮은 값·경계값
3건을 넣었고, `flow_test.dart`의 가짜 소스도 실기기와 같은 0.6을 흘린다.

### 겪은 버그: 프레임이 두 번 수집된 것 (인증이 헐거워진 원인)

Challenge를 거쳐 인증하면 4초에 **119~120프레임**이 모였다. Challenge 이전에는
같은 4초에 52~62개였으니 정확히 두 배다.

```
OnDeviceLandmarkSource.stop()이 검출 스트림 구독을 끊지 않았다
  → 화면을 옮기며 stop() → start() 하면 구독이 하나 더 붙는다
  → 네이티브 이벤트 채널이라 같은 검출 결과가 구독 수만큼 흘러나온다
```

**이게 인증을 통째로 헐겁게 만들었다.** 모델 입력의 절반이 속도 feature인데,
같은 프레임이 두 번씩 들어가면 프레임 간 변위가 0이 된다. 손이 거의 안 움직이는
것처럼 보여 동작 간 차이도 사람 간 차이도 뭉개진다. 남의 동작도 다른 사람도
통과하던 이유가 이것이다.

지금은 `stop()`이 구독·카메라·플러그인을 모두 정리하고, `CaptureSession`이
버퍼에 넣기 전에 **tMs 단조 증가**를 보장한다(등록 2회차의 422
`non_monotonic_timestamps`도 같은 원인으로 보인다).

`test/frame_duplication_test.dart`가 이 상황을 재현한다. 고치기 전 결과가
실기기 로그와 정확히 일치했다 — 120장.

### 겪은 버그: 판정 입력에 센서 회전을 빼먹은 것

실기기에서 화살표대로 움직여도 "요청한 방향과 다르다"가 계속 떴다.

```
req=MOVE_UP   axis=x- (축비 19.21) label=MOVE_RIGHT
req=MOVE_LEFT axis=y+ (축비 47.25) label=MOVE_DOWN
```

축비가 19~47배로 확실한데 x/y만 swap돼 있었다. 오버레이에는
`transform.rotationDegrees`를 적용하면서 판정 입력에는 넣지 않은 것이 원인이다.
`challenge_response`도 영상 회전 메타데이터를 안 쓰던 시절 이동 일치율이 0~6%였다.
같은 종류의 실수다.

### 겪은 버그: 프레임 공백 기준이 고정 상수였던 것

`blocked=window`가 압도적이고 `lost=`가 15 → 28까지 올라갔다. 실측 프레임 간격은
보통 60~90ms인데 110~170ms로 자주 튀었다. '손 없음' 기준이 고정 100ms라 그때마다
손 없음이 주입되고 **이동 윈도우가 비워져** 550ms를 채울 기회가 없었다.

지금은 최근 프레임 간격의 **중앙값 × `frameStaleFactor`** 로 유도하고 상·하한으로
묶는다. 세 값 모두 서버 설정이다(`tracking.frameStale*`). 중앙값을 쓰는 이유는
한 번 크게 튄 프레임에 기준이 끌려가면 안 되기 때문이다.

`frameStaleFactor`는 **측정값이 아니라 정책값**이다. 실기기 체감으로 조정한다.

### 손이 사라졌을 때 (검토 결과)

**지금 값을 유지한다.** `maxLostFrames`(38프레임 = 30fps 기준 약 1.25초)를 넘겨
손이 안 보이면 `HAND_LOST`로 끝나고, 이 사유는 재시도 대상이 아니다.

느슨하게 풀지 않은 이유:

- **보안 관문이다.** 손을 프레임 밖으로 빼는 것(`NEG_exit`)이 안티스푸핑이 막으려는
  공격 중 하나다. 재시도로 회복되게 하면 손을 감췄다 나타내며 무한히 다시 시도할 수 있다.
- **1.25초는 짧지 않다.** 사용자가 겪던 "금방 실패한다"의 상당 부분은 **손을 들기 전**
  이 관문이 돌던 것이었고, 그건 대기 단계로 해결됐다.
- **근거 없이 바꾸지 않는다.** 38은 측정값이 아니라 임시값이다. 어느 방향으로 옮기든
  지금은 근거가 없다.

대신 **실제로 얼마나 자주 나는지 먼저 잰다.** 로그에 이미 남는다:

```bash
curl -s localhost:8000/debug/challenge | grep -c 'reason=HAND_LOST'
```

정상 사용자에게 자주 뜨면 서버에서 올린다(앱 재배포 없음):

```bash
curl -X PATCH localhost:8000/admin/config -H 'Content-Type: application/json'   -d '{"challenge": {"tracking": {"maxLostFrames": 60}}}'
```

### Challenge의 알려진 한계

| 한계 | 상세 |
|---|---|
| **앱 판정** | 앱을 조작하면 우회된다. 서버가 검증하지 않는다 (위 참고) |
| **검출 신뢰도 관문이 꺼져 있다** | `minDetectionScore=0.938`을 받지만 `hand_landmarker` 3.0.1이 신뢰도를 주지 않는다. 앱은 `HandFrame.score`에 `minHandDetectionConfidence`(0.6)를 **하한값**으로 넣는데, 이건 "0.6 이상"이라는 뜻이지 측정값이 아니다. 측정하지 않은 값으로 관문을 판정할 수 없으므로 `LandmarkSource.providesDetectionScore`가 false인 소스는 관문을 건너뛴다. **결과적으로 `TRACKING_UNSTABLE`은 앱에서 발생하지 않고, 흔들리는 손을 거를 관문 하나가 없는 상태다.** 플러그인이 진짜 신뢰도를 주면 그 플래그만 true로 바꾸면 관문이 살아난다 |
| **`maxLostFrames`가 측정값이 아니다** | 38은 임시값이다(30fps 기준 약 1.25초). 정상 영상의 중간 끊김이 1건뿐이라(최소 20건 필요) p95를 도출하지 못했고, 2026-09-16에 임시로 정한 값이다. 30fps 기준 1,267ms에 해당한다. **실사용 세션이 쌓이면 다시 재야 한다** |
| 1단계에는 이탈 관문이 없다 | 시작 시점에 이미 1단계 손 모양이면 그대로 통과된다. 매번 시작 자세를 요구하는 비용이 더 크다고 봤다(challenge_response README 5.7). 2·3단계에는 관문이 있어 정지된 손 하나로 전체를 통과할 수는 없다 |
| 이동 방향 근거가 좁다 | `directionMap`의 상하는 참가자 1명(P05)의 영상 4개에 기댄다 |
| `shapeConfidenceMin`이 null | 분포가 겹쳐 도출하지 못했다. 신뢰도 게이트를 끈 채로 간다 |
| **통과율 미측정** | 실기기에서 3단계를 끝까지 통과한 세션이 **1회(8.5초)** 다. 정상 사용자가 몇 번에 한 번 통과하는지, 어느 단계에서 주로 막히는지는 표본이 없다. `backend/logs/challenge_debug.log`의 `blocked=`·`verdict=`를 세어 보면 나온다 |
| 임계값이 거치 조건에서 도출됨 | 파일럿은 폰을 **고정하고** 손만 움직였다. 손에 들면 폰도 따라가 상대 변위가 줄어든다. 실사용 조건에서 다시 재야 한다 |

## 인증 성공 후 이어지는 서비스

이 인증이 **2차 인증**으로 쓰인다는 것을 보여주는 흐름이다. 성공 화면에만
"계속하기"가 뜨고, 누르면 외부 브라우저로 서비스 주소를 연다.

주소는 서버가 준다(`GET /config`의 `postAuthUrl`, 기본 `https://www.naver.com`).
앱에 박아두면 바꿀 때마다 다시 배포해야 한다.

```bash
curl -X PATCH localhost:8000/admin/config -H 'Content-Type: application/json'   -d '{"postAuthUrl": "https://portal.example.com/sso"}'
```

- **https만 연다.** 서버가 422로 막고, 앱도 받은 값을 다시 확인한다
  (`ServerConfig.hasPostAuthUrl`). 외부 브라우저로 여는 주소라 다른 스킴은
  무엇이 열릴지 알 수 없다
- 서버가 주소를 안 주면(오래된 서버, 응답 실패) 버튼을 숨기고 기존
  "확인" + 자동 복귀로 돌아간다
- 실패 화면에는 띄우지 않는다
- 앱 안 웹뷰가 아니라 외부 브라우저인 이유: 2차 인증을 마치고 원래 쓰던
  브라우저 세션으로 돌아가는 흐름이기 때문이다

## 실기기 검증 기록

Galaxy A34 5G (SM-A346N, Android 14, arm64)에서 릴리스 빌드로 확인했다.
카메라 프리뷰, MediaPipe 손 검출, 오버레이 정렬, 캡처 상태 머신, 안티스푸핑
Challenge 3단계, 제스처 인증, 결과 화면까지 전부 동작한다.

검증 과정에서 **실기기에서만 드러난 문제**를 여러 번 고쳤다. 다른 기기로 옮길 때
같은 증상이 나오면 여기부터 볼 것. 공통점이 있다 — 전부 화면 표시 쪽은 멀쩡한데
판정 입력 쪽이 틀렸거나, 프레임 수로 센 값이 낮은 fps에서 다른 시간이 된 경우다.

**0. 안티스푸핑 Challenge (2026-09-18)**

3단계 전체 통과, **8.5초**. 버그 두 건을 고친 뒤의 결과다 — 판정 입력에 센서 회전
누락(축 90도 swap), 프레임 공백 기준 100ms 고정이 14fps에서 이동 윈도우를 계속 비움.
둘 다 위의 "겪은 버그" 절에 자세히 적었다.

**1. 오버레이 좌표 회전**

플러그인이 돌려주는 좌표는 **센서 프레임 그대로**다. `processFrame()`에
`sensorOrientation`을 넘기지만 그건 추론용이고, 결과 좌표를 세로 기준으로
돌려주지 않는다. 그래서 표시할 때 `sensorOrientation`만큼 직접 회전시켜야 한다
(`OnDeviceLandmarkSource.transform`의 `rotationDegrees`).

이 기기는 전면 카메라 `sensorOrientation = 270`이고, 270도 회전에서 정확히 겹쳤다.

⚠️ **미러링은 그 뒤에 두 번 바뀌었다.** 처음에는 프리뷰를 직접 반전하고
오버레이는 `mirror: false`로 뒀는데, `camera_android_camerax` 0.7.4+6이 전면
프리뷰를 이미 반전해 그리는 것을 확인하고 프리뷰 반전을 빼고 오버레이를
`mirror: true`로 바꿨다. 지금 값이 그것이다.

**회전 규칙은 `lib/core/screen_rotation.dart` 한 곳에 있다.** 오버레이와 Challenge
판정이 같은 함수를 쓴다. 두 군데에 따로 두었다가 판정 쪽에서 빠져 이동 방향이
90도 돌아간 적이 있다.

다른 기기에서 뼈대가 손을 벗어나면 실행 직후 로그부터 확인한다.

```
SignID/camera sensorOrientation=270 previewSize=... lens=CameraLensDirection.front
```

**2. 전면 프리뷰 미러링**

Android의 camera 플러그인은 전면 카메라 프리뷰를 반전하지 않고 센서가 보는
그대로 띄운다. SPEC 8.2가 요구하는 거울 모드를 만들려면 `buildPreview()`에서
직접 좌우 반전해야 한다.

**3. 프리뷰가 늦게 뜨는 문제**

`buildPreview()`는 카메라 초기화가 끝나기 전에는 null을 돌려준다. 화면이 그
뒤에 다시 그려지지 않으면 원 안이 계속 비어 있다. 각 화면의 `initState`에서
`attach()`를 await한 뒤 한 번 `setState`를 호출해 해결했다.

**주의:** 위 좌표 변환은 이 기기 한 대에서만 검증했다. `sensorOrientation`이
다른 기기(후면 카메라나 일부 태블릿)에서는 다시 확인이 필요하다. 조정할 곳은
`OnDeviceLandmarkSource.transform` 하나뿐이고, 화면이나 `HandOverlayPainter`는
건드릴 필요가 없다.

# Sign-ID — 수어 제스처 기반 비접촉 인증 (Android 앱 프론트엔드)

카드키·지문 대신 **수어 제스처**로 출입을 인증하는 안드로이드 앱.
사용자가 카메라 앞에서 자신만의 손동작("수어 암호")을 수행하면, 앱이 MediaPipe로
손 랜드마크 21점을 수집해 서버로 보내고 서버가 본인 여부를 판정한다.

이 저장소의 범위는 **UI + 랜드마크 추출 + 목(mock) API 연동**까지다.
실제 AI 인증 모델과 백엔드 서버는 별도 팀에서 개발 중이다.

| 포함 | 제외 |
|---|---|
| 전체 화면 UI (홈/인증/결과/등록/관리자) | 실제 AI 인증 모델 |
| 카메라 프리뷰 + 실시간 손 뼈대 오버레이 | 실제 백엔드 서버 |
| MediaPipe 랜드마크 추출 및 프레임 수집 | 사용자 계정/비밀번호 인증 |
| 목 API 레이어 (서버 응답 시뮬레이션) | 실제 DB |
| 상태 관리, 화면 전환, 에러 처리 | 푸시 알림 |

---

## 실행 방법

### 준비물

| 항목 | 버전 |
|---|---|
| Flutter SDK | 3.44 이상 (개발 시 3.44.8 / Dart 3.12.2) |
| JDK | 17 이상 |
| Android minSdk | 24 |
| compileSdk | 36 |

**Android 전용이다.** `flutter create` 시 `--platforms android`만 지정했고
`ios/`, `web/`, `windows/` 등의 폴더는 만들지 않는다. `hand_landmarker`
플러그인이 JNI 기반 Android 전용이라 다른 플랫폼에서는 빌드되지 않는다.

### 빌드 · 실행

```bash
flutter pub get
flutter run                 # 실기기 또는 에뮬레이터
flutter build apk --debug   # APK 빌드
```

### 검증

```bash
flutter analyze   # 경고 0개여야 한다
flutter test      # 상태 머신 / 오버레이 / 화면 전환 테스트
```

### 에뮬레이터에서 확인하기

에뮬레이터에는 실제 손이 없으므로 `lib/core/config.dart`의
`kUseFakeLandmarks = true`(기본값)로 두면 가짜 랜드마크가 흐르면서
인증 흐름 전체가 끝까지 동작한다. 카메라 없이도 상태 머신, 오버레이 렌더링,
카운트다운, 진행률 아크, 결과 화면을 전부 확인할 수 있다.

---

## 플래그

전부 `lib/core/config.dart`에 있다. 컴파일 타임 상수라 값을 바꾸면 다시 빌드해야 한다.

| 플래그 | 기본값 | 설명 |
|---|---|---|
| `kUseMockApi` | `true` | `true`면 `MockApiClient`(지연·랜덤 점수·5% 타임아웃), `false`면 `HttpApiClient`(아직 스텁) |
| `kUseFakeLandmarks` | `true` | `true`면 `FakeLandmarkSource`(사인파 가짜 손), `false`면 `OnDeviceLandmarkSource`(실제 카메라 + MediaPipe) |
| `kEnrollRepeatCount` | `5` | 등록 시 같은 제스처를 반복 수집하는 횟수. AI팀이 정하면 바뀔 값 |
| `kRecordDuration` | `2000ms` | 한 번의 캡처에서 프레임을 모으는 시간 |
| `kNominalFps` | `30` | 카메라 명목 fps. 서버로 보내는 `nominalFps` 값 |
| `kMinFramesForVerify` | `20` | 이보다 적게 모이면 서버로 보내지 않고 재시도를 안내 |
| `kHandReadyFrameThreshold` | `10` | 이만큼 연속 검출되면 카운트다운 시작 |
| `kHandLostFrameThreshold` | `15` | 이만큼 연속으로 손이 사라지면 수집을 버리고 처음부터 |
| `kAssumedHandedness` | `'Right'` | 전송 JSON의 `handedness` 고정값 (아래 "알려진 제약" 참고) |

홈 화면 하단에 현재 모드(목 API / 가짜 랜드마크)가 칩으로 표시된다.

실제 서버로 붙일 때는 `HttpApiClient`의 각 메서드를 채우고, 서버 주소는
코드에 넣지 말고 빌드 시 주입한다:

```bash
flutter run --dart-define=SIGNID_API_BASE=https://example.internal
```

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

### C. 목 API는 스위치 하나로 교체

`ApiClient` 인터페이스를 `MockApiClient`와 `HttpApiClient`가 함께 구현한다.
`kUseMockApi` 하나만 바꾸면 전환된다.

**판정 임계값(threshold)은 서버가 소유한다.** 앱에 상수로 박지 않고 응답에 실려
온 값을 그대로 표시만 한다. 운영 중 조정이 가능해야 하기 때문이다.

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
  models/
    landmark.dart                Landmark, HandFrame
    verify.dart                  VerifyRequest, VerifyResponse
    enroll.dart                  EnrollRequest, EnrollResponse
    auth_log.dart                AuthLog, MonthlyStat
  services/
    landmark_source.dart         추상 인터페이스 + LandmarkTransform
    on_device_landmark_source.dart
    fake_landmark_source.dart
    api_client.dart              추상 인터페이스
    mock_api_client.dart
    http_api_client.dart         스텁 (TODO 주석만)
  state/
    capture_session.dart         손 탐색→카운트다운→수집 공용 절차
    auth_flow_controller.dart
    enroll_controller.dart
    admin_controller.dart
    providers.dart               DI 지점
  screens/
    home_screen.dart             사용자 선택 + 3개 진입점
    auth_screen.dart             ★ 가장 중요한 화면
    result_screen.dart
    enroll_screen.dart
    admin_screen.dart
  widgets/
    hand_overlay_painter.dart    좌표 변환이 격리된 곳
    capture_ring.dart
    primary_button.dart
    secondary_button.dart
    status_chip.dart
```

---

## 인증 상태 머신

`lib/state/auth_flow_controller.dart` + `lib/state/capture_session.dart`.

```
idle          카메라 켜짐. "수어 암호를 입력하세요". 인증 버튼 활성
   ↓ 인증 버튼
handSearching 손을 찾는 중. "손을 원 안에 위치시켜 주세요". 원 테두리 = 회색
   ↓ 연속 10프레임 검출
handReady     "3초 후 시작합니다". 원 테두리 = 민트. 3→2→1 카운트다운
   ↓ 카운트다운 종료
recording     2000ms 수집. "동작을 수행하세요". 원 테두리 = 진행률 아크
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
  "userId": "kim",
  "capturedAt": "2026-08-24T10:39:01+09:00",
  "nominalFps": 30,
  "durationMs": 2000,
  "frames": [
    { "tMs": 0,  "handedness": "Right", "score": 0.98,
      "lm": [[0.51,0.62,0.00], [0.53,0.58,-0.01], "...21개..."] },
    { "tMs": 33, "handedness": "Right", "score": 0.97, "lm": ["..."] }
  ]
}
```

등록(`EnrollRequest`)은 같은 프레임 구조를 회차 배열(`takes`)로 감싼 형태다.
**등록 스키마는 서버 팀과 아직 확정되지 않았다.**

---

## 알려진 제약

`hand_landmarker` 3.0.1의 `Hand` 클래스는 `landmarks`만 노출하고
**handedness(좌/우)와 검출 신뢰도(score)를 돌려주지 않는다.** 그래서:

- `handedness` — `kAssumedHandedness`의 고정값(`'Right'`)을 보낸다. 좌표만으로
  좌우를 추정하면 손바닥이 뒤집힐 때 틀리므로 추정하지 않았다.
- `score` — 플러그인에 설정한 `minHandDetectionConfidence`(0.6)를 하한값으로
  기록한다. 플러그인이 그 미만은 걸러내므로 "이 값 이상"은 참이다.

서버가 정확한 좌우/신뢰도를 필요로 한다면 플러그인 확장이나 서버 측 추정이 필요하다.

또한 `OnDeviceLandmarkSource`는 **실기기에서 검증되지 않았다.** 개발 환경에
안드로이드 기기가 없어 `flutter analyze`와 Fake 소스 기반 테스트로만 확인했다.
실기기에서 오버레이가 프리뷰와 어긋난다면 `OnDeviceLandmarkSource.transform`의
`rotationDegrees`만 조정하면 되고, 화면이나 페인터 코드는 건드릴 필요가 없다.

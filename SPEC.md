# Sign-ID — Flutter 프론트엔드 구현 명세

> 수어 제스처 기반 비접촉 인증 시스템의 **안드로이드 앱 프론트엔드**.
> AI 인증 모델은 별도 팀에서 개발 중이므로, 이 작업의 범위는 **UI + 랜드마크 추출 + 목(mock) API 연동**까지다.

---

## 0. 작업 전 필수 확인

**코드를 작성하기 전에 아래 두 가지를 반드시 먼저 수행할 것.**

1. `hand_landmarker` (pub.dev) 패키지의 **README와 example 코드를 실제로 확인**하고, 최신 API 시그니처에 맞춰 구현한다. 이 문서에 적힌 클래스명·메서드명은 참고용 추정치이므로, 실제 패키지와 다르면 **패키지 쪽을 정답으로 삼는다.**
2. `camera`, `fl_chart`, `flutter_riverpod` 각각의 최신 안정 버전을 확인하고 `pubspec.yaml`에 넣는다. 버전을 하드코딩으로 추측하지 말 것.

작업이 끝나면 `flutter analyze`가 **경고 0개**로 통과해야 한다. (실기기가 없으므로 `flutter run`은 하지 않아도 된다.)

---

## 1. 프로젝트 개요

### 무엇을 만드는가
사내 출입 인증을 카드키·지문 대신 **수어 제스처**로 하는 안드로이드 앱. 사용자가 카메라 앞에서 자신만의 손동작(= "수어 암호")을 수행하면, 그 동작의 궤적·속도·템포 패턴을 분석해 본인 여부를 판정한다.

### 이번 작업의 범위
| 포함 | 제외 |
|---|---|
| 전체 화면 UI | 실제 AI 인증 모델 |
| 카메라 프리뷰 + 실시간 손 뼈대 오버레이 | 실제 백엔드 서버 |
| MediaPipe 랜드마크 추출 및 프레임 수집 | 사용자 계정/비밀번호 인증 |
| 목 API 레이어 (서버 응답 시뮬레이션) | 실제 DB |
| 상태 관리, 화면 전환, 에러 처리 | 푸시 알림 |

### 타겟
- **Android 전용.** iOS 코드는 작성하지 않는다. (`hand_landmarker` 플러그인이 JNI 기반 Android 전용)
- minSdkVersion 24 이상
- 세로 모드 고정 (`portraitUp`)

---

## 2. 아키텍처 원칙

### 원칙 A — 앱은 원본 좌표만 다룬다
**전처리(정규화, 리샘플링, 속도·각도 특징 추출)를 Dart로 구현하지 말 것.**

MediaPipe가 뱉는 raw 좌표를 그대로 수집해서 서버로 보낸다. 이유: AI팀의 Python 전처리 코드(`02_build_features.py`)와 Dart 구현이 미세하게 어긋나면 인증 정확도가 조용히 깎이고, 원인 추적이 매우 어렵다. 전처리는 전적으로 서버 책임이다.

앱에서 좌표에 하는 유일한 가공은 **화면에 그리기 위한 좌표 변환**이며, 이 변환 결과는 절대 서버로 보내지 않는다. 전송용 데이터와 렌더링용 데이터를 분리할 것.

### 원칙 B — 랜드마크 추출 방식을 교체 가능하게
나중에 "서버에서 영상을 받아 추출"하는 방식으로 바뀔 수 있으므로 인터페이스로 감싼다.

```dart
abstract class LandmarkSource {
  Stream<HandFrame> get frames;
  Future<void> start();
  Future<void> stop();
  void dispose();
}

class OnDeviceLandmarkSource implements LandmarkSource { /* MediaPipe */ }
class FakeLandmarkSource implements LandmarkSource { /* 에뮬레이터/테스트용 */ }
```

UI는 `LandmarkSource` 인터페이스에만 의존하고, 구현체는 DI로 주입한다.

### 원칙 C — 목 API는 스위치 하나로 교체
`lib/core/config.dart`에 `const bool kUseMockApi = true;` 를 두고, 이 값 하나만 바꾸면 실제 서버로 전환되게 한다. 목 구현과 실제 구현은 동일한 추상 클래스를 구현한다.

### 원칙 D — MediaPipe 버전 고정
`hand_landmarker` 플러그인이 사용하는 네이티브 MediaPipe 버전을 README에서 확인해 프로젝트 루트 `README.md`에 명시한다. AI팀 Python `mediapipe` 버전과 맞춰야 하므로 기록이 필요하다.

---

## 3. 기술 스택

```yaml
dependencies:
  flutter: { sdk: flutter }
  camera: ^최신
  hand_landmarker: ^최신        # Android 전용, MediaPipe JNI 브릿지
  flutter_riverpod: ^최신       # 상태 관리
  fl_chart: ^최신               # 대시보드 차트
  intl: ^최신                   # 날짜/시간 포맷
  permission_handler: ^최신     # 카메라 권한
  http: ^최신                   # (목 단계에선 미사용, 스텁만)
```

상태 관리는 Riverpod을 쓰되 과하게 추상화하지 말 것. `StateNotifierProvider` 정도면 충분하다.

---

## 4. 폴더 구조

```
lib/
  main.dart
  core/
    config.dart              # kUseMockApi, 상수
    theme.dart               # 색상/타이포 토큰 (아래 5장)
    hand_connections.dart    # MediaPipe 21점 연결 정의
  models/
    landmark.dart            # Landmark, HandFrame
    verify.dart              # VerifyRequest, VerifyResponse
    enroll.dart              # EnrollRequest, EnrollResponse
    auth_log.dart            # AuthLog (이력 1건)
  services/
    landmark_source.dart     # 추상 인터페이스
    on_device_landmark_source.dart
    fake_landmark_source.dart
    api_client.dart          # 추상 인터페이스
    mock_api_client.dart
    http_api_client.dart     # 스텁 (TODO 주석만)
  state/
    auth_flow_controller.dart
    enroll_controller.dart
    admin_controller.dart
  screens/
    home_screen.dart
    auth_screen.dart
    result_screen.dart
    enroll_screen.dart
    admin_screen.dart
  widgets/
    hand_overlay_painter.dart
    capture_ring.dart
    primary_button.dart
    secondary_button.dart
    status_chip.dart
```

---

## 5. 디자인 토큰

첨부된 목업의 다크 테마를 정확히 재현할 것. 임의로 밝은 테마나 다른 액센트 컬러를 만들지 말 것.

```dart
// core/theme.dart
class AppColors {
  static const bg           = Color(0xFF121417); // 화면 배경 (거의 검정)
  static const surface      = Color(0xFF1C1F24); // 카드/패널
  static const surfaceAlt   = Color(0xFF23272D); // 표 헤더, 보조 버튼
  static const primary      = Color(0xFF2F80ED); // 인증 버튼 (파랑)
  static const ring         = Color(0xFF3DDC97); // 손 가이드 원 (민트)
  static const landmark     = Color(0xFF22D3EE); // 랜드마크 점 (시안)
  static const connection   = Color(0xFF0E7490); // 뼈대 선 (어두운 청록)
  static const success      = Color(0xFF34D399);
  static const danger       = Color(0xFFEF4444);
  static const textPrimary  = Color(0xFFFFFFFF);
  static const textSecondary= Color(0xFF9AA0A6);
  static const divider      = Color(0xFF2A2E34);
}
```

**타이포그래피**
- 앱 전체 기본 폰트는 Pretendard 계열이 이상적이나, 폰트 파일 추가 없이 Flutter 기본 폰트로 진행한다. 대신 웨이트와 자간을 명확히 잡을 것.
- `displayTitle` — 24sp / w600 / letterSpacing 0.5 (로고 "Sign-ID")
- `screenTitle` — 20sp / w600 (화면 제목)
- `body` — 15sp / w400
- `caption` — 13sp / w400 / textSecondary
- `tableCell` — 13sp / w400
- `buttonLabel` — 16sp / w600

**모양**
- 주 버튼: 높이 52, borderRadius 26 (완전 알약형), 배경 primary
- 보조 버튼: 높이 44, borderRadius 22, 배경 surfaceAlt, 텍스트 textSecondary
- 카드: borderRadius 12, 배경 surface
- 표: 셀 구분선 divider 1px, 헤더 배경 surfaceAlt

**카피 원칙**
- 버튼은 실제 일어나는 일을 그대로 쓴다. "제출"이 아니라 "인증".
- 에러 메시지는 사과하지 않고, 무엇이 잘못됐고 어떻게 고치는지를 말한다.
  - 나쁨: "죄송합니다. 오류가 발생했습니다."
  - 좋음: "손이 인식되지 않습니다. 손 전체가 원 안에 들어오도록 해주세요."
- 빈 화면은 다음 행동을 안내한다. "데이터 없음"이 아니라 "아직 등록된 제스처가 없습니다. 등록을 시작해보세요."

---

## 6. 데이터 모델

```dart
// models/landmark.dart
class Landmark {
  final double x;  // [0,1] 정규화 좌표 (이미지 폭 기준)
  final double y;  // [0,1] 정규화 좌표 (이미지 높이 기준)
  final double z;  // 손목 기준 상대 깊이
}

class HandFrame {
  final int tMs;              // 캡처 시작 시점부터의 경과 시간 (ms)
  final List<Landmark> landmarks;  // 정확히 21개
  final String handedness;    // "Left" | "Right"
  final double score;         // 검출 신뢰도
}
```

```dart
// models/verify.dart
class VerifyRequest {
  final String userId;
  final DateTime capturedAt;
  final double nominalFps;      // 카메라 설정 fps
  final int durationMs;
  final List<HandFrame> frames;
}

class VerifyResponse {
  final double score;       // 0.0 ~ 1.0 유사도
  final double threshold;   // 서버가 소유. 앱에 하드코딩 금지
  final bool passed;
  final int latencyMs;
  final String? reason;     // 실패 사유 (예: "insufficient_frames")
}
```

```dart
// models/auth_log.dart
class AuthLog {
  final String userName;
  final String department;
  final DateTime timestamp;
  final bool passed;
}
```

### 전송 JSON 스키마 (서버 팀과 합의된 형태)
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

**`tMs`는 반드시 실제 프레임 타임스탬프를 기록할 것.** 폰 부하에 따라 프레임 간격이 흔들리는데, 서버가 고정 길이로 리샘플링하려면 이 값이 필요하다. 균등 간격이라고 가정하고 인덱스×33으로 계산하면 안 된다.

---

## 7. MediaPipe 손 연결 정의

오버레이를 그릴 때 사용할 21점 연결 쌍. `core/hand_connections.dart`에 상수로 둔다.

```dart
const handConnections = <List<int>>[
  // 엄지
  [0,1],[1,2],[2,3],[3,4],
  // 검지
  [0,5],[5,6],[6,7],[7,8],
  // 중지
  [9,10],[10,11],[11,12],
  // 약지
  [13,14],[14,15],[15,16],
  // 새끼
  [0,17],[17,18],[18,19],[19,20],
  // 손바닥
  [5,9],[9,13],[13,17],
];
```

---

## 8. 화면 명세

### 8.1 홈 (`home_screen.dart`)
목업에는 없지만 진입점으로 필요하다. 최소 구성:
- 상단 "Sign-ID" 로고
- 사용자 선택 드롭다운 (목 데이터: 홍길동/김길동/오박사/둘리/또치/고길동)
- "인증하기" → 인증 화면
- "제스처 등록" → 등록 화면
- "인증 이력" → 관리자 화면

로그인은 구현하지 않는다. 사용자 선택 드롭다운으로 대체한다.

### 8.2 인증 (`auth_screen.dart`) — **가장 중요한 화면**

목업 왼쪽 화면. 레이아웃:
```
┌─────────────────────┐
│ Sign-ID             │  ← 좌상단 로고
│                     │
│    ╭───────────╮    │
│    │           │    │  ← 민트색 원 (지름 = 화면폭 * 0.78)
│    │  카메라   │    │     원 안에만 카메라 프리뷰가 보이도록 클립
│    │  + 뼈대   │    │     그 위에 랜드마크 오버레이
│    │           │    │
│    ╰───────────╯    │
│                     │
│ 수어 암호를 입력하세요 │  ← 상태에 따라 문구 변경
│                     │
│  ┌───────────────┐  │
│  │     인증      │  │  ← 파란 알약 버튼
│  └───────────────┘  │
│      ( 취소 )       │  ← 회색 알약 버튼
└─────────────────────┘
```

**상태 머신** (`auth_flow_controller.dart`):
```
idle          → 카메라 켜짐, 안내 문구 "수어 암호를 입력하세요"
                인증 버튼 활성

handSearching → 인증 버튼 누른 직후. 손을 찾는 중.
                문구 "손을 원 안에 위치시켜 주세요"
                원 테두리 = textSecondary

handReady     → 손이 연속 10프레임 이상 검출됨
                문구 "3초 후 시작합니다"
                원 테두리 = ring(민트), 3→2→1 카운트다운 표시

recording     → 2000ms 동안 HandFrame 수집
                문구 "동작을 수행하세요"
                원 테두리를 진행률 아크로 렌더링 (0%→100%)

uploading     → 서버 전송 중
                문구 "확인 중입니다"
                원 안에 인디케이터

done          → 결과 화면으로 전환
```

**중요한 처리들:**
- `recording` 중 손이 15프레임 이상 연속 사라지면 → `handSearching`으로 되돌리고 수집 버퍼를 비운다. 문구 "손이 화면을 벗어났습니다. 다시 시도해주세요."
- `recording` 종료 시 수집된 프레임이 20개 미만이면 서버로 보내지 말고 재시도를 안내한다.
- 전면 카메라를 사용하며, 프리뷰는 좌우 반전(mirror)해서 보여준다. **단, 서버로 보내는 좌표는 반전하지 않은 원본이어야 한다.** 이 부분에서 실수가 잦으니 주석으로 명시할 것.
- 카메라 회전(`sensorOrientation`)에 따라 오버레이 좌표가 어긋나므로, 좌표 변환 로직을 `HandOverlayPainter` 안에 격리하고 변환 파라미터를 생성자로 받는다.
- 화면 이탈 시 카메라와 랜드마커를 반드시 `dispose`한다.

**오버레이 렌더링** (`hand_overlay_painter.dart`):
- `CustomPainter`로 구현
- 연결선: `connection` 색, strokeWidth 2.0
- 랜드마크 점: `landmark` 색, 반지름 3.5
- 손끝(4, 8, 12, 16, 20)은 반지름 5.0으로 조금 크게
- `shouldRepaint`는 프레임이 바뀔 때만 true

### 8.3 결과 (`result_screen.dart`)
- 성공: 큰 체크 아이콘(success 색), "인증되었습니다", 유사도 점수 표시(개발용), "확인" 버튼
- 실패: X 아이콘(danger 색), "인증에 실패했습니다", 재시도 버튼과 홈으로 버튼
- 2.5초 후 자동으로 홈 복귀 (성공 시에만)

### 8.4 등록 (`enroll_screen.dart`)
목업에는 없지만 없으면 앱이 성립하지 않는다. 인증 화면과 UI를 재사용하되 **같은 제스처를 5회 반복 수집**한다.

```
1/5 회차 → 수집 → 짧은 확인 → 2/5 → ... → 5/5 → 등록 완료
```
- 상단에 진행 인디케이터(점 5개)
- 각 회차 사이에 "다시 한 번 같은 동작을 해주세요" 안내와 1.5초 대기
- 회차 수(5)는 `config.dart`의 상수로 뺄 것. AI팀이 정하면 바뀔 값이다.
- 완료 시 `EnrollRequest`를 목 API로 전송

### 8.5 관리자 / 인증 이력 (`admin_screen.dart`)

목업 오른쪽 화면. 구성:
- 화면 제목 "인증 이력 조회"
- 우측 상단에 현재 시각 (`2026-08-24 10:39:13 KST` 형식, `intl` 사용)
- 표: 사용자 / 부서 / 인증시간 / 결과
  - 결과 컬럼은 체크(success) 또는 X(danger) 아이콘
  - 헤더 배경 surfaceAlt, 행 구분선 divider
- 하단 카드: "월별 인증 현황" 꺾은선 차트 (`fl_chart`의 `LineChart`)
  - X축 1월~5월, Y축 0~500
  - 선 색상 landmark, 아래쪽에 옅은 그라데이션 영역
  - 데이터 포인트에 작은 원 표시
- 목 데이터는 `mock_api_client.dart`에 두고, 표는 최소 12행 정도 넣어 스크롤이 되는지 확인할 것

---

## 9. 목 API 동작 명세

`mock_api_client.dart`는 네트워크 지연을 흉내 내야 한다. 즉시 반환하면 로딩 UI를 테스트할 수 없다.

```dart
Future<VerifyResponse> verify(VerifyRequest req) async {
  await Future.delayed(const Duration(milliseconds: 1200));

  // 프레임 수가 너무 적으면 실패
  if (req.frames.length < 20) {
    return VerifyResponse(score: 0.0, threshold: 0.72, passed: false,
                          latencyMs: 1200, reason: 'insufficient_frames');
  }

  // 그 외에는 0.55~0.95 사이 랜덤 점수
  final score = 0.55 + Random().nextDouble() * 0.40;
  const threshold = 0.72;
  return VerifyResponse(score: score, threshold: threshold,
                        passed: score >= threshold, latencyMs: 1200);
}
```

- **threshold는 반드시 응답에 담아서 서버가 소유하게 한다.** 앱에 상수로 박으면 나중에 운영 중 조정이 불가능하다.
- 5% 확률로 `TimeoutException`을 던지게 해서 에러 UI도 확인할 수 있게 한다.
- `http_api_client.dart`는 동일 인터페이스를 구현하되 각 메서드 본문에 `throw UnimplementedError('AI 서버 연동 대기 중')`과 TODO 주석만 둔다.

---

## 10. 에뮬레이터 대응

개발 PC의 에뮬레이터에는 실제 손이 없으므로 `FakeLandmarkSource`를 만들어 둔다.
- 33ms 간격으로 사인파 기반의 가짜 21점 좌표를 생성해 스트림으로 흘린다.
- 손 모양처럼 보이게 하되 정교할 필요는 없다. 오버레이 렌더링과 상태 머신을 검증하는 용도다.
- `config.dart`의 `kUseFakeLandmarks` 플래그로 전환한다.

---

## 11. 완료 기준

아래를 전부 만족해야 완료다.

- [ ] `flutter analyze` 경고 0개
- [ ] 5개 화면(홈/인증/결과/등록/관리자) 모두 이동 가능하고 렌더링됨
- [ ] `kUseFakeLandmarks = true`로 두면 실기기 없이 인증 화면의 전체 흐름이 끝까지 동작함
- [ ] 인증 상태 머신의 6개 상태가 모두 화면에 반영됨 (문구/원 테두리/버튼 상태)
- [ ] 수집된 `HandFrame`의 `tMs`가 실제 경과 시간이며 균등 간격 가정이 없음
- [ ] 서버 전송용 좌표에 미러링·정규화·전처리가 적용되지 않음
- [ ] `AndroidManifest.xml`에 카메라 권한이 선언되고, 앱 내에서 권한 요청 흐름이 동작함
- [ ] 목 API의 지연·실패·타임아웃이 각각 UI에 다르게 반영됨
- [ ] 루트 `README.md`에 실행 방법, 플래그 설명, MediaPipe 버전이 기록됨

---

## 12. 작업 순서 (권장)

1. 프로젝트 생성, 의존성 추가, 테마·모델·상수 정의
2. `FakeLandmarkSource` + `HandOverlayPainter` — 실기기 없이 오버레이부터 눈으로 확인
3. `auth_flow_controller` 상태 머신 + 인증 화면 (Fake 소스로 검증)
4. 목 API + 결과 화면
5. `OnDeviceLandmarkSource` (실제 MediaPipe 연결)
6. 등록 화면
7. 관리자 화면 + 차트
8. 홈 화면, 라우팅 정리, README 작성

각 단계가 끝날 때마다 `flutter analyze`를 돌려서 다음 단계로 넘어가기 전에 정리할 것.

---

## 13. 하지 말아야 할 것

- iOS 관련 코드나 설정을 추가하지 말 것
- Dart로 좌표 정규화/특징추출을 구현하지 말 것
- threshold를 앱에 하드코딩하지 말 것
- 목업에 없는 화려한 애니메이션이나 그라데이션을 추가하지 말 것 (카운트다운과 진행률 아크 외에는 절제)
- 라이브러리를 임의로 추가하지 말 것. 필요하면 이유를 주석으로 남길 것
- 실제 서버 주소나 API 키를 코드에 넣지 말 것

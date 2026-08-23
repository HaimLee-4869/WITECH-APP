/// 앱 전역 설정 플래그와 튜닝 상수.
///
/// SPEC 원칙 C: 목 API ↔ 실제 API 전환은 [kUseMockApi] 하나만 바꾸면 되도록 한다.
library;

/// true면 [MockApiClient], false면 [HttpApiClient]를 주입한다.
///
/// AI 서버 연동이 끝나면 이 값만 false로 바꾼다. 화면/컨트롤러 코드는 손대지 않는다.
const bool kUseMockApi = true;

/// true면 카메라 대신 [FakeLandmarkSource]가 가짜 랜드마크를 흘린다.
///
/// 에뮬레이터·CI처럼 실제 손이 없는 환경에서 상태 머신과 오버레이를 검증하는 용도.
/// 실기기 테스트 시 false로 바꾼다.
const bool kUseFakeLandmarks = true;

// ─── 캡처 파라미터 ────────────────────────────────────────────────

/// 한 번의 인증에서 동작을 수집하는 시간.
const Duration kRecordDuration = Duration(milliseconds: 2000);

/// 카메라에 요청하는 명목 fps. 서버로 보내는 `nominalFps` 값이기도 하다.
///
/// 실제 프레임 간격은 폰 부하에 따라 흔들리므로, 서버 리샘플링은
/// 이 값이 아니라 각 프레임의 `tMs`를 기준으로 해야 한다. (SPEC 6장)
const double kNominalFps = 30.0;

/// 이만큼 연속으로 손이 검출되면 `handSearching` → `handReady`.
const int kHandReadyFrameThreshold = 10;

/// `recording` 중 이만큼 연속으로 손이 사라지면 수집을 버리고 `handSearching`으로.
const int kHandLostFrameThreshold = 15;

/// 수집된 프레임이 이 개수 미만이면 서버로 보내지 않고 재시도를 안내한다.
const int kMinFramesForVerify = 20;

/// `handReady`에서 `recording`으로 넘어가기 전 카운트다운 초.
const int kCountdownSeconds = 3;

// ─── 등록 파라미터 ────────────────────────────────────────────────

/// 등록 시 같은 제스처를 반복 수집하는 횟수.
///
/// AI팀이 학습에 필요한 샘플 수를 정하면 바뀔 값이라 상수로 뺐다. (SPEC 8.4)
const int kEnrollRepeatCount = 5;

/// 등록 회차 사이의 대기 시간.
const Duration kEnrollInterval = Duration(milliseconds: 1500);

// ─── 랜드마크 소스 ────────────────────────────────────────────────

/// 전송 JSON의 `handedness`에 넣을 값.
///
/// hand_landmarker 3.0.1의 `Hand`는 landmarks만 주고 좌/우 정보를 주지 않는다.
/// 좌표만으로 좌우를 추정하면 손바닥이 뒤집힐 때 틀리므로 추정하지 않고,
/// 합의된 고정값을 보낸다. 서버가 좌우를 구분해야 한다면 플러그인 확장이나
/// 서버 측 추정이 필요하다. (SPEC 0장 — 패키지 실제 API를 따른다)
const String kAssumedHandedness = 'Right';

// ─── 레이아웃 ────────────────────────────────────────────────────

/// 인증 화면 가이드 원의 지름 = 화면 폭 × 이 비율. (SPEC 8.2)
const double kCaptureRingDiameterRatio = 0.78;

/// 목 데이터용 사용자 목록. 로그인 대신 홈 화면 드롭다운으로 선택한다.
const List<String> kMockUsers = <String>[
  '홍길동',
  '김길동',
  '오박사',
  '둘리',
  '또치',
  '고길동',
];

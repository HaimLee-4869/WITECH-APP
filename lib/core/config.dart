/// 앱 전역 설정 플래그와 튜닝 상수.
///
/// SPEC 원칙 C: 목 API ↔ 실제 API 전환은 [kUseMockApi] 하나만 바꾸면 되도록 한다.
library;

/// true면 [MockApiClient], false면 [HttpApiClient]를 주입한다.
///
/// 실서버로 붙일 때 이 값만 false로 바꾸고, 주소는 빌드 시 주입한다:
///
/// ```
/// flutter run --dart-define=SIGNID_API_BASE=http://192.168.0.10:8000
/// ```
///
/// 화면/컨트롤러 코드는 손대지 않는다.
const bool kUseMockApi = true;

/// 백엔드 주소. 코드에 넣지 않고 빌드 시 주입한다. (SPEC 13장)
///
/// 비어 있는 채로 [kUseMockApi]=false로 두면 [HttpApiClient]가 무엇을 해야 하는지
/// 알려주는 예외를 던진다.
const String kApiBaseUrl = String.fromEnvironment('SIGNID_API_BASE');

/// 서버 요청 타임아웃.
const Duration kApiTimeout = Duration(seconds: 20);

/// true면 카메라 대신 [FakeLandmarkSource]가 가짜 랜드마크를 흘린다.
///
/// 에뮬레이터·CI처럼 실제 손이 없는 환경에서 상태 머신과 오버레이를 검증하는 용도.
/// 실기기 테스트 시 false로 바꾼다.
const bool kUseFakeLandmarks = false;

// ─── 캡처 파라미터 ────────────────────────────────────────────────

/// 한 번의 인증에서 동작을 수집하는 시간.
///
/// 서버 `GET /config`의 `captureDurationMs`가 정답이고 이 값은 응답 전 기본값이다.
/// 서버 최소 조건은 750ms다. (backend/README 4.1)
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
///
/// 서버 최소 조건은 유효 프레임 8개지만, 그보다 여유 있게 잡아 왕복을 아낀다.
const int kMinFramesForVerify = 20;

/// `handReady`에서 `recording`으로 넘어가기 전 카운트다운 초.
const int kCountdownSeconds = 3;

// ─── 등록 파라미터 ────────────────────────────────────────────────

/// 등록 회차 수의 **기본값**. 실제 값은 `GET /config`의 `enrollmentTakes`다.
///
/// 서버 값과 다르면 등록이 422 `take_count_mismatch`로 거절되므로, 서버 응답을
/// 받기 전까지만 쓰는 임시값으로만 사용한다. (backend/README 4.3)
const int kDefaultEnrollTakes = 3;

/// 등록 회차 사이의 대기 시간.
const Duration kEnrollInterval = Duration(milliseconds: 1500);

// ─── 수어 암호(제스처) ────────────────────────────────────────────

/// 서버가 아는 제스처 ID. `gestures` 테이블과 같아야 한다.
///
/// AI팀이 개인 제스처 ID 방식을 주면 **값만** 바뀐다. 앱은 이 목록을 그대로
/// 서버에 보내고, 서버는 문자열 키로 템플릿을 조회한다. (backend/README 2장)
const List<String> kGestureIds = <String>['G1', 'G2', 'G3', 'G4', 'G5'];

/// 홈 화면에서 아직 고르지 않았을 때의 기본 수어 암호.
const String kDefaultGestureId = 'G1';

// ─── 랜드마크 소스 ────────────────────────────────────────────────

/// hand_landmarker 3.0.1의 `Hand`는 landmarks만 주고 좌/우(handedness)를 주지 않는다.
///
/// 그래서 앱은 `handedness`를 **보내지 않는다.** 좌표만으로 좌우를 추정하면 손바닥이
/// 뒤집힐 때 틀리고, 모르는 값을 'Right'로 채워 보내면 실제 왼손을 오른손으로
/// 위장하게 된다(AI 릴리스 README가 금지). 대신 화면에서 오른손 사용을 안내한다.
///
/// 플러그인이 handedness를 주게 되면 [OnDeviceLandmarkSource]에서 그 값을 그대로
/// 실어 보내면 되고, 그때부터 서버가 왼손을 422 `wrong_hand`로 거른다.
const bool kPluginProvidesHandedness = false;

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

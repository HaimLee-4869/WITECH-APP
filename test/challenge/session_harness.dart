/// 연속 세션 테스트가 함께 쓰는 하네스.
///
/// 한 컨트롤러가 Challenge와 제스처 수집을 모두 하게 되면서, 흐름 테스트와
/// 전송 규약 테스트가 같은 배선을 필요로 한다. 한 곳에 둔다.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:signid/challenge/challenge_config.dart';
import 'package:signid/challenge/geometry.dart';
import 'package:signid/challenge/hand_sketch.dart';
import 'package:signid/models/app_user.dart';
import 'package:signid/models/camera_info.dart';
import 'package:signid/models/landmark.dart';
import 'package:signid/models/server_config.dart';
import 'package:signid/models/verify.dart';
import 'package:signid/services/api_client.dart';
import 'package:signid/services/mock_api_client.dart';
import 'package:signid/services/landmark_source.dart';
import 'package:signid/state/auth_session_controller.dart';
import 'package:signid/state/providers.dart';

import 'config_fixture.dart';

/// 대본대로 프레임을 흘리는 테스트용 소스.
///
/// [FakeLandmarkSource]는 사인파 손이라 요청 모양을 만들 수 없다. 여기서는
/// 요청 동작에 맞는 손을 직접 만들어 넣는다.
class ScriptedSource implements LandmarkSource {
  final _controller = StreamController<HandFrame>.broadcast();
  bool started = false;
  bool stopped = false;

  /// 프레임에 실을 신뢰도.
  ///
  /// 기본값은 실기기와 같다. `OnDeviceLandmarkSource`는 신뢰도를 **측정하지
  /// 못하면서도** `minHandDetectionConfidence`(0.6)를 하한값으로 채워 넣는다.
  /// 이 값을 null로 두면 실기기에서만 터지는 경로를 테스트가 못 본다.
  double? detectionScore = 0.6;

  /// [detectionScore]가 **측정된** 값인지. false면 하한값일 뿐이다.
  bool scoreIsMeasured = false;

  @override
  bool get providesDetectionScore => scoreIsMeasured;

  @override
  Stream<HandFrame> get frames => _controller.stream;

  @override
  CameraInfo? get imageSize => const CameraInfo(width: 720, height: 1280);

  @override
  Widget? buildPreview() => null;

  @override
  LandmarkTransform get transform => const LandmarkTransform();

  /// 세션 내내 한 번만 잡혀야 한다.
  int startCount = 0;

  @override
  Future<void> start() async {
    started = true;
    startCount++;
  }

  @override
  Future<void> stop() async {
    stopped = true;
    stopCount++;
  }

  /// 세션 끝에 한 번만 놓여야 한다.
  int stopCount = 0;

  @override
  void resetClock() {}

  @override
  void dispose() => _controller.close();

  /// 정규화 좌표계(0~1)에 얹은 손 하나를 흘린다.
  void emitHand(Coords hand, {int tMs = 0}) {
    _controller.add(HandFrame(
      tMs: tMs,
      landmarks: <Landmark>[
        for (final List<double> p in hand)
          // 손 모델은 원점 근처의 ±1 좌표다. 화면 한가운데로 옮기고 줄인다.
          Landmark(0.5 + p[0] * 0.12, 0.5 + p[1] * 0.12, p[2] * 0.12),
      ],
      score: detectionScore,
    ));
  }

  /// 손이 (dx, dy)만큼 옮겨간 프레임.
  void emitMovedHand(Coords hand, double dx, double dy, {int tMs = 0}) {
    emitHand(
      <List<double>>[
        for (final List<double> p in hand) <double>[p[0] + dx, p[1] + dy, p[2]],
      ],
      tMs: tMs,
    );
  }
}


/// 세션 컨트롤러를 돌리는 데 필요한 주입 묶음.
///
/// 이제 한 컨트롤러가 Challenge와 제스처 인증을 모두 하므로 사용자·API도 필요하다.
ProviderContainer sessionContainer(
  ScriptedSource source,
  ChallengeConfig? challenge,
  ApiClient api, {
  int captureMs = 1500,
}) =>
    ProviderContainer(
      overrides: [
        landmarkSourceProvider.overrideWithValue(source),
        apiClientProvider.overrideWithValue(api),
        serverConfigProvider.overrideWith(
          () => StubConfig(challenge, captureMs: captureMs),
        ),
      ],
    );

/// 인증을 통과시키는 API. 세션 흐름만 보는 테스트라 응답 내용은 고정한다.
class PassingApi extends MockApiClient {
  int verifyCalls = 0;

  @override
  Future<List<AppUser>> fetchUsers() async =>
      <AppUser>[const AppUser(id: 'u1', name: '테스트', department: '개발팀')];

  @override
  Future<VerifyResponse> verify(VerifyRequest req) async {
    verifyCalls++;
    lastRequest = req;
    return const VerifyResponse(
      score: 0.99,
      threshold: 0.34,
      gestureScore: 0.99,
      gestureThreshold: 0.90,
      passed: true,
      gestureId: 'G1',
      modelVersion: 'test',
      latencyMs: 10,
    );
  }

  VerifyRequest? lastRequest;
}


/// 세션을 시작한다.
///
/// 사용자 목록은 비동기로 온다. 컨트롤러를 먼저 살려 두고(그래야 ref.listen이
/// 값을 받는다) 목록이 도착한 뒤에 시작해야 한다. 실기기에서도 홈 화면이
/// 목록을 받은 뒤에 인증으로 들어온다.
Future<void> startSession(ProviderContainer c) async {
  c.read(authSessionProvider);
  await c.read(usersProvider.future);
  await c.read(authSessionProvider.notifier).begin();
}


/// 이 파일 전용 설정.
///
/// **컨트롤러 배선**(좌표 변환·워치독·구독·연속성)을 보는 파일이라, 실제 시간을
/// 오래 기다려야 하는 항목은 짧게 줄인다. 임계값 자체는 각 단위 테스트가 본다.
///
/// - `movement.windowMs`: 기본 600ms는 550ms를 연속으로 채워야 한다. 전체 테스트가
///   붙어 돌면 이벤트 루프가 그보다 오래 멈춘다
/// - `tracking.frameStaleMinMs`: 테스트는 Future.delayed로 프레임을 흘리는데
///   20ms 간격이 150ms를 넘길 때가 있다. 그때마다 워치독이 '손 없음'을 넣는다
ChallengeConfig flowConfig([Map<String, dynamic> overrides = const {}]) =>
    configWith(deepMergeMaps(<String, dynamic>{
      'movement': <String, dynamic>{'windowMs': 200},
      'tracking': <String, dynamic>{'frameStaleMinMs': 600},
      'timing': <String, dynamic>{
        'perActionTimeoutMs': 4000,
        'totalTimeoutMs': 30000,
        'maxRetries': 0,
        'stepPrepareMs': 0,
        'stepResultHoldMs': 0,
      },
    }, overrides));


class StubConfig extends ServerConfigController {
  final ChallengeConfig? challenge;

  /// 제스처 수집 길이. 테스트가 실제 4초를 기다리지 않게 짧게 둔다.
  final int captureMs;

  StubConfig(this.challenge, {this.captureMs = 300});

  @override
  ServerConfigState build() => ServerConfigState(
        config: ServerConfig(
          enrollmentTakes: 3,
          enrollmentGestures: 1,
          captureDurationMs: captureMs,
          handRequired: 'right',
          modelVersion: 'test',
          postAuthUrl: '',
          challenge: challenge,
        ),
        loaded: true,
      );

  @override
  Future<void> load() async {}
}

/// 한 프레임 간격. 상태 머신은 **실제 경과 시간**으로 판정하므로 테스트도
/// 실시간으로 흘려야 한다. 실기기 13~16fps와 비슷하게 잡았다.
const Duration kFrameGap = Duration(milliseconds: 20);

/// 한 단계짜리 Challenge.
///
/// Challenge 규칙이 아니라 **그 뒤에 이어지는 전송 규약**을 보는 테스트가 쓴다.
/// 단계가 짧을수록 그 테스트가 빨라진다.
ChallengeConfig oneStepConfig([Map<String, dynamic> extra = const {}]) =>
    flowConfig(deepMergeMaps(<String, dynamic>{
      'steps': <String, dynamic>{'numShapes': 1, 'numMoves': 0},
    }, extra));

/// Challenge를 통과시키고 제스처 수집까지 끝낸다. 세션이 끝나면 돌아온다.
///
/// [stamp]로 프레임 타임스탬프를 정한다. 기본값은 일정 간격이 아니다 —
/// 컨트롤러가 tMs를 다시 계산하지 않고 소스 값을 그대로 싣는지 보려면
/// 간격이 들쭉날쭉해야 한다.
Future<void> runSession(
  ProviderContainer c,
  ScriptedSource source,
  ChallengeConfig config, {
  Duration limit = const Duration(seconds: 30),
  int Function(int index) stamp = defaultStamp,
}) async {
  AuthSessionState st() => c.read(authSessionProvider);
  await startSession(c);
  if (st().phase != SessionPhase.challenge) return;

  final Coords hand = sketchForShape(st().actions.first, config).landmarks;
  final Stopwatch clock = Stopwatch()..start();
  int i = 0;
  while (!st().finished && clock.elapsed < limit) {
    source.emitHand(hand, tMs: stamp(i++));
    await Future<void>.delayed(kFrameGap);
  }
}

int defaultStamp(int i) => i * 20 + (i % 3) * 7;

/// 응답을 테스트가 정하는 API. 업로드 실패 경로(타임아웃·오류·판정 실패)를 본다.
class StubApi extends MockApiClient {
  StubApi(this.onVerify);

  final Future<VerifyResponse> Function(VerifyRequest) onVerify;

  int verifyCalls = 0;
  VerifyRequest? lastRequest;

  /// 서버 users 목록. 요청의 userId가 이름이 아니라 이 id여야 한다.
  @override
  Future<List<AppUser>> fetchUsers() async => const <AppUser>[
        AppUser(id: 'hong', name: '홍길동', department: '개발팀'),
        AppUser(id: 'kim', name: '김길동', department: '인사팀'),
        AppUser(id: 'oh', name: '오박사', department: '영업팀'),
      ];

  @override
  Future<VerifyResponse> verify(VerifyRequest req) {
    verifyCalls++;
    lastRequest = req;
    return onVerify(req);
  }
}

/// 카메라 권한이 거부된 상황을 흉내 내는 소스.
class DeniedSource extends ScriptedSource {
  @override
  Future<void> start() async {
    throw const LandmarkSourceException(
      '카메라 권한이 없습니다. 설정 > 앱 > Sign-ID에서 카메라 접근을 허용해주세요.',
    );
  }
}

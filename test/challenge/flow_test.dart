/// 실기기 없이 Challenge 전체 흐름이 끝까지 도는지.
///
/// 컨트롤러는 카메라 스트림을 [Observation]으로 바꿔주는 층이다. 상태 머신 단위
/// 테스트가 규칙을 보장하더라도, 좌표 변환이나 워치독이 어긋나면 실기기에서만
/// 드러난다. 여기서 대본대로 손을 흘려보내 통과·실패가 나는지 확인한다.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:signid/challenge/challenge_config.dart';
import 'package:signid/challenge/challenge_state_machine.dart';
import 'package:signid/challenge/geometry.dart';
import 'package:signid/challenge/hand_action_detector.dart';
import 'package:signid/challenge/hand_sketch.dart';
import 'package:signid/models/camera_info.dart';
import 'package:signid/models/landmark.dart';
import 'package:signid/models/server_config.dart';
import 'package:signid/services/landmark_source.dart';
import 'package:signid/state/challenge_controller.dart';
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

  @override
  Future<void> start() async => started = true;

  @override
  Future<void> stop() async => stopped = true;

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

void main() {
  late ScriptedSource source;
  late ProviderContainer container;
  late ChallengeConfig config;

  setUp(() {
    source = ScriptedSource();
    // 실기기에서 Challenge를 끝낼 수 있게 여유를 둔 설정. 임계값 자체는
    // 서버 기본값 그대로다.
    config = configWith(<String, dynamic>{
      'timing': <String, dynamic>{
        'perActionTimeoutMs': 4000,
        'totalTimeoutMs': 30000,
        'maxRetries': 0,
      },
    });
    container = ProviderContainer(
      overrides: [
        landmarkSourceProvider.overrideWithValue(source),
        serverConfigProvider.overrideWith(() => _StubConfig(config)),
      ],
    );
  });

  tearDown(() {
    container.dispose();
    source.dispose();
  });

  ChallengeController controller() =>
      container.read(challengeControllerProvider.notifier);

  ChallengeFlowState flow() => container.read(challengeControllerProvider);

  /// 한 프레임 간격. 상태 머신은 **실제 경과 시간**으로 판정하므로
  /// (컨트롤러가 자기 시계를 쓴다) 테스트도 실시간으로 흘려야 한다.
  /// 실기기 13~16fps와 비슷하게 잡았다.
  const Duration frameGap = Duration(milliseconds: 20);

  /// 요청 동작을 수행한다. 단계가 넘어가거나 세션이 끝날 때까지 흘린다.
  ///
  /// 프레임 수를 고정하면 유지 시간(shapeHoldFrames)이나 이동 윈도우가 찰 때까지
  /// 모자랄 수 있다. 조건이 채워질 때까지 넣는다.
  Future<void> perform(String action, {int maxFrames = 80}) async {
    final int before = flow().stepIndex;
    final bool isShape = kShapePatterns.containsKey(action);
    final Coords hand =
        sketchForShape(isShape ? action : 'OPEN_PALM', config).landmarks;

    // 화면(거울) 기준 방향으로 보이려면 원본 좌표는 반대로 움직여야 한다.
    // coordinateFrame=mirrored가 **라벨을** 뒤집기 때문이다. 좌표를 여기서
    // 뒤집는 게 아니라, 실제 손이 반대로 가야 화면에서 그 방향으로 보인다.
    final double sign = config.coordinateFrame == 'mirrored' ? -1.0 : 1.0;
    final ({double dx, double dy})? dir = isShape ? null : arrowFor(action);

    // 준비 시간(stepPrepareMs) 동안에는 판정이 돌지 않는다. 그 프레임은 한도에
    // 넣지 않는다 — 실제 사용자도 그림을 보며 기다린다.
    int used = 0;
    int i = 0;
    while (used < maxFrames) {
      if (isShape) {
        source.emitHand(hand, tMs: i * 20);
      } else {
        // 한 방향으로 등속. 되돌아오면 그 구간이 반대 방향으로 잡힌다.
        source.emitMovedHand(
          hand,
          dir!.dx * sign * used * 0.15,
          dir.dy * used * 0.15,
          tMs: i * 20,
        );
      }
      i++;
      await Future<void>.delayed(frameGap);
      if (flow().finished || flow().stepIndex != before) return;
      if (!(flow().status?.preparing ?? false)) used++;
    }
  }

  test('Challenge 전체를 끝까지 통과한다', () async {
    await controller().begin();
    expect(source.started, isTrue);
    expect(flow().phase, ChallengePhase.running);
    expect(flow().actions.length, 3);

    for (final String action in flow().actions) {
      // 이탈 관문이 걸린 단계는 먼저 다른 모양으로 벗어나야 한다.
      // (이동 다음 단계가 OPEN_PALM이면 손이 이미 그 모양이라 공짜 통과가 된다)
      final Status? status = flow().status;
      if (status != null && status.awaitingEscape) {
        final String escapeTo =
            status.escapeFrom == 'FIST' ? 'OPEN_PALM' : 'FIST';
        await perform(escapeTo, maxFrames: 30);
      }
      await perform(action);
      if (flow().finished) break;
    }

    expect(flow().phase, ChallengePhase.passed,
        reason: '요청: ${flow().actions}, 사유: ${flow().status?.failReason}');
    expect(flow().status!.steps.every((StepResult s) => s.passed), isTrue);
    // 통과하면 카메라를 놓는다.
    expect(source.stopped, isTrue);
  });

  test('손을 들지 않아도 바로 끝나지 않는다 (대기 단계)', () async {
    // 화면이 뜨자마자 판정이 시작되면 손을 들기도 전에 끝난다.
    await controller().begin();
    await Future<void>.delayed(const Duration(milliseconds: 2500));

    expect(flow().phase, ChallengePhase.running);
    expect(flow().status!.state, ChallengeState.waitHand);
    expect(flow().status!.awaitingHand, isTrue);
  });

  test('대기 제한(안전장치)까지 지나면 HAND_NOT_FOUND', () async {
    config = configWith(<String, dynamic>{
      'timing': <String, dynamic>{
        'perActionTimeoutMs': 4000,
        'totalTimeoutMs': 30000,
        'maxRetries': 0,
        'waitHandTimeoutMs': 800,
      },
    });
    final ProviderContainer short = ProviderContainer(
      overrides: [
        landmarkSourceProvider.overrideWithValue(source),
        serverConfigProvider.overrideWith(() => _StubConfig(config)),
      ],
    );
    addTearDown(short.dispose);

    await short.read(challengeControllerProvider.notifier).begin();
    await Future<void>.delayed(const Duration(milliseconds: 1500));

    final ChallengeFlowState state = short.read(challengeControllerProvider);
    expect(state.phase, ChallengePhase.failed);
    expect(state.status!.failReason, FailReason.handNotFound);
  });

  test('요청과 다른 손 모양만 하면 실패한다', () async {
    await controller().begin();
    final String first = flow().actions.first;
    // 요청이 손 모양일 때만 의미가 있는 시나리오다.
    if (!kShapePatterns.containsKey(first)) return;

    final String wrong = kShapePatterns.keys.firstWhere((String k) => k != first);
    final Coords hand = sketchForShape(wrong, config).landmarks;
    for (int i = 0; i < 400 && !flow().finished; i++) {
      source.emitHand(hand, tMs: i * 20);
      await Future<void>.delayed(const Duration(milliseconds: 12));
    }

    expect(flow().phase, ChallengePhase.failed);
    expect(
      flow().status!.failReason,
      anyOf(FailReason.wrongShape, FailReason.wrongOrder,
          FailReason.actionTimeout, FailReason.totalTimeout),
    );
  });

  test('설정을 못 받으면 시작하지 않는다', () async {
    final ProviderContainer bare = ProviderContainer(
      overrides: [
        landmarkSourceProvider.overrideWithValue(source),
        serverConfigProvider.overrideWith(() => _StubConfig(null)),
      ],
    );
    addTearDown(bare.dispose);

    await bare.read(challengeControllerProvider.notifier).begin();
    final ChallengeFlowState state = bare.read(challengeControllerProvider);

    expect(state.phase, ChallengePhase.unavailable);
    expect(state.notice, contains('Challenge 설정'));
    // 임계값을 추측해서 진행하지 않는다.
    expect(source.started, isFalse);
  });

  test('angleSpace가 world면 막는다 (플러그인이 world 좌표를 주지 않는다)', () async {
    final ProviderContainer worldContainer = ProviderContainer(
      overrides: [
        landmarkSourceProvider.overrideWithValue(source),
        serverConfigProvider.overrideWith(
          () => _StubConfig(configWith(<String, dynamic>{'angleSpace': 'world'})),
        ),
      ],
    );
    addTearDown(worldContainer.dispose);

    await worldContainer.read(challengeControllerProvider.notifier).begin();
    expect(
      worldContainer.read(challengeControllerProvider).phase,
      ChallengePhase.unavailable,
    );
    expect(source.started, isFalse);
  });

  test('취소하면 카메라를 놓고 상태를 되돌린다', () async {
    await controller().begin();
    expect(flow().phase, ChallengePhase.running);

    controller().cancel();
    expect(flow().phase, ChallengePhase.idle);
    expect(source.stopped, isTrue);
  });

  // ─── 회귀: 실기기에서 TRACKING_UNSTABLE이 계속 뜨던 문제 ──────────────
  //
  // OnDeviceLandmarkSource는 신뢰도를 **측정하지 못하면서도** score에
  // minHandDetectionConfidence(0.6)를 하한값으로 채워 넣는다. 그 0.6이
  // minDetectionScore(0.938)와 비교되어 매 프레임 미달로 판정됐다.
  //
  // 0.6은 "이 값 이상"이라는 뜻이지 측정된 신뢰도가 아니다. 도출된 임계값
  // (정상 영상 검출 프레임 p5=0.938)과 비교할 수 있는 값이 아니다.
  test('신뢰도 하한값(0.6)만 있는 소스에서도 끝까지 돈다', () async {
    source.detectionScore = 0.6; // 실기기와 같은 조건

    await controller().begin();
    for (final String action in flow().actions) {
      final Status? status = flow().status;
      if (status != null && status.awaitingEscape) {
        await perform(
          status.escapeFrom == 'FIST' ? 'OPEN_PALM' : 'FIST',
          maxFrames: 30,
        );
      }
      await perform(action);
      if (flow().finished) break;
    }

    expect(
      flow().status?.failReason,
      isNot(FailReason.trackingUnstable),
      reason: '측정하지 않은 하한값을 신뢰도 관문에 넣으면 안 된다',
    );
    expect(flow().phase, ChallengePhase.passed);
  });

  test('진짜로 측정된 낮은 신뢰도는 여전히 거른다', () async {
    // 하한값을 무시한다고 관문 자체를 없애면, 플러그인이 진짜 신뢰도를 주게
    // 됐을 때 아무것도 안 걸러진다.
    source.detectionScore = 0.5;
    source.scoreIsMeasured = true;

    await controller().begin();
    final String first = flow().actions.first;
    final Coords hand =
        sketchForShape(kShapePatterns.containsKey(first) ? first : 'OPEN_PALM',
                config)
            .landmarks;

    // 프레임 수가 아니라 벽시계로 돈다. 관문이 시간 기준이라 전체 테스트가
    // 붙어 돌 때는 같은 프레임 수가 다른 시간이 된다.
    final Stopwatch clock = Stopwatch()..start();
    int i = 0;
    while (!flow().finished && clock.elapsed < const Duration(seconds: 6)) {
      source.emitHand(hand, tMs: i++ * 20);
      await Future<void>.delayed(const Duration(milliseconds: 12));
    }

    expect(
      flow().status?.failReason,
      FailReason.trackingUnstable,
      reason: '${clock.elapsedMilliseconds}ms, $i프레임 뒤 상태=${flow().phase}',
    );
  });
}

/// 서버 왕복 없이 설정을 주입한다.
class _StubConfig extends ServerConfigController {
  final ChallengeConfig? challenge;

  _StubConfig(this.challenge);

  @override
  ServerConfigState build() => ServerConfigState(
        config: ServerConfig.fallback.copyWithChallenge(challenge),
        loaded: true,
      );

  @override
  Future<void> load() async {}
}

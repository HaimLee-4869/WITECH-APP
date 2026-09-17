/// 실기기 없이 Challenge 전체 흐름이 끝까지 도는지.
///
/// 컨트롤러는 카메라 스트림을 [Observation]으로 바꿔주는 층이다. 상태 머신 단위
/// 테스트가 규칙을 보장하더라도, 좌표 변환이나 워치독이 어긋나면 실기기에서만
/// 드러난다. 여기서 대본대로 손을 흘려보내 통과·실패가 나는지 확인한다.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:signid/challenge/challenge_config.dart';
import 'package:signid/core/config.dart';
import 'package:signid/challenge/challenge_state_machine.dart';
import 'package:signid/challenge/geometry.dart';
import 'package:signid/challenge/hand_action_detector.dart';
import 'package:signid/challenge/hand_sketch.dart';
import 'package:signid/state/auth_session_controller.dart';

import 'config_fixture.dart';
import 'session_harness.dart';

void main() {
  late ScriptedSource source;
  late ProviderContainer container;
  late ChallengeConfig config;
  late PassingApi api;

  setUp(() {
    source = ScriptedSource();
    // 실기기에서 Challenge를 끝낼 수 있게 여유를 둔 설정. 임계값 자체는
    // 서버 기본값 그대로다.
    // 이 파일은 **컨트롤러 배선**(좌표 변환·워치독·구독)을 본다. 결과 표시와 준비
    // 시간은 실제 시간을 그대로 기다리므로, 켜 두면 3단계에 10초 넘게 걸려
    // 전체 테스트가 붙어 돌 때 불안정해진다. 그 규칙은 step_result_test.dart와
    // step_prepare_test.dart가 따로 본다. 여기서는 짧게 한 번만 확인한다.
    config = flowConfig();
    api = PassingApi();
    container = sessionContainer(source, config, api);
  });

  tearDown(() {
    container.dispose();
    source.dispose();
  });

  AuthSessionController controller() =>
      container.read(authSessionProvider.notifier);

  AuthSessionState flow() => container.read(authSessionProvider);

  /// 한 프레임 간격. 상태 머신은 **실제 경과 시간**으로 판정하므로
  /// (컨트롤러가 자기 시계를 쓴다) 테스트도 실시간으로 흘려야 한다.
  /// 실기기 13~16fps와 비슷하게 잡았다.
  const Duration frameGap = Duration(milliseconds: 20);

  /// 요청 동작을 수행한다. 단계가 넘어가거나 세션이 끝날 때까지 흘린다.
  ///
  /// 프레임 수를 고정하면 유지 시간(shapeHoldFrames)이나 이동 윈도우가 찰 때까지
  /// 모자랄 수 있다. 조건이 채워질 때까지 넣는다.
  /// 한 단계에 쓸 수 있는 실제 시간.
  ///
  /// 프레임 수로 한도를 잡으면 전체 테스트가 붙어 돌 때(스케줄러 지연) 같은
  /// 프레임 수가 더 긴 시간이 되어 들쭉날쭉해진다. 벽시계로 잰다.
  Future<void> perform(String action,
      {Duration budget = const Duration(seconds: 8)}) async {
    final int before = flow().stepIndex;
    final bool isShape = kShapePatterns.containsKey(action);
    final Coords hand =
        sketchForShape(isShape ? action : 'OPEN_PALM', config).landmarks;

    // 화면(거울) 기준 방향으로 보이려면 원본 좌표는 반대로 움직여야 한다.
    // coordinateFrame=mirrored가 **라벨을** 뒤집기 때문이다. 좌표를 여기서
    // 뒤집는 게 아니라, 실제 손이 반대로 가야 화면에서 그 방향으로 보인다.
    final double sign = config.coordinateFrame == 'mirrored' ? -1.0 : 1.0;
    final ({double dx, double dy})? dir = isShape ? null : arrowFor(action);

    // 결과 표시(stepResultHoldMs)와 준비 시간(stepPrepareMs) 동안에는 판정이
    // 돌지 않는다. 그 시간은 한도에 넣지 않는다 — 실제 사용자도 기다린다.
    final Stopwatch judging = Stopwatch();
    int used = 0;
    int i = 0;
    while (judging.elapsed < budget) {
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
      final Status? s = flow().status;
      final bool waiting =
          (s?.preparing ?? false) || (s?.stepResult != null);
      if (waiting) {
        judging.stop();
      } else {
        used++;
        if (!judging.isRunning) judging.start();
      }
    }
  }

  test('Challenge 전체를 끝까지 통과한다', () async {
    await startSession(container);
    expect(source.started, isTrue);
    expect(flow().phase, SessionPhase.challenge);
    expect(flow().actions.length, 3);

    for (final String action in flow().actions) {
      // 이탈 관문이 걸린 단계는 먼저 다른 모양으로 벗어나야 한다.
      // (이동 다음 단계가 OPEN_PALM이면 손이 이미 그 모양이라 공짜 통과가 된다)
      final Status? status = flow().status;
      if (status != null && status.awaitingEscape) {
        final String escapeTo =
            status.escapeFrom == 'FIST' ? 'OPEN_PALM' : 'FIST';
        await perform(escapeTo, budget: const Duration(seconds: 4));
      }
      await perform(action);
      if (flow().finished) break;
    }

    // 마지막 단계 PASS 표시가 끝나야 통과로 확정된다.
    // 마지막 단계 PASS 표시가 끝나면 **카메라를 놓지 않고** 제스처 수집으로
    // 이어진다. 손을 계속 보여줘야 세션이 끊기지 않는다.
    final Coords wait = sketchForShape('OPEN_PALM', config).landmarks;
    final Stopwatch clock = Stopwatch()..start();
    int i = 0;
    while (!flow().finished && clock.elapsed < const Duration(seconds: 15)) {
      source.emitHand(wait, tMs: 9000 + i++ * 20);
      await Future<void>.delayed(frameGap);
    }

    expect(flow().phase, SessionPhase.done,
        reason: '요청: ${flow().actions}, 단계: ${flow().stepIndex}, '
            '사유: ${flow().status?.failReason}, 안내: ${flow().notice}');
    expect(flow().status!.steps.every((StepResult s) => s.passed), isTrue);
    // 통과하면 카메라를 놓는다.
    expect(source.stopped, isTrue);
  });

  test('손을 들지 않아도 바로 끝나지 않는다 (대기 단계)', () async {
    // 화면이 뜨자마자 판정이 시작되면 손을 들기도 전에 끝난다.
    await startSession(container);
    await Future<void>.delayed(const Duration(milliseconds: 2500));

    expect(flow().phase, SessionPhase.challenge);
    expect(flow().status!.state, ChallengeState.waitHand);
    expect(flow().status!.awaitingHand, isTrue);
  });

  test('대기 제한(안전장치)까지 지나면 HAND_NOT_FOUND', () async {
    config = flowConfig(<String, dynamic>{
      'timing': <String, dynamic>{'waitHandTimeoutMs': 800},
    });
    final ProviderContainer short = sessionContainer(source, config, api);
    addTearDown(short.dispose);

    await startSession(short);
    await Future<void>.delayed(const Duration(milliseconds: 1500));

    final AuthSessionState state = short.read(authSessionProvider);
    expect(state.phase, SessionPhase.failed);
    expect(state.status!.failReason, FailReason.handNotFound);
  });

  test('요청과 다른 손 모양만 하면 실패한다', () async {
    await startSession(container);
    final String first = flow().actions.first;
    // 요청이 손 모양일 때만 의미가 있는 시나리오다.
    if (!kShapePatterns.containsKey(first)) return;

    final String wrong = kShapePatterns.keys.firstWhere((String k) => k != first);
    final Coords hand = sketchForShape(wrong, config).landmarks;
    for (int i = 0; i < 400 && !flow().finished; i++) {
      source.emitHand(hand, tMs: i * 20);
      await Future<void>.delayed(const Duration(milliseconds: 12));
    }

    expect(flow().phase, SessionPhase.failed);
    expect(
      flow().status!.failReason,
      anyOf(FailReason.wrongShape, FailReason.wrongOrder,
          FailReason.actionTimeout, FailReason.totalTimeout),
    );
  });

  test('설정을 못 받으면 시작하지 않는다', () async {
    final ProviderContainer bare = sessionContainer(source, null, api);
    addTearDown(bare.dispose);

    await startSession(bare);
    final AuthSessionState state = bare.read(authSessionProvider);

    expect(state.phase, SessionPhase.unavailable);
    expect(state.notice, contains('Challenge 설정'));
    // 임계값을 추측해서 진행하지 않는다.
    expect(source.started, isFalse);
  });

  test('angleSpace가 world면 막는다 (플러그인이 world 좌표를 주지 않는다)', () async {
    final ProviderContainer worldContainer = sessionContainer(source,
        configWith(<String, dynamic>{'angleSpace': 'world'}),
        api,);
    addTearDown(worldContainer.dispose);

    await startSession(worldContainer);
    expect(
      worldContainer.read(authSessionProvider).phase,
      SessionPhase.unavailable,
    );
    expect(source.started, isFalse);
  });

  test('결과 표시와 준비 시간을 지나 통과까지 간다', () async {
    // 표시 시간을 짧게 켜고 한 단계만 돌린다. 컨트롤러가 이 구간에서
    // 멈추지 않고 끝까지 가는지 본다.
    config = flowConfig(<String, dynamic>{
      'steps': <String, dynamic>{'numShapes': 1, 'numMoves': 0},
      'timing': <String, dynamic>{'stepPrepareMs': 200, 'stepResultHoldMs': 200},
    });
    final ProviderContainer short = sessionContainer(source, config, api);
    addTearDown(short.dispose);

    await startSession(short);
    AuthSessionState st() => short.read(authSessionProvider);
    expect(st().actions.length, 1);

    final Coords hand = sketchForShape(st().actions.first, config).landmarks;
    bool sawResult = false;
    final Stopwatch clock = Stopwatch()..start();
    int i = 0;
    // PASS 표시가 끝나도 카메라를 놓지 않고 제스처 수집으로 이어진다.
    // 세션이 끝날 때까지 손을 계속 보여준다.
    while (!st().finished && clock.elapsed < const Duration(seconds: 15)) {
      source.emitHand(hand, tMs: i++ * 20);
      await Future<void>.delayed(frameGap);
      if (st().status?.stepResult != null) sawResult = true;
    }

    expect(sawResult, isTrue, reason: 'PASS 표시를 거치지 않았다');
    expect(st().phase, SessionPhase.done);
  });

  test('취소하면 카메라를 놓고 상태를 되돌린다', () async {
    await startSession(container);
    expect(flow().phase, SessionPhase.challenge);

    controller().cancel();
    expect(flow().phase, SessionPhase.idle);
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

    await startSession(container);
    for (final String action in flow().actions) {
      final Status? status = flow().status;
      if (status != null && status.awaitingEscape) {
        await perform(
          status.escapeFrom == 'FIST' ? 'OPEN_PALM' : 'FIST',
          budget: const Duration(seconds: 4),
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

    // 마지막 단계 PASS 표시가 끝나야 통과로 확정된다.
    // 마지막 단계 PASS 표시가 끝나면 **카메라를 놓지 않고** 제스처 수집으로
    // 이어진다. 손을 계속 보여줘야 세션이 끊기지 않는다.
    final Coords wait = sketchForShape('OPEN_PALM', config).landmarks;
    final Stopwatch clock = Stopwatch()..start();
    int i = 0;
    while (!flow().finished && clock.elapsed < const Duration(seconds: 15)) {
      source.emitHand(wait, tMs: 9000 + i++ * 20);
      await Future<void>.delayed(frameGap);
    }
    expect(flow().phase, SessionPhase.done);
  });

  test('진짜로 측정된 낮은 신뢰도는 여전히 거른다', () async {
    // 하한값을 무시한다고 관문 자체를 없애면, 플러그인이 진짜 신뢰도를 주게
    // 됐을 때 아무것도 안 걸러진다.
    source.detectionScore = 0.5;
    source.scoreIsMeasured = true;

    await startSession(container);
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

  // ─── 연속 세션 ──────────────────────────────────────────────────
  //
  // Challenge와 제스처 인증을 한 번의 촬영으로 묶는 것이 이번 구조의 목적이다.
  // 촬영을 둘로 나누면 "Challenge는 본인 손, 인증은 피해자 영상"을 막지 못한다.

  /// 한 단계짜리 Challenge 설정. 여기서 보는 것은 단계 규칙이 아니라
  /// **Challenge에서 수집으로 넘어가는 이음매**라 짧을수록 좋다.
  ChallengeConfig oneStep([Map<String, dynamic> extra = const {}]) =>
      flowConfig(deepMergeMaps(<String, dynamic>{
        'steps': <String, dynamic>{'numShapes': 1, 'numMoves': 0},
      }, extra));

  /// Challenge를 통과시켜 제스처 수집까지 끌고 간다. 마지막으로 흘린 tMs를 준다.
  Future<int> runToRecording(ProviderContainer c) async {
    AuthSessionState st() => c.read(authSessionProvider);
    await startSession(c);
    final Coords hand = sketchForShape(st().actions.first, config).landmarks;
    final Stopwatch clock = Stopwatch()..start();
    int i = 0;
    while (st().phase == SessionPhase.challenge &&
        clock.elapsed < const Duration(seconds: 10)) {
      source.emitHand(hand, tMs: i++ * 20);
      await Future<void>.delayed(frameGap);
    }
    expect(st().phase, SessionPhase.recording,
        reason: 'Challenge에서 수집으로 이어지지 않았다 (${st().notice})');
    return i * 20;
  }

  /// 세션이 끝날 때까지 기다린다. [hand]가 있으면 계속 흘린다.
  Future<void> drain(ProviderContainer c, {Coords? hand, int fromTMs = 0}) async {
    AuthSessionState st() => c.read(authSessionProvider);
    final Stopwatch clock = Stopwatch()..start();
    int t = fromTMs;
    while (!st().finished && clock.elapsed < const Duration(seconds: 20)) {
      if (hand != null) source.emitHand(hand, tMs: t += 20);
      await Future<void>.delayed(frameGap);
    }
  }

  test('한 번 잡은 카메라로 Challenge와 수집을 이어서 한다', () async {
    // 화면을 옮기며 stop/start 하면 그 사이가 비고, 구독이 누수되어 프레임이
    // 두 배로 수집되는 문제도 거기서 났다.
    config = oneStep();
    final ProviderContainer c = sessionContainer(source, config, api);
    addTearDown(c.dispose);
    AuthSessionState st() => c.read(authSessionProvider);

    final int t = await runToRecording(c);
    expect(source.startCount, 1);
    // begin()이 이전 시도를 한 번 정리한다. 그 뒤로는 세션이 끝날 때까지
    // 카메라를 놓지 않아야 한다.
    expect(source.stopCount, 1, reason: 'Challenge 끝에 카메라를 놓았다');

    await drain(c,
        hand: sketchForShape('OPEN_PALM', config).landmarks, fromTMs: t);

    expect(st().phase, SessionPhase.done, reason: st().notice ?? '');
    expect(api.verifyCalls, 1);
    expect(api.lastRequest!.frames.length,
        greaterThanOrEqualTo(kMinFramesForVerify));
    expect(source.startCount, 1, reason: '수집을 시작하며 카메라를 다시 잡았다');
    expect(source.stopCount, 2, reason: '끝나고도 카메라를 놓지 않았다');
  });

  test('제스처 수집 중에 손이 사라지면 세션이 끊긴다', () async {
    // 여기가 "Challenge는 본인 손, 인증은 피해자 영상"의 자리다.
    config = oneStep(<String, dynamic>{
      'tracking': <String, dynamic>{'maxLostFrames': 3},
    });
    // 손이 사라진 것을 알아채기 전에 수집이 끝나버리면 이 테스트가 의미 없다.
    final ProviderContainer c =
        sessionContainer(source, config, api, captureMs: 6000);
    addTearDown(c.dispose);
    AuthSessionState st() => c.read(authSessionProvider);

    await runToRecording(c);
    await drain(c); // 손을 뺀다

    expect(st().phase, SessionPhase.failed);
    // 수집 구간은 상태 머신이 돌지 않는다. 사유는 안내 문구로 나간다.
    expect(st().notice, contains('손이 화면에서 벗어났습니다'));
    expect(api.verifyCalls, 0, reason: '끊긴 세션을 서버로 보냈다');
  });

  test('PASS 표시 구간에 손이 사라져도 세션이 끊긴다', () async {
    // 통과 표시를 본 사용자가 손을 내리는 순간이 가장 위험하다.
    config = oneStep(<String, dynamic>{
      'timing': <String, dynamic>{'stepResultHoldMs': 3000},
      'tracking': <String, dynamic>{'maxLostFrames': 3},
    });
    final ProviderContainer c = sessionContainer(source, config, api);
    addTearDown(c.dispose);
    AuthSessionState st() => c.read(authSessionProvider);
    await startSession(c);

    final Coords hand = sketchForShape(st().actions.first, config).landmarks;
    final Stopwatch clock = Stopwatch()..start();
    int i = 0;
    while (st().status?.stepResult == null &&
        clock.elapsed < const Duration(seconds: 10)) {
      source.emitHand(hand, tMs: i++ * 20);
      await Future<void>.delayed(frameGap);
    }
    expect(st().status?.stepResult, StepOutcome.pass,
        reason: 'PASS 표시에 들어가지 못했다');

    // 표시 중에는 판정이 멈춰 있다. 그래도 추적은 살아 있어야 한다.
    await drain(c);

    expect(st().phase, SessionPhase.failed);
    expect(st().status?.failReason, FailReason.sessionBroken);
    expect(api.verifyCalls, 0);
  });
}

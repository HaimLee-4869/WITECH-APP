/// `challenge_response/tests/test_state_machine.py`의 이식.
///
/// 순서 위반·타임아웃·손 소실이 각각 올바른 [FailReason]을 내는지 본다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:signid/challenge/challenge_config.dart';
import 'package:signid/challenge/challenge_generator.dart';
import 'package:signid/challenge/challenge_state_machine.dart';
import 'package:signid/challenge/geometry.dart';
import 'package:signid/challenge/hand_action_detector.dart';

import 'config_fixture.dart';
import 'synth.dart';

const double kFps = 30.0;
const double kFrameMs = 1000.0 / kFps;

/// Python 테스트의 CONFIG와 같은 값.
ChallengeConfig smConfig([Map<String, dynamic> overrides = const {}]) =>
    configWith(<String, dynamic>{
      'angleSpace': 'world',
      'coordinateFrame': 'raw',
      'fingerExtendedAngle': <String, dynamic>{'thumb': 150.0, 'others': 160.0},
      'shapeConfidenceMarginDeg': 10.0,
      'shapeConfidenceMin': 0.5,
      'shapeHoldFrames': 5,
      'fistMaxTipWristRatio': null,
      'escapeFrames': 0, // 이탈 관문은 escape_gate_test.dart에서 따로 본다
      'movement': <String, dynamic>{
        'windowMs': 400, // 30fps에서 12프레임
        'minDisplacementRatio': 1.2,
        'axisDominanceRatio': 2.0,
        'maxDurationMs': 2500,
      },
      'timing': <String, dynamic>{
        'perActionTimeoutMs': 2000,
        'totalTimeoutMs': 9000,
        'maxRetries': 0,
      },
      'tracking': <String, dynamic>{'maxLostFrames': 5, 'minDetectionScore': 0.5},
      ...overrides,
    });

Coords shapeHand(String label) => makePatternHand(
      extended: <String, bool>{
        'thumb': true,
        for (final (int i, String name) in kNonThumbFingers.indexed)
          name: kShapePatterns[label]![i],
      },
      extendedAngle: kExtendedAngle,
      curledAngle: kCurledAngle,
    );

ChallengeStateMachine build(List<String> actions, [ChallengeConfig? config]) {
  final ChallengeConfig cfg = config ?? smConfig();
  return ChallengeStateMachine(
    config: cfg,
    challenge: Challenge(
      challengeId: 'test',
      actions: actions,
      createdAt: DateTime.utc(2026),
      shapePool: cfg.shapePool,
      movePool: cfg.movePool,
    ),
    fps: kFps,
  );
}

Observation obs(
  double tMs, {
  Coords? hand,
  bool found = true,
  double? score = 1.0,
  List<double> center = const <double>[0.0, 0.0, 0.0],
}) {
  final Coords coords = hand ?? makeHand(uniformAngle: 180.0, center: center);
  return Observation(
    timestampMs: tMs,
    handFound: found,
    detectionScore: score,
    angleCoords: coords,
    screenCoords: coords,
  );
}

Status? feedShape(
  ChallengeStateMachine sm,
  String label,
  int frames, [
  double startMs = 0.0,
]) {
  Status? status;
  for (int i = 0; i < frames; i++) {
    status = sm.update(obs(startMs + i * kFrameMs, hand: shapeHand(label)));
    if (status.finished) break;
  }
  return status;
}

/// 단계 제한 시간을 넘기기에 충분한 프레임 수.
int timeoutFrames(ChallengeConfig config) =>
    (config.timing.perActionTimeoutMs / kFrameMs).toInt() + 2;

Status? feedUntilTimeout(
  ChallengeStateMachine sm,
  String label, [
  ChallengeConfig? config,
  double startMs = 0.0,
]) =>
    feedShape(sm, label, timeoutFrames(config ?? sm.config), startMs);

/// 제한 시간을 넘길 때까지 한 방향으로 등속 이동시킨다.
/// 되돌아오면 그 구간이 반대 방향으로 검출되므로 한 방향으로만 간다.
Status? feedMoveUntilTimeout(
  ChallengeStateMachine sm,
  double dx,
  double dy, {
  double startMs = 0.0,
  double rate = 0.5,
}) {
  Status? status;
  for (int i = 0; i < timeoutFrames(sm.config); i++) {
    status = sm.update(obs(
      startMs + i * kFrameMs,
      center: <double>[dx * rate * i, dy * rate * i, 0.0],
    ));
    if (status.finished) break;
  }
  return status;
}

/// window 길이 동안 origin에서 (dx, dy)만큼 등속 이동.
(Status?, double) stroke(
  ChallengeStateMachine sm,
  double dx,
  double dy,
  double startMs, {
  List<double> origin = const <double>[0.0, 0.0],
}) {
  final int window = sm.movementDetector.windowFrames(kFps);
  Status? status;
  for (int i = 0; i < window; i++) {
    final double f = i / (window - 1);
    status = sm.update(obs(
      startMs + i * kFrameMs,
      center: <double>[origin[0] + dx * f, origin[1] + dy * f, 0.0],
    ));
    if (status.finished || sm.stepIndex > 0) break;
  }
  return (status, startMs + window * kFrameMs);
}

void main() {
  group('정상 흐름', () {
    test('요청한 모양을 유지하면 단계를 통과한다', () {
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'FIST', 'MOVE_RIGHT']);
      feedShape(sm, 'OPEN_PALM', sm.config.shapeHoldFrames);
      expect(sm.stepIndex, 1);
      expect(sm.steps[0].passed, isTrue);
    });

    test('유지 길이를 다 못 채우면 통과하지 않는다', () {
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'FIST', 'MOVE_RIGHT']);
      feedShape(sm, 'OPEN_PALM', sm.config.shapeHoldFrames - 1);
      expect(sm.stepIndex, 0);
      expect(sm.steps[0].passed, isFalse);
    });

    test('3단계 전체를 통과할 수 있다', () {
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'FIST', 'MOVE_RIGHT']);
      final int hold = sm.config.shapeHoldFrames;
      double t = 0.0;
      feedShape(sm, 'OPEN_PALM', hold, t);
      t += hold * kFrameMs;
      feedShape(sm, 'FIST', hold, t);
      t += hold * kFrameMs;

      final int window = sm.movementDetector.windowFrames(kFps);
      Status? status;
      for (int i = 0; i < window; i++) {
        status = sm.update(obs(
          t + i * kFrameMs,
          center: <double>[3.0 * i / (window - 1), 0.0, 0.0],
        ));
      }
      expect(status!.state, ChallengeState.passed);
      expect(status.steps.every((StepResult s) => s.passed), isTrue);
    });

    test('유지 진행도를 알려준다', () {
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'FIST', 'MOVE_RIGHT']);
      final Status status =
          feedShape(sm, 'OPEN_PALM', sm.config.shapeHoldFrames - 2)!;
      expect(status.holdProgress, greaterThan(0.0));
      expect(status.holdProgress, lessThan(1.0));
    });
  });

  group('실패 사유', () {
    test('틀린 모양은 제한 시간 뒤 WRONG_SHAPE', () {
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'INDEX', 'MOVE_RIGHT']);
      final Status status = feedUntilTimeout(sm, 'FIST')!;
      expect(status.state, ChallengeState.failed);
      expect(status.failReason, FailReason.wrongShape);
    });

    test('틀린 모양을 했다가 바로잡으면 통과한다', () {
      // 유예가 없으면 손을 든 순간의 모양이 요청과 다르다는 이유로 0.3초 만에
      // 세션이 끝난다. 실기기 테스트에서 실패 11건 중 7건이 이 경우였다.
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'INDEX', 'MOVE_RIGHT']);
      final int wrongFrames = sm.config.shapeHoldFrames * 2;
      final Status status = feedShape(sm, 'FIST', wrongFrames)!;
      expect(status.state, isNot(ChallengeState.failed));

      feedShape(sm, 'OPEN_PALM', sm.config.shapeHoldFrames,
          wrongFrames * kFrameMs);
      expect(sm.steps[0].passed, isTrue);
      expect(sm.stepIndex, 1);
    });

    test('서로 다른 오검출이 번갈아 나오면 누적되지 않는다', () {
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'MOVE_RIGHT', 'MOVE_UP']);
      Status? status;
      for (int i = 0; i < sm.config.shapeHoldFrames * 3; i++) {
        status = sm.update(
          obs(i * kFrameMs, hand: shapeHand(i.isOdd ? 'FIST' : 'INDEX')),
        );
        if (status.finished) break;
      }
      expect(status!.failReason, isNot(FailReason.wrongShape));
    });

    test('나중 단계 동작을 먼저 하면 WRONG_ORDER', () {
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'MOVE_RIGHT', 'FIST']);
      final Status status = feedUntilTimeout(sm, 'FIST')!;
      expect(status.state, ChallengeState.failed);
      expect(status.failReason, FailReason.wrongOrder);
    });

    test('틀린 방향은 WRONG_DIRECTION', () {
      final ChallengeStateMachine sm =
          build(<String>['MOVE_RIGHT', 'OPEN_PALM', 'FIST']);
      final Status status = feedMoveUntilTimeout(sm, -3.0, 0.0)!;
      expect(status.state, ChallengeState.failed);
      expect(status.failReason, FailReason.wrongDirection);
    });

    test('알아볼 수 없는 동작만 하면 ACTION_TIMEOUT', () {
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'FIST', 'MOVE_RIGHT']);
      final Coords ambiguous = makeHand(angles: <String, double>{
        'thumb': 180.0,
        'index': 180.0,
        'middle': 180.0,
        'ring': 180.0,
        'pinky': sm.config.fingerExtendedAngle.others,
      });
      Status? status;
      double t = 0.0;
      while (t <= sm.config.timing.perActionTimeoutMs + kFrameMs) {
        status = sm.update(obs(t, hand: ambiguous));
        if (status.finished) break;
        t += kFrameMs;
      }
      expect(status!.state, ChallengeState.failed);
      expect(status.failReason, FailReason.actionTimeout);
    });

    test('전체 제한이 단계 제한보다 먼저 걸린다', () {
      final ChallengeStateMachine sm = build(
        <String>['OPEN_PALM', 'FIST', 'MOVE_RIGHT'],
        smConfig(<String, dynamic>{
          'timing': <String, dynamic>{
            'perActionTimeoutMs': 100000,
            'totalTimeoutMs': 500,
            'maxRetries': 0,
          },
        }),
      );
      sm.update(obs(0.0, hand: shapeHand('OPEN_PALM')));
      final Status status = sm.update(obs(600.0, hand: shapeHand('OPEN_PALM')));
      expect(status.state, ChallengeState.failed);
      expect(status.failReason, FailReason.totalTimeout);
    });

    test('실패한 단계가 사유를 기록한다', () {
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'INDEX', 'MOVE_RIGHT']);
      final Status status = feedUntilTimeout(sm, 'FIST')!;
      expect(status.steps[0].failReason, FailReason.wrongShape);
      expect(status.steps[0].passed, isFalse);
    });

    test('사유 코드가 Python enum 값과 같다', () {
      expect(FailReason.wrongShape.code, 'WRONG_SHAPE');
      expect(FailReason.handNotFound.code, 'HAND_NOT_FOUND');
      expect(FailReason.trackingUnstable.code, 'TRACKING_UNSTABLE');
      expect(FailReason.values.length, 8);
    });
  });

  group('반대 방향 즉시 실패', () {
    test('반대 방향이 먼저 확정되면 제한 시간을 기다리지 않는다', () {
      final ChallengeStateMachine sm =
          build(<String>['MOVE_RIGHT', 'OPEN_PALM', 'FIST']); // maxRetries 0
      final (Status? status, double t) = stroke(sm, -3.0, 0.0, 0.0);
      expect(status!.state, ChallengeState.failed);
      expect(status.failReason, FailReason.wrongDirection);
      expect(t, lessThan(sm.config.timing.perActionTimeoutMs));
    });

    test('재시도가 남아 있으면 다시 기회를 준다', () {
      final ChallengeStateMachine sm = build(
        <String>['MOVE_RIGHT', 'OPEN_PALM', 'FIST'],
        smConfig(<String, dynamic>{
          'timing': <String, dynamic>{
            'perActionTimeoutMs': 2000,
            'totalTimeoutMs': 9000,
            'maxRetries': 1,
          },
        }),
      );
      final (_, double t) = stroke(sm, -3.0, 0.0, 0.0);
      expect(sm.state, isNot(ChallengeState.failed));
      expect(sm.steps[0].retriesUsed, 1);

      stroke(sm, 3.0, 0.0, t, origin: <double>[-3.0, 0.0]);
      expect(sm.steps[0].passed, isTrue);
    });

    test('요청 방향이 먼저 잡히면 되돌아오는 획은 상관없다', () {
      final ChallengeStateMachine sm =
          build(<String>['MOVE_RIGHT', 'OPEN_PALM', 'FIST']);
      stroke(sm, 3.0, 0.0, 0.0);
      expect(sm.steps[0].passed, isTrue);
    });

    test('수직 방향은 즉시 실패시키지 않는다', () {
      final ChallengeStateMachine sm =
          build(<String>['MOVE_RIGHT', 'OPEN_PALM', 'FIST']);
      final (_, double t) = stroke(sm, 0.0, -3.0, 0.0);
      expect(sm.state, isNot(ChallengeState.failed));
      stroke(sm, 3.0, 0.0, t, origin: <double>[0.0, -3.0]);
      expect(sm.steps[0].passed, isTrue);
    });
  });

  group('추적', () {
    test('손이 한 번도 안 잡히면 HAND_NOT_FOUND', () {
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'FIST', 'MOVE_RIGHT']);
      Status? status;
      for (int i = 0; i < sm.config.tracking.maxLostFrames + 2; i++) {
        status = sm.update(
          Observation(timestampMs: i * kFrameMs, handFound: false),
        );
      }
      expect(status!.state, ChallengeState.failed);
      expect(status.failReason, FailReason.handNotFound);
    });

    test('도중에 손이 사라지면 HAND_LOST', () {
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'FIST', 'MOVE_RIGHT']);
      feedShape(sm, 'OPEN_PALM', 2);
      Status? status;
      final double t = 3 * kFrameMs;
      for (int i = 0; i < sm.config.tracking.maxLostFrames + 2; i++) {
        status = sm.update(
          Observation(timestampMs: t + i * kFrameMs, handFound: false),
        );
      }
      expect(status!.state, ChallengeState.failed);
      expect(status.failReason, FailReason.handLost);
    });

    test('짧은 끊김은 견딘다', () {
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'FIST', 'MOVE_RIGHT']);
      feedShape(sm, 'OPEN_PALM', 2);
      final double t = 3 * kFrameMs;
      for (int i = 0; i < sm.config.tracking.maxLostFrames; i++) {
        final Status status = sm.update(
          Observation(timestampMs: t + i * kFrameMs, handFound: false),
        );
        expect(status.state, isNot(ChallengeState.failed));
      }
      expect(sm.state, isNot(ChallengeState.failed));
    });

    test('신뢰도가 낮으면 TRACKING_UNSTABLE', () {
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'FIST', 'MOVE_RIGHT']);
      final double low = sm.config.tracking.minDetectionScore - 0.1;
      Status? status;
      for (int i = 0; i < sm.config.tracking.maxLostFrames + 2; i++) {
        status = sm.update(
          obs(i * kFrameMs, hand: shapeHand('OPEN_PALM'), score: low),
        );
      }
      expect(status!.state, ChallengeState.failed);
      expect(status.failReason, FailReason.trackingUnstable);
    });

    test('신뢰도가 null이면 관문을 건너뛴다 (앱의 실제 상황)', () {
      // hand_landmarker 3.0.1은 검출 신뢰도를 주지 않는다. null을 0으로 취급하면
      // 모든 인증이 TRACKING_UNSTABLE로 죽는다.
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'FIST', 'MOVE_RIGHT']);
      for (int i = 0; i < sm.config.tracking.maxLostFrames + 2; i++) {
        sm.update(obs(i * kFrameMs, hand: shapeHand('OPEN_PALM'), score: null));
      }
      expect(sm.state, isNot(ChallengeState.failed));
      expect(sm.steps[0].passed, isTrue);
    });
  });

  group('재시도', () {
    ChallengeConfig retryConfig(int retries) =>
        smConfig(<String, dynamic>{
          'timing': <String, dynamic>{
            'perActionTimeoutMs': 2000,
            'totalTimeoutMs': 9000,
            'maxRetries': retries,
          },
        });

    test('재시도가 단계에 한 번 더 기회를 준다', () {
      final ChallengeConfig config = retryConfig(1);
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'INDEX', 'MOVE_RIGHT'], config);
      final Status status = feedUntilTimeout(sm, 'FIST', config)!;
      expect(status.state, isNot(ChallengeState.failed));
      expect(sm.steps[0].retriesUsed, 1);

      feedShape(sm, 'OPEN_PALM', config.shapeHoldFrames,
          timeoutFrames(config) * kFrameMs);
      expect(sm.steps[0].passed, isTrue);
    });

    test('재시도를 다 쓰면 실패한다', () {
      final ChallengeConfig config = retryConfig(1);
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'INDEX', 'MOVE_RIGHT'], config);
      final double span = timeoutFrames(config) * kFrameMs;
      feedUntilTimeout(sm, 'FIST', config);
      final Status status = feedUntilTimeout(sm, 'FIST', config, span)!;
      expect(status.state, ChallengeState.failed);
      expect(status.failReason, FailReason.wrongShape);
    });

    test('손 소실은 재시도 대상이 아니다', () {
      final ChallengeConfig config = retryConfig(5);
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'FIST', 'MOVE_RIGHT'], config);
      feedShape(sm, 'OPEN_PALM', 2);
      Status? status;
      final double t = 3 * kFrameMs;
      for (int i = 0; i < config.tracking.maxLostFrames + 2; i++) {
        status = sm.update(
          Observation(timestampMs: t + i * kFrameMs, handFound: false),
        );
      }
      expect(status!.failReason, FailReason.handLost);
    });
  });

  group('상태 전이', () {
    test('IDLE에서 시작해 ACTION으로 간다', () {
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'FIST', 'MOVE_RIGHT']);
      expect(sm.state, ChallengeState.idle);
      sm.update(obs(0.0, hand: shapeHand('OPEN_PALM')));
      expect(sm.state, ChallengeState.action);
    });

    test('끝난 뒤의 프레임은 무시한다', () {
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'INDEX', 'MOVE_RIGHT']);
      feedUntilTimeout(sm, 'FIST');
      final int before = sm.stepIndex;
      final Status status = sm.update(obs(999.0, hand: shapeHand('OPEN_PALM')));
      expect(status.state, ChallengeState.failed);
      expect(sm.stepIndex, before);
    });
  });

  group('시간 기준 판정 (실기기 fps)', () {
    // ⚠️ 프레임 수로 세면 14fps에서 같은 조건이 두 배 넘게 길어진다.
    // challenge_response는 20fps에서, 앱은 14fps에서 이 문제를 겪었다.
    test('14fps에서도 유지 시간이 30fps와 같다', () {
      const double slowFrameMs = 1000.0 / 14.0;
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'FIST', 'MOVE_RIGHT']);

      // 30fps 기준 5프레임 = 3.5 × 33.3ms ≈ 117ms
      final double requiredMs = sm.config.consecutiveMs(5);
      expect(requiredMs, closeTo(116.67, 0.1));

      double t = 0.0;
      int frames = 0;
      while (sm.stepIndex == 0) {
        sm.update(obs(t, hand: shapeHand('OPEN_PALM')));
        t += slowFrameMs;
        frames++;
        if (frames > 50) break;
      }
      // 14fps에서는 3프레임(약 143ms)이면 채워진다. 5프레임을 기다리지 않는다.
      expect(frames, lessThan(5));
      expect(sm.steps[0].passed, isTrue);
    });

    test('손 소실 판정도 시간 기준이다', () {
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'FIST', 'MOVE_RIGHT']);
      // maxLostFrames=5 → +1 해서 6프레임 연속 = 4.5 × 33.3ms = 150ms
      final double requiredMs = sm.config.consecutiveMs(6);
      expect(requiredMs, closeTo(150.0, 0.1));

      // 14fps로 넣으면 3프레임이면 시간이 찬다
      const double slowFrameMs = 1000.0 / 14.0;
      Status? status;
      for (int i = 0; i < 4; i++) {
        status = sm.update(
          Observation(timestampMs: i * slowFrameMs, handFound: false),
        );
      }
      expect(status!.failReason, FailReason.handNotFound);
    });
  });
}

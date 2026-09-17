/// 단계 결과(PASS/FAIL)를 보여주는 시간.
///
/// 동작을 맞게 해도 순식간에 다음으로 넘어가면 제대로 한 건지 인지가 안 된다.
///
///     동작 통과 → PASS 표시 → 다음 동작 준비 → 판정
///
/// **표시하는 동안에는 제한 시간이 흐르지 않는다.** 표시가 제한 시간을 먹으면
/// 보여주기만 하다가 타임아웃이 난다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:signid/challenge/challenge_config.dart';
import 'package:signid/challenge/challenge_state_machine.dart';

import 'state_machine_test.dart'
    show kFrameMs, build, feedShape, obs, shapeHand, smConfig;

ChallengeConfig holdConfig({
  double holdMs = 1500,
  double prepareMs = 1500,
  double perActionMs = 2000,
  double totalMs = 9000,
  int retries = 0,
}) =>
    smConfig(<String, dynamic>{
      'timing': <String, dynamic>{
        'perActionTimeoutMs': perActionMs,
        'totalTimeoutMs': totalMs,
        'maxRetries': retries,
        'waitHandReadyMs': 0,
        'stepPrepareMs': prepareMs,
        'stepResultHoldMs': holdMs,
      },
    });

const List<String> kActions = <String>['OPEN_PALM', 'FIST', 'MOVE_RIGHT'];

/// 1단계를 통과시키고 결과 표시에 들어간 상태를 만든다.
(ChallengeStateMachine, double) afterFirstStep([ChallengeConfig? config]) {
  final ChallengeStateMachine sm = build(kActions, config ?? holdConfig());
  feedShape(sm, 'OPEN_PALM', sm.config.shapeHoldFrames);
  expect(sm.steps[0].passed, isTrue, reason: '1단계가 통과해야 시나리오가 성립한다');
  return (sm, sm.config.shapeHoldFrames * kFrameMs);
}

void main() {
  group('PASS 표시', () {
    test('통과하면 먼저 PASS를 보여준다', () {
      final (ChallengeStateMachine sm, double t) = afterFirstStep();
      final Status s = sm.update(obs(t, hand: shapeHand('FIST')));

      expect(s.stepResult, StepOutcome.pass);
      expect(s.stepResultReason, isNull);
      expect(s.stepResultRemainingMs, greaterThan(0));
      expect(s.justPassedStep, 0);
    });

    test('표시 중에는 준비 시간이 아직 시작되지 않는다', () {
      // 순서가 PASS → 준비다. 둘이 동시에 흐르면 표시가 안 보인다.
      final (ChallengeStateMachine sm, double t) = afterFirstStep();
      final Status s = sm.update(obs(t + 100, hand: shapeHand('FIST')));
      expect(s.preparing, isFalse);
    });

    test('표시가 끝나면 준비로 넘어간다', () {
      final (ChallengeStateMachine sm, double t) = afterFirstStep();
      Status? s;
      for (double u = t; u < t + 1700; u += kFrameMs) {
        s = sm.update(obs(u, hand: shapeHand('FIST')));
      }
      expect(s!.stepResult, isNull);
      expect(s.preparing, isTrue, reason: 'PASS 다음은 준비 시간이다');
    });

    test('표시 중에는 판정하지 않는다', () {
      // 2단계가 FIST인데 표시 중에 FIST를 유지해도 통과하면 안 된다.
      final (ChallengeStateMachine sm, double t) = afterFirstStep();
      for (double u = t; u < t + 1400; u += kFrameMs) {
        sm.update(obs(u, hand: shapeHand('FIST')));
      }
      expect(sm.stepIndex, 1);
    });

    test('남은 표시 시간이 줄어든다', () {
      final (ChallengeStateMachine sm, double t) = afterFirstStep();
      final Status a = sm.update(obs(t + 100, hand: shapeHand('FIST')));
      final Status b = sm.update(obs(t + 900, hand: shapeHand('FIST')));
      expect(b.stepResultRemainingMs, lessThan(a.stepResultRemainingMs));
    });
  });

  group('FAIL 표시 (재시도)', () {
    test('재시도되는 실패는 FAIL을 보여준다', () {
      final ChallengeConfig config = holdConfig(retries: 1);
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'INDEX', 'MOVE_RIGHT'], config);

      // 틀린 모양으로 제한 시간을 넘긴다.
      Status? s;
      double t = 0.0;
      for (int i = 0; i < 200 && (s?.stepResult == null); i++) {
        s = sm.update(obs(t, hand: shapeHand('FIST')));
        t += kFrameMs;
      }
      expect(s!.stepResult, StepOutcome.fail);
      expect(s.stepResultReason, isNotNull);
      expect(sm.state, isNot(ChallengeState.failed), reason: '재시도가 남아 있다');
      expect(sm.steps[0].retriesUsed, 1);
    });

    test('FAIL 표시가 끝나면 같은 단계를 다시 준비한다', () {
      final ChallengeConfig config = holdConfig(retries: 1);
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'INDEX', 'MOVE_RIGHT'], config);

      double t = 0.0;
      Status? s;
      for (int i = 0; i < 200 && (s?.stepResult == null); i++) {
        s = sm.update(obs(t, hand: shapeHand('FIST')));
        t += kFrameMs;
      }
      // 표시가 끝날 때까지
      for (double u = t; u < t + 1700; u += kFrameMs) {
        s = sm.update(obs(u, hand: shapeHand('FIST')));
      }
      expect(s!.stepResult, isNull);
      expect(sm.stepIndex, 0, reason: '같은 단계를 다시 한다');
    });

    test('재시도가 없으면 바로 실패로 끝난다', () {
      // 표시 단계가 세션을 붙잡고 있으면 안 된다. 끝난 화면이 FAIL을 보여준다.
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM', 'INDEX', 'MOVE_RIGHT'], holdConfig());
      Status? s;
      double t = 0.0;
      for (int i = 0; i < 200 && !(s?.finished ?? false); i++) {
        s = sm.update(obs(t, hand: shapeHand('FIST')));
        t += kFrameMs;
      }
      expect(s!.state, ChallengeState.failed);
      expect(s.failReason, FailReason.wrongShape);
    });
  });

  group('표시 중에는 시계가 멈춘다', () {
    test('PASS 1.5초 + 준비 1.5초가 단계 제한(2초)을 먹지 않는다', () {
      final (ChallengeStateMachine sm, double t) = afterFirstStep();
      double u = t;
      for (int i = 0; i < 300 && !sm.steps[1].passed; i++) {
        sm.update(obs(u, hand: shapeHand('FIST')));
        u += kFrameMs;
        if (sm.state == ChallengeState.failed) break;
      }
      expect(sm.state, isNot(ChallengeState.failed),
          reason: '사유=${sm.failReason}');
      expect(sm.steps[1].passed, isTrue);
    });

    test('전체 제한도 먹지 않는다', () {
      final ChallengeConfig config = holdConfig(totalMs: 4000);
      final (ChallengeStateMachine sm, double t) = afterFirstStep(config);
      double u = t;
      for (int i = 0; i < 400 && !sm.steps[1].passed; i++) {
        sm.update(obs(u, hand: shapeHand('FIST')));
        u += kFrameMs;
        if (sm.state == ChallengeState.failed) break;
      }
      expect(sm.failReason, isNot(FailReason.totalTimeout));
      expect(sm.steps[1].passed, isTrue);
    });
  });

  group('마지막 단계', () {
    test('PASS를 보여준 뒤에 끝난다', () {
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM'], holdConfig());
      final Status? s = feedShape(sm, 'OPEN_PALM', sm.config.shapeHoldFrames);

      // 표시 중에는 아직 끝나지 않는다. 화면이 PASS를 보여줄 시간이 필요하다.
      expect(s!.stepResult, StepOutcome.pass);
      expect(s.state, ChallengeState.action);
      expect(s.finished, isFalse);
    });

    test('표시가 끝나면 통과로 끝난다', () {
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM'], holdConfig());
      double t = 0.0;
      Status? s;
      for (int i = 0; i < 200 && !(s?.finished ?? false); i++) {
        s = sm.update(obs(t, hand: shapeHand('OPEN_PALM')));
        t += kFrameMs;
      }
      expect(s!.state, ChallengeState.passed);
      // 마지막 단계에는 준비 시간이 붙지 않는다.
      expect(s.preparing, isFalse);
    });
  });

  group('설정', () {
    test('0이면 바로 넘어간다 (옛 동작)', () {
      final (ChallengeStateMachine sm, double t) =
          afterFirstStep(holdConfig(holdMs: 0, prepareMs: 0));
      final Status s = sm.update(obs(t, hand: shapeHand('FIST')));
      expect(s.stepResult, isNull);
      expect(s.preparing, isFalse);
    });

    test('서버가 길이를 정한다', () {
      final (ChallengeStateMachine sm, double t) =
          afterFirstStep(holdConfig(holdMs: 3000));
      Status? s;
      for (double u = t; u < t + 2500; u += kFrameMs) {
        s = sm.update(obs(u, hand: shapeHand('FIST')));
      }
      expect(s!.stepResult, StepOutcome.pass, reason: '3000ms가 필요하다');
    });
  });
}

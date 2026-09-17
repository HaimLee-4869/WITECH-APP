/// 단계가 넘어간 뒤 다음 판정까지 주는 준비 시간.
///
/// 실기기에서 각 단계가 순식간에 지나가 무엇을 했는지 인지가 안 됐다.
/// 요청 동작 그림을 보고 손을 만들 시간을 준다.
///
/// **이 동안에는 제한 시간이 흐르지 않는다.** 준비 시간이 `perActionTimeoutMs`를
/// 먹으면 준비만 하다가 타임아웃이 난다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:signid/challenge/challenge_config.dart';
import 'package:signid/challenge/challenge_state_machine.dart';

import 'state_machine_test.dart'
    show kFrameMs, build, feedShape, obs, shapeHand, smConfig;

ChallengeConfig prepareConfig({
  double prepareMs = 1500,
  double perActionMs = 2000,
  double totalMs = 9000,
}) =>
    smConfig(<String, dynamic>{
      'timing': <String, dynamic>{
        'perActionTimeoutMs': perActionMs,
        'totalTimeoutMs': totalMs,
        'maxRetries': 0,
        'waitHandReadyMs': 0,
        'stepPrepareMs': prepareMs,
      },
    });

const List<String> kActions = <String>['OPEN_PALM', 'FIST', 'MOVE_RIGHT'];

/// 1단계를 통과시키고 준비 시간에 들어간 상태를 만든다.
(ChallengeStateMachine, double) afterFirstStep([ChallengeConfig? config]) {
  final ChallengeStateMachine sm = build(kActions, config ?? prepareConfig());
  feedShape(sm, 'OPEN_PALM', sm.config.shapeHoldFrames);
  expect(sm.steps[0].passed, isTrue, reason: '1단계가 통과해야 시나리오가 성립한다');
  return (sm, sm.config.shapeHoldFrames * kFrameMs);
}

void main() {
  group('준비 시간', () {
    test('단계를 통과하면 준비 시간에 들어간다', () {
      final (ChallengeStateMachine sm, double t) = afterFirstStep();
      final Status s = sm.update(obs(t, hand: shapeHand('FIST')));

      expect(s.preparing, isTrue);
      expect(s.prepareRemainingMs, greaterThan(0));
      expect(s.justPassedStep, 0, reason: '방금 통과한 단계를 알려줘야 한다');
    });

    test('준비 시간 동안에는 판정하지 않는다', () {
      // 2단계가 FIST인데, 준비 시간 동안 FIST를 유지해도 통과하면 안 된다.
      final (ChallengeStateMachine sm, double t) = afterFirstStep();
      for (double u = t; u < t + 1400; u += kFrameMs) {
        sm.update(obs(u, hand: shapeHand('FIST')));
      }
      expect(sm.stepIndex, 1, reason: '준비 시간에 2단계가 넘어갔다');
    });

    test('준비 시간이 끝나면 판정이 시작된다', () {
      final (ChallengeStateMachine sm, double t) = afterFirstStep();
      double u = t;
      // 준비 시간 + 유지 시간만큼 FIST를 유지한다.
      for (int i = 0; i < 80 && sm.stepIndex == 1; i++) {
        sm.update(obs(u, hand: shapeHand('FIST')));
        u += kFrameMs;
      }
      expect(sm.steps[1].passed, isTrue);
      expect(u - t, greaterThan(1500), reason: '준비 시간을 건너뛰었다');
    });

    test('남은 준비 시간이 줄어든다', () {
      final (ChallengeStateMachine sm, double t) = afterFirstStep();
      final Status first = sm.update(obs(t + 100, hand: shapeHand('FIST')));
      final Status later = sm.update(obs(t + 900, hand: shapeHand('FIST')));
      expect(later.prepareRemainingMs, lessThan(first.prepareRemainingMs));
    });
  });

  group('준비 시간에는 시계가 멈춘다', () {
    test('단계 제한 시간을 소모하지 않는다', () {
      // perActionTimeoutMs=2000, stepPrepareMs=1500.
      // 준비가 제한을 먹으면 남은 500ms 안에 2단계를 끝내야 해서 거의 불가능하다.
      final (ChallengeStateMachine sm, double t) = afterFirstStep();
      double u = t;
      for (int i = 0; i < 200 && !sm.steps[1].passed; i++) {
        sm.update(obs(u, hand: shapeHand('FIST')));
        u += kFrameMs;
        if (sm.state == ChallengeState.failed) break;
      }
      expect(sm.state, isNot(ChallengeState.failed),
          reason: '사유=${sm.failReason}');
      expect(sm.steps[1].passed, isTrue);
    });

    test('전체 제한 시간도 함께 멈춘다', () {
      // 준비 시간이 단계마다 붙으면 전체 제한을 넘기기 쉽다.
      final ChallengeConfig config =
          prepareConfig(prepareMs: 1500, perActionMs: 2000, totalMs: 4000);
      final (ChallengeStateMachine sm, double t) = afterFirstStep(config);

      double u = t;
      for (int i = 0; i < 300 && !sm.steps[1].passed; i++) {
        sm.update(obs(u, hand: shapeHand('FIST')));
        u += kFrameMs;
        if (sm.state == ChallengeState.failed) break;
      }
      expect(sm.failReason, isNot(FailReason.totalTimeout));
      expect(sm.steps[1].passed, isTrue);
    });
  });

  group('설정', () {
    test('0이면 바로 다음 판정으로 간다 (옛 동작)', () {
      final (ChallengeStateMachine sm, double t) =
          afterFirstStep(prepareConfig(prepareMs: 0));
      final Status s = sm.update(obs(t, hand: shapeHand('FIST')));
      expect(s.preparing, isFalse);
    });

    test('서버가 길이를 정한다', () {
      final (ChallengeStateMachine sm, double t) =
          afterFirstStep(prepareConfig(prepareMs: 3000));
      // 2500ms 뒤에도 아직 준비 중이어야 한다.
      Status? s;
      for (double u = t; u < t + 2500; u += kFrameMs) {
        s = sm.update(obs(u, hand: shapeHand('FIST')));
      }
      expect(s!.preparing, isTrue);
    });

    test('마지막 단계를 통과하면 준비 시간이 없다', () {
      // 끝났는데 준비 시간이 붙으면 결과 화면이 늦어진다.
      final ChallengeStateMachine sm =
          build(<String>['OPEN_PALM'], prepareConfig());
      final Status? s = feedShape(sm, 'OPEN_PALM', sm.config.shapeHoldFrames);
      expect(s!.state, ChallengeState.passed);
      expect(s.preparing, isFalse);
    });
  });
}

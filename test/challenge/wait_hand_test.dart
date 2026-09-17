/// 손을 들기 전에는 아무 시계도 흐르지 않는다.
///
/// 2026-09-18 실기기 회귀: 화면이 뜨자마자 1단계 판정이 시작돼서, 손을 들기도 전에
/// 제한 시간이 지나가고 손 소실 관문까지 돌아 `HAND_NOT_FOUND`로 끝났다.
/// 인증 화면의 `handSearching`과 같은 대기 단계를 앞에 둔다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:signid/challenge/challenge_config.dart';
import 'package:signid/challenge/challenge_state_machine.dart';

import 'state_machine_test.dart' show kFrameMs, build, obs, shapeHand, smConfig;

/// 대기 시간을 실제 기본값(400ms)으로 둔 설정.
ChallengeConfig waitConfig({
  double readyMs = 400,
  double waitTimeoutMs = 15000,
  double perActionMs = 2000,
  double totalMs = 6000,
}) =>
    smConfig(<String, dynamic>{
      'timing': <String, dynamic>{
        'perActionTimeoutMs': perActionMs,
        'totalTimeoutMs': totalMs,
        'maxRetries': 1,
        'waitHandReadyMs': readyMs,
        'waitHandTimeoutMs': waitTimeoutMs,
      },
    });

const List<String> kActions = <String>['OPEN_PALM', 'FIST', 'MOVE_RIGHT'];

void main() {
  group('대기 단계', () {
    test('첫 프레임에 바로 시작하지 않는다', () {
      final ChallengeStateMachine sm = build(kActions, waitConfig());
      final Status s = sm.update(obs(0.0, hand: shapeHand('OPEN_PALM')));

      expect(s.state, ChallengeState.waitHand);
      expect(s.awaitingHand, isTrue);
      expect(sm.stepIndex, 0);
      expect(sm.steps[0].passed, isFalse);
    });

    test('400ms 연속 검출되면 1단계가 시작된다', () {
      final ChallengeStateMachine sm = build(kActions, waitConfig());
      double t = 0.0;
      while (sm.state != ChallengeState.action && t <= 1000) {
        sm.update(obs(t, hand: shapeHand('OPEN_PALM')));
        t += kFrameMs;
      }
      expect(sm.state, ChallengeState.action);
      expect(t, greaterThanOrEqualTo(400.0), reason: '400ms 전에 시작했다');
    });

    test('손이 끊기면 연속 카운트가 초기화된다', () {
      final ChallengeStateMachine sm = build(kActions, waitConfig());
      for (double t = 0; t < 300; t += kFrameMs) {
        sm.update(obs(t, hand: shapeHand('OPEN_PALM')));
      }
      sm.update(obs(320, found: false));
      // 다시 300ms. 합쳐서 600ms지만 연속이 아니므로 아직 시작하면 안 된다.
      for (double t = 350; t < 650; t += kFrameMs) {
        sm.update(obs(t, hand: shapeHand('OPEN_PALM')));
      }
      expect(sm.state, ChallengeState.waitHand);
    });

    test('진행도를 알려준다', () {
      final ChallengeStateMachine sm = build(kActions, waitConfig());
      sm.update(obs(0.0, hand: shapeHand('OPEN_PALM')));
      final Status s = sm.update(obs(200.0, hand: shapeHand('OPEN_PALM')));
      expect(s.handReadyProgress, closeTo(0.5, 0.01));
    });
  });

  group('대기 중에는 시계가 흐르지 않는다', () {
    test('손 소실 관문이 돌지 않는다 (HAND_NOT_FOUND 즉시 실패 금지)', () {
      // 고치기 전에는 maxLostFrames+1 = 약 1.25초 만에 끝났다.
      final ChallengeStateMachine sm = build(kActions, waitConfig());
      for (double t = 0; t < 5000; t += kFrameMs) {
        final Status s = sm.update(obs(t, found: false));
        expect(s.state, ChallengeState.waitHand, reason: 't=$t 에서 끝났다');
      }
    });

    test('전체 제한 시간이 흐르지 않는다', () {
      // totalTimeoutMs가 6000인데 10초를 기다려도 살아 있어야 한다.
      final ChallengeStateMachine sm = build(kActions, waitConfig());
      for (double t = 0; t < 10000; t += 100) {
        sm.update(obs(t, found: false));
      }
      expect(sm.state, ChallengeState.waitHand);

      // 손을 들면 전체 제한 시간이 그때부터 시작된다.
      double t = 10000;
      while (sm.state != ChallengeState.action) {
        sm.update(obs(t, hand: shapeHand('OPEN_PALM')));
        t += kFrameMs;
      }
      expect(sm.state, ChallengeState.action);
      final Status s =
          sm.update(obs(t + kFrameMs, hand: shapeHand('OPEN_PALM')));
      expect(s.failReason, isNot(FailReason.totalTimeout));
    });

    test('단계 제한 시간도 손을 든 뒤부터다', () {
      final ChallengeStateMachine sm = build(kActions, waitConfig());
      for (double t = 0; t < 5000; t += 100) {
        sm.update(obs(t, found: false));
      }
      double t = 5000;
      while (sm.state != ChallengeState.action) {
        sm.update(obs(t, hand: shapeHand('OPEN_PALM')));
        t += kFrameMs;
      }
      for (int i = 0; i < 20 && sm.stepIndex == 0; i++) {
        sm.update(obs(t, hand: shapeHand('OPEN_PALM')));
        t += kFrameMs;
      }
      expect(sm.steps[0].passed, isTrue);
    });

    test('재시도가 차감되지 않는다', () {
      final ChallengeStateMachine sm = build(kActions, waitConfig());
      for (double t = 0; t < 8000; t += 100) {
        sm.update(obs(t, found: false));
      }
      expect(sm.steps.every((StepResult s) => s.retriesUsed == 0), isTrue);
    });
  });

  group('안전장치', () {
    test('아예 손을 안 들면 대기 제한으로 끝난다', () {
      final ChallengeStateMachine sm =
          build(kActions, waitConfig(waitTimeoutMs: 3000));
      Status? s;
      for (double t = 0; t < 4000; t += 100) {
        s = sm.update(obs(t, found: false));
        if (s.finished) break;
      }
      expect(s!.state, ChallengeState.failed);
      expect(s.failReason, FailReason.handNotFound);
    });

    test('대기 제한은 판정 제한보다 훨씬 길다', () {
      // 손을 드는 데 걸리는 시간을 판정 제한으로 재면 안 된다.
      final ChallengeConfig c = waitConfig();
      expect(c.timing.waitHandTimeoutMs, greaterThan(c.timing.totalTimeoutMs));
    });
  });

  group('설정', () {
    test('서버가 대기 시간을 정한다', () {
      final ChallengeStateMachine sm =
          build(kActions, waitConfig(readyMs: 1000));
      for (double t = 0; t < 900; t += kFrameMs) {
        sm.update(obs(t, hand: shapeHand('OPEN_PALM')));
      }
      expect(sm.state, ChallengeState.waitHand, reason: '1000ms가 필요하다');
    });

    test('0이면 첫 프레임에 바로 시작한다', () {
      final ChallengeStateMachine sm = build(kActions, waitConfig(readyMs: 0));
      sm.update(obs(0.0, hand: shapeHand('OPEN_PALM')));
      expect(sm.state, ChallengeState.action);
    });
  });
}

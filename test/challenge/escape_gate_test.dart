/// `challenge_response/tests/test_escape_gate.py`의 이식.
///
/// MOVE_*는 손바닥을 편 채로 수행한다. 이동이 끝난 시점의 손은 이미 OPEN_PALM이라,
/// 다음 단계가 OPEN_PALM이면 사용자가 아무것도 안 해도 통과된다. 공격자도 손바닥
/// 편 영상 하나로 그 단계를 넘길 수 있으므로 UX가 아니라 **보안 문제**다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:signid/challenge/challenge_config.dart';
import 'package:signid/challenge/challenge_state_machine.dart';

import 'state_machine_test.dart' show kFps, kFrameMs, build, shapeHand, smConfig;
import 'synth.dart';

const int kEscape = 4;

ChallengeConfig escapeConfig([Map<String, dynamic> overrides = const {}]) =>
    smConfig(<String, dynamic>{
      'escapeFrames': kEscape,
      'timing': <String, dynamic>{
        'perActionTimeoutMs': 2000,
        'totalTimeoutMs': 20000,
        'maxRetries': 0,
      },
      ...overrides,
    });

/// 프레임을 흘려보내며 시각을 관리한다.
class Clock {
  final ChallengeStateMachine machine;
  double t = 0.0;

  Clock(this.machine);

  Status? shape(String label, int frames) {
    Status? status;
    for (int i = 0; i < frames; i++) {
      final hand = shapeHand(label);
      status = machine.update(Observation(
        timestampMs: t,
        handFound: true,
        detectionScore: 1.0,
        angleCoords: hand,
        screenCoords: hand,
      ));
      t += kFrameMs;
      if (status.finished) break;
    }
    return status;
  }

  Status? move(double dx, double dy, int frames) {
    Status? status;
    for (int i = 0; i < frames; i++) {
      final hand = makeHand(
        uniformAngle: 180.0,
        center: <double>[dx * i * 0.4, dy * i * 0.4, 0.0],
      );
      status = machine.update(Observation(
        timestampMs: t,
        handFound: true,
        detectionScore: 1.0,
        angleCoords: hand,
        screenCoords: hand,
      ));
      t += kFrameMs;
      if (status.finished) break;
    }
    return status;
  }
}

/// 이동을 먼저 통과시킨 뒤의 상태를 만든다.
(ChallengeStateMachine, Clock) moveThenShape({
  List<String> actions = const <String>['MOVE_RIGHT', 'OPEN_PALM', 'FIST'],
  ChallengeConfig? config,
}) {
  final ChallengeStateMachine machine = build(actions, config ?? escapeConfig());
  final Clock clock = Clock(machine);
  final int window = machine.movementDetector.windowFrames(kFps);
  clock.move(1.0, 0.0, window + 2);
  expect(machine.steps[0].passed, isTrue,
      reason: '이동 단계가 먼저 통과해야 시나리오가 성립한다');
  return (machine, clock);
}

void main() {
  group('핵심 — 공짜 통과 차단', () {
    test('이동 후 손을 그대로 두면 통과되지 않는다', () {
      final (ChallengeStateMachine machine, Clock clock) = moveThenShape();
      clock.shape('OPEN_PALM', machine.config.shapeHoldFrames * 3);
      expect(machine.steps[1].passed, isFalse);
      expect(machine.stepIndex, 1);
    });

    test('손을 한 번 바꿨다가 다시 하면 통과한다', () {
      final (ChallengeStateMachine machine, Clock clock) = moveThenShape();
      clock.shape('FIST', kEscape); // 이전 모양에서 벗어남
      clock.shape('OPEN_PALM', machine.config.shapeHoldFrames);
      expect(machine.steps[1].passed, isTrue);
    });

    test('이탈 길이를 다 채워야 관문이 열린다', () {
      final (ChallengeStateMachine machine, Clock clock) = moveThenShape();
      clock.shape('FIST', kEscape - 1); // 한 프레임 모자람
      clock.shape('OPEN_PALM', machine.config.shapeHoldFrames * 2);
      expect(machine.steps[1].passed, isFalse);
    });

    test('잠깐 벗어났다 되돌아오면 처음부터 다시 센다', () {
      final (ChallengeStateMachine machine, Clock clock) = moveThenShape();
      for (int i = 0; i < 3; i++) {
        clock.shape('FIST', kEscape - 1);
        clock.shape('OPEN_PALM', 1); // 되돌아옴 → 연속 카운트 초기화
      }
      clock.shape('OPEN_PALM', machine.config.shapeHoldFrames * 2);
      expect(machine.steps[1].passed, isFalse);
    });
  });

  group('관문 대기 중에는 시계가 멈춘다', () {
    test('단계 제한 시간을 소모하지 않는다', () {
      final (ChallengeStateMachine machine, Clock clock) = moveThenShape();
      final int longWait =
          (machine.config.timing.perActionTimeoutMs / kFrameMs).toInt() * 3;
      final Status status = clock.shape('OPEN_PALM', longWait)!;
      expect(status.state, isNot(ChallengeState.failed));

      clock.shape('FIST', kEscape);
      clock.shape('OPEN_PALM', machine.config.shapeHoldFrames);
      expect(machine.steps[1].passed, isTrue);
    });

    test('전체 제한 시간도 함께 멈춘다', () {
      // 단계 제한만 멈추고 전체 제한을 흐르게 두면 마지막 단계에서 TOTAL_TIMEOUT으로
      // 죽는다. 실기기에서 TWO_FINGERS → MOVE_UP → OPEN_PALM 조합으로 실제 발생했다.
      final ChallengeConfig config = escapeConfig(<String, dynamic>{
        'timing': <String, dynamic>{
          'perActionTimeoutMs': 2000,
          'totalTimeoutMs': 4000,
          'maxRetries': 0,
        },
      });
      final ChallengeStateMachine machine =
          build(<String>['MOVE_RIGHT', 'FIST', 'OPEN_PALM'], config);
      final Clock clock = Clock(machine);
      final int window = machine.movementDetector.windowFrames(kFps);
      clock.move(1.0, 0.0, window + 2);
      clock.shape('FIST', kEscape + config.shapeHoldFrames);
      expect(machine.steps[1].passed, isTrue);

      // 마지막 단계 관문 앞에서 전체 제한을 훌쩍 넘는 시간 머문다
      final Status status = clock.shape(
        'FIST',
        (config.timing.totalTimeoutMs / kFrameMs).toInt() * 2,
      )!;
      expect(status.state, isNot(ChallengeState.failed),
          reason: '관문 대기 중 전체 제한 시간이 흘렀다');

      clock.shape('INDEX', kEscape);
      clock.shape('OPEN_PALM', config.shapeHoldFrames);
      expect(machine.steps[2].passed, isTrue);
    });
  });

  group('관문 적용 범위', () {
    test('이동 단계에는 걸지 않는다', () {
      // 이동은 단계 전환 때 윈도우를 비우므로 정지한 손으로 통과할 수 없다.
      // 관문을 걸면 편 손으로 하는 이동을 하려고 주먹을 쥐었다 펴야 한다.
      final ChallengeStateMachine machine =
          build(<String>['OPEN_PALM', 'MOVE_RIGHT', 'FIST'], escapeConfig());
      final Clock clock = Clock(machine);
      clock.shape('OPEN_PALM', machine.config.shapeHoldFrames);
      expect(machine.steps[0].passed, isTrue);

      final int window = machine.movementDetector.windowFrames(kFps);
      clock.move(1.0, 0.0, window + 2);
      expect(machine.steps[1].passed, isTrue);
    });

    test('1단계에는 관문이 없다 (README 5.7의 의도된 한계)', () {
      final ChallengeStateMachine machine =
          build(<String>['OPEN_PALM', 'FIST', 'MOVE_RIGHT'], escapeConfig());
      final Clock clock = Clock(machine);
      clock.shape('OPEN_PALM', machine.config.shapeHoldFrames);
      expect(machine.steps[0].passed, isTrue);
    });

    test('모양→모양 전환은 부담이 되지 않는다', () {
      final ChallengeStateMachine machine =
          build(<String>['OPEN_PALM', 'FIST', 'MOVE_RIGHT'], escapeConfig());
      final Clock clock = Clock(machine);
      clock.shape('OPEN_PALM', machine.config.shapeHoldFrames);
      clock.shape('FIST', kEscape + machine.config.shapeHoldFrames);
      expect(machine.steps[1].passed, isTrue);
    });

    test('escapeFrames가 0이면 관문을 끈다', () {
      final (ChallengeStateMachine machine, Clock clock) = moveThenShape(
        config: escapeConfig(<String, dynamic>{'escapeFrames': 0}),
      );
      clock.shape('OPEN_PALM', machine.config.shapeHoldFrames);
      expect(machine.steps[1].passed, isTrue);
    });
  });

  group('화면에 알려주는 값', () {
    test('벗어나야 할 모양을 알려준다', () {
      final (_, Clock clock) = moveThenShape();
      final Status status = clock.shape('OPEN_PALM', 1)!;
      expect(status.awaitingEscape, isTrue);
      expect(status.escapeFrom, 'OPEN_PALM');
      expect(status.escapeProgress, greaterThanOrEqualTo(0.0));
      expect(status.escapeProgress, lessThan(1.0));
    });

    test('진행도가 올라가고 열리면 지워진다', () {
      final (_, Clock clock) = moveThenShape();
      final Status first = clock.shape('FIST', 1)!;
      final Status second = clock.shape('FIST', 1)!;
      expect(second.escapeProgress, greaterThan(first.escapeProgress));

      final Status done = clock.shape('FIST', kEscape)!;
      expect(done.awaitingEscape, isFalse);
      expect(done.escapeFrom, isNull);
    });
  });
}

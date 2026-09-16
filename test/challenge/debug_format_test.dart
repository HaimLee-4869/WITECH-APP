/// 로그 한 줄 형식을 고정한다.
///
/// PC에서 이 줄을 보고 임계값을 판단하게 되므로, 값이 틀리면 엉뚱한 결론을 낸다.
/// 화면 패널과 **같은 숫자**여야 한다는 것도 여기서 확인한다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:signid/challenge/challenge_config.dart';
import 'package:signid/challenge/challenge_debug_format.dart';
import 'package:signid/challenge/challenge_generator.dart';
import 'package:signid/challenge/challenge_state_machine.dart';
import 'package:signid/challenge/hand_action_detector.dart';
import 'package:signid/challenge/hand_sketch.dart';
import 'package:signid/challenge/movement_detector.dart';
import 'package:signid/widgets/challenge_move_debug.dart';

import 'config_fixture.dart';

final ChallengeConfig config = configWith();

/// `key=value`를 뽑는다. grep으로 하려는 일과 같다.
String? field(String line, String key) {
  final RegExp re = RegExp('(?:^| )$key=([^ ]*)');
  return re.firstMatch(line)?.group(1);
}

void main() {
  group('한 줄 형식', () {
    test('모든 줄이 CHALLENGE로 시작한다', () {
      final Challenge challenge = Challenge(
        challengeId: '3f2a1b4c-0000-4000-8000-000000000000',
        actions: const <String>['FIST', 'MOVE_LEFT', 'OPEN_PALM'],
        createdAt: DateTime.utc(2026),
        shapePool: config.shapePool,
        movePool: config.movePool,
      );
      expect(formatBeginLine(challenge, config), startsWith('CHALLENGE '));
      expect(
        formatStepLine(0, 3, StepResult('FIST')..passed = true),
        startsWith('CHALLENGE '),
      );
    });

    test('줄바꿈이 없다 (한 줄에 다 들어간다)', () {
      final String line = formatMoveLine(
        const MoveProbe(
          windowReady: true,
          spanMs: 560,
          spanNeededMs: 550,
          framesFilled: 8,
          displacementRatio: 0.15,
          axisRatio: 2.1,
          axis: 'x',
          sign: -1,
          label: kNoMove,
          reason: MoveReason.tooSmall,
        ),
        config,
        requested: 'MOVE_LEFT',
      );
      expect(line.contains('\n'), isFalse);
    });
  });

  group('이동 줄', () {
    final MoveProbe blocked = const MoveProbe(
      windowReady: true,
      spanMs: 560,
      spanNeededMs: 550,
      framesFilled: 8,
      displacementRatio: 0.15,
      axisRatio: 2.1,
      axis: 'x',
      sign: -1,
      label: kNoMove,
      reason: MoveReason.tooSmall,
    );

    test('요청한 예시 형식 그대로', () {
      final String line = formatMoveLine(
        blocked,
        config,
        requested: 'MOVE_LEFT',
        lostInjections: 3,
        observedFps: 14.2,
        frameGapMs: 71,
      );
      expect(field(line, 'req'), 'MOVE_LEFT');
      expect(field(line, 'win'), '560/550ms(8f)O');
      expect(field(line, 'disp'), '0.150/0.226(x0.66)X');
      expect(field(line, 'axisRatio'), '2.10/3.63(x0.58)X');
      expect(field(line, 'axis'), 'x-');
      expect(field(line, 'label'), 'NONE');
      expect(field(line, 'lost'), '3');
      expect(field(line, 'fps'), '14.2');
      expect(field(line, 'gap'), '71ms');
    });

    test('막은 관문을 따로 찍는다 (grep 대상)', () {
      expect(field(formatMoveLine(blocked, config, requested: 'MOVE_LEFT'),
          'blocked'), 'gate1_disp');

      final String diagonal = formatMoveLine(
        const MoveProbe(
          windowReady: true,
          displacementRatio: 0.9,
          axisRatio: 2.1,
          axis: 'x',
          sign: -1,
          label: kNoMove,
          reason: MoveReason.notAxisDominant,
        ),
        config,
      );
      expect(field(diagonal, 'blocked'), 'gate2_axis');

      final String waiting = formatMoveLine(
        const MoveProbe(spanMs: 120, spanNeededMs: 550, framesFilled: 3),
        config,
      );
      expect(field(waiting, 'blocked'), 'window');
      expect(field(waiting, 'win'), '120/550ms(3f).');
      expect(field(waiting, 'disp'), 'wait');
    });

    test('요청과 판정의 관계를 네 가지로 찍는다', () {
      MoveProbe probeWith(String label) => MoveProbe(
            windowReady: true,
            displacementRatio: 1.0,
            axisRatio: 9.0,
            axis: 'x',
            sign: 1,
            label: label,
            reason: MoveReason.ok,
          );
      String verdictOf(String label) => field(
            formatMoveLine(probeWith(label), config, requested: 'MOVE_LEFT'),
            'verdict',
          )!;

      expect(verdictOf('MOVE_LEFT'), 'match');
      expect(verdictOf('MOVE_RIGHT'), 'opposite');
      expect(verdictOf('MOVE_UP'), 'other_axis');
      expect(verdictOf(kNoMove), 'undetermined');
    });

    test('순수 축 이동(축비 무한대)도 읽을 수 있게 찍는다', () {
      final String line = formatMoveLine(
        const MoveProbe(
          windowReady: true,
          displacementRatio: 1.0,
          axisRatio: double.infinity,
          axis: 'y',
          sign: 1,
          label: 'MOVE_DOWN',
          reason: MoveReason.ok,
        ),
        config,
      );
      expect(field(line, 'axisRatio'), startsWith('inf/'));
      expect(field(line, 'axis'), 'y+');
    });

    test('화면 패널과 같은 숫자를 쓴다', () {
      // 두 곳이 다른 값을 보여주면 어느 쪽을 믿어야 할지 알 수 없다.
      final List<DebugRow> rows =
          moveDebugRows(blocked, config, requested: 'MOVE_LEFT');
      final String line = formatMoveLine(blocked, config, requested: 'MOVE_LEFT');

      // 패널 "0.15 / 0.226  ×0.66" ↔ 로그 "0.150/0.226(x0.66)X"
      expect(rows.firstWhere((DebugRow r) => r.label == '관문1 변위').value,
          contains('×0.66'));
      expect(field(line, 'disp'), contains('(x0.66)'));
      expect(rows.firstWhere((DebugRow r) => r.label == '관문2 축비').value,
          contains('×0.58'));
      expect(field(line, 'axisRatio'), contains('(x0.58)'));
    });
  });

  group('손 모양 줄', () {
    test('손가락별 각도와 펴짐 여부를 찍는다', () {
      final ShapeSketch sketch = sketchForShape('INDEX', config);
      final ShapeResult result =
          HandActionDetector(config).detect(sketch.landmarks);
      final Status status = Status(
        state: ChallengeState.action,
        stepIndex: 0,
        currentAction: 'FIST',
        detectedShape: result.label,
        detectedMove: kNoMove,
        shapeConfidence: result.confidence,
        holdProgress: 0.0,
        remainingMs: 1800,
        failReason: null,
        steps: <StepResult>[StepResult('FIST')],
        moveProbe: null,
        escapeFrom: null,
        escapeProgress: 1.0,
      );

      final String line = formatShapeLine(status, result, config,
          observedFps: 14.2, frameGapMs: 71);

      expect(field(line, 'req'), 'FIST');
      expect(field(line, 'det'), 'INDEX');
      // 요청과 검출이 다른 것이 한눈에 보여야 한다
      expect(field(line, 'req'), isNot(field(line, 'det')));

      final String angles = field(line, 'ang')!;
      expect(angles.split('/').length, 5);
      expect(angles, startsWith('t')); // thumb, index, middle, ring, pinky
      expect(angles, contains('i')); // 검지
      // 검지는 펴짐(+), 중지는 접힘(-)
      expect(RegExp(r'i[\d.]+\+').hasMatch(angles), isTrue, reason: angles);
      expect(RegExp(r'm[\d.]+-').hasMatch(angles), isTrue, reason: angles);

      expect(field(line, 'thr'), '148.9/135.9');
      expect(field(line, 'tipWrist'), endsWith('/0.909'));
      expect(field(line, 'hold'), '0%/7f');
      expect(field(line, 'conf'), endsWith('/off')); // shapeConfidenceMin이 null
    });

    test('이탈 관문 상태를 찍는다', () {
      final Status status = Status(
        state: ChallengeState.action,
        stepIndex: 1,
        currentAction: 'OPEN_PALM',
        detectedShape: 'OPEN_PALM',
        detectedMove: kNoMove,
        shapeConfidence: 1.0,
        holdProgress: 0.0,
        remainingMs: 2000,
        failReason: null,
        steps: <StepResult>[StepResult('MOVE_LEFT'), StepResult('OPEN_PALM')],
        moveProbe: null,
        escapeFrom: 'OPEN_PALM',
        escapeProgress: 0.43,
      );
      expect(field(formatShapeLine(status, null, config), 'escape'),
          'OPEN_PALM(43%)');
    });
  });

  group('단계와 결과', () {
    test('단계 전환', () {
      final StepResult step = StepResult('MOVE_LEFT')
        ..passed = true
        ..elapsedMs = 812.4
        ..retriesUsed = 1;
      final String line = formatStepLine(1, 3, step);
      expect(line, 'CHALLENGE step 2/3 action=MOVE_LEFT -> PASS '
          'elapsed=812ms retries=1');
    });

    test('통과 결과', () {
      final Status status = Status(
        state: ChallengeState.passed,
        stepIndex: 3,
        currentAction: null,
        detectedShape: kUnknownShape,
        detectedMove: kNoMove,
        shapeConfidence: 0,
        holdProgress: 0,
        remainingMs: 0,
        failReason: null,
        steps: <StepResult>[
          StepResult('FIST')..passed = true,
          StepResult('MOVE_LEFT')..passed = true,
          StepResult('OPEN_PALM')..passed = true,
        ],
        moveProbe: null,
        escapeFrom: null,
        escapeProgress: 1.0,
      );
      final String line =
          formatResultLine(status, elapsedMs: 2840, observedFps: 14.2);
      expect(line, startsWith('CHALLENGE result PASS'));
      expect(field(line, 'steps'), '3/3');
      expect(field(line, 'elapsed'), '2840ms');
    });

    test('실패 결과는 FailReason까지', () {
      final Status status = Status(
        state: ChallengeState.failed,
        stepIndex: 1,
        currentAction: 'MOVE_LEFT',
        detectedShape: kUnknownShape,
        detectedMove: kNoMove,
        shapeConfidence: 0,
        holdProgress: 0,
        remainingMs: 0,
        failReason: FailReason.wrongDirection,
        steps: <StepResult>[
          StepResult('FIST')..passed = true,
          StepResult('MOVE_LEFT')..failReason = FailReason.wrongDirection,
          StepResult('OPEN_PALM'),
        ],
        moveProbe: null,
        escapeFrom: null,
        escapeProgress: 1.0,
      );
      final String line = formatResultLine(status,
          elapsedMs: 4102, lostInjections: 7, observedFps: 13.9);
      expect(line, startsWith('CHALLENGE result FAIL'));
      expect(field(line, 'reason'), 'WRONG_DIRECTION');
      expect(field(line, 'step'), '2/3');
      expect(field(line, 'action'), 'MOVE_LEFT');
      expect(field(line, 'steps'), '1/3');
      expect(field(line, 'lost'), '7');
    });
  });
}

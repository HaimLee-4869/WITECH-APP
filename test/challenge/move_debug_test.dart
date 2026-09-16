/// 이동 진단 패널이 막고 있는 관문을 정확히 가리키는지.
///
/// 이 표시를 보고 임계값을 조정하게 되므로, 값이 틀리면 엉뚱한 값을 만지게 된다.
/// `challenge_response/scripts/run_challenge.py`의 `draw_move_debug()`와 같은 형식이다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:signid/challenge/challenge_config.dart';
import 'package:signid/challenge/challenge_state_machine.dart';
import 'package:signid/challenge/movement_detector.dart';
import 'package:signid/widgets/challenge_move_debug.dart';

import 'config_fixture.dart';

/// 서버 기본 설정: minDisplacementRatio 0.226, axisDominanceRatio 3.634
final ChallengeConfig config = configWith();

String valueOf(List<DebugRow> rows, String label) =>
    rows.firstWhere((DebugRow r) => r.label == label).value;

bool? okOf(List<DebugRow> rows, String label) =>
    rows.firstWhere((DebugRow r) => r.label == label).ok;

void main() {
  group('윈도우가 차기 전', () {
    final MoveProbe probe = const MoveProbe(
      framesFilled: 5,
      framesNeeded: 18,
      spanMs: 120.0,
      spanNeededMs: 550.0,
      windowReady: false,
    );
    final List<DebugRow> rows =
        moveDebugRows(probe, config, requested: 'MOVE_LEFT');

    test('담긴 시간과 프레임 수를 보여준다', () {
      expect(valueOf(rows, '윈도우'), '120/550ms (5f)');
    });

    test('아직 안 찬 것은 실패가 아니다 (X를 붙이지 않는다)', () {
      expect(okOf(rows, '윈도우'), isNull);
    });

    test('관문은 대기로 표시한다', () {
      expect(valueOf(rows, '관문1 변위'), '대기');
      expect(valueOf(rows, '관문2 축비'), '대기');
    });

    test('확정 안 된 이유가 윈도우임을 알려준다', () {
      expect(valueOf(rows, '요청/판정'), contains('윈도우 채우는 중'));
    });
  });

  group('관문1 변위에서 막힐 때', () {
    // 실기기에서 "화살표대로 움직였는데 인식을 못 한다"의 가장 흔한 원인이다.
    final MoveProbe probe = const MoveProbe(
      framesFilled: 18,
      framesNeeded: 18,
      spanMs: 560.0,
      spanNeededMs: 550.0,
      windowReady: true,
      displacementRatio: 0.15,
      axisRatio: 8.0,
      axis: 'x',
      sign: -1,
      label: kNoMove,
      reason: MoveReason.tooSmall,
    );
    final List<DebugRow> rows =
        moveDebugRows(probe, config, requested: 'MOVE_LEFT');

    test('값 / 임계값 / 배수를 함께 보여준다', () {
      // 0.15 / 0.226 = ×0.66 — 임계값의 66%까지밖에 못 갔다
      expect(valueOf(rows, '관문1 변위'), '0.15 / 0.226  ×0.66');
    });

    test('관문1이 X다', () {
      expect(okOf(rows, '관문1 변위'), isFalse);
    });

    test('관문2는 통과하지 못한 것으로 본다 (거기까지 못 갔다)', () {
      expect(okOf(rows, '관문2 축비'), isFalse);
    });

    test('확정 안 됨 + 막은 관문을 말해준다', () {
      expect(valueOf(rows, '요청/판정'), 'MOVE_LEFT → 확정 안 됨 (관문1 변위 부족)');
    });
  });

  group('관문2 축비에서 막힐 때 (대각선)', () {
    final MoveProbe probe = const MoveProbe(
      framesFilled: 18,
      framesNeeded: 18,
      spanMs: 560.0,
      spanNeededMs: 550.0,
      windowReady: true,
      displacementRatio: 0.9,
      axisRatio: 2.1,
      axis: 'x',
      sign: -1,
      label: kNoMove,
      reason: MoveReason.notAxisDominant,
    );
    final List<DebugRow> rows =
        moveDebugRows(probe, config, requested: 'MOVE_LEFT');

    test('관문1은 통과, 관문2는 실패', () {
      expect(okOf(rows, '관문1 변위'), isTrue);
      expect(okOf(rows, '관문2 축비'), isFalse);
      expect(valueOf(rows, '관문2 축비'), '2.10 / 3.63  ×0.58');
    });

    test('대각선이라고 알려준다', () {
      expect(valueOf(rows, '요청/판정'), contains('대각선'));
    });
  });

  group('주축과 부호', () {
    test('음의 부호는 −로 보여준다', () {
      final List<DebugRow> rows = moveDebugRows(
        const MoveProbe(
          windowReady: true,
          displacementRatio: 1.0,
          axisRatio: 9.0,
          axis: 'x',
          sign: -1,
          label: 'MOVE_RIGHT',
          reason: MoveReason.ok,
        ),
        config,
      );
      expect(valueOf(rows, '주축'), 'x−  →  MOVE_RIGHT');
    });

    test('순수 축 이동은 축비가 ∞다', () {
      final List<DebugRow> rows = moveDebugRows(
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
      expect(valueOf(rows, '관문2 축비'), '∞ (순수 축)');
      expect(valueOf(rows, '주축'), 'y+  →  MOVE_DOWN');
    });
  });

  group('요청 방향과 판정 결과', () {
    MoveProbe probeWith(String label) => MoveProbe(
          windowReady: true,
          displacementRatio: 1.0,
          axisRatio: 9.0,
          axis: 'x',
          sign: 1,
          label: label,
          reason: MoveReason.ok,
        );

    test('일치', () {
      final List<DebugRow> rows =
          moveDebugRows(probeWith('MOVE_LEFT'), config, requested: 'MOVE_LEFT');
      expect(valueOf(rows, '요청/판정'), 'MOVE_LEFT → 일치');
      expect(okOf(rows, '요청/판정'), isTrue);
    });

    test('반대 방향 — 확정은 됐는데 뒤집혔다', () {
      // 좌표계가 잘못됐을 때 이렇게 나온다. 확정 안 됨과 구분해야 한다.
      final List<DebugRow> rows =
          moveDebugRows(probeWith('MOVE_RIGHT'), config, requested: 'MOVE_LEFT');
      expect(valueOf(rows, '요청/판정'), 'MOVE_LEFT → 반대 방향');
      expect(okOf(rows, '요청/판정'), isFalse);
    });

    test('다른 축', () {
      final List<DebugRow> rows =
          moveDebugRows(probeWith('MOVE_UP'), config, requested: 'MOVE_LEFT');
      expect(valueOf(rows, '요청/판정'), 'MOVE_LEFT → 다른 축');
    });

    test('확정 안 됨', () {
      final List<DebugRow> rows = moveDebugRows(
        const MoveProbe(
          windowReady: true,
          displacementRatio: 0.1,
          axisRatio: 9.0,
          axis: 'x',
          sign: 1,
          label: kNoMove,
          reason: MoveReason.tooSmall,
        ),
        config,
        requested: 'MOVE_LEFT',
      );
      expect(valueOf(rows, '요청/판정'), contains('확정 안 됨'));
    });

    test('verdict가 네 경우를 구분한다', () {
      expect(moveVerdictOf('MOVE_LEFT', 'MOVE_LEFT'), MoveVerdict.matched);
      expect(moveVerdictOf('MOVE_LEFT', 'MOVE_RIGHT'), MoveVerdict.opposite);
      expect(moveVerdictOf('MOVE_LEFT', 'MOVE_UP'), MoveVerdict.otherAxis);
      expect(moveVerdictOf('MOVE_LEFT', kNoMove), MoveVerdict.undetermined);
      expect(moveVerdictOf('MOVE_UP', 'MOVE_DOWN'), MoveVerdict.opposite);
    });
  });

  test('임계값은 설정에서 읽는다 (패널에 하드코딩 없음)', () {
    final ChallengeConfig other = configWith(<String, dynamic>{
      'movement': <String, dynamic>{
        'minDisplacementRatio': 0.5,
        'axisDominanceRatio': 2.0,
      },
    });
    final List<DebugRow> rows = moveDebugRows(
      const MoveProbe(
        windowReady: true,
        displacementRatio: 0.25,
        axisRatio: 1.0,
        axis: 'x',
        sign: 1,
        label: kNoMove,
        reason: MoveReason.tooSmall,
      ),
      other,
    );
    expect(valueOf(rows, '관문1 변위'), '0.25 / 0.500  ×0.50');
    expect(valueOf(rows, '관문2 축비'), '1.00 / 2.00  ×0.50');
  });
}

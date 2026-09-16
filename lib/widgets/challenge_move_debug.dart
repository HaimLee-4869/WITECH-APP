/// 이동 판정 진단 패널.
///
/// `challenge_response/scripts/run_challenge.py`의 `draw_move_debug()`와 같은
/// 형식이다. **임계값을 짐작해서 바꾸기 전에, 무엇이 막고 있는지부터 눈으로 본다.**
///
/// 임계값은 파일럿 영상(폰 거치, 30fps)에서 도출했다. 손에 들고 화면을 보면서
/// 하는 실사용 조건과 다를 수 있으므로, 실기기에서 실제로 어떤 값이 나오는지
/// 보고 나서 조정해야 한다.
library;

import 'package:flutter/material.dart';

import '../challenge/challenge_config.dart';
import '../challenge/challenge_state_machine.dart';
import '../challenge/movement_detector.dart';
import '../core/theme.dart';

/// 패널 한 줄. [ok]가 null이면 관문이 아니라 정보 줄이다.
@immutable
class DebugRow {
  final String label;
  final String value;
  final bool? ok;

  const DebugRow(this.label, this.value, [this.ok]);
}

/// 요청 방향과 판정 결과의 관계. 반대로 잡힌 것과 확정이 안 된 것을 구분한다.
enum MoveVerdict {
  /// 요청한 방향으로 확정됐다.
  matched,

  /// 같은 축의 **반대 방향**으로 확정됐다. 즉시 실패 규칙에 걸린다.
  opposite,

  /// 다른 축으로 확정됐다.
  otherAxis,

  /// 아직 아무 방향도 확정되지 않았다. 관문에서 막힌 것이다.
  undetermined,
}

MoveVerdict moveVerdictOf(String? requested, String detected) {
  if (detected == kNoMove) return MoveVerdict.undetermined;
  if (requested == null) return MoveVerdict.undetermined;
  if (detected == requested) return MoveVerdict.matched;
  if (detected == kOppositeDirection[requested]) return MoveVerdict.opposite;
  return MoveVerdict.otherAxis;
}

String moveVerdictText(MoveVerdict verdict) => switch (verdict) {
      MoveVerdict.matched => '일치',
      MoveVerdict.opposite => '반대 방향',
      MoveVerdict.otherAxis => '다른 축',
      MoveVerdict.undetermined => '확정 안 됨',
    };

/// 관문에서 막힌 이유를 한 마디로. 확정이 안 됐을 때만 의미가 있다.
String moveBlockedBy(MoveProbe probe) {
  if (!probe.windowReady) return '윈도우 채우는 중';
  return switch (probe.reason) {
    MoveReason.noTrack => '손 추적 끊김',
    MoveReason.tooSmall => '관문1 변위 부족',
    MoveReason.notAxisDominant => '관문2 축비 부족 (대각선)',
    MoveReason.unmappedAxis => '표에 없는 축',
    MoveReason.ok => '통과',
    _ => probe.reason,
  };
}

/// 패널에 그릴 줄들을 만든다. 화면과 분리해 테스트로 형식을 고정한다.
List<DebugRow> moveDebugRows(
  MoveProbe probe,
  ChallengeConfig config, {
  String? requested,
}) {
  final double minDisp = config.movement.minDisplacementRatio;
  final double axisMin = config.movement.axisDominanceRatio;

  final List<DebugRow> rows = <DebugRow>[
    // 윈도우는 프레임 수가 아니라 시간으로 찬다(기준 fps 환산).
    // 아직 안 찬 것은 실패가 아니므로 X를 붙이지 않는다.
    DebugRow(
      '윈도우',
      '${probe.spanMs.toStringAsFixed(0)}/${probe.spanNeededMs.toStringAsFixed(0)}ms'
          ' (${probe.framesFilled}f)',
      probe.windowReady ? true : null,
    ),
  ];

  if (!probe.windowReady) {
    rows.add(const DebugRow('관문1 변위', '대기'));
    rows.add(const DebugRow('관문2 축비', '대기'));
    rows.add(const DebugRow('주축', '-'));
  } else {
    final double disp = probe.displacementRatio;
    rows.add(DebugRow(
      '관문1 변위',
      disp.isFinite
          ? '${disp.toStringAsFixed(2)} / ${minDisp.toStringAsFixed(3)}'
              '  ×${(disp / minDisp).toStringAsFixed(2)}'
          : '--',
      probe.displacementOk,
    ));

    final double axisRatio = probe.axisRatio;
    rows.add(DebugRow(
      '관문2 축비',
      axisRatio.isFinite
          ? '${axisRatio.toStringAsFixed(2)} / ${axisMin.toStringAsFixed(2)}'
              '  ×${(axisRatio / axisMin).toStringAsFixed(2)}'
          : '∞ (순수 축)',
      probe.axisOk,
    ));

    final String sign = switch (probe.sign) {
      > 0 => '+',
      < 0 => '−',
      _ => '?',
    };
    rows.add(DebugRow('주축', '${probe.axis}$sign  →  ${probe.label}'));
  }

  // 요청 방향과 판정 결과. 반대로 잡히는 건지 아예 확정이 안 되는 건지 구분한다.
  final MoveVerdict verdict = moveVerdictOf(requested, probe.label);
  final String detail = verdict == MoveVerdict.undetermined
      ? '${moveVerdictText(verdict)} (${moveBlockedBy(probe)})'
      : moveVerdictText(verdict);
  rows.add(DebugRow(
    '요청/판정',
    '${requested ?? '-'} → $detail',
    verdict == MoveVerdict.matched,
  ));

  return rows;
}

/// [moveDebugRows]를 그린다.
class ChallengeMoveDebug extends StatelessWidget {
  final MoveProbe probe;
  final ChallengeConfig config;
  final String? requested;

  /// 실측 fps. 임계값은 30fps 영상에서 도출됐으므로 같이 보여준다.
  final double? observedFps;

  /// 마지막 프레임 간격(ms)과 워치독이 '손 없음'을 넣은 횟수.
  ///
  /// 손 없음은 이동 윈도우를 비운다. 손이 보이는데도 이 수가 올라가면
  /// 윈도우가 찰 기회가 없다는 뜻이다.
  final int? lastFrameGapMs;
  final int? lostInjections;

  const ChallengeMoveDebug({
    super.key,
    required this.probe,
    required this.config,
    this.requested,
    this.observedFps,
    this.lastFrameGapMs,
    this.lostInjections,
  });

  @override
  Widget build(BuildContext context) {
    final List<DebugRow> rows =
        moveDebugRows(probe, config, requested: requested);

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: AppColors.surface.withValues(alpha: 0.85),
        border: Border.all(color: AppColors.divider),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          for (final DebugRow row in rows) _RowLine(row: row),
          if (observedFps != null && observedFps! > 0)
            _RowLine(
              row: DebugRow(
                'fps',
                '${observedFps!.toStringAsFixed(1)} '
                    '(임계값 도출 ${config.frameReferenceFps.toStringAsFixed(0)}fps)'
                    '${lastFrameGapMs == null ? '' : '  간격 ${lastFrameGapMs}ms'}',
              ),
            ),
          if (lostInjections != null && lostInjections! > 0)
            _RowLine(
              // 손이 보이는데도 올라가면 프레임이 늦어 윈도우가 비워지는 것이다.
              row: DebugRow('손없음', '$lostInjections회 주입 (윈도우 비움)', false),
            ),
        ],
      ),
    );
  }
}

class _RowLine extends StatelessWidget {
  final DebugRow row;

  const _RowLine({required this.row});

  @override
  Widget build(BuildContext context) {
    final Color color = switch (row.ok) {
      null => AppColors.textPrimary,
      true => AppColors.success,
      false => AppColors.danger,
    };
    final TextStyle mono = AppText.caption.copyWith(
      fontFamily: 'monospace',
      fontFeatures: const <FontFeature>[FontFeature.tabularFigures()],
    );

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 1),
      child: Row(
        children: <Widget>[
          SizedBox(
            width: 74,
            child: Text(
              row.label,
              style: mono.copyWith(color: AppColors.textSecondary),
            ),
          ),
          Expanded(
            child: Text(
              row.value,
              style: mono.copyWith(color: color),
              overflow: TextOverflow.ellipsis,
            ),
          ),
          SizedBox(
            width: 16,
            child: Text(
              row.ok == null ? '' : (row.ok! ? 'O' : 'X'),
              textAlign: TextAlign.right,
              style: mono.copyWith(color: color, fontWeight: FontWeight.w700),
            ),
          ),
        ],
      ),
    );
  }
}

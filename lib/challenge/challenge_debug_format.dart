/// Challenge 판정 로그의 한 줄 형식.
///
/// 실기기 화면의 진단 패널은 프레임마다 바뀌어 읽을 수 없다. 같은 내용을 PC에서
/// 보려고 서버로 보낸다(`POST /debug/challenge` → `backend/logs/challenge_debug.log`).
///
/// **한 줄에 다 넣고 `key=value`로 적는다.** 여러 줄이면 grep이 소용없다.
/// 전부 `CHALLENGE `로 시작한다.
///
/// 형식은 화면 패널과 같은 값을 쓴다. 두 곳이 다른 숫자를 보여주면 안 되므로
/// 테스트로 고정한다.
library;

import 'challenge_config.dart';
import 'challenge_generator.dart';
import 'challenge_state_machine.dart';
import 'geometry.dart';
import 'hand_action_detector.dart';
import 'movement_detector.dart';

const String kDebugPrefix = 'CHALLENGE';

String _n(double v, int digits) => v.isFinite ? v.toStringAsFixed(digits) : 'nan';

String _gate(double value, double threshold, bool ok, int digits) {
  if (!value.isFinite) return 'inf/${threshold.toStringAsFixed(digits)}(-)${ok ? 'O' : 'X'}';
  return '${value.toStringAsFixed(digits)}/${threshold.toStringAsFixed(digits)}'
      '(x${(value / threshold).toStringAsFixed(2)})${ok ? 'O' : 'X'}';
}

/// 세션 시작.
///
/// 예: `CHALLENGE begin id=3f2a actions=[FIST,MOVE_LEFT,OPEN_PALM] rule=2026-09-16.opposite-first-fails fpsRef=30.0`
String formatBeginLine(Challenge challenge, ChallengeConfig config) {
  return '$kDebugPrefix begin id=${challenge.challengeId.split('-').first}'
      ' actions=[${challenge.actions.join(',')}]'
      ' rule=${config.ruleVersion}'
      ' fpsRef=${_n(config.frameReferenceFps, 1)}'
      ' hold=${config.shapeHoldFrames}f escape=${config.escapeFrames}f'
      ' perAction=${_n(config.timing.perActionTimeoutMs, 0)}ms'
      ' total=${_n(config.timing.totalTimeoutMs, 0)}ms';
}

/// 이동 단계 한 프레임.
///
/// 예: `CHALLENGE move req=MOVE_LEFT win=560/550ms(8f) disp=0.15/0.226(x0.66)X
///      axisRatio=2.10/3.63(x0.58)X axis=x- label=NONE blocked=gate1_disp lost=3 fps=14.2`
///
/// 사용자가 준 예시와 달리 관문2를 `axisRatio=`로, 주축을 `axis=`로 나눴다.
/// 같은 키가 두 번 나오면 grep이 두 값을 구분하지 못한다.
String formatMoveLine(
  MoveProbe probe,
  ChallengeConfig config, {
  String? requested,
  int lostInjections = 0,
  double observedFps = 0.0,
  int frameGapMs = 0,
}) {
  final double minDisp = config.movement.minDisplacementRatio;
  final double axisMin = config.movement.axisDominanceRatio;

  final StringBuffer b = StringBuffer()
    ..write('$kDebugPrefix move req=${requested ?? '-'}')
    ..write(' win=${_n(probe.spanMs, 0)}/${_n(probe.spanNeededMs, 0)}ms'
        '(${probe.framesFilled}f)${probe.windowReady ? 'O' : '.'}');

  if (probe.windowReady) {
    b
      ..write(' disp=${_gate(probe.displacementRatio, minDisp, probe.displacementOk, 3)}')
      ..write(' axisRatio=${_gate(probe.axisRatio, axisMin, probe.axisOk, 2)}')
      ..write(' axis=${probe.axis}${_sign(probe.sign)}')
      ..write(' label=${probe.label}');
  } else {
    b.write(' disp=wait axisRatio=wait axis=- label=${probe.label}');
  }

  b
    ..write(' verdict=${_verdict(requested, probe.label)}')
    ..write(' blocked=${_blocked(probe)}')
    ..write(' lost=$lostInjections')
    ..write(' fps=${_n(observedFps, 1)} gap=${frameGapMs}ms');
  return b.toString();
}

/// 손 모양 단계 한 프레임.
///
/// 예: `CHALLENGE shape req=FIST det=UNKNOWN conf=0.00 hold=0%/7f
///      ang=t151.2/i172.4/m168.0/r63.1/p61.8 tipWrist=1.12 escape=FIST(43%) lost=0 fps=14.2`
String formatShapeLine(
  Status status,
  ShapeResult? result,
  ChallengeConfig config, {
  int lostInjections = 0,
  double observedFps = 0.0,
  int frameGapMs = 0,
}) {
  final StringBuffer b = StringBuffer()
    ..write('$kDebugPrefix shape req=${status.currentAction ?? '-'}')
    ..write(' det=${status.detectedShape}')
    ..write(' conf=${_n(status.shapeConfidence, 2)}')
    ..write('/${config.shapeConfidenceMin == null ? 'off' : _n(config.shapeConfidenceMin!, 2)}')
    ..write(' hold=${(status.holdProgress * 100).round()}%/${config.shapeHoldFrames}f');

  if (result != null) {
    final List<String> parts = <String>[];
    for (final (int i, String name) in kFingerNames.indexed) {
      parts.add('${name[0]}${_n(result.angles[i], 1)}'
          '${result.flags[i] ? '+' : '-'}');
    }
    b
      ..write(' ang=${parts.join('/')}')
      ..write(' thr=${_n(config.fingerExtendedAngle.thumb, 1)}'
          '/${_n(config.fingerExtendedAngle.others, 1)}')
      ..write(' tipWrist=${_n(result.tipWristRatio, 3)}'
          '/${config.fistMaxTipWristRatio == null ? 'off' : _n(config.fistMaxTipWristRatio!, 3)}');
  }

  b
    ..write(' escape=${status.escapeFrom == null ? '-' : '${status.escapeFrom}'
        '(${(status.escapeProgress * 100).round()}%)'}')
    ..write(' lost=$lostInjections')
    ..write(' fps=${_n(observedFps, 1)} gap=${frameGapMs}ms');
  return b.toString();
}

/// 단계 전환.
///
/// 예: `CHALLENGE step 2/3 action=MOVE_LEFT -> PASS elapsed=812ms retries=0`
String formatStepLine(int index, int total, StepResult step) {
  return '$kDebugPrefix step ${index + 1}/$total action=${step.action}'
      ' -> ${step.passed ? 'PASS' : 'FAIL'}'
      ' elapsed=${step.elapsedMs.round()}ms retries=${step.retriesUsed}';
}

/// 최종 결과.
///
/// 예: `CHALLENGE result FAIL reason=WRONG_DIRECTION step=2/3 action=MOVE_LEFT
///      steps=1/3 elapsed=4102ms lost=7 fps=14.2`
String formatResultLine(
  Status status, {
  required int elapsedMs,
  int lostInjections = 0,
  double observedFps = 0.0,
}) {
  final int passed = status.steps.where((StepResult s) => s.passed).length;
  final StringBuffer b = StringBuffer()
    ..write('$kDebugPrefix result ')
    ..write(status.state == ChallengeState.passed ? 'PASS' : 'FAIL');

  if (status.failReason != null) {
    b
      ..write(' reason=${status.failReason!.code}')
      ..write(' step=${status.stepIndex + 1}/${status.steps.length}')
      ..write(' action=${status.currentAction ?? '-'}');
  }

  b
    ..write(' steps=$passed/${status.steps.length}')
    ..write(' elapsed=${elapsedMs}ms')
    ..write(' lost=$lostInjections fps=${_n(observedFps, 1)}');
  return b.toString();
}

/// 시작하지 못한 경우.
String formatUnavailableLine(String notice) =>
    '$kDebugPrefix unavailable notice=${notice.replaceAll(' ', '_')}';

String _sign(int sign) => switch (sign) {
      > 0 => '+',
      < 0 => '-',
      _ => '?',
    };

/// 요청 방향과 판정 결과의 관계. 반대로 잡힌 것과 확정이 안 된 것을 구분한다.
String _verdict(String? requested, String detected) {
  if (detected == kNoMove) return 'undetermined';
  if (requested == null) return 'unknown';
  if (detected == requested) return 'match';
  if (detected == kOppositeDirection[requested]) return 'opposite';
  return 'other_axis';
}

String _blocked(MoveProbe probe) {
  if (!probe.windowReady) return 'window';
  return switch (probe.reason) {
    MoveReason.noTrack => 'no_track',
    MoveReason.tooSmall => 'gate1_disp',
    MoveReason.notAxisDominant => 'gate2_axis',
    MoveReason.unmappedAxis => 'unmapped_axis',
    MoveReason.ok => 'none',
    _ => probe.reason,
  };
}

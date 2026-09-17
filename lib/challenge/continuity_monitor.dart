/// 연속 세션에서 **손이 바뀌었는지** 본다.
///
/// Challenge와 제스처 인증을 한 번의 촬영으로 묶으면 "Challenge는 본인 손,
/// 인증은 피해자 영상"을 막을 수 있다. 손을 빼면 세션이 끊기기 때문이다.
/// 다만 **손을 빼지 않고 화면을 들이미는** 경우가 남는데, 그때는 손 크기와
/// 손목 위치가 한 프레임 사이에 튄다.
///
/// ⚠️ **검사는 기본으로 꺼져 있다.**
///
/// 정상 세션의 프레임 간 변화량을 아직 재지 않았다. 임계값을 추측해서 넣으면
/// 정상 사용자를 막거나(너무 좁게) 아무것도 막지 못한다(너무 넓게). 지금은
/// **재기만 한다** — 측정값이 디버그 로그에 쌓이면 그 분포에서 도출한다.
///
/// 이 프로젝트의 다른 임계값이 전부 실측 분포에서 나왔다는 원칙을 여기서도 지킨다.
library;

import 'dart:math' as math;

import 'challenge_config.dart';
import 'geometry.dart';

/// 프레임 하나에서 잰 값.
class ContinuitySample {
  /// 직전 프레임 대비 손 크기 배수. 1.0이면 그대로, 2.0이면 두 배로 커졌다.
  ///
  /// 커지든 작아지든 같은 크기로 보려고 항상 1.0 이상이 되게 뒤집는다.
  final double scaleJump;

  /// 직전 프레임 대비 손목 이동량 / 손 크기.
  ///
  /// 손 크기로 나누므로 카메라 거리에 무관하다.
  final double wristJump;

  /// 직전 프레임과의 간격. 점프는 시간이 길수록 커지므로 같이 본다.
  final double gapMs;

  const ContinuitySample({
    required this.scaleJump,
    required this.wristJump,
    required this.gapMs,
  });

  bool get isFinite => scaleJump.isFinite && wristJump.isFinite;
}

/// 세션 동안 프레임 간 점프를 재고, 설정이 켜져 있으면 판정한다.
class ContinuityMonitor {
  final ChallengeConfig config;

  List<double>? _lastWrist;
  double _lastScale = double.nan;
  double _lastTimestampMs = double.nan;

  /// 지금까지 본 최대값. 로그에 남겨 분포를 모은다.
  double maxScaleJump = 0.0;
  double maxWristJump = 0.0;

  /// 잰 프레임 수.
  int samples = 0;

  ContinuityMonitor(this.config);

  bool get enabled => config.continuity.enabled;

  /// 프레임 하나를 넣는다. 손이 없는 프레임은 넣지 않는다(끊김은 별도 규칙).
  ///
  /// [screenCoords]는 종횡비 보정이 끝난 좌표여야 한다.
  ContinuitySample? add(Coords screenCoords, double timestampMs) {
    final List<double> wrist = screenCoords[kWrist];
    final double scale = handScale(screenCoords);

    final List<double>? prevWrist = _lastWrist;
    final double prevScale = _lastScale;
    _lastWrist = <double>[wrist[0], wrist[1], wrist[2]];
    _lastScale = scale;
    final double prevT = _lastTimestampMs;
    _lastTimestampMs = timestampMs;

    // 첫 프레임은 비교 대상이 없다.
    if (prevWrist == null || !prevScale.isFinite || prevScale <= 0) return null;
    if (!scale.isFinite || scale <= 0) return null;

    final double scaleJump = math.max(scale / prevScale, prevScale / scale);
    final double dx = wrist[0] - prevWrist[0];
    final double dy = wrist[1] - prevWrist[1];
    // 손 크기로 나눈다. 카메라가 멀어 손이 작아도 같은 기준이 되게.
    final double wristJump = math.sqrt(dx * dx + dy * dy) / prevScale;

    final ContinuitySample sample = ContinuitySample(
      scaleJump: scaleJump,
      wristJump: wristJump,
      gapMs: prevT.isFinite ? timestampMs - prevT : double.nan,
    );
    if (!sample.isFinite) return sample;

    samples++;
    if (scaleJump > maxScaleJump) maxScaleJump = scaleJump;
    if (wristJump > maxWristJump) maxWristJump = wristJump;
    return sample;
  }

  /// 손이 끊긴 구간이 있었으면 비교 기준을 버린다.
  ///
  /// 끊김 전후 프레임을 비교하면 당연히 크게 튄다. 그건 연속성이 아니라
  /// 손 소실 규칙(SESSION_BROKEN)이 볼 일이다.
  void resetReference() {
    _lastWrist = null;
    _lastScale = double.nan;
    _lastTimestampMs = double.nan;
  }

  /// 이 표본이 세션을 끊었다고 볼지. **검사가 꺼져 있으면 언제나 false.**
  bool breaksSession(ContinuitySample? sample) {
    if (!enabled || sample == null || !sample.isFinite) return false;
    final double? maxScale = config.continuity.maxScaleJumpRatio;
    final double? maxWrist = config.continuity.maxWristJumpRatio;
    // 설정이 켜져 있으면 서버가 두 임계값을 모두 보장한다. 방어적으로 한 번 더.
    if (maxScale == null || maxWrist == null) return false;
    return sample.scaleJump > maxScale || sample.wristJump > maxWrist;
  }

  /// 로그 한 줄에 실을 요약. 이 값으로 임계값을 도출한다.
  String summary() => 'scaleJumpMax=${_n(maxScaleJump)} '
      'wristJumpMax=${_n(maxWristJump)} n=$samples '
      'gate=${enabled ? 'on' : 'off'}';

  static String _n(double v) => v.isFinite ? v.toStringAsFixed(3) : 'nan';
}

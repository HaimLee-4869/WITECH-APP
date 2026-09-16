/// 이동 방향 판정. `challenge_response/core/movement_detector.py`의 이식.
///
///   1. 손바닥 중심과 손 크기 궤적을 만든다
///   2. 시작점 대비 최대 변위를 손 크기로 나눈다
///   3. 변위가 [MovementConfig.minDisplacementRatio] 미만이면 NONE  ← 제자리 흔들기
///   4. 주축비가 [MovementConfig.axisDominanceRatio] 미만이면 NONE  ← 대각선
///   5. 주축 부호로 방향을 정한다
///   6. coordinateFrame이 'mirrored'면 **라벨의** 좌우를 뒤집는다
///
/// ⚠️ 6번이 좌표계 규칙의 핵심이다. **좌표를 뒤집지 않는다.** 화면 오버레이는
/// 이미 거울이고 좌표를 한 번 더 뒤집으면 이중 반전이 된다. MediaPipe 입력과
/// 서버 전송 좌표는 언제나 원본이다.
library;

import 'challenge_config.dart';
import 'geometry.dart';
import 'window_motion.dart';

const String kNoMove = 'NONE';
const String kFrameMirrored = 'mirrored';
const String kFrameRaw = 'raw';

/// 좌우가 뒤집혔을 때 서로 바뀌는 라벨 쌍. 상하는 거울에 영향받지 않는다.
const Map<String, String> kLeftRight = <String, String>{
  'MOVE_LEFT': 'MOVE_RIGHT',
  'MOVE_RIGHT': 'MOVE_LEFT',
};

/// 같은 축의 반대 방향. '반대 방향이 먼저 확정되면 즉시 실패'에 쓴다.
const Map<String, String> kOppositeDirection = <String, String>{
  'MOVE_LEFT': 'MOVE_RIGHT',
  'MOVE_RIGHT': 'MOVE_LEFT',
  'MOVE_UP': 'MOVE_DOWN',
  'MOVE_DOWN': 'MOVE_UP',
};

/// NONE일 때 어느 관문에서 걸렸는지.
class MoveReason {
  static const String noTrack = 'NO_TRACK';
  static const String tooSmall = 'TOO_SMALL';
  static const String notAxisDominant = 'NOT_AXIS_DOMINANT';
  static const String unmappedAxis = 'UNMAPPED_AXIS';
  static const String ok = 'OK';
}

class MoveResult {
  final String label;
  final double confidence;
  final double displacementRatio;
  final double axisRatio;
  final String axis;
  final int sign;
  final String reason;

  const MoveResult({
    required this.label,
    required this.confidence,
    required this.displacementRatio,
    required this.axisRatio,
    required this.axis,
    required this.sign,
    required this.reason,
  });
}

class MovementDetector {
  final double minDisplacementRatio;
  final double axisDominanceRatio;
  final double windowMs;
  final double maxDurationMs;
  final Map<AxisSign, String> directionByAxis;
  final String coordinateFrame;

  MovementDetector(ChallengeConfig config)
      : minDisplacementRatio = config.movement.minDisplacementRatio,
        axisDominanceRatio = config.movement.axisDominanceRatio,
        windowMs = config.movement.windowMs,
        maxDurationMs = config.movement.maxDurationMs,
        directionByAxis = config.movement.byAxisSign,
        coordinateFrame = config.coordinateFrame {
    if (coordinateFrame != kFrameRaw && coordinateFrame != kFrameMirrored) {
      throw ArgumentError(
        "coordinateFrame은 '$kFrameRaw' 또는 '$kFrameMirrored': $coordinateFrame",
      );
    }
  }

  /// 주어진 fps에 맞는 판정 윈도우 길이(프레임).
  int windowFrames(double fps) {
    final int n = (windowMs / 1000.0 * fps).round();
    return n < 2 ? 2 : n;
  }

  /// 이미 계산된 손바닥 중심/손 크기 궤적으로 판정한다.
  MoveResult detectFromTracks(
    List<List<double>> centers,
    List<double> scales,
  ) {
    final WindowMotion motion =
        windowMotion(centers, scales, 0, scales.length);

    MoveResult none(String reason) => MoveResult(
          label: kNoMove,
          confidence: 0.0,
          displacementRatio: motion.displacementRatio,
          axisRatio: motion.axisRatio,
          axis: motion.axis,
          sign: motion.sign,
          reason: reason,
        );

    if (!motion.valid) return none(MoveReason.noTrack);
    if (motion.displacementRatio < minDisplacementRatio) {
      return none(MoveReason.tooSmall);
    }
    if (motion.axisRatio < axisDominanceRatio) {
      return none(MoveReason.notAxisDominant);
    }

    String? label = directionByAxis[AxisSign(motion.axis, motion.sign)];
    if (label == null) return none(MoveReason.unmappedAxis);

    if (coordinateFrame == kFrameMirrored) {
      // 라벨만 뒤집는다. 사용자가 화면(거울)을 보고 인식하는 방향으로 답해야 하므로,
      // 센서 좌표에서 오른쪽으로 간 손은 화면에서 왼쪽으로 간 것으로 보인다.
      label = kLeftRight[label] ?? label;
    }

    final double dispExcess = motion.displacementRatio / minDisplacementRatio;
    final double axisExcess = motion.axisRatio.isFinite
        ? motion.axisRatio / axisDominanceRatio
        : double.infinity;
    final double smaller = dispExcess < axisExcess ? dispExcess : axisExcess;
    final double confidence = smaller.isFinite ? smaller.clamp(0.0, 1.0) : 1.0;

    return MoveResult(
      label: label,
      confidence: confidence,
      displacementRatio: motion.displacementRatio,
      axisRatio: motion.axisRatio,
      axis: motion.axis,
      sign: motion.sign,
      reason: MoveReason.ok,
    );
  }

  /// [sequence]는 종횡비 보정이 끝난 화면 좌표 프레임들.
  MoveResult detect(List<Coords> sequence) {
    return detectFromTracks(
      <List<double>>[for (final Coords f in sequence) palmCenter(f)],
      <double>[for (final Coords f in sequence) handScale(f)],
    );
  }
}

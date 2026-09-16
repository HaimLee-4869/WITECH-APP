/// 손 모양 판정. `challenge_response/core/hand_action_detector.py`의 이식.
///
/// 패턴 매칭이 핵심이다. 손가락 4개(엄지 제외)의 펴짐/굽힘 조합이 **정확히**
/// 일치할 때만 라벨을 준다. 단일 임계값으로 뭉뚱그리지 않기 때문에 세 손가락
/// [T,T,T,F]이나 검지+약지 [T,F,T,F] 같은 어중간한 손이 자연히 걸러진다.
///
/// 임계값 리터럴은 없다. 전부 [ChallengeConfig]에서 온다.
library;

import 'challenge_config.dart';
import 'geometry.dart';

const String kUnknownShape = 'UNKNOWN';

/// [index, middle, ring, pinky] 조합 → 라벨. 임계값이 아니라 프로토콜 정의다.
const Map<String, List<bool>> kShapePatterns = <String, List<bool>>{
  'OPEN_PALM': <bool>[true, true, true, true],
  'FIST': <bool>[false, false, false, false],
  'INDEX': <bool>[true, false, false, false],
  'TWO_FINGERS': <bool>[true, true, false, false],
};

class ShapeResult {
  final String label;

  /// 판정에 쓰인 4손가락이 임계값에서 얼마나 확실히 떨어져 있는지. 0.0~1.0.
  /// 가장 아슬아슬한 손가락이 전체 신뢰도를 결정한다.
  final double confidence;

  /// [kFingerNames] 순서(엄지 포함).
  final List<bool> flags;
  final List<double> angles;

  /// 임계값과의 여유(도).
  final List<double> margins;

  /// 손끝-손목 거리 / 손 크기. FIST 게이트에 쓴다.
  final double tipWristRatio;

  const ShapeResult({
    required this.label,
    required this.confidence,
    required this.flags,
    required this.angles,
    required this.margins,
    this.tipWristRatio = double.nan,
  });

  bool get isKnown => label != kUnknownShape;
}

class HandActionDetector {
  final double thumbThreshold;
  final double otherThreshold;
  final double confidenceMarginDeg;
  final String angleSpace;

  /// null이면 FIST 게이트를 걸지 않는다. OPEN_PALM 쪽에는 원래 걸지 않는다.
  final double? fistMaxTipWristRatio;

  HandActionDetector(ChallengeConfig config)
      : thumbThreshold = config.fingerExtendedAngle.thumb,
        otherThreshold = config.fingerExtendedAngle.others,
        confidenceMarginDeg = config.shapeConfidenceMarginDeg,
        angleSpace = config.angleSpace,
        fistMaxTipWristRatio = config.fistMaxTipWristRatio;

  /// 정규화 좌표를 설정된 [angleSpace]로 옮긴다.
  ///
  /// `world`는 MediaPipe world landmarks를 그대로 넘겨야 한다는 뜻인데,
  /// 앱이 쓰는 `hand_landmarker` 3.0.1은 world 좌표를 주지 않는다. 서버 설정이
  /// world로 바뀌면 조용히 틀린 각도로 판정하는 대신 여기서 막는다.
  Coords prepare(Coords landmarks, {int? width, int? height}) {
    if (angleSpace == 'world') {
      return landmarks;
    }
    if (width == null || height == null) {
      throw ArgumentError('image_iso 좌표계는 width/height가 필요하다');
    }
    return toIsotropic(landmarks, width, height);
  }

  /// [coords]는 이미 설정된 좌표계(image_iso면 종횡비 보정 완료)여야 한다.
  ShapeResult detect(Coords coords) {
    final List<double> angles = fingerAngles(coords);
    final r = extensionFlags(angles, thumbThreshold, otherThreshold);
    final List<int> idx = <int>[
      for (final String n in kNonThumbFingers) kFingerNames.indexOf(n),
    ];

    // 각도를 못 구한 손가락이 하나라도 있으면 판정하지 않는다.
    // 이게 없으면 랜드마크가 전부 NaN인 프레임의 flags가 모두 false가 되어
    // FIST([F,F,F,F])로 오인된다.
    final bool allFinite = idx.every((int i) => angles[i].isFinite);
    if (!allFinite) {
      return ShapeResult(
        label: kUnknownShape,
        confidence: 0.0,
        flags: r.flags,
        angles: angles,
        margins: r.margins,
      );
    }

    final List<bool> pattern = <bool>[for (final int i in idx) r.flags[i]];
    String label = kUnknownShape;
    for (final MapEntry<String, List<bool>> e in kShapePatterns.entries) {
      if (_samePattern(e.value, pattern)) {
        label = e.key;
        break;
      }
    }

    final double tipWrist = fingertipWristRatio(coords);
    if (label == 'FIST' && fistMaxTipWristRatio != null) {
      // 손끝 거리를 못 재면 반쯤 쥔 손인지 확인할 수 없으므로 FIST로 인정하지 않는다.
      if (!tipWrist.isFinite || tipWrist >= fistMaxTipWristRatio!) {
        label = kUnknownShape;
      }
    }

    double confidence = double.infinity;
    for (final int i in idx) {
      final double d = r.margins[i].isFinite
          ? (r.margins[i].abs() / confidenceMarginDeg).clamp(0.0, 1.0)
          : 0.0;
      if (d < confidence) confidence = d;
    }
    if (!confidence.isFinite) confidence = 0.0;

    return ShapeResult(
      label: label,
      confidence: confidence,
      flags: r.flags,
      angles: angles,
      margins: r.margins,
      tipWristRatio: tipWrist,
    );
  }

  static bool _samePattern(List<bool> a, List<bool> b) {
    for (int i = 0; i < a.length; i++) {
      if (a[i] != b[i]) return false;
    }
    return true;
  }
}

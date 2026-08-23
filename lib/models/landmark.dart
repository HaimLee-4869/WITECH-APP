import '../core/hand_connections.dart';

/// MediaPipe가 뱉는 랜드마크 한 점. **원본 좌표 그대로** 담는다.
///
/// SPEC 원칙 A: 정규화·리샘플링·특징추출을 앱에서 하지 않는다.
/// 이 클래스는 순수한 값 컨테이너이고, 좌표를 가공하는 메서드를 두지 않는다.
class Landmark {
  /// [0,1] 정규화 좌표 (이미지 폭 기준). MediaPipe가 주는 값 그대로.
  final double x;

  /// [0,1] 정규화 좌표 (이미지 높이 기준). MediaPipe가 주는 값 그대로.
  final double y;

  /// 손목 기준 상대 깊이.
  final double z;

  const Landmark(this.x, this.y, this.z);

  /// 전송 JSON의 `lm` 배열 원소 형태 `[x, y, z]`. (SPEC 6장)
  List<double> toJson() => <double>[x, y, z];

  @override
  String toString() =>
      'Landmark(${x.toStringAsFixed(3)}, ${y.toStringAsFixed(3)}, '
      '${z.toStringAsFixed(3)})';
}

/// 한 프레임에서 검출된 손 하나.
class HandFrame {
  /// 캡처 시작 시점부터의 **실제** 경과 시간 (ms).
  ///
  /// 인덱스×33 같은 균등 간격 가정을 절대 쓰지 않는다. 폰 부하로 프레임 간격이
  /// 흔들리므로 서버가 고정 길이로 리샘플링하려면 진짜 타임스탬프가 필요하다.
  /// (SPEC 6장)
  final int tMs;

  /// 정확히 [kLandmarkCount]개.
  final List<Landmark> landmarks;

  /// "Left" | "Right".
  final String handedness;

  /// 검출 신뢰도.
  final double score;

  const HandFrame({
    required this.tMs,
    required this.landmarks,
    required this.handedness,
    required this.score,
  });

  /// 랜드마크가 21개 다 있는지. 오버레이 렌더링 전 방어용.
  bool get isComplete => landmarks.length == kLandmarkCount;

  /// 전송 JSON의 frames 원소. (SPEC 6장)
  Map<String, dynamic> toJson() => <String, dynamic>{
    'tMs': tMs,
    'handedness': handedness,
    'score': score,
    'lm': landmarks.map((l) => l.toJson()).toList(),
  };
}

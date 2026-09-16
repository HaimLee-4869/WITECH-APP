/// 각도·거리·정규화 계산.
///
/// `challenge_response/core/geometry.py`의 이식이다. **임계값은 하나도 들어있지
/// 않다.** 순수 기하 계산만 한다. Python과 같은 입력에 같은 값을 내야 하므로
/// 계산 순서까지 원본을 따른다.
library;

import 'dart:math' as math;

/// 랜드마크 21개 × (x, y, z). MediaPipe 원본 순서 그대로.
typedef Coords = List<List<double>>;

/// 손가락별 (MCP, PIP, TIP) 인덱스. 임계값이 아니라 손 구조 상수다.
const Map<String, List<int>> kFingerJoints = <String, List<int>>{
  'thumb': <int>[1, 2, 4],
  'index': <int>[5, 6, 8],
  'middle': <int>[9, 10, 12],
  'ring': <int>[13, 14, 16],
  'pinky': <int>[17, 18, 20],
};

const List<String> kFingerNames = <String>[
  'thumb',
  'index',
  'middle',
  'ring',
  'pinky',
];

/// 손 모양 패턴 판정에 쓰는 4개. 엄지는 개인차가 커서 패턴에서 뺀다.
const List<String> kNonThumbFingers = <String>['index', 'middle', 'ring', 'pinky'];

const int kWrist = 0;
const int kMiddleMcp = 9;

/// 손바닥 뼈대. 손끝은 흔들려서 중심 계산에서 뺀다.
const List<int> kPalmPoints = <int>[0, 5, 9, 13, 17];

/// 정규화 좌표([0,1])를 화면 종횡비가 반영된 등방 좌표(픽셀)로.
///
/// x, y를 그대로 두면 16:9 화면에서 각도가 왜곡된다. MediaPipe의 z는 x와 대략
/// 같은 스케일이라 width를 곱한다.
Coords toIsotropic(Coords landmarks, int width, int height) {
  return <List<double>>[
    for (final List<double> p in landmarks)
      <double>[p[0] * width, p[1] * height, p[2] * width],
  ];
}

/// 점 b를 꼭짓점으로 하는 a-b-c 사잇각(도). 계산 불가면 NaN.
double angleAt(List<double> a, List<double> b, List<double> c) {
  final List<double> v1 = <double>[a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  final List<double> v2 = <double>[c[0] - b[0], c[1] - b[1], c[2] - b[2]];
  final double n1 = _norm(v1);
  final double n2 = _norm(v2);
  if (!n1.isFinite || !n2.isFinite || n1 == 0 || n2 == 0) return double.nan;

  final double dot = v1[0] * v2[0] + v1[1] * v2[1] + v1[2] * v2[2];
  final double cos = (dot / (n1 * n2)).clamp(-1.0, 1.0);
  return _degrees(math.acos(cos));
}

/// 손가락별 MCP-PIP-TIP 사잇각(도). 펴지면 180도에 가깝다.
///
/// 반환 순서는 [kFingerNames].
List<double> fingerAngles(Coords landmarks) {
  return <double>[
    for (final String name in kFingerNames)
      angleAt(
        landmarks[kFingerJoints[name]![0]],
        landmarks[kFingerJoints[name]![1]],
        landmarks[kFingerJoints[name]![2]],
      ),
  ];
}

/// 손목(0)-중지 MCP(9) 거리. 카메라 거리 정규화 기준.
double handScale(Coords landmarks) {
  final List<double> a = landmarks[kMiddleMcp];
  final List<double> b = landmarks[kWrist];
  return _norm(<double>[a[0] - b[0], a[1] - b[1], a[2] - b[2]]);
}

/// 엄지 제외 4손끝과 손목 사이 평균 거리 / 손 크기. **화면 평면(x, y)에서** 잰다.
///
/// MCP-PIP-TIP 각도는 손바닥 쪽 관절(MCP)이 굽은 것을 보지 못한다. 반쯤 쥔 손은
/// 손끝이 손목에서 주먹보다 멀리 있으므로 이 거리로 FIST와 가른다.
/// z는 MediaPipe 추정 잡음이 커서 쓰지 않는다.
double fingertipWristRatio(Coords landmarks) {
  final List<double> wrist = landmarks[kWrist];
  final List<double> mcp = landmarks[kMiddleMcp];
  final double scale = _norm2(<double>[mcp[0] - wrist[0], mcp[1] - wrist[1]]);
  if (!scale.isFinite || scale == 0) return double.nan;

  double sum = 0.0;
  for (final String name in kNonThumbFingers) {
    final List<double> tip = landmarks[kFingerJoints[name]![2]];
    sum += _norm2(<double>[tip[0] - wrist[0], tip[1] - wrist[1]]);
  }
  return sum / kNonThumbFingers.length / scale;
}

/// 손바닥 뼈대(0,5,9,13,17)의 평균.
List<double> palmCenter(Coords landmarks) {
  final List<double> sum = <double>[0.0, 0.0, 0.0];
  for (final int i in kPalmPoints) {
    for (int axis = 0; axis < 3; axis++) {
      sum[axis] += landmarks[i][axis];
    }
  }
  return <double>[
    sum[0] / kPalmPoints.length,
    sum[1] / kPalmPoints.length,
    sum[2] / kPalmPoints.length,
  ];
}

/// 각도 → (펴짐 여부, 임계값과의 여유). 순서는 [kFingerNames].
///
/// 각도를 못 구한 손가락(NaN)은 펴지지 않은 것으로 두되 여유는 NaN으로 남긴다.
/// "굽었다"와 "모른다"를 뒤에서 구분해야 하기 때문이다.
({List<bool> flags, List<double> margins}) extensionFlags(
  List<double> angles,
  double thumbThreshold,
  double otherThreshold,
) {
  final List<bool> flags = <bool>[];
  final List<double> margins = <double>[];
  for (int i = 0; i < kFingerNames.length; i++) {
    final double threshold =
        kFingerNames[i] == 'thumb' ? thumbThreshold : otherThreshold;
    final double margin = angles[i] - threshold;
    flags.add(angles[i].isFinite && margin >= 0.0);
    margins.add(angles[i].isFinite ? margin : double.nan);
  }
  return (flags: flags, margins: margins);
}

double _norm(List<double> v) => math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);

double _norm2(List<double> v) => math.sqrt(v[0] * v[0] + v[1] * v[1]);

double _degrees(double radians) => radians * 180.0 / math.pi;

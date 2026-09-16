/// 요청 동작을 그림으로 보여주기 위한 손 모델.
///
/// **안내 그림을 판정 규칙에서 직접 만든다.** 손 모양 그림을 따로 그려 두면
/// `kShapePatterns`가 바뀌었을 때 그림만 옛 모양으로 남아 "화면은 검지를 펴라는데
/// 판정은 두 손가락을 기다리는" 상태가 된다. 여기서는 패턴과 서버 임계값으로
/// 좌표를 만들고, 테스트가 그 좌표를 실제 판정기에 넣어 라벨이 같은지 확인한다.
///
/// 손 구조 상수는 `challenge_response/tests/synth.py`와 같다.
library;

import 'dart:math' as math;

import 'challenge_config.dart';
import 'geometry.dart';
import 'hand_action_detector.dart';

// 손가락별 MCP 위치(손 크기 1 기준). 임계값이 아니라 손 구조 상수다.
const Map<String, double> kSketchMcpX = <String, double>{
  'thumb': -0.7,
  'index': -0.35,
  'middle': 0.0,
  'ring': 0.3,
  'pinky': 0.6,
};
const Map<String, double> kSketchMcpY = <String, double>{
  'thumb': -0.5,
  'index': -1.0,
  'middle': -1.0,
  'ring': -0.95,
  'pinky': -0.85,
};
const double kSketchSeg1 = 0.45; // MCP -> PIP
const double kSketchSeg2 = 0.55; // PIP -> TIP

/// MCP-PIP-TIP 사이에 낀 나머지 랜드마크(DIP 등)의 인덱스.
const Map<String, int> kSketchExtra = <String, int>{
  'thumb': 3,
  'index': 7,
  'middle': 11,
  'ring': 15,
  'pinky': 19,
};

/// 손가락별 관절 각도(도)로 21점 손을 만든다.
///
/// 손목(0)이 원점, 손가락은 -y(화면 위쪽)로 뻗는다.
/// [mcpFlex]는 손가락 전체를 MCP에서 손바닥 쪽으로 접는 각도(도)다. 생략하면 0이라
/// `challenge_response/tests/synth.py`와 같은 좌표가 나온다.
///
/// MCP 굽힘을 더해도 MCP-PIP-TIP 사잇각은 그대로다(손가락을 통째로 돌리기 때문).
/// 판정기가 보는 각도는 바뀌지 않고, 손끝이 손목에 가까워지는 것만 달라진다.
/// 실제 주먹이 그렇게 생겼고, PIP만 굽힌 손은 손끝-손목 거리가 주먹에 못 미친다.
Coords buildHand({
  Map<String, double>? angles,
  double uniformAngle = 180.0,
  double scale = 1.0,
  List<double> center = const <double>[0.0, 0.0, 0.0],
  Map<String, double> mcpFlex = const <String, double>{},
}) {
  final Map<String, double> a = angles ??
      <String, double>{for (final String n in kFingerNames) n: uniformAngle};

  final Coords lm = <List<double>>[
    for (int i = 0; i < 21; i++) <double>[0.0, 0.0, 0.0],
  ];

  for (final String name in kFingerNames) {
    final List<int> joints = kFingerJoints[name]!;
    final List<double> mcp = <double>[kSketchMcpX[name]!, kSketchMcpY[name]!, 0.0];
    List<double> pip = <double>[mcp[0], mcp[1] - kSketchSeg1, 0.0];
    // PIP에서 MCP를 향하는 방향은 +y. 이를 지정 각도만큼 돌려 TIP 방향을 만든다.
    final double theta = a[name]! * math.pi / 180.0;
    List<double> tip = <double>[
      pip[0] + math.sin(theta) * kSketchSeg2,
      pip[1] + math.cos(theta) * kSketchSeg2,
      0.0,
    ];

    final double flex = mcpFlex[name] ?? 0.0;
    if (flex != 0.0) {
      final double phi = flex * math.pi / 180.0;
      List<double> rotate(List<double> p) {
        final double dx = p[0] - mcp[0];
        final double dy = p[1] - mcp[1];
        return <double>[
          mcp[0] + dx * math.cos(phi) - dy * math.sin(phi),
          mcp[1] + dx * math.sin(phi) + dy * math.cos(phi),
          p[2],
        ];
      }

      pip = rotate(pip);
      tip = rotate(tip);
    }

    lm[joints[0]] = mcp;
    lm[joints[1]] = pip;
    lm[joints[2]] = tip;
    lm[kSketchExtra[name]!] = <double>[
      (pip[0] + tip[0]) / 2.0,
      (pip[1] + tip[1]) / 2.0,
      0.0,
    ];
  }
  lm[0] = <double>[0.0, 0.0, 0.0]; // 손목

  return <List<double>>[
    for (final List<double> p in lm)
      <double>[
        p[0] * scale + center[0],
        p[1] * scale + center[1],
        p[2] * scale + center[2],
      ],
  ];
}

/// 요청 손 모양의 그림용 좌표와 손가락별 펴짐 여부.
class ShapeSketch {
  final Coords landmarks;

  /// [kFingerNames] 순서. 펴는 손가락은 초록, 접는 손가락은 회색으로 그린다.
  final List<bool> extended;

  const ShapeSketch(this.landmarks, this.extended);
}

/// [label]이 요구하는 손 모양을 그린다.
///
/// 각도는 서버가 준 임계값에서 만든다. 임계값이 바뀌면 그림도 따라 움직인다.
/// 엄지는 판정에 쓰지 않지만(개인차가 커서) 그림에는 그려야 하므로, 자연스럽게
/// 편 손은 펴고 주먹은 접는다.
ShapeSketch sketchForShape(String label, ChallengeConfig config) {
  final List<bool>? pattern = kShapePatterns[label];
  if (pattern == null) {
    throw ArgumentError('손 모양 라벨이 아니다: $label');
  }

  final double margin = config.shapeConfidenceMarginDeg;
  // 임계값에서 신뢰도 1.0만큼 떨어뜨린다. 경계에 걸친 그림을 그리지 않는다.
  double extendedAngle(double threshold) =>
      math.min(threshold + margin, 179.0);
  double curledAngle(double threshold) =>
      math.max(threshold - 2 * margin, 15.0);

  final double others = config.fingerExtendedAngle.others;
  final double thumb = config.fingerExtendedAngle.thumb;

  // 엄지: 주먹만 접고 나머지는 편다.
  final bool thumbExtended = label != 'FIST';

  final double curledOthers = curledAngle(others);
  final Map<String, double> angles = <String, double>{
    'thumb': thumbExtended ? extendedAngle(thumb) : curledAngle(thumb),
    for (final (int i, String name) in kNonThumbFingers.indexed)
      name: pattern[i] ? extendedAngle(others) : curledOthers,
  };

  // FIST는 각도 패턴만으로는 부족하다. 손끝-손목 거리 게이트도 넘어야 판정기가
  // FIST로 인정한다. 각도만 보고 그리면 '반쯤 쥔 손'을 그려 놓고 사용자가 그대로
  // 따라 해도 UNKNOWN이 되는 그림이 된다.
  final Map<String, double> flex = label == 'FIST'
      ? _flexUntilFistGate(angles, config)
      : const <String, double>{};

  return ShapeSketch(
    buildHand(angles: angles, mcpFlex: flex),
    <bool>[
      thumbExtended,
      for (final bool f in pattern) f,
    ],
  );
}

/// 손끝이 손목에 충분히 가까워질 때까지 MCP를 접는다.
///
/// 게이트 값(`fistMaxTipWristRatio`)은 서버가 준다. 각도를 상수로 박으면 게이트가
/// 조정됐을 때 그림이 게이트 밖으로 나간다. 그림이 게이트를 **실제로 넘는지
/// 확인하면서** 접는다. 여유를 10% 둬서 경계에 붙이지 않는다.
///
/// MCP를 돌려도 MCP-PIP-TIP 각도는 그대로라, 굽힘 패턴 판정에는 영향이 없다.
Map<String, double> _flexUntilFistGate(
  Map<String, double> angles,
  ChallengeConfig config,
) {
  final double? gate = config.fistMaxTipWristRatio;
  if (gate == null) return const <String, double>{};

  const double step = 5.0;
  const double maxFlex = 170.0;
  for (double flex = 0.0; flex <= maxFlex; flex += step) {
    final Map<String, double> candidate = <String, double>{
      for (final String n in kNonThumbFingers) n: flex,
    };
    final double ratio =
        fingertipWristRatio(buildHand(angles: angles, mcpFlex: candidate));
    if (ratio.isFinite && ratio < gate * 0.9) return candidate;
  }
  // 이 손 모델로는 게이트를 넘길 수 없다. 가장 많이 접은 상태로 그린다.
  return <String, double>{for (final String n in kNonThumbFingers) n: maxFlex};
}

/// 이동 방향을 화면 좌표 단위 벡터로. 그대로 화살표 방향이 된다.
///
/// ⚠️ 여기에 [ChallengeConfig.movement]의 `directionMap`을 쓰면 **안 된다.**
/// 그 표는 센서 좌표의 축·부호를 라벨로 옮기는 용도이고, `coordinateFrame`이
/// mirrored면 판정기가 이미 라벨을 뒤집어 놓았다. 라벨 자체가 **사용자가 거울
/// 화면에서 보는 방향**이므로, 화살표는 라벨이 말하는 대로 그리면 된다.
/// 여기서 표를 한 번 더 참조하면 화살표만 반대로 간다.
({double dx, double dy}) arrowFor(String label) => switch (label) {
      'MOVE_LEFT' => (dx: -1.0, dy: 0.0),
      'MOVE_RIGHT' => (dx: 1.0, dy: 0.0),
      'MOVE_UP' => (dx: 0.0, dy: -1.0),
      'MOVE_DOWN' => (dx: 0.0, dy: 1.0),
      _ => throw ArgumentError('이동 라벨이 아니다: $label'),
    };

/// 손 뼈대를 그릴 때 이을 선. (시작, 끝) 랜드마크 인덱스.
const List<List<int>> kSketchPalmBones = <List<int>>[
  <int>[0, 1],
  <int>[0, 5],
  <int>[5, 9],
  <int>[9, 13],
  <int>[13, 17],
  <int>[0, 17],
];

/// 손가락별 뼈대 (MCP → PIP → 중간 → TIP).
List<List<int>> sketchFingerBones(String finger) {
  final List<int> j = kFingerJoints[finger]!;
  final int extra = kSketchExtra[finger]!;
  return <List<int>>[
    <int>[j[0], j[1]],
    <int>[j[1], extra],
    <int>[extra, j[2]],
  ];
}

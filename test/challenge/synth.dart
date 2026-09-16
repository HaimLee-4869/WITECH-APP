/// 합성 랜드마크 생성기. `challenge_response/tests/synth.py`의 이식이다.
///
/// 손 모델: 손목(0)이 원점, 손가락은 -y 방향(화면 위쪽)으로 뻗는다.
/// 각 손가락은 (MCP, PIP, TIP)의 사잇각을 지정한 값으로 정확히 만들 수 있다.
///
/// Python 쪽과 상수·계산 순서가 같아야 두 구현의 결과를 비교할 수 있다.
library;

import 'dart:math' as math;

import 'package:signid/challenge/geometry.dart';

// 손가락별 MCP 위치(손 크기 1 기준). 임계값이 아니라 손 구조 상수다.
const Map<String, double> _mcpX = <String, double>{
  'thumb': -0.7,
  'index': -0.35,
  'middle': 0.0,
  'ring': 0.3,
  'pinky': 0.6,
};
const Map<String, double> _mcpY = <String, double>{
  'thumb': -0.5,
  'index': -1.0,
  'middle': -1.0,
  'ring': -0.95,
  'pinky': -0.85,
};
const double _seg1 = 0.45; // MCP -> PIP
const double _seg2 = 0.55; // PIP -> TIP

// MCP-PIP-TIP 사이에 낀 나머지 랜드마크(DIP 등)는 보간해서 채운다.
const Map<String, int> _extra = <String, int>{
  'thumb': 3,
  'index': 7,
  'middle': 11,
  'ring': 15,
  'pinky': 19,
};

/// 손가락별 관절 각도(도)를 지정해 (21,3) 랜드마크를 만든다.
///
/// [angles]가 null이면 전 손가락 180도(쫙 편 손).
Coords makeHand({
  Map<String, double>? angles,
  double uniformAngle = 180.0,
  double scale = 1.0,
  List<double> center = const <double>[0.0, 0.0, 0.0],
}) {
  final Map<String, double> a = angles ??
      <String, double>{for (final String n in kFingerNames) n: uniformAngle};

  final Coords lm = <List<double>>[
    for (int i = 0; i < 21; i++) <double>[0.0, 0.0, 0.0],
  ];

  for (final String name in kFingerNames) {
    final List<int> joints = kFingerJoints[name]!;
    final List<double> mcp = <double>[_mcpX[name]!, _mcpY[name]!, 0.0];
    final List<double> pip = <double>[mcp[0], mcp[1] - _seg1, 0.0];
    // PIP에서 MCP를 향하는 방향은 +y. 이를 지정 각도만큼 돌려 TIP 방향을 만든다.
    final double theta = a[name]! * math.pi / 180.0;
    final List<double> tip = <double>[
      pip[0] + math.sin(theta) * _seg2,
      pip[1] + math.cos(theta) * _seg2,
      0.0,
    ];
    lm[joints[0]] = mcp;
    lm[joints[1]] = pip;
    lm[joints[2]] = tip;
    lm[_extra[name]!] = <double>[
      (pip[0] + tip[0]) / 2.0,
      (pip[1] + tip[1]) / 2.0,
      0.0,
    ];
  }

  // 손목. 엄지 관절(1,2,4)은 위 루프가 채우므로 덮어쓰지 않는다.
  lm[0] = <double>[0.0, 0.0, 0.0];

  return <List<double>>[
    for (final List<double> p in lm)
      <double>[
        p[0] * scale + center[0],
        p[1] * scale + center[1],
        p[2] * scale + center[2],
      ],
  ];
}

/// 손가락별 펴짐 여부로 손을 만든다.
Coords makePatternHand({
  required Map<String, bool> extended,
  required double extendedAngle,
  required double curledAngle,
  double scale = 1.0,
  List<double> center = const <double>[0.0, 0.0, 0.0],
}) {
  return makeHand(
    angles: <String, double>{
      for (final String n in kFingerNames)
        n: (extended[n] ?? false) ? extendedAngle : curledAngle,
    },
    scale: scale,
    center: center,
  );
}

/// start에서 end로 선형 이동하는 시퀀스.
List<Coords> makeSequence({
  required List<double> start,
  required List<double> end,
  required int frames,
  double scale = 1.0,
  double uniformAngle = 180.0,
}) {
  return <Coords>[
    for (int i = 0; i < frames; i++)
      makeHand(
        uniformAngle: uniformAngle,
        scale: scale,
        center: <double>[
          for (int axis = 0; axis < 3; axis++)
            start[axis] +
                (end[axis] - start[axis]) * (i / math.max(frames - 1, 1)),
        ],
      ),
  ];
}

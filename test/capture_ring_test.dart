/// 촬영 진행률 아크가 상태 색과 구분되는지.
///
/// 아크가 초록이면 차오르는 것이 "정답/통과"로 읽힌다. 실제로는 촬영이 얼마나
/// 진행됐는지일 뿐이라 별도 색(보라)을 쓴다.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:signid/core/theme.dart';
import 'package:signid/widgets/capture_ring.dart';

/// 캔버스에 실제로 쓰인 색을 모은다.
///
/// [Canvas]는 상속할 수 없어 인터페이스만 구현하고 나머지 호출은 흘려보낸다.
/// 여기서는 어떤 색으로 그렸는지만 보면 된다.
class _ColorRecorder implements Canvas {
  final List<Color> arcColors = <Color>[];
  final List<Color> circleColors = <Color>[];

  @override
  void drawArc(Rect rect, double start, double sweep, bool useCenter, Paint paint) {
    arcColors.add(paint.color);
  }

  @override
  void drawCircle(Offset c, double radius, Paint paint) {
    circleColors.add(paint.color);
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

/// `Paint.color`는 내부 표현이 달라 `==`가 어긋난다. ARGB 값으로 비교한다.
int argb(Color c) => c.toARGB32();

List<int> argbOf(List<Color> colors) =>
    <int>[for (final Color c in colors) argb(c)];

_ColorRecorder paintRing({required Color borderColor, double? progress}) {
  final _ColorRecorder canvas = _ColorRecorder();
  ringPainterForTest(color: borderColor, progress: progress)
      .paint(canvas, const Size(240, 240));
  return canvas;
}

void main() {
  test('진행률 아크는 보라다 (상태 색이 아니다)', () {
    final _ColorRecorder c =
        paintRing(borderColor: AppColors.ring, progress: 0.5);
    expect(argbOf(c.arcColors), contains(argb(AppColors.progress)));
    expect(argbOf(c.arcColors), isNot(contains(argb(AppColors.ring))));
  });

  test('상태 색은 그대로 쓴다 (바탕 원)', () {
    // 테두리 상태(탐색/준비/성공/실패)는 계속 보여야 한다.
    final _ColorRecorder c =
        paintRing(borderColor: AppColors.ring, progress: 0.5);
    // 바탕 원은 상태 색을 흐리게(alpha 0.22) 그리므로 RGB만 본다.
    expect(
      argbOf(c.circleColors).map((int v) => v & 0x00FFFFFF),
      contains(argb(AppColors.ring) & 0x00FFFFFF),
      reason: '바탕 원이 상태 색이 아니다',
    );
  });

  test('진행률이 없으면 상태 색 원만 그린다', () {
    final _ColorRecorder c = paintRing(borderColor: AppColors.textSecondary);
    expect(c.arcColors, isEmpty);
    expect(argbOf(c.circleColors), <int>[argb(AppColors.textSecondary)]);
  });

  test('진행률 색은 상태 색 어느 것과도 같지 않다', () {
    // 겹치면 의미가 섞인다.
    for (final Color state in <Color>[
      AppColors.ring, // 준비됨 (민트)
      AppColors.success, // 성공 (초록)
      AppColors.danger, // 실패 (빨강)
      AppColors.textSecondary, // 손 탐색 중 (회색)
    ]) {
      expect(argb(AppColors.progress), isNot(argb(state)));
    }
  });
}

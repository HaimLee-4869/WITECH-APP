/// 요청 동작 안내 그림.
///
/// 손 모양은 [sketchForShape]가, 화살표 방향은 [arrowFor]가 정한다. 둘 다 판정
/// 규칙에서 나오므로 **안내와 판정이 어긋날 수 없다**
/// (test/challenge/hand_sketch_test.dart가 그림을 실제 판정기에 넣어 확인한다).
library;

import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../challenge/challenge_config.dart';
import '../challenge/geometry.dart';
import '../challenge/hand_action_detector.dart';
import '../challenge/hand_sketch.dart';
import '../core/theme.dart';

/// 요청 동작 하나를 그린다. 손 모양이면 손 뼈대, 이동이면 손 + 화살표.
class ChallengeGuide extends StatelessWidget {
  final String action;
  final ChallengeConfig config;
  final double size;

  /// 아직 차례가 아닌 단계는 흐리게.
  final bool dimmed;

  /// 펴는 손가락·화살표 색. 단계가 통과했는지에 따라 호출하는 쪽이 정한다.
  final Color accent;

  const ChallengeGuide({
    super.key,
    required this.action,
    required this.config,
    this.size = 120,
    this.dimmed = false,
    this.accent = AppColors.ring,
  });

  bool get _isShape => kShapePatterns.containsKey(action);

  @override
  Widget build(BuildContext context) {
    // 이동 단계에서도 손은 그린다. 손바닥을 편 채로 움직이는 동작이라
    // OPEN_PALM 그림에 화살표를 얹는다.
    final ShapeSketch sketch =
        sketchForShape(_isShape ? action : 'OPEN_PALM', config);

    return SizedBox(
      width: size,
      height: size,
      child: CustomPaint(
        painter: _GuidePainter(
          sketch: sketch,
          arrow: _isShape ? null : arrowFor(action),
          opacity: dimmed ? 0.35 : 1.0,
          accent: accent,
        ),
      ),
    );
  }
}

class _GuidePainter extends CustomPainter {
  final ShapeSketch sketch;
  final ({double dx, double dy})? arrow;
  final double opacity;
  final Color accent;

  _GuidePainter({
    required this.sketch,
    required this.arrow,
    required this.opacity,
    required this.accent,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final List<Offset> points = _fit(sketch.landmarks, size);

    final Paint bone = Paint()
      ..strokeWidth = 3.0
      ..strokeCap = StrokeCap.round
      ..style = PaintingStyle.stroke;

    // 손바닥 뼈대는 늘 같은 색이다. 판정에 쓰이지 않는다.
    bone.color = AppColors.textSecondary.withValues(alpha: opacity * 0.7);
    for (final List<int> b in kSketchPalmBones) {
      canvas.drawLine(points[b[0]], points[b[1]], bone);
    }

    // 손가락: 펴는 손가락은 [accent], 접는 손가락은 회색.
    for (final (int i, String finger) in kFingerNames.indexed) {
      final bool extended = sketch.extended[i];
      bone.color = (extended ? accent : AppColors.textSecondary)
          .withValues(alpha: opacity * (extended ? 1.0 : 0.45));
      for (final List<int> b in sketchFingerBones(finger)) {
        canvas.drawLine(points[b[0]], points[b[1]], bone);
      }
      // 편 손가락 끝에 점을 찍어 어디를 펴야 하는지 분명히 한다.
      if (extended) {
        canvas.drawCircle(
          points[kFingerJoints[finger]![2]],
          3.5,
          Paint()..color = accent.withValues(alpha: opacity),
        );
      }
    }

    if (arrow != null) _drawArrow(canvas, size);
  }

  void _drawArrow(Canvas canvas, Size size) {
    final ({double dx, double dy}) a = arrow!;
    final Offset center = Offset(size.width / 2, size.height / 2);
    final double reach = size.shortestSide * 0.42;
    final Offset dir = Offset(a.dx, a.dy);

    // 손을 가리지 않도록 손 바깥쪽에서 시작한다.
    final Offset from = center + dir * (reach * 0.45);
    final Offset to = center + dir * reach;

    final Paint paint = Paint()
      ..color = accent.withValues(alpha: opacity)
      ..strokeWidth = 4.0
      ..strokeCap = StrokeCap.round
      ..style = PaintingStyle.stroke;
    canvas.drawLine(from, to, paint);

    // 화살촉
    const double head = 10.0;
    final double angle = math.atan2(dir.dy, dir.dx);
    for (final double spread in <double>[2.6, -2.6]) {
      canvas.drawLine(
        to,
        to + Offset(math.cos(angle + spread), math.sin(angle + spread)) * head,
        paint,
      );
    }
  }

  /// 손 좌표를 캔버스에 맞춰 넣는다. 종횡비를 유지한다.
  List<Offset> _fit(Coords landmarks, Size size) {
    double minX = double.infinity, maxX = -double.infinity;
    double minY = double.infinity, maxY = -double.infinity;
    for (final List<double> p in landmarks) {
      minX = math.min(minX, p[0]);
      maxX = math.max(maxX, p[0]);
      minY = math.min(minY, p[1]);
      maxY = math.max(maxY, p[1]);
    }
    final double spanX = math.max(maxX - minX, 1e-6);
    final double spanY = math.max(maxY - minY, 1e-6);

    // 화살표 자리를 남기려고 손을 캔버스의 60%만 차지하게 둔다.
    final double box = size.shortestSide * 0.6;
    final double scale = math.min(box / spanX, box / spanY);
    final double offsetX = (size.width - spanX * scale) / 2;
    final double offsetY = (size.height - spanY * scale) / 2;

    return <Offset>[
      for (final List<double> p in landmarks)
        Offset(
          offsetX + (p[0] - minX) * scale,
          offsetY + (p[1] - minY) * scale,
        ),
    ];
  }

  @override
  bool shouldRepaint(_GuidePainter old) =>
      old.sketch != sketch ||
      old.arrow != arrow ||
      old.opacity != opacity ||
      old.accent != accent;
}

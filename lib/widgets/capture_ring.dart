import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../core/config.dart';
import '../core/theme.dart';

/// 화면 크기에 맞는 가이드 원 지름.
///
/// 기본은 화면 폭의 [kCaptureRingDiameterRatio]배지만(SPEC 8.2), 화면이 낮으면
/// 그 값이 세로 공간을 넘겨 문구와 버튼이 잘려 나간다. 세로로도 상한을 둔다.
/// 일반적인 세로 폰에서는 폭 기준이 그대로 이긴다.
double captureRingDiameter(Size screen) {
  final byWidth = screen.width * kCaptureRingDiameterRatio;
  final byHeight = screen.height * 0.45;
  return byWidth < byHeight ? byWidth : byHeight;
}

/// 주어진 공간을 꽉 채우는 지름.
///
/// 안티스푸핑 Challenge처럼 **손을 크게 움직여야 하는** 화면에서 쓴다. 원이 작으면
/// 프리뷰에 보이는 범위가 좁아 사용자가 손을 조금만 움직이고, 변위 관문
/// (`minDisplacementRatio`)을 못 넘긴다. 인증·등록은 손을 제자리에서 수행하므로
/// [captureRingDiameter]의 고정 비율을 그대로 쓴다.
double captureRingDiameterIn(BoxConstraints constraints) {
  final side = math.min(constraints.maxWidth, constraints.maxHeight);
  // 너무 작으면 오버레이가 안 보이고, 너무 크면 태블릿에서 화면을 다 먹는다.
  return side.clamp(180.0, 560.0);
}

/// 인증/등록 화면의 원형 캡처 영역. (SPEC 8.2)
///
/// 원 안쪽에만 [child](카메라 프리뷰 + 오버레이)가 보이도록 클립하고, 테두리를
/// 상태에 따라 다른 색으로 그린다. [progress]가 주어지면 테두리를 진행률
/// 아크로 렌더링한다.
class CaptureRing extends StatelessWidget {
  final double diameter;

  /// 테두리 색. 상태 머신이 결정한다. (handSearching=회색, handReady 이후=민트)
  final Color borderColor;

  /// 0.0~1.0. null이면 진행률 아크 없이 테두리 원만 그린다.
  final double? progress;

  /// 원 안에 표시할 내용. 원형으로 클립된다.
  final Widget? child;

  const CaptureRing({
    super.key,
    required this.diameter,
    required this.borderColor,
    this.progress,
    this.child,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: diameter,
      height: diameter,
      child: Stack(
        fit: StackFit.expand,
        children: [
          // 원 안쪽 배경. 프리뷰가 없을 때도 원이 비어 보이지 않게 한다.
          DecoratedBox(
            decoration: const BoxDecoration(
              shape: BoxShape.circle,
              color: AppColors.surface,
            ),
          ),
          if (child != null) ClipOval(child: child),
          // 테두리는 항상 내용 위에 그린다.
          CustomPaint(
            painter: _RingPainter(color: borderColor, progress: progress),
          ),
        ],
      ),
    );
  }
}

class _RingPainter extends CustomPainter {
  static const double _strokeWidth = 3.0;

  final Color color;
  final double? progress;

  const _RingPainter({required this.color, this.progress});

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final radius = (math.min(size.width, size.height) - _strokeWidth) / 2;

    final p = progress;
    if (p == null) {
      canvas.drawCircle(
        center,
        radius,
        Paint()
          ..color = color
          ..strokeWidth = _strokeWidth
          ..style = PaintingStyle.stroke,
      );
      return;
    }

    // 진행률 아크: 남은 구간은 흐리게, 지나간 구간은 진하게. 12시 방향에서 시작.
    //
    // 아크만 [AppColors.progress](보라)를 쓴다. 상태 색을 그대로 쓰면 차오르는
    // 아크가 "정답/통과"로 읽히는데, 이건 촬영이 얼마나 진행됐는지일 뿐이다.
    // 바탕 원은 상태 색을 흐리게 남겨 테두리 상태를 계속 보여준다.
    final rect = Rect.fromCircle(center: center, radius: radius);
    canvas.drawCircle(
      center,
      radius,
      Paint()
        ..color = color.withValues(alpha: 0.22)
        ..strokeWidth = _strokeWidth
        ..style = PaintingStyle.stroke,
    );
    canvas.drawArc(
      rect,
      -math.pi / 2,
      2 * math.pi * p.clamp(0.0, 1.0),
      false,
      Paint()
        ..color = AppColors.progress
        ..strokeWidth = _strokeWidth
        ..strokeCap = StrokeCap.round
        ..style = PaintingStyle.stroke,
    );
  }

  @override
  bool shouldRepaint(covariant _RingPainter old) =>
      old.color != color || old.progress != progress;
}

/// 테스트가 페인터만 따로 그려볼 수 있게 열어 둔다.
///
/// 색 규칙(진행률 아크 = 보라, 테두리 = 상태 색)이 위젯 트리를 띄우지 않고도
/// 검증돼야 한다. 색이 섞이면 사용자가 진행률을 판정 결과로 읽는다.
CustomPainter ringPainterForTest({required Color color, double? progress}) =>
    _RingPainter(color: color, progress: progress);

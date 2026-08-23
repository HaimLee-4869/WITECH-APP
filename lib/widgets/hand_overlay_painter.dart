import 'package:flutter/material.dart';

import '../core/hand_connections.dart';
import '../core/theme.dart';
import '../models/landmark.dart';

/// 손 뼈대 오버레이. (SPEC 8.2)
///
/// **좌표 변환은 전부 이 클래스 안에서만 일어난다.** 카메라 회전과 전면 카메라
/// 미러링 때문에 오버레이가 프리뷰와 어긋나기 쉬운데, 변환 로직이 여러 곳에
/// 흩어지면 원인을 못 찾는다. 변환 파라미터는 전부 생성자로 받는다.
///
/// 여기서 만든 화면 좌표는 **절대 서버로 보내지 않는다.** 전송용 데이터는
/// [HandFrame]의 원본 좌표이며, 이 클래스는 그것을 읽기만 한다. (SPEC 원칙 A)
class HandOverlayPainter extends CustomPainter {
  /// 그릴 프레임. null이면 아무것도 그리지 않는다.
  final HandFrame? frame;

  /// 카메라 센서 회전각(0/90/180/270). 이미지 내용을 시계방향으로 이만큼 돌린
  /// 좌표계로 변환한다.
  final int rotationDegrees;

  /// 전면 카메라 프리뷰는 좌우 반전해서 보여주므로 오버레이도 같이 반전한다.
  ///
  /// **이 반전은 화면 표시 전용이다. 서버로 가는 좌표는 반전하지 않은 원본이다.**
  /// 이 구분을 놓치면 학습 데이터와 인증 데이터의 좌우가 뒤집혀서, 인증률이
  /// 조용히 떨어지고 원인을 찾기 매우 어려워진다. (SPEC 8.2)
  final bool mirror;

  /// 원본 이미지의 가로/세로 비. null이면 캔버스를 꽉 채우도록 늘린다.
  ///
  /// 값이 있으면 [BoxFit.cover]와 동일한 스케일·오프셋을 적용한다. 카메라
  /// 프리뷰를 cover로 깔았을 때 오버레이가 정확히 겹치게 하기 위함이다.
  final double? sourceAspectRatio;

  const HandOverlayPainter({
    required this.frame,
    this.rotationDegrees = 0,
    this.mirror = false,
    this.sourceAspectRatio,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final f = frame;
    // 21점이 다 없는 프레임은 연결선 인덱스가 범위를 벗어나므로 그리지 않는다.
    if (f == null || !f.isComplete) return;

    final points = <Offset>[
      for (final lm in f.landmarks) _project(lm, size),
    ];

    final linePaint = Paint()
      ..color = AppColors.connection
      ..strokeWidth = 2.0
      ..strokeCap = StrokeCap.round
      ..style = PaintingStyle.stroke;

    for (final c in handConnections) {
      canvas.drawLine(points[c[0]], points[c[1]], linePaint);
    }

    final dotPaint = Paint()
      ..color = AppColors.landmark
      ..style = PaintingStyle.fill;

    for (var i = 0; i < points.length; i++) {
      // 손끝은 조금 크게 그려서 손가락 방향이 눈에 들어오게 한다.
      canvas.drawCircle(
        points[i],
        fingertipIndices.contains(i) ? 5.0 : 3.5,
        dotPaint,
      );
    }
  }

  /// 정규화 원본 좌표 → 캔버스 좌표.
  Offset _project(Landmark lm, Size size) {
    var x = lm.x;
    var y = lm.y;

    // 1) 센서 회전 보정. 이미지 내용을 시계방향으로 rotationDegrees 만큼 돌린다.
    switch (rotationDegrees % 360) {
      case 90:
        final tx = x;
        x = 1.0 - y;
        y = tx;
      case 180:
        x = 1.0 - x;
        y = 1.0 - y;
      case 270:
        final tx = x;
        x = y;
        y = 1.0 - tx;
      default:
        break; // 0도는 그대로
    }

    // 2) 표시용 미러링. (서버 전송 좌표에는 적용되지 않는다)
    if (mirror) x = 1.0 - x;

    // 3) 캔버스 크기에 맞추기.
    final aspect = sourceAspectRatio;
    if (aspect == null || size.height == 0) {
      return Offset(x * size.width, y * size.height);
    }

    // BoxFit.cover와 동일한 계산: 짧은 쪽을 채우고 긴 쪽은 잘라낸다.
    final canvasAspect = size.width / size.height;
    if (aspect > canvasAspect) {
      final drawnWidth = size.height * aspect;
      final dx = (size.width - drawnWidth) / 2;
      return Offset(x * drawnWidth + dx, y * size.height);
    }
    final drawnHeight = size.width / aspect;
    final dy = (size.height - drawnHeight) / 2;
    return Offset(x * size.width, y * drawnHeight + dy);
  }

  /// 프레임이나 변환 파라미터가 바뀔 때만 다시 그린다. (SPEC 8.2)
  @override
  bool shouldRepaint(covariant HandOverlayPainter old) {
    return !identical(old.frame, frame) ||
        old.rotationDegrees != rotationDegrees ||
        old.mirror != mirror ||
        old.sourceAspectRatio != sourceAspectRatio;
  }
}

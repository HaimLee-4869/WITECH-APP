/// 이동량 계산. `challenge_response/core/features.py`의 `window_motion` 이식.
///
/// 시작점 대비 **가장 멀리 간 지점**까지의 변위를 손 크기로 나눈다. 마지막
/// 프레임까지의 변위가 아니라 최대 변위인 이유는, 손이 갔다가 돌아오는 궤적에서
/// 마지막 변위가 0에 가까워지기 때문이다.
library;

import 'dart:math' as math;

const double _eps = 1e-9;

/// 한 윈도우의 이동량.
class WindowMotion {
  /// 손 크기로 나눈 최대 변위의 크기. 못 구하면 NaN.
  final double displacementRatio;

  /// 주축 변위 / 부축 변위. 부축이 0에 가까우면 무한대.
  final double axisRatio;

  /// 'x' | 'y' | 'none'.
  final String axis;

  /// 주축의 부호. +1 / -1, 못 구하면 0.
  final int sign;

  /// 윈도우 안에서 손이 잡힌 프레임 비율.
  final double coverage;

  /// 손 크기로 나눈 x/y 변위. 디버그·분석용.
  final double dx;
  final double dy;

  const WindowMotion({
    required this.displacementRatio,
    required this.dx,
    required this.dy,
    required this.axisRatio,
    required this.axis,
    required this.sign,
    required this.coverage,
  });

  /// 판정에 쓸 수 있는 값인지.
  bool get valid => displacementRatio.isFinite;

  static WindowMotion invalid(double coverage) => WindowMotion(
    displacementRatio: double.nan,
    dx: double.nan,
    dy: double.nan,
    axisRatio: double.nan,
    axis: 'none',
    sign: 0,
    coverage: coverage,
  );
}

/// [centers]/[scales]의 `[start, stop)` 구간 이동량.
///
/// [centers]는 손바닥 중심 궤적, [scales]는 프레임별 손 크기다. 손이 없던
/// 프레임은 NaN으로 들어오고 여기서 걸러진다.
WindowMotion windowMotion(
  List<List<double>> centers,
  List<double> scales,
  int start,
  int stop,
) {
  final List<List<double>> points = <List<double>>[];
  final List<double> okScales = <double>[];
  final int total = stop - start;

  for (int i = start; i < stop; i++) {
    final bool ok =
        centers[i][0].isFinite && scales[i].isFinite && scales[i] > 0;
    if (ok) {
      points.add(centers[i]);
      okScales.add(scales[i]);
    }
  }
  final double coverage = total > 0 ? points.length / total : 0.0;

  if (points.length < 2) return WindowMotion.invalid(coverage);

  final double scale = _median(okScales);
  if (!scale.isFinite || scale <= 0) return WindowMotion.invalid(coverage);

  // 시작점에서 가장 멀리 간 지점을 찾는다.
  final List<double> origin = points.first;
  double best = -1.0;
  List<double> peak = <double>[0.0, 0.0];
  for (final List<double> p in points) {
    final double ex = p[0] - origin[0];
    final double ey = p[1] - origin[1];
    final double magnitude = math.sqrt(ex * ex + ey * ey);
    if (magnitude > best) {
      best = magnitude;
      peak = <double>[ex, ey];
    }
  }

  final double dx = peak[0] / scale;
  final double dy = peak[1] / scale;
  final double displacement = math.sqrt(dx * dx + dy * dy);

  final String axis;
  final double primary;
  final double secondary;
  final int sign;
  if (dx.abs() >= dy.abs()) {
    axis = 'x';
    primary = dx.abs();
    secondary = dy.abs();
    sign = dx >= 0 ? 1 : -1;
  } else {
    axis = 'y';
    primary = dy.abs();
    secondary = dx.abs();
    sign = dy >= 0 ? 1 : -1;
  }
  final double axisRatio =
      secondary > _eps ? primary / secondary : double.infinity;

  return WindowMotion(
    displacementRatio: displacement,
    dx: dx,
    dy: dy,
    axisRatio: axisRatio,
    axis: axis,
    sign: sign,
    coverage: coverage,
  );
}

/// numpy의 `np.median`과 같은 규칙(짝수 개면 가운데 둘의 평균).
double _median(List<double> values) {
  final List<double> sorted = List<double>.of(values)..sort();
  final int n = sorted.length;
  if (n == 0) return double.nan;
  if (n.isOdd) return sorted[n ~/ 2];
  return (sorted[n ~/ 2 - 1] + sorted[n ~/ 2]) / 2.0;
}

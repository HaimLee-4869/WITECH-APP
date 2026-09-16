/// `challenge_response/core/features.py`의 `window_motion` 이식 검증.
///
/// 이동 판정 3단계(변위 / 주축 / 부호) 중 1·2단계의 원재료를 만드는 함수다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:signid/challenge/geometry.dart';
import 'package:signid/challenge/window_motion.dart';

import 'synth.dart';

/// 시퀀스를 궤적(손바닥 중심 / 손 크기)으로 바꾼다.
({List<List<double>> centers, List<double> scales}) tracks(List<Coords> seq) => (
      centers: <List<double>>[for (final Coords f in seq) palmCenter(f)],
      scales: <double>[for (final Coords f in seq) handScale(f)],
    );

WindowMotion motionOf(List<Coords> seq) {
  final t = tracks(seq);
  return windowMotion(t.centers, t.scales, 0, t.scales.length);
}

void main() {
  test('오른쪽으로 손 크기의 2배 움직이면 변위비가 2에 가깝다', () {
    final List<Coords> seq = makeSequence(
      start: <double>[0.0, 0.0, 0.0],
      end: <double>[2.0 * handScale(makeHand()), 0.0, 0.0],
      frames: 12,
    );
    final WindowMotion m = motionOf(seq);
    expect(m.displacementRatio, closeTo(2.0, 1e-6));
    expect(m.axis, 'x');
    expect(m.sign, 1);
  });

  test('왼쪽 이동은 x축 음의 부호', () {
    final WindowMotion m = motionOf(makeSequence(
      start: <double>[0.0, 0.0, 0.0],
      end: <double>[-1.5, 0.0, 0.0],
      frames: 12,
    ));
    expect(m.axis, 'x');
    expect(m.sign, -1);
  });

  test('아래 이동은 y축 양의 부호 (화면 좌표는 y가 아래로 증가)', () {
    final WindowMotion m = motionOf(makeSequence(
      start: <double>[0.0, 0.0, 0.0],
      end: <double>[0.0, 1.5, 0.0],
      frames: 12,
    ));
    expect(m.axis, 'y');
    expect(m.sign, 1);
  });

  test('갔다가 돌아와도 최대 변위를 쓴다 (마지막 위치가 아니다)', () {
    final List<Coords> out = makeSequence(
      start: <double>[0.0, 0.0, 0.0],
      end: <double>[2.0, 0.0, 0.0],
      frames: 8,
    );
    final List<Coords> back = makeSequence(
      start: <double>[2.0, 0.0, 0.0],
      end: <double>[0.0, 0.0, 0.0],
      frames: 8,
    );
    final WindowMotion m = motionOf(<Coords>[...out, ...back]);
    // 시작과 끝이 같은 자리인데도 변위가 잡힌다.
    expect(m.displacementRatio, greaterThan(1.0));
  });

  test('대각선 이동은 주축비가 1에 가깝다', () {
    final WindowMotion m = motionOf(makeSequence(
      start: <double>[0.0, 0.0, 0.0],
      end: <double>[1.5, 1.5, 0.0],
      frames: 12,
    ));
    expect(m.axisRatio, closeTo(1.0, 1e-6));
  });

  test('순수 축 이동은 주축비가 무한대 (부축 변위 0)', () {
    final WindowMotion m = motionOf(makeSequence(
      start: <double>[0.0, 0.0, 0.0],
      end: <double>[1.5, 0.0, 0.0],
      frames: 12,
    ));
    expect(m.axisRatio, double.infinity);
  });

  test('유효 프레임이 2개 미만이면 판정 불가', () {
    final t = tracks(makeSequence(
      start: <double>[0.0, 0.0, 0.0],
      end: <double>[1.0, 0.0, 0.0],
      frames: 6,
    ));
    for (int i = 1; i < t.scales.length; i++) {
      t.scales[i] = double.nan;
    }
    final WindowMotion m = windowMotion(t.centers, t.scales, 0, t.scales.length);
    expect(m.valid, isFalse);
    expect(m.axis, 'none');
  });

  test('손이 잡힌 비율(coverage)을 알려준다', () {
    final t = tracks(makeSequence(
      start: <double>[0.0, 0.0, 0.0],
      end: <double>[1.0, 0.0, 0.0],
      frames: 10,
    ));
    for (int i = 0; i < 4; i++) {
      t.scales[i] = double.nan;
    }
    final WindowMotion m = windowMotion(t.centers, t.scales, 0, 10);
    expect(m.coverage, closeTo(0.6, 1e-9));
    expect(m.valid, isTrue);
  });

  test('손 크기로 나누므로 카메라 거리에 불변이다', () {
    double ratioAt(double scale) => motionOf(makeSequence(
          start: <double>[0.0, 0.0, 0.0],
          end: <double>[2.0 * scale, 0.0, 0.0],
          frames: 12,
          scale: scale,
        )).displacementRatio;
    expect(ratioAt(1.0), closeTo(ratioAt(0.35), 1e-6));
  });
}

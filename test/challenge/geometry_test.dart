/// `challenge_response/tests/test_geometry.py`의 이식.
///
/// 알려진 좌표에서 각도가 맞는지, 정규화가 거리 변화에 불변인지.
library;

import 'dart:math' as math;

import 'package:flutter_test/flutter_test.dart';
import 'package:signid/challenge/geometry.dart';

import 'synth.dart';

/// Python 쪽 `finger_angles(...)[name]`에 해당한다.
double _angleOf(Coords hand, String finger) =>
    fingerAngles(hand)[kFingerNames.indexOf(finger)];

Coords _zeros() => <List<double>>[
      for (int i = 0; i < 21; i++) <double>[0.0, 0.0, 0.0],
    ];

void main() {
  group('angleAt', () {
    test('직각', () {
      expect(
        angleAt(<double>[1, 0, 0], <double>[0, 0, 0], <double>[0, 1, 0]),
        closeTo(90.0, 1e-9),
      );
    });

    test('일직선은 180도', () {
      expect(
        angleAt(<double>[-1, 0, 0], <double>[0, 0, 0], <double>[1, 0, 0]),
        closeTo(180.0, 1e-9),
      );
    });

    test('완전히 접히면 0도', () {
      expect(
        angleAt(<double>[1, 0, 0], <double>[0, 0, 0], <double>[2, 0, 0]),
        closeTo(0.0, 1e-6),
      );
    });

    test('60도', () {
      final List<double> a = <double>[
        math.cos(60.0 * math.pi / 180.0),
        math.sin(60.0 * math.pi / 180.0),
        0.0,
      ];
      expect(
        angleAt(a, <double>[0, 0, 0], <double>[1, 0, 0]),
        closeTo(60.0, 1e-9),
      );
    });

    test('길이가 0이면 NaN (계산 불가를 0도로 위장하지 않는다)', () {
      expect(
        angleAt(<double>[0, 0, 0], <double>[0, 0, 0], <double>[1, 0, 0]).isNaN,
        isTrue,
      );
    });
  });

  group('fingerAngles', () {
    for (final double target in <double>[180.0, 160.0, 120.0, 90.0, 40.0]) {
      test('합성 손의 목표 각도 $target도가 그대로 나온다', () {
        final List<double> angles = fingerAngles(makeHand(uniformAngle: target));
        for (final double a in angles) {
          expect(a, closeTo(target, 1e-6));
        }
      });
    }

    test('반환 순서가 kFingerNames와 같다', () {
      final Coords hand = makeHand(angles: <String, double>{
        'thumb': 100.0,
        'index': 180.0,
        'middle': 170.0,
        'ring': 60.0,
        'pinky': 50.0,
      });
      expect(kFingerNames, <String>['thumb', 'index', 'middle', 'ring', 'pinky']);
      final List<double> angles = fingerAngles(hand);
      for (final (int i, double expected)
          in <double>[100.0, 180.0, 170.0, 60.0, 50.0].indexed) {
        expect(angles[i], closeTo(expected, 1e-6));
      }
    });

    test('손 크기와 위치가 바뀌어도 각도는 같다', () {
      final Coords near = makeHand(uniformAngle: 150.0);
      final Coords far = makeHand(
        uniformAngle: 150.0,
        scale: 0.3,
        center: <double>[0.4, 0.7, 0.1],
      );
      final List<double> a = fingerAngles(near);
      final List<double> b = fingerAngles(far);
      for (int i = 0; i < a.length; i++) {
        expect(a[i], closeTo(b[i], 1e-6));
      }
    });
  });

  group('handScale', () {
    test('손목-중지 MCP 거리다', () {
      final Coords hand = makeHand(scale: 2.0);
      final List<double> a = hand[kMiddleMcp];
      final List<double> b = hand[kWrist];
      final double expected = math.sqrt(
        math.pow(a[0] - b[0], 2) + math.pow(a[1] - b[1], 2) + math.pow(a[2] - b[2], 2),
      );
      expect(handScale(hand), closeTo(expected, 1e-9));
    });

    test('손 크기에 비례한다', () {
      expect(
        handScale(makeHand(scale: 3.0)),
        closeTo(3.0 * handScale(makeHand(scale: 1.0)), 1e-9),
      );
    });

    test('카메라가 멀어져도 (변위/손크기)는 같다', () {
      final List<double> ratios = <double>[];
      for (final double scale in <double>[1.0, 0.4]) {
        final Coords a = makeHand(scale: scale);
        final Coords b = makeHand(
          scale: scale,
          center: <double>[2.0 * scale, 0.0, 0.0],
        );
        final List<double> ca = palmCenter(a);
        final List<double> cb = palmCenter(b);
        final double disp = math.sqrt(
          math.pow(cb[0] - ca[0], 2) +
              math.pow(cb[1] - ca[1], 2) +
              math.pow(cb[2] - ca[2], 2),
        );
        ratios.add(disp / handScale(a));
      }
      expect(ratios[0], closeTo(ratios[1], 1e-9));
    });
  });

  group('palmCenter', () {
    test('손바닥 점 5개의 평균이다', () {
      final Coords hand = makeHand();
      final List<double> expected = <double>[0.0, 0.0, 0.0];
      for (final int i in kPalmPoints) {
        for (int axis = 0; axis < 3; axis++) {
          expected[axis] += hand[i][axis] / kPalmPoints.length;
        }
      }
      final List<double> got = palmCenter(hand);
      for (int axis = 0; axis < 3; axis++) {
        expect(got[axis], closeTo(expected[axis], 1e-9));
      }
    });

    test('손끝이 움직여도 중심은 그대로다', () {
      final List<double> open = palmCenter(makeHand(uniformAngle: 180.0));
      final List<double> closed = palmCenter(makeHand(uniformAngle: 30.0));
      for (int axis = 0; axis < 3; axis++) {
        expect(open[axis], closeTo(closed[axis], 1e-9));
      }
    });
  });

  group('toIsotropic', () {
    test('종횡비를 반영한다', () {
      final Coords lm = _zeros();
      lm[0] = <double>[0.5, 0.5, 0.1];
      final List<double> got = toIsotropic(lm, 1920, 1080)[0];
      expect(got[0], closeTo(960.0, 1e-9));
      expect(got[1], closeTo(540.0, 1e-9));
      expect(got[2], closeTo(192.0, 1e-9));
    });

    test('16:9에서 각도 왜곡을 바로잡는다', () {
      final Coords normalized = _zeros();
      final List<int> j = kFingerJoints['index']!;
      // 픽셀 기준으로 정확히 45도가 되도록 배치한 뒤 정규화한 값
      normalized[j[1]] = <double>[0.5, 0.5, 0.0];
      normalized[j[0]] = <double>[0.5 + 100.0 / 1920.0, 0.5, 0.0];
      normalized[j[2]] = <double>[
        0.5 + 100.0 / 1920.0,
        0.5 + 100.0 / 1080.0,
        0.0,
      ];
      final double raw = _angleOf(normalized, 'index');
      final double fixed = _angleOf(toIsotropic(normalized, 1920, 1080), 'index');
      expect(fixed, closeTo(45.0, 1e-6));
      expect((raw - 45.0).abs(), greaterThan(1.0));
    });

    test('입력을 바꾸지 않는다', () {
      final Coords lm = _zeros();
      lm[0] = <double>[0.5, 0.5, 0.5];
      toIsotropic(lm, 100, 200);
      expect(lm[0], <double>[0.5, 0.5, 0.5]);
    });
  });

  group('extensionFlags', () {
    test('엄지는 다른 임계값을 쓴다', () {
      final List<double> angles = <double>[155.0, 155.0, 170.0, 90.0, 90.0];
      final r = extensionFlags(angles, 150.0, 160.0);
      expect(r.flags, <bool>[true, false, true, false, false]);
      expect(r.margins[0], closeTo(5.0, 1e-9));
      expect(r.margins[1], closeTo(-5.0, 1e-9));
    });

    test('NaN 각도는 펴진 것이 아니고 여유도 NaN이다', () {
      final r = extensionFlags(
        <double>[double.nan, 180.0, 180.0, 180.0, 180.0],
        150.0,
        160.0,
      );
      expect(r.flags[0], isFalse);
      expect(r.margins[0].isNaN, isTrue);
    });
  });

  group('fingertipWristRatio', () {
    test('손 크기·위치에 불변이다', () {
      final double near = fingertipWristRatio(makeHand(uniformAngle: 60.0));
      final double far = fingertipWristRatio(makeHand(
        uniformAngle: 60.0,
        scale: 0.3,
        center: <double>[0.7, 0.4, 0.2],
      ));
      expect(near, closeTo(far, 1e-9));
    });

    test('꽉 쥘수록 작다 — FIST 게이트의 전제', () {
      expect(
        fingertipWristRatio(makeHand(uniformAngle: 20.0)),
        lessThan(fingertipWristRatio(makeHand(uniformAngle: 80.0))),
      );
      expect(
        fingertipWristRatio(makeHand(uniformAngle: 80.0)),
        lessThan(fingertipWristRatio(makeHand(uniformAngle: 180.0))),
      );
    });

    test('깊이(z)는 보지 않는다', () {
      final Coords hand = makeHand(uniformAngle: 60.0);
      final Coords deep = <List<double>>[
        for (final (int i, List<double> p) in hand.indexed)
          <double>[p[0], p[1], p[2] + 5.0 * i / 20.0],
      ];
      expect(
        fingertipWristRatio(deep),
        closeTo(fingertipWristRatio(hand), 1e-9),
      );
    });

    test('손 크기가 0이면 NaN', () {
      expect(fingertipWristRatio(_zeros()).isNaN, isTrue);
    });
  });
}

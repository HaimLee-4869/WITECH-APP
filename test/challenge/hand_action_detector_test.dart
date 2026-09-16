/// `challenge_response/tests/test_hand_actions.py`의 이식.
///
/// 패턴 매칭이 핵심이다. 선언한 4개 조합에 **정확히** 맞을 때만 라벨을 준다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:signid/challenge/challenge_config.dart';
import 'package:signid/challenge/geometry.dart';
import 'package:signid/challenge/hand_action_detector.dart';

import 'config_fixture.dart';
import 'synth.dart';

Coords handFor(List<bool> pattern, {bool thumbExtended = true, double scale = 1.0, List<double> center = const <double>[0, 0, 0]}) {
  return makePatternHand(
    extended: <String, bool>{
      'thumb': thumbExtended,
      for (final (int i, String name) in kNonThumbFingers.indexed)
        name: pattern[i],
    },
    extendedAngle: kExtendedAngle,
    curledAngle: kCurledAngle,
    scale: scale,
    center: center,
  );
}

Coords fistHand() => handFor(kShapePatterns['FIST']!);

void main() {
  final HandActionDetector detector = HandActionDetector(synthConfig);

  group('선언한 패턴', () {
    for (final MapEntry<String, List<bool>> e in kShapePatterns.entries) {
      test('${e.key}은 자기 라벨을 받는다', () {
        expect(detector.detect(handFor(e.value)).label, e.key);
      });
    }

    test('선언한 4개 패턴은 서로 다르다', () {
      final Set<String> seen = <String>{};
      for (final List<bool> p in kShapePatterns.values) {
        expect(seen.add(p.join(',')), isTrue, reason: '중복 패턴 $p');
      }
    });
  });

  group('선언하지 않은 패턴은 UNKNOWN', () {
    final List<(String, List<bool>)> cases = <(String, List<bool>)>[
      ('세 손가락', <bool>[true, true, true, false]),
      ('검지+약지', <bool>[true, false, true, false]),
      ('검지+새끼', <bool>[true, false, false, true]),
      ('중지만', <bool>[false, true, false, false]),
      ('약지+새끼', <bool>[false, false, true, true]),
      ('엄지 뺀 넷 중 셋', <bool>[false, true, true, true]),
    ];
    for (final (String name, List<bool> flags) in cases) {
      test(name, () {
        expect(detector.detect(handFor(flags)).label, kUnknownShape);
      });
    }

    test('세 손가락이 OPEN_PALM으로 새지 않는다', () {
      final ShapeResult r = detector.detect(handFor(<bool>[true, true, true, false]));
      expect(r.label, kUnknownShape);
      expect(r.label, isNot('OPEN_PALM'));
    });

    test('검지+약지가 TWO_FINGERS로 새지 않는다', () {
      expect(
        detector.detect(handFor(<bool>[true, false, true, false])).label,
        kUnknownShape,
      );
    });
  });

  group('불변성', () {
    for (final bool thumb in <bool>[true, false]) {
      test('엄지(${thumb ? '펴짐' : '접힘'})는 라벨을 바꾸지 않는다', () {
        expect(
          detector
              .detect(handFor(kShapePatterns['TWO_FINGERS']!, thumbExtended: thumb))
              .label,
          'TWO_FINGERS',
        );
      });
    }

    test('손 크기·위치가 바뀌어도 라벨과 신뢰도가 같다', () {
      final ShapeResult near = detector.detect(handFor(kShapePatterns['INDEX']!));
      final ShapeResult far = detector.detect(handFor(
        kShapePatterns['INDEX']!,
        scale: 0.25,
        center: <double>[0.8, 0.6, 0.2],
      ));
      expect(near.label, 'INDEX');
      expect(far.label, 'INDEX');
      expect(near.confidence, closeTo(far.confidence, 1e-9));
    });
  });

  group('신뢰도', () {
    test('임계값에서 멀면 높다', () {
      final ShapeResult r = detector.detect(handFor(kShapePatterns['OPEN_PALM']!));
      final double margin = kExtendedAngle - synthConfig.fingerExtendedAngle.others;
      final double expected =
          (margin / synthConfig.shapeConfidenceMarginDeg).clamp(0.0, 1.0);
      expect(r.confidence, closeTo(expected, 1e-9));
      expect(r.confidence, greaterThan(0.5));
    });

    test('1.0에서 포화한다', () {
      expect(
        detector.detect(makeHand(uniformAngle: 180.0)).confidence,
        closeTo(1.0, 1e-9),
      );
    });

    test('경계에 걸친 손가락이 있으면 떨어진다', () {
      final double threshold = synthConfig.fingerExtendedAngle.others;
      final Coords hand = makeHand(angles: <String, double>{
        for (final String n in kFingerNames) n: kExtendedAngle,
        'pinky': threshold + 1.0,
      });
      final ShapeResult r = detector.detect(hand);
      expect(r.label, 'OPEN_PALM');
      expect(r.confidence, lessThan(0.2));
    });

    test('가장 약한 손가락이 전체 신뢰도를 정한다', () {
      final double margin = synthConfig.shapeConfidenceMarginDeg;
      final double threshold = synthConfig.fingerExtendedAngle.others;
      final Coords hand = makeHand(angles: <String, double>{
        for (final String n in kFingerNames) n: threshold + margin,
        'ring': threshold + margin / 2.0,
      });
      expect(detector.detect(hand).confidence, closeTo(0.5, 1e-9));
    });
  });

  group('읽지 못한 랜드마크', () {
    test('전부 NaN이면 UNKNOWN이고 신뢰도 0 — FIST로 새면 안 된다', () {
      final Coords nan = <List<double>>[
        for (int i = 0; i < 21; i++)
          <double>[double.nan, double.nan, double.nan],
      ];
      final ShapeResult r = detector.detect(nan);
      expect(r.label, kUnknownShape);
      expect(r.confidence, closeTo(0.0, 1e-9));
    });

    test('한 손가락만 못 읽어도 패턴을 확정하지 않는다', () {
      final Coords hand = handFor(kShapePatterns['OPEN_PALM']!);
      hand[8] = <double>[double.nan, double.nan, double.nan]; // 검지 TIP
      expect(detector.detect(hand).label, kUnknownShape);
    });

    test('디버그용으로 flags와 angles를 돌려준다', () {
      final ShapeResult r = detector.detect(handFor(kShapePatterns['FIST']!));
      expect(r.flags.length, kFingerNames.length);
      expect(r.angles.length, kFingerNames.length);
      expect(r.flags.sublist(1).every((bool f) => !f), isTrue);
    });
  });

  group('prepare (좌표계)', () {
    test('image_iso는 화면 크기를 요구한다', () {
      final HandActionDetector d = HandActionDetector(
        configWith(<String, dynamic>{'angleSpace': 'image_iso'}),
      );
      expect(
        () => d.prepare(makeHand()),
        throwsA(isA<ArgumentError>()),
      );
    });

    test('image_iso는 종횡비를 보정한다', () {
      final HandActionDetector d = HandActionDetector(
        configWith(<String, dynamic>{'angleSpace': 'image_iso'}),
      );
      final Coords lm = <List<double>>[
        for (int i = 0; i < 21; i++) <double>[0.0, 0.0, 0.0],
      ];
      lm[0] = <double>[0.5, 0.5, 0.0];
      final List<double> got = d.prepare(lm, width: 1920, height: 1080)[0];
      expect(got[0], closeTo(960.0, 1e-9));
      expect(got[1], closeTo(540.0, 1e-9));
    });
  });

  group('FIST 손끝 거리 게이트', () {
    test('null이면 게이트를 걸지 않는다 (도출 실패 = 게이트 없음)', () {
      expect(synthConfig.fistMaxTipWristRatio, isNull);
      expect(detector.detect(fistHand()).label, 'FIST');
    });

    test('손끝이 손목에 가까우면 통과한다', () {
      final double ratio = fingertipWristRatio(fistHand());
      final HandActionDetector d = HandActionDetector(
        configWith(<String, dynamic>{
          'angleSpace': 'world',
          'fingerExtendedAngle': <String, dynamic>{'thumb': 150.0, 'others': 160.0},
          'shapeConfidenceMarginDeg': 20.0,
          'fistMaxTipWristRatio': ratio + 0.05,
        }),
      );
      final ShapeResult r = d.detect(fistHand());
      expect(r.label, 'FIST');
      expect(r.tipWristRatio, closeTo(ratio, 1e-9));
    });

    test('각도는 FIST지만 손끝이 멀면 반쯤 쥔 손이다', () {
      final double ratio = fingertipWristRatio(fistHand());
      final HandActionDetector d = HandActionDetector(
        configWith(<String, dynamic>{
          'angleSpace': 'world',
          'fingerExtendedAngle': <String, dynamic>{'thumb': 150.0, 'others': 160.0},
          'shapeConfidenceMarginDeg': 20.0,
          'fistMaxTipWristRatio': ratio - 0.05,
        }),
      );
      expect(d.detect(fistHand()).label, kUnknownShape);
    });

    test('경계는 배타적이다 (같으면 거절)', () {
      final double ratio = fingertipWristRatio(fistHand());
      final HandActionDetector d = HandActionDetector(
        configWith(<String, dynamic>{
          'angleSpace': 'world',
          'fingerExtendedAngle': <String, dynamic>{'thumb': 150.0, 'others': 160.0},
          'shapeConfidenceMarginDeg': 20.0,
          'fistMaxTipWristRatio': ratio,
        }),
      );
      expect(d.detect(fistHand()).label, kUnknownShape);
    });

    for (final String label in <String>['OPEN_PALM', 'INDEX', 'TWO_FINGERS']) {
      test('$label에는 게이트를 걸지 않는다', () {
        final HandActionDetector d = HandActionDetector(
          configWith(<String, dynamic>{
            'angleSpace': 'world',
            'fingerExtendedAngle': <String, dynamic>{'thumb': 150.0, 'others': 160.0},
            'shapeConfidenceMarginDeg': 20.0,
            'fistMaxTipWristRatio': 0.01,
          }),
        );
        expect(d.detect(handFor(kShapePatterns[label]!)).label, label);
      });
    }
  });
}

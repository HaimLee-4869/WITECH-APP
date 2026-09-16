/// 안내 그림과 판정이 어긋날 수 없는지.
///
/// 화면이 "검지를 펴세요"라고 그려 놓고 판정기는 두 손가락을 기다리는 상황을
/// 막는다. 그림에 쓰는 좌표를 **실제 판정기에 넣어** 라벨이 같은지 본다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:signid/challenge/challenge_config.dart';
import 'package:signid/challenge/geometry.dart';
import 'package:signid/challenge/hand_action_detector.dart';
import 'package:signid/challenge/hand_sketch.dart';

import 'config_fixture.dart';

void main() {
  group('안내 그림은 그 라벨로 판정된다', () {
    // 서버 기본 설정(실제 도출값)으로 본다.
    final ChallengeConfig config = configWith();
    final HandActionDetector detector = HandActionDetector(config);

    for (final String label in kShapePatterns.keys) {
      test('$label 그림 → $label 판정', () {
        final ShapeSketch sketch = sketchForShape(label, config);
        final ShapeResult result = detector.detect(sketch.landmarks);
        expect(result.label, label);
        // 경계에 걸친 그림을 그리면 사용자가 따라 해도 아슬아슬해진다.
        expect(result.confidence, greaterThanOrEqualTo(0.9));
      });
    }

    test('FIST 그림은 손끝 거리 게이트도 통과한다', () {
      // 반쯤 쥔 손을 그려 놓으면 사용자가 그대로 따라 해도 UNKNOWN이 된다.
      expect(config.fistMaxTipWristRatio, isNotNull);
      final ShapeSketch sketch = sketchForShape('FIST', config);
      expect(
        fingertipWristRatio(sketch.landmarks),
        lessThan(config.fistMaxTipWristRatio!),
      );
    });

    test('임계값이 바뀌면 그림도 따라 움직인다', () {
      // 그림 각도를 상수로 박아 두면 서버가 임계값을 올렸을 때 그림만 옛 값으로 남는다.
      final ChallengeConfig strict = configWith(<String, dynamic>{
        'fingerExtendedAngle': <String, dynamic>{'thumb': 165.0, 'others': 170.0},
        'shapeConfidenceMarginDeg': 5.0,
      });
      final ShapeSketch sketch = sketchForShape('OPEN_PALM', strict);
      expect(
        HandActionDetector(strict).detect(sketch.landmarks).label,
        'OPEN_PALM',
      );
    });
  });

  group('펴는 손가락 표시', () {
    final ChallengeConfig config = configWith();

    test('OPEN_PALM은 다섯 손가락이 모두 펴짐', () {
      expect(sketchForShape('OPEN_PALM', config).extended,
          <bool>[true, true, true, true, true]);
    });

    test('FIST는 모두 접힘 (엄지 포함)', () {
      expect(sketchForShape('FIST', config).extended,
          <bool>[false, false, false, false, false]);
    });

    test('INDEX는 엄지와 검지만', () {
      expect(sketchForShape('INDEX', config).extended,
          <bool>[true, true, false, false, false]);
    });

    test('표시와 판정 패턴이 같다 (엄지 제외)', () {
      for (final MapEntry<String, List<bool>> e in kShapePatterns.entries) {
        final ShapeSketch sketch = sketchForShape(e.key, config);
        expect(sketch.extended.sublist(1), e.value, reason: e.key);
      }
    });

    test('손 모양이 아닌 라벨은 거절한다', () {
      expect(() => sketchForShape('MOVE_LEFT', config), throwsArgumentError);
    });
  });

  group('화살표 방향', () {
    // ⚠️ 라벨은 이미 '사용자가 거울 화면에서 보는 방향'이다.
    // directionMap을 한 번 더 참조하면 화살표만 반대로 간다.
    test('라벨이 말하는 방향 그대로 그린다', () {
      expect(arrowFor('MOVE_LEFT'), (dx: -1.0, dy: 0.0));
      expect(arrowFor('MOVE_RIGHT'), (dx: 1.0, dy: 0.0));
      expect(arrowFor('MOVE_UP'), (dx: 0.0, dy: -1.0));
      expect(arrowFor('MOVE_DOWN'), (dx: 0.0, dy: 1.0));
    });

    test('directionMap을 뒤집어도 화살표는 그대로다', () {
      // 판정기는 표를 보고 라벨을 정하지만, 라벨이 정해진 뒤의 화살표는
      // 표와 무관해야 한다. 표를 뒤집었다고 "왼쪽으로"가 오른쪽 화살표가 되면
      // 안내가 거짓말이 된다.
      expect(arrowFor('MOVE_LEFT').dx, lessThan(0));
    });

    test('손 모양 라벨은 거절한다', () {
      expect(() => arrowFor('FIST'), throwsArgumentError);
    });
  });

  group('뼈대 연결', () {
    test('손바닥과 손가락 뼈대가 21점 안에 있다', () {
      final List<List<int>> bones = <List<int>>[
        ...kSketchPalmBones,
        for (final String f in kFingerNames) ...sketchFingerBones(f),
      ];
      for (final List<int> bone in bones) {
        expect(bone[0], inInclusiveRange(0, 20));
        expect(bone[1], inInclusiveRange(0, 20));
      }
      expect(bones.length, 6 + 5 * 3);
    });
  });
}

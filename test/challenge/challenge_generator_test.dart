/// `challenge_response/tests/test_challenge_generator.py`의 이식.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:signid/challenge/challenge_config.dart';
import 'package:signid/challenge/challenge_generator.dart';

import 'config_fixture.dart';

const int kTrials = 400;

void main() {
  final ChallengeConfig config = configWith();
  final ChallengeGenerator generator = ChallengeGenerator();

  Challenge draw() => generator.generate(config);

  test('설정이 정한 단계 수만큼 나온다', () {
    expect(draw().actions.length, config.steps.total);
    expect(config.steps.total, 3); // 기본값 확인
  });

  test('손 모양 2개는 항상 서로 다르다', () {
    for (int i = 0; i < kTrials; i++) {
      final Challenge c = draw();
      final List<String> shapes =
          c.actions.where(c.isShapeAction).toList();
      expect(shapes.length, config.steps.numShapes);
      expect(shapes.toSet().length, config.steps.numShapes);
    }
  });

  test('이동은 정확히 1개다', () {
    for (int i = 0; i < kTrials; i++) {
      final Challenge c = draw();
      expect(c.actions.where(c.isMoveAction).length, config.steps.numMoves);
    }
  });

  test('선언한 풀에서만 나온다', () {
    final Set<String> pool = <String>{...config.shapePool, ...config.movePool};
    for (int i = 0; i < kTrials; i++) {
      for (final String action in draw().actions) {
        expect(pool, contains(action));
      }
    }
  });

  test('challengeId는 UUID v4 형식이다', () {
    final String id = draw().challengeId;
    expect(
      RegExp(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
          .hasMatch(id),
      isTrue,
      reason: id,
    );
  });

  test('challengeId는 중복되지 않는다', () {
    final Set<String> ids = <String>{
      for (int i = 0; i < kTrials; i++) draw().challengeId,
    };
    expect(ids.length, kTrials);
  });

  test('생성 시각을 기록한다', () {
    expect(draw().createdAt.isUtc, isTrue);
  });

  test('이동 단계가 모든 위치에 나타난다 (순서를 섞는다)', () {
    // 이동이 항상 마지막이면 섞기가 동작하지 않는 것이다.
    final Set<int> positions = <int>{};
    for (int i = 0; i < kTrials; i++) {
      final Challenge c = draw();
      positions.add(c.actions.indexWhere(c.isMoveAction));
    }
    expect(positions, <int>{0, 1, 2});
  });

  test('손 모양 조합이 전부 나온다', () {
    final Set<String> seen = <String>{};
    for (int i = 0; i < kTrials * 4; i++) {
      final Challenge c = draw();
      final List<String> shapes = c.actions.where(c.isShapeAction).toList()..sort();
      seen.add(shapes.join(','));
    }
    final Set<String> expected = <String>{
      for (final String a in config.shapePool)
        for (final String b in config.shapePool)
          if (a != b) (<String>[a, b]..sort()).join(','),
    };
    expect(seen, expected);
    expect(expected.length, 6); // 4개 중 2개 = 6조합
  });

  test('풀보다 많이 뽑으려 하면 거절한다', () {
    final ChallengeConfig tooMany = configWith(<String, dynamic>{
      'shapePool': <String>['OPEN_PALM', 'FIST'],
      'steps': <String, dynamic>{'numShapes': 3, 'numMoves': 1},
    });
    expect(
      () => generator.generate(tooMany),
      throwsA(isA<ArgumentError>()),
    );
  });

  test('단계 구성을 서버가 바꾸면 따라간다 (3단계 → 2단계)', () {
    final ChallengeConfig two = configWith(<String, dynamic>{
      'steps': <String, dynamic>{'numShapes': 1, 'numMoves': 1},
    });
    for (int i = 0; i < 50; i++) {
      final Challenge c = generator.generate(two);
      expect(c.actions.length, 2);
      expect(c.actions.where(c.isShapeAction).length, 1);
      expect(c.actions.where(c.isMoveAction).length, 1);
    }
  });
}

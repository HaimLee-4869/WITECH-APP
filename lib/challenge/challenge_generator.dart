/// 무작위 Challenge 생성. `challenge_response/core/challenge_generator.py`의 이식.
///
/// - `Random()`이 아니라 `Random.secure()`를 쓴다. 기본 난수는 시드 예측이 가능해
///   재현 공격에 취약하다 (Python 쪽이 `secrets`를 쓰는 것과 같은 이유다).
/// - 손 모양은 서로 달라야 한다. 같은 모양이 연속되면 사용자가 손을 그대로 두어도
///   두 단계를 통과해버린다.
library;

import 'dart:math';

import 'challenge_config.dart';

class Challenge {
  final String challengeId;

  /// 수행할 동작 순서. 손 모양과 이동이 섞여 있다.
  final List<String> actions;

  final DateTime createdAt;
  final List<String> shapePool;
  final List<String> movePool;

  const Challenge({
    required this.challengeId,
    required this.actions,
    required this.createdAt,
    required this.shapePool,
    required this.movePool,
  });

  int get length => actions.length;

  bool isShapeAction(String action) => shapePool.contains(action);

  bool isMoveAction(String action) => movePool.contains(action);
}

class ChallengeGenerator {
  final Random _random;

  /// [random]을 주면 테스트에서 순서를 고정할 수 있다. 운영에서는 비워 둔다.
  ChallengeGenerator({Random? random}) : _random = random ?? Random.secure();

  /// 설정이 정한 개수만큼 뽑아 순서를 섞는다.
  Challenge generate(ChallengeConfig config) {
    final List<String> shapes =
        _sampleDistinct(config.shapePool, config.steps.numShapes);
    final List<String> moves =
        _sampleDistinct(config.movePool, config.steps.numMoves);
    return Challenge(
      challengeId: _uuidV4(),
      actions: _shuffle(<String>[...shapes, ...moves]),
      createdAt: DateTime.now().toUtc(),
      shapePool: List<String>.unmodifiable(config.shapePool),
      movePool: List<String>.unmodifiable(config.movePool),
    );
  }

  /// 중복 없이 k개를 뽑는다.
  List<String> _sampleDistinct(List<String> pool, int k) {
    if (k > pool.length) {
      throw ArgumentError('풀(${pool.length})보다 많은 $k개를 뽑을 수 없다');
    }
    final List<String> remaining = List<String>.of(pool);
    final List<String> picked = <String>[];
    for (int i = 0; i < k; i++) {
      picked.add(remaining.removeAt(_random.nextInt(remaining.length)));
    }
    return picked;
  }

  /// Fisher-Yates.
  List<String> _shuffle(List<String> items) {
    final List<String> out = List<String>.of(items);
    for (int i = out.length - 1; i > 0; i--) {
      final int j = _random.nextInt(i + 1);
      final String tmp = out[i];
      out[i] = out[j];
      out[j] = tmp;
    }
    return out;
  }

  String _uuidV4() {
    final List<int> bytes =
        List<int>.generate(16, (_) => _random.nextInt(256));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    final String hex =
        bytes.map((int b) => b.toRadixString(16).padLeft(2, '0')).join();
    return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-'
        '${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
  }
}

/// `challenge_response/tests/test_movements.py`의 이식.
///
/// 촬영 방식 판별(`move_style`) 관련 6개는 옮기지 않았다. 오프라인 임계값 도출
/// 스크립트(04/05)만 쓰는 함수라 앱 판정 경로에 없다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:signid/challenge/challenge_config.dart';
import 'package:signid/challenge/geometry.dart';
import 'package:signid/challenge/movement_detector.dart';

import 'config_fixture.dart';
import 'synth.dart';

const int kFrames = 20;

/// Python 테스트와 같은 임계값. 합성 시퀀스로 관문 경계를 보기 위한 값이다.
ChallengeConfig moveConfig({
  String coordinateFrame = 'raw',
  Map<String, dynamic>? directionMap,
}) =>
    configWith(<String, dynamic>{
      'coordinateFrame': coordinateFrame,
      'movement': <String, dynamic>{
        'windowMs': 1000,
        'minDisplacementRatio': 1.2,
        'axisDominanceRatio': 2.0,
        'maxDurationMs': 2500,
        'directionMap': ?directionMap,
      },
    });

/// 손 크기 배수로 (dx, dy)만큼 이동하는 시퀀스.
List<Coords> move(double dx, double dy, {double scale = 1.0, int frames = kFrames}) {
  return makeSequence(
    start: <double>[0.0, 0.0, 0.0],
    end: <double>[dx * scale, dy * scale, 0.0],
    frames: frames,
    scale: scale,
  );
}

void main() {
  final MovementDetector detector = MovementDetector(moveConfig());

  group('축 이동 판정', () {
    final List<(double, double, String)> cases = <(double, double, String)>[
      (3.0, 0.0, 'MOVE_RIGHT'),
      (-3.0, 0.0, 'MOVE_LEFT'),
      (0.0, -3.0, 'MOVE_UP'),
      (0.0, 3.0, 'MOVE_DOWN'),
    ];
    for (final (double dx, double dy, String expected) in cases) {
      test('($dx, $dy) → $expected', () {
        expect(detector.detect(move(dx, dy)).label, expected);
      });
    }
  });

  group('대각선 거부', () {
    test('45도는 NONE (주축 지배력 미달)', () {
      final MoveResult r = detector.detect(move(3.0, 3.0));
      expect(r.label, kNoMove);
      expect(r.reason, MoveReason.notAxisDominant);
    });

    test('임계값 바로 아래는 거부', () {
      const double ratio = 2.0;
      expect(detector.detect(move(3.0, 3.0 / (ratio - 0.2))).label, kNoMove);
    });

    test('임계값을 넘으면 통과', () {
      const double ratio = 2.0;
      expect(detector.detect(move(3.0, 3.0 / (ratio + 1.0))).label, 'MOVE_RIGHT');
    });
  });

  group('제자리 흔들기 거부', () {
    test('최소 변위 미만은 NONE', () {
      const double limit = 1.2;
      final MoveResult r = detector.detect(move(limit * 0.5, 0.0));
      expect(r.label, kNoMove);
      expect(r.reason, MoveReason.tooSmall);
    });

    test('순 이동 없이 떠는 손은 NONE', () {
      const double limit = 1.2;
      final double amp = limit * 0.3;
      final List<Coords> seq = <Coords>[
        for (int i = 0; i < kFrames; i++)
          makeHand(center: <double>[i.isOdd ? amp : -amp, 0.0, 0.0]),
      ];
      expect(detector.detect(seq).label, kNoMove);
    });
  });

  group('거리 불변성', () {
    for (final double scale in <double>[0.25, 1.0, 4.0]) {
      test('손 크기 $scale배에서도 같은 결과', () {
        final MoveResult r = detector.detect(move(3.0, 0.0, scale: scale));
        expect(r.label, 'MOVE_RIGHT');
        expect(r.displacementRatio, closeTo(3.0, 1e-6));
      });
    }

    test('변위는 손 크기 배수로 잰다', () {
      expect(
        detector.detect(move(2.5, 0.0)).displacementRatio,
        closeTo(2.5, 1e-6),
      );
    });
  });

  group('좌표계 (거울)', () {
    // ⚠️ 이 그룹이 이중 반전 방지의 핵심이다.
    //
    // 좌표는 **원본 그대로** 넣는다. x가 증가하는(센서 기준 오른쪽) 이동을 넣으면
    // mirrored에서는 MOVE_LEFT가 나와야 한다. 사용자는 거울 화면을 보고 있어서
    // 자기 손이 왼쪽으로 간 것으로 인식하기 때문이다.
    //
    // 만약 좌표를 미리 뒤집고 라벨도 뒤집으면 반전이 상쇄돼 MOVE_RIGHT가 나온다.
    // 그 경우 이 테스트가 깨진다.
    final MovementDetector mirrored =
        MovementDetector(moveConfig(coordinateFrame: 'mirrored'));

    test('원본 좌표에서 x 증가 → 화면 기준 MOVE_LEFT', () {
      expect(mirrored.detect(move(3.0, 0.0)).label, 'MOVE_LEFT');
    });

    test('원본 좌표에서 x 감소 → 화면 기준 MOVE_RIGHT', () {
      expect(mirrored.detect(move(-3.0, 0.0)).label, 'MOVE_RIGHT');
    });

    test('상하는 거울에 영향받지 않는다', () {
      expect(mirrored.detect(move(0.0, -3.0)).label, 'MOVE_UP');
      expect(mirrored.detect(move(0.0, 3.0)).label, 'MOVE_DOWN');
    });

    test('raw는 뒤집지 않는다', () {
      expect(detector.detect(move(3.0, 0.0)).label, 'MOVE_RIGHT');
    });

    test('알 수 없는 좌표계는 거절한다', () {
      expect(
        () => MovementDetector(moveConfig(coordinateFrame: 'screen')),
        throwsA(isA<ArgumentError>()),
      );
    });
  });

  group('방향 대응표는 설정에서 온다', () {
    test('표를 뒤집으면 결과도 뒤집힌다 (추측하지 않는다)', () {
      final MovementDetector swapped = MovementDetector(moveConfig(
        directionMap: <String, dynamic>{
          'MOVE_LEFT': <dynamic>['x', 1],
          'MOVE_RIGHT': <dynamic>['x', -1],
          'MOVE_UP': <dynamic>['y', 1],
          'MOVE_DOWN': <dynamic>['y', -1],
        },
      ));
      expect(swapped.detect(move(3.0, 0.0)).label, 'MOVE_LEFT');
    });

    test('표에 없는 축은 NONE', () {
      final MovementDetector partial = MovementDetector(moveConfig(
        directionMap: <String, dynamic>{
          'MOVE_LEFT': <dynamic>['x', -1],
          'MOVE_RIGHT': <dynamic>['x', 1],
        },
      ));
      final MoveResult r = partial.detect(move(0.0, 3.0));
      expect(r.label, kNoMove);
      expect(r.reason, MoveReason.unmappedAxis);
    });
  });

  group('기타', () {
    test('전부 못 읽은 프레임은 NO_TRACK', () {
      final List<Coords> nan = <Coords>[
        for (int i = 0; i < kFrames; i++)
          <List<double>>[
            for (int j = 0; j < 21; j++)
              <double>[double.nan, double.nan, double.nan],
          ],
      ];
      final MoveResult r = detector.detect(nan);
      expect(r.label, kNoMove);
      expect(r.reason, MoveReason.noTrack);
    });

    test('윈도우 프레임 수는 fps에 비례한다', () {
      expect(detector.windowFrames(30.0), 30);
      expect(detector.windowFrames(60.0), 60);
    });

    test('실기기 fps에서도 최소 2프레임은 확보한다', () {
      // windowMs가 아주 짧아도 2프레임 미만으로 내려가면 변위를 잴 수 없다.
      final MovementDetector fast = MovementDetector(configWith(<String, dynamic>{
        'movement': <String, dynamic>{'windowMs': 10},
      }));
      expect(fast.windowFrames(14.0), 2);
    });

    test('실기기 14fps에서 600ms 윈도우는 8프레임', () {
      expect(MovementDetector(configWith()).windowFrames(14.0), 8);
    });
  });
}

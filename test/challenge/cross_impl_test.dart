/// Python 원본과 Dart 이식본이 같은 입력에 같은 결과를 내는지.
///
/// 기대값은 손으로 옮긴 것이 아니라 **파이썬 실행 결과**다.
/// `challenge_response/scripts/export_dart_golden.py`로 다시 만든다.
///
/// 두 구현이 갈라지면 안티스푸핑 규칙이 조용히 달라진다. 이 파일이 그걸 막는다.
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:signid/challenge/challenge_config.dart';
import 'package:signid/challenge/challenge_generator.dart';
import 'package:signid/challenge/challenge_state_machine.dart';
import 'package:signid/challenge/geometry.dart';
import 'package:signid/challenge/hand_action_detector.dart';
import 'package:signid/challenge/movement_detector.dart';

import 'synth.dart';

/// 파이썬이 NaN/Infinity를 문자열로 남긴다. JSON에 그 리터럴이 없기 때문이다.
double toDouble(dynamic v) => switch (v) {
      'NaN' => double.nan,
      'Infinity' => double.infinity,
      '-Infinity' => double.negativeInfinity,
      final num n => n.toDouble(),
      _ => throw ArgumentError('숫자가 아니다: $v'),
    };

/// NaN끼리도 같다고 본다 (둘 다 '계산 불가'라는 같은 뜻이다).
void expectSame(double got, double expected, {double tolerance = 1e-6}) {
  if (expected.isNaN) {
    expect(got.isNaN, isTrue, reason: 'NaN이어야 하는데 $got');
    return;
  }
  if (expected.isInfinite) {
    expect(got, expected);
    return;
  }
  expect(got, closeTo(expected, tolerance));
}

void main() {
  final Map<String, dynamic> golden = jsonDecode(
    File('test/challenge/golden/cross_impl.json').readAsStringSync(),
  ) as Map<String, dynamic>;

  final ChallengeConfig config =
      ChallengeConfig.fromJson(golden['config'] as Map<String, dynamic>);
  final double extendedAngle = (golden['extendedAngle'] as num).toDouble();
  final double curledAngle = (golden['curledAngle'] as num).toDouble();
  final double fps = (golden['fps'] as num).toDouble();
  final double frameMs = 1000.0 / fps;

  Coords patternHand(List<bool> flags,
      {bool thumb = true,
      double scale = 1.0,
      List<double> center = const <double>[0, 0, 0]}) {
    return makePatternHand(
      extended: <String, bool>{
        'thumb': thumb,
        for (final (int i, String name) in kNonThumbFingers.indexed)
          name: flags[i],
      },
      extendedAngle: extendedAngle,
      curledAngle: curledAngle,
      scale: scale,
      center: center,
    );
  }

  List<Coords> moveSequence(double dx, double dy, int frames, double scale) {
    return <Coords>[
      for (int i = 0; i < frames; i++)
        makeHand(
          uniformAngle: 180.0,
          scale: scale,
          center: <double>[
            dx * scale * i / (frames - 1),
            dy * scale * i / (frames - 1),
            0.0,
          ],
        ),
    ];
  }

  group('합성기가 같은 좌표를 만든다', () {
    // 이게 깨지면 아래 모든 비교가 무의미하다. 입력부터 다른 것이다.
    for (final dynamic raw in golden['synthSamples'] as List<dynamic>) {
      final Map<String, dynamic> c = raw as Map<String, dynamic>;
      test(c['name'] as String, () {
        final Map<String, dynamic> p = c['params'] as Map<String, dynamic>;
        final Coords hand = makeHand(
          angles: (p['angles'] as Map<String, dynamic>?)?.map(
            (String k, dynamic v) => MapEntry<String, double>(k, (v as num).toDouble()),
          ),
          uniformAngle: (p['uniformAngle'] as num?)?.toDouble() ?? 180.0,
          scale: (p['scale'] as num?)?.toDouble() ?? 1.0,
          center: ((p['center'] as List<dynamic>?) ?? <dynamic>[0, 0, 0])
              .map((dynamic v) => (v as num).toDouble())
              .toList(),
        );
        final List<dynamic> expected = c['landmarks'] as List<dynamic>;
        expect(hand.length, expected.length);
        for (int i = 0; i < hand.length; i++) {
          for (int axis = 0; axis < 3; axis++) {
            expectSame(
              hand[i][axis],
              toDouble((expected[i] as List<dynamic>)[axis]),
              tolerance: 1e-9,
            );
          }
        }
      });
    }
  });

  group('손 모양 판정이 일치한다', () {
    final HandActionDetector detector = HandActionDetector(config);
    for (final dynamic raw in golden['shapeCases'] as List<dynamic>) {
      final Map<String, dynamic> c = raw as Map<String, dynamic>;
      test(c['name'] as String, () {
        final ShapeResult r = detector.detect(patternHand(
          (c['flags'] as List<dynamic>).cast<bool>(),
          thumb: c['thumb'] as bool,
          scale: (c['scale'] as num).toDouble(),
          center: (c['center'] as List<dynamic>)
              .map((dynamic v) => (v as num).toDouble())
              .toList(),
        ));
        expect(r.label, c['label'] as String);
        expectSame(r.confidence, toDouble(c['confidence']));
        expectSame(r.tipWristRatio, toDouble(c['tipWristRatio']));
        expect(r.flags, (c['flagsOut'] as List<dynamic>).cast<bool>());
        final List<dynamic> angles = c['angles'] as List<dynamic>;
        for (int i = 0; i < angles.length; i++) {
          expectSame(r.angles[i], toDouble(angles[i]));
        }
      });
    }
  });

  group('이동 판정이 일치한다 (축비·대각선 거부 포함)', () {
    final MovementDetector detector = MovementDetector(config);
    for (final dynamic raw in golden['moveCases'] as List<dynamic>) {
      final Map<String, dynamic> c = raw as Map<String, dynamic>;
      test(c['name'] as String, () {
        final MoveResult r = detector.detect(moveSequence(
          (c['dx'] as num).toDouble(),
          (c['dy'] as num).toDouble(),
          (c['frames'] as num).toInt(),
          (c['scale'] as num).toDouble(),
        ));
        expect(r.label, c['label'] as String);
        expect(r.reason, c['reason'] as String);
        expect(r.axis, c['axis'] as String);
        expect(r.sign, (c['sign'] as num).toInt());
        expectSame(r.displacementRatio, toDouble(c['displacementRatio']));
        expectSame(r.axisRatio, toDouble(c['axisRatio']));
      });
    }
  });

  group('거울 좌표계 라벨이 일치한다', () {
    // ⚠️ 좌표는 원본, 라벨만 뒤집는다. 양쪽이 같은 규칙을 쓰는지 본다.
    final MovementDetector mirrored = MovementDetector(
      ChallengeConfig.fromJson(<String, dynamic>{
        ...golden['config'] as Map<String, dynamic>,
        'coordinateFrame': 'mirrored',
      }),
    );
    for (final dynamic raw in golden['mirroredMoveCases'] as List<dynamic>) {
      final Map<String, dynamic> c = raw as Map<String, dynamic>;
      test(c['name'] as String, () {
        final MoveResult r = mirrored.detect(moveSequence(
          (c['dx'] as num).toDouble(),
          (c['dy'] as num).toDouble(),
          (c['frames'] as num).toInt(),
          1.0,
        ));
        expect(r.label, c['label'] as String);
      });
    }
  });

  group('상태 머신 전체 흐름이 일치한다', () {
    for (final dynamic raw in golden['sequenceCases'] as List<dynamic>) {
      final Map<String, dynamic> c = raw as Map<String, dynamic>;
      test(c['name'] as String, () {
        final List<String> actions =
            (c['actions'] as List<dynamic>).cast<String>();
        final ChallengeStateMachine machine = ChallengeStateMachine(
          config: config,
          challenge: Challenge(
            challengeId: 'golden',
            actions: actions,
            createdAt: DateTime.utc(2026),
            shapePool: config.shapePool,
            movePool: config.movePool,
          ),
          fps: fps,
        );

        double t = 0.0;
        Status? status;
        for (final dynamic stepRaw in c['script'] as List<dynamic>) {
          final Map<String, dynamic> step = stepRaw as Map<String, dynamic>;
          final int frames = (step['frames'] as num).toInt();
          for (int i = 0; i < frames; i++) {
            final Observation obs;
            switch (step['kind'] as String) {
              case 'shape':
                final Coords hand =
                    patternHand(kShapePatterns[step['label'] as String]!);
                obs = Observation(
                  timestampMs: t,
                  handFound: true,
                  detectionScore: 1.0,
                  angleCoords: hand,
                  screenCoords: hand,
                );
              case 'move':
                final Coords hand = makeHand(
                  uniformAngle: 180.0,
                  center: <double>[
                    (step['dx'] as num).toDouble() * i * 0.4,
                    (step['dy'] as num).toDouble() * i * 0.4,
                    0.0,
                  ],
                );
                obs = Observation(
                  timestampMs: t,
                  handFound: true,
                  detectionScore: 1.0,
                  angleCoords: hand,
                  screenCoords: hand,
                );
              default:
                obs = Observation(timestampMs: t, handFound: false);
            }
            status = machine.update(obs);
            t += frameMs;
            if (status.finished) break;
          }
          if (status != null && status.finished) break;
        }

        expect(_stateCode(status!.state), c['state'] as String);
        expect(status.failReason?.code, c['failReason'] as String?);
        expect(machine.stepIndex, (c['stepIndex'] as num).toInt());
        expect(
          machine.steps.map((StepResult s) => s.passed).toList(),
          (c['stepsPassed'] as List<dynamic>).cast<bool>(),
        );
      });
    }
  });

  test('규칙 버전이 일치한다', () {
    // 규칙이 바뀌면 골든을 다시 뽑아야 한다. 버전이 어긋나면 그걸 잊은 것이다.
    expect(config.ruleVersion, golden['ruleVersion'] as String);
    expect(config.ruleVersion, isNotEmpty);
  });
}

/// Python `State` enum 값과 맞춘다.
String _stateCode(ChallengeState state) => switch (state) {
      ChallengeState.idle => 'IDLE',
      ChallengeState.waitHand => 'WAIT_HAND',
      ChallengeState.action => 'ACTION',
      ChallengeState.passed => 'PASS',
      ChallengeState.failed => 'FAIL',
    };

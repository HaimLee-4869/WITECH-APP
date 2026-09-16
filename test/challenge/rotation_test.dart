/// 센서 회전이 이동 방향 판정에 제대로 들어가는지.
///
/// 2026-09-18 실기기 회귀: 오버레이에는 회전을 적용하는데 판정 입력에는 빼먹어서
/// 축이 90도 돌아갔다.
///
///     req=MOVE_UP   → axis=x- (축비 19.21) → label=MOVE_RIGHT
///     req=MOVE_LEFT → axis=y+ (축비 47.25) → label=MOVE_DOWN
///
/// 축비가 19~47배로 확실한데 x/y만 swap된 모양이었다. 각도는 회전에 불변이라
/// 손 모양 판정은 멀쩡했고, 그래서 더 늦게 드러났다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:signid/challenge/challenge_config.dart';
import 'package:signid/challenge/geometry.dart';
import 'package:signid/challenge/movement_detector.dart';
import 'package:signid/core/screen_rotation.dart';
import 'package:signid/models/landmark.dart';

import 'config_fixture.dart';
import 'synth.dart';

/// 서버 기본 설정(coordinateFrame: mirrored).
final ChallengeConfig config = configWith();

/// 센서가 [degrees]로 돌아가 있을 때, 화면에서 (dx, dy)로 보이도록 움직이는
/// **센서 원본 좌표** 시퀀스를 만든다.
///
/// 컨트롤러가 하는 일의 역함수다. 회전을 되돌려 센서 좌표를 만든 뒤, 판정 경로가
/// 다시 회전을 적용해 원래 화면 방향을 복원하는지 본다.
List<Coords> sensorFramesFor({
  required int degrees,
  required double dx,
  required double dy,
  int frames = 24,
}) {
  final Coords base = makeHand(uniformAngle: 180.0, scale: 0.12);

  return <Coords>[
    for (int i = 0; i < frames; i++)
      <List<double>>[
        for (final List<double> p in base)
          () {
            final double t = i / (frames - 1);
            // 화면에서 보이길 원하는 위치 (정규화 0~1)
            final double sx = 0.5 + p[0] + dx * t * 0.3;
            final double sy = 0.5 + p[1] + dy * t * 0.3;
            // 센서 좌표로 되돌린다 (회전의 역 = 360-degrees)
            final r = rotateNormalizedPoint(sx, sy, 360 - degrees);
            return <double>[r.x, r.y, p[2]];
          }(),
      ],
  ];
}

/// 컨트롤러와 같은 순서로 판정 입력을 만든다.
/// **회전만 적용하고 거울은 넣지 않는다.**
MoveResult judge(List<Coords> sensorFrames, int degrees,
    {int width = 720, int height = 480}) {
  final size = rotatedFrameSize(width, height, degrees);
  final List<Coords> screen = <Coords>[
    for (final Coords f in sensorFrames)
      toIsotropic(
        <List<double>>[
          for (final List<double> p in f)
            () {
              final r = rotateNormalizedPoint(p[0], p[1], degrees);
              return <double>[r.x, r.y, p[2]];
            }(),
        ],
        size.width,
        size.height,
      ),
  ];
  return MovementDetector(config).detect(screen);
}

void main() {
  group('rotateNormalizedPoint', () {
    test('오버레이가 쓰던 매핑과 같다', () {
      // HandOverlayPainter._project의 원래 case 문과 같은 값이어야 한다.
      void expectPoint(({double x, double y}) got, double x, double y) {
        expect(got.x, closeTo(x, 1e-9));
        expect(got.y, closeTo(y, 1e-9));
      }

      expectPoint(rotateNormalizedPoint(0.2, 0.7, 90), 0.3, 0.2);
      expectPoint(rotateNormalizedPoint(0.2, 0.7, 180), 0.8, 0.3);
      expectPoint(rotateNormalizedPoint(0.2, 0.7, 270), 0.7, 0.8);
      expectPoint(rotateNormalizedPoint(0.2, 0.7, 0), 0.2, 0.7);
    });

    test('실기기 실측값과 맞는다 (270도)', () {
      // OnDeviceLandmarkSource 주석의 기록: (0.245, 0.652) → (0.350, 0.262)
      final r = rotateNormalizedPoint(0.350, 0.262, 270);
      expect(r.x, closeTo(0.262, 1e-9));
      expect(r.y, closeTo(0.650, 1e-3));
    });

    test('네 번 돌리면 제자리다', () {
      var p = (x: 0.2, y: 0.7);
      for (int i = 0; i < 4; i++) {
        p = rotateNormalizedPoint(p.x, p.y, 90);
      }
      expect(p.x, closeTo(0.2, 1e-9));
      expect(p.y, closeTo(0.7, 1e-9));
    });
  });

  group('rotatedFrameSize', () {
    test('90·270도에서 가로·세로가 바뀐다', () {
      expect(rotatedFrameSize(720, 480, 90), (width: 480, height: 720));
      expect(rotatedFrameSize(720, 480, 270), (width: 480, height: 720));
    });

    test('0·180도는 그대로', () {
      expect(rotatedFrameSize(720, 480, 0), (width: 720, height: 480));
      expect(rotatedFrameSize(720, 480, 180), (width: 720, height: 480));
    });
  });

  group('sensorOrientation과 무관하게 화면 방향으로 판정한다', () {
    // 화면 좌표: y가 작아지는 쪽이 위, x가 커지는 쪽이 오른쪽.
    // coordinateFrame=mirrored라 좌우 **라벨**은 뒤집힌다. 사용자는 거울 프리뷰를
    // 보고 있어서, 화면에서 오른쪽으로 간 손은 본인 눈에 왼쪽으로 보인다.
    for (final int degrees in <int>[0, 90, 180, 270]) {
      test('$degrees도: 화면 위로 이동 → MOVE_UP', () {
        final MoveResult r =
            judge(sensorFramesFor(degrees: degrees, dx: 0.0, dy: -1.0), degrees);
        expect(r.label, 'MOVE_UP', reason: 'reason=${r.reason} axis=${r.axis}${r.sign}');
      });

      test('$degrees도: 화면 아래로 이동 → MOVE_DOWN', () {
        final MoveResult r =
            judge(sensorFramesFor(degrees: degrees, dx: 0.0, dy: 1.0), degrees);
        expect(r.label, 'MOVE_DOWN', reason: 'reason=${r.reason}');
      });

      test('$degrees도: 화면 오른쪽으로 이동 → MOVE_LEFT (거울)', () {
        final MoveResult r =
            judge(sensorFramesFor(degrees: degrees, dx: 1.0, dy: 0.0), degrees);
        expect(r.label, 'MOVE_LEFT', reason: 'reason=${r.reason}');
      });

      test('$degrees도: 화면 왼쪽으로 이동 → MOVE_RIGHT (거울)', () {
        final MoveResult r =
            judge(sensorFramesFor(degrees: degrees, dx: -1.0, dy: 0.0), degrees);
        expect(r.label, 'MOVE_RIGHT', reason: 'reason=${r.reason}');
      });
    }
  });

  test('회전을 빼먹으면 90도 돌아간다 (회귀의 재현)', () {
    // 실기기 로그와 같은 모양: 화면 위로 움직였는데 x축으로 잡힌다.
    const int degrees = 90;
    final List<Coords> sensor =
        sensorFramesFor(degrees: degrees, dx: 0.0, dy: -1.0);

    // 회전을 적용하지 않고 그대로 넣으면 (버그 당시 코드)
    final List<Coords> unrotated = <Coords>[
      for (final Coords f in sensor) toIsotropic(f, 720, 480),
    ];
    final MoveResult wrong = MovementDetector(config).detect(unrotated);

    expect(wrong.axis, 'x', reason: '축이 swap된다');
    expect(wrong.label, isNot('MOVE_UP'));

    // 회전을 적용하면 제대로 나온다
    expect(judge(sensor, degrees).label, 'MOVE_UP');
  });

  _serverPayloadGroup();
  _staleGroup();
}

// ─── 서버 전송 좌표는 건드리지 않는다 ────────────────────────────────

void _serverPayloadGroup() {
  group('서버 전송 좌표는 원본이다', () {
    test('회전은 판정 입력에만 들어간다', () {
      // 등록과 인증이 같은 규약(원본 좌표)을 쓰고 있어 잘 동작한다.
      // 여기에 회전을 넣으면 기존 템플릿이 전부 무효가 된다.
      const double x = 0.25, y = 0.80, z = -0.03;

      // 전송용: HandFrame.toJson은 좌표를 그대로 싣는다
      final Landmark sent = Landmark(x, y, z);
      expect(sent.toJson(), <double>[x, y, z]);

      // 판정용: 회전이 들어가서 값이 달라진다
      final r = rotateNormalizedPoint(x, y, 270);
      expect(r.x, isNot(closeTo(x, 1e-6)));
      expect(r.y, isNot(closeTo(y, 1e-6)));
    });
  });
}

// ─── 프레임 공백 기준 ────────────────────────────────────────────────

void _staleGroup() {
  group('손 없음 기준을 실측 간격에서 유도한다', () {
    final TrackingConfig tracking = config.tracking;

    test('중앙값 × factor', () {
      // 14fps면 간격 71ms → 71 × 3.0 = 213ms
      expect(tracking.staleThreshold(71).inMilliseconds, 213);
      // 30fps면 33ms → 99ms지만 하한 150ms에 걸린다
      expect(tracking.staleThreshold(33).inMilliseconds, 150);
    });

    test('실기기에서 관측된 튐(110~170ms)을 손 없음으로 보지 않는다', () {
      // 이게 고정 100ms였을 때 윈도우가 계속 비워졌다.
      final int threshold = tracking.staleThreshold(71).inMilliseconds;
      expect(threshold, greaterThan(170));
    });

    test('상·하한으로 묶는다', () {
      expect(tracking.staleThreshold(1).inMilliseconds, tracking.frameStaleMinMs);
      expect(tracking.staleThreshold(5000).inMilliseconds,
          tracking.frameStaleMaxMs);
    });

    test('표본이 없으면 하한을 쓴다', () {
      expect(tracking.staleThreshold(0).inMilliseconds, tracking.frameStaleMinMs);
    });

    test('서버 설정으로 조정된다', () {
      final ChallengeConfig loose = configWith(<String, dynamic>{
        'tracking': <String, dynamic>{'frameStaleFactor': 5.0},
      });
      expect(loose.tracking.staleThreshold(71).inMilliseconds, 355);
    });

    test('손 소실 판정(maxLostFrames)보다는 훨씬 짧다', () {
      // 이 기준은 '손 없음 관측을 만들 때'만 쓴다. 진짜 실패는 maxLostFrames가
      // 시간으로 정한다. 둘이 뒤집히면 손이 사라져도 실패하지 않는다.
      expect(
        tracking.staleThreshold(71).inMilliseconds,
        lessThan(config.consecutiveMs(tracking.maxLostFrames + 1)),
      );
    });
  });
}

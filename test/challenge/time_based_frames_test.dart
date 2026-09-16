/// `challenge_response/tests/test_time_based_frames.py`의 이식.
///
/// 설정의 `shapeHoldFrames`·`escapeFrames`·`maxLostFrames`와 이동 윈도우는
/// 파일럿 영상(30fps)에서 센 프레임 수다. **실기기는 13~16fps다.** 프레임 수로 세면
/// 같은 값이 두 배 넘게 긴 시간이 된다.
///
/// challenge_response는 웹캠 20fps에서, 앱은 14fps의 handReady에서 이미 한 번씩
/// 겪은 문제다. 기준 fps로 들어오면 예전과 같고, 다른 fps면 같은 '시간'이 걸려야 한다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:signid/challenge/challenge_config.dart';
import 'package:signid/challenge/challenge_state_machine.dart';
import 'package:signid/challenge/geometry.dart';

import 'state_machine_test.dart' show build, obs, shapeHand, smConfig;

const double kReferenceFps = 30.0;

/// 실기기 fps. 실측으로 13~16fps가 나왔다.
const double kDeviceFps = 14.0;

ChallengeConfig timeConfig() =>
    smConfig(<String, dynamic>{'frameReferenceFps': kReferenceFps});

Status? feed(
  ChallengeStateMachine sm,
  double frameMs,
  int frames, {
  Coords? hand,
  bool found = true,
  List<double> center = const <double>[0.0, 0.0, 0.0],
}) {
  Status? status;
  for (int i = 0; i < frames; i++) {
    status = sm.update(
      obs(i * frameMs, hand: hand, found: found, center: center),
    );
    if (status.finished) break;
  }
  return status;
}

void main() {
  group('FrameSpan', () {
    for (int frames = 1; frames <= 20; frames++) {
      test('기준 fps에서 $frames프레임이면 정확히 $frames번째에 완료된다', () {
        // 타임스탬프가 ±5ms 흔들려도 결과가 같아야 한다.
        final FrameSpan span = FrameSpan(frames, timeConfig());
        int? doneAt;
        for (int i = 0; i < frames + 5; i++) {
          final double jitter = i == 0 ? 0.0 : ((i * 37) % 11 - 5).toDouble();
          if (span.hit(i * 1000.0 / kReferenceFps + jitter)) {
            doneAt = i + 1;
            break;
          }
        }
        expect(doneAt, frames);
      });
    }

    test('낮은 fps에서는 프레임 수가 아니라 시간으로 완료된다', () {
      // 30fps 7프레임 = 첫~끝 간격 약 183ms
      final FrameSpan span = FrameSpan(7, timeConfig());
      int frames = 0;
      double t = 0.0;
      while (!span.hit(t)) {
        frames++;
        t += 1000.0 / kDeviceFps; // 약 71ms
      }
      expect(t, lessThanOrEqualTo(183.0 + 1000.0 / kDeviceFps));
      expect(frames + 1, lessThan(7));
    });

    test('진행도와 초기화', () {
      final FrameSpan span = FrameSpan(7, timeConfig());
      span.hit(0.0);
      span.hit(100.0);
      expect(span.progress, greaterThan(0.0));
      expect(span.progress, lessThan(1.0));
      span.reset();
      expect(span.active, isFalse);
      expect(span.progress, 0.0);
    });
  });

  group('TimeWindow', () {
    test('기준 fps에서는 지정한 프레임 수만큼 담는다', () {
      final TimeWindow window = TimeWindow(18, timeConfig());
      for (int i = 0; i < 40; i++) {
        window.add(i * 1000.0 / kReferenceFps, <double>[0, 0, 0], 1.0);
      }
      expect(window.length, 18);
      expect(window.ready, isTrue);
    });

    test('낮은 fps에서도 같은 시간이 지나면 준비된다', () {
      // 30fps 18프레임 = 첫~끝 약 550ms
      final TimeWindow window = TimeWindow(18, timeConfig());
      double t = 0.0;
      while (true) {
        window.add(t, <double>[0, 0, 0], 1.0);
        if (window.ready) break;
        t += 1000.0 / kDeviceFps;
      }
      expect(t, greaterThanOrEqualTo(500.0));
      expect(t, lessThanOrEqualTo(650.0));
      expect(window.length, lessThan(18));
    });
  });

  group('상태 머신 — 실기기 fps에서 같은 시간', () {
    test('손 모양 유지 시간이 같다', () {
      final ChallengeStateMachine at30 =
          build(<String>['OPEN_PALM', 'FIST', 'MOVE_RIGHT'], timeConfig());
      final ChallengeStateMachine at14 =
          build(<String>['OPEN_PALM', 'FIST', 'MOVE_RIGHT'], timeConfig());
      feed(at30, 1000.0 / 30.0, 60, hand: shapeHand('OPEN_PALM'));
      feed(at14, 1000.0 / kDeviceFps, 40, hand: shapeHand('OPEN_PALM'));

      expect(at30.steps[0].passed, isTrue);
      expect(at14.steps[0].passed, isTrue);
      expect(
        (at30.steps[0].elapsedMs - at14.steps[0].elapsedMs).abs(),
        lessThanOrEqualTo(1000.0 / kDeviceFps),
      );
    });

    test('손 소실 판정 시간이 같다', () {
      final Map<double, double> lostMs = <double, double>{};
      for (final double fps in <double>[30.0, kDeviceFps]) {
        final ChallengeStateMachine sm =
            build(<String>['OPEN_PALM', 'FIST', 'MOVE_RIGHT'], timeConfig());
        sm.update(obs(0.0, hand: shapeHand('OPEN_PALM')));
        final double frameMs = 1000.0 / fps;
        double t = 0.0;
        Status? status;
        while (status == null || !status.finished) {
          t += frameMs;
          status = sm.update(obs(t, found: false));
        }
        expect(status.failReason, FailReason.handLost);
        lostMs[fps] = t;
      }
      final double gap = (lostMs[30.0]! - lostMs[kDeviceFps]!).abs();

      // 판정 시각은 프레임 격자에 걸린다. 연속 구간의 시작 프레임 위치와 완료
      // 프레임 위치가 각각 최대 한 프레임씩 어긋나므로 두 프레임 간격까지 벌어진다.
      expect(gap, lessThanOrEqualTo(2 * 1000.0 / kDeviceFps));

      // 프레임 수로 셌다면 maxLostFrames+1 = 6프레임이 14fps에서 429ms가 되어
      // 30fps(200ms)와 200ms 넘게 벌어진다. 시간 기준이라 그렇지 않다.
      expect(gap, lessThan(200.0));
    });

    test('이동 판정 시간이 같다', () {
      // 프레임 수로 세면 14fps에서 윈도우가 차는 데 두 배 넘게 걸린다.
      final Map<double, double> passedMs = <double, double>{};
      for (final double fps in <double>[30.0, kDeviceFps]) {
        final ChallengeStateMachine sm =
            build(<String>['MOVE_RIGHT', 'OPEN_PALM', 'FIST'], timeConfig());
        final double frameMs = 1000.0 / fps;
        for (int i = 0; i < (3000 / frameMs).toInt(); i++) {
          final double t = i * frameMs;
          // 손 크기/초 속도가 fps와 무관하도록 시각으로 위치를 정한다
          sm.update(obs(t, center: <double>[0.006 * t, 0.0, 0.0]));
          if (sm.stepIndex > 0) break;
        }
        expect(sm.steps[0].passed, isTrue);
        passedMs[fps] = sm.steps[0].elapsedMs;
      }
      expect(
        (passedMs[30.0]! - passedMs[kDeviceFps]!).abs(),
        lessThanOrEqualTo(1000.0 / kDeviceFps),
      );
    });
  });

  group('설정값 환산', () {
    test('consecutiveMs는 반 프레임 여유를 둔다', () {
      final ChallengeConfig config = timeConfig();
      // N프레임 연속 = (N-1)프레임 간격. 흔들림 대비로 0.5프레임 뺀다.
      expect(config.consecutiveMs(7), closeTo(5.5 * config.frameMs, 1e-9));
      expect(config.consecutiveMs(1), closeTo(0.0, 1e-9));
      expect(config.consecutiveMs(0), 0.0);
    });

    test('기준 fps가 바뀌면 환산 시간도 바뀐다', () {
      final ChallengeConfig at60 =
          smConfig(<String, dynamic>{'frameReferenceFps': 60.0});
      expect(at60.frameMs, closeTo(1000.0 / 60.0, 1e-9));
      expect(at60.consecutiveMs(7), closeTo(timeConfig().consecutiveMs(7) / 2, 1e-9));
    });
  });
}

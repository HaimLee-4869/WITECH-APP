/// 연속 세션에서 손이 바뀌었는지 보는 검사.
///
/// 지금은 **재기만 한다.** 정상 세션의 프레임 간 변화량을 아직 재지 않아
/// 임계값이 없고, 임계값 없이는 켤 수 없다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:signid/challenge/challenge_config.dart';
import 'package:signid/challenge/continuity_monitor.dart';
import 'package:signid/challenge/geometry.dart';

import 'config_fixture.dart';
import 'synth.dart';

/// 화면 좌표(종횡비 보정 완료) 한 프레임.
Coords frame({double scale = 1.0, List<double> at = const <double>[0, 0, 0]}) =>
    toIsotropic(makeHand(scale: scale, center: at), 720, 480);

void main() {
  group('기본은 꺼져 있다', () {
    test('서버 기본 설정에서 검사가 꺼져 있다', () {
      // 근거 없는 임계값으로 사용자를 막지 않는다.
      final ChallengeConfig config = configWith();
      expect(config.continuity.enabled, isFalse);
      expect(config.continuity.maxScaleJumpRatio, isNull);
      expect(config.continuity.maxWristJumpRatio, isNull);
    });

    test('임계값 없이 켜면 켜지지 않는다', () {
      // 서버도 422로 막지만, 앱이 받은 값을 다시 본다.
      final ChallengeConfig config = configWith(<String, dynamic>{
        'continuity': <String, dynamic>{'enabled': true},
      });
      expect(config.continuity.enabled, isFalse);
    });

    test('꺼져 있으면 어떤 점프도 세션을 끊지 않는다', () {
      final ContinuityMonitor m = ContinuityMonitor(configWith());
      m.add(frame(), 0);
      // 손이 다섯 배로 커지고 화면 반대편으로 순간이동해도
      final ContinuitySample? s = m.add(frame(scale: 5.0, at: <double>[3, 3, 0]), 66);
      expect(s, isNotNull);
      expect(s!.scaleJump, greaterThan(4.0));
      expect(m.breaksSession(s), isFalse, reason: '꺼진 검사가 판정했다');
    });

    test('설정에 continuity가 없어도 동작한다 (옛 서버)', () {
      final ChallengeConfig config = ChallengeConfig.fromJson(
        Map<String, dynamic>.of(rawDefaults())..remove('continuity'),
      );
      expect(config.continuity.enabled, isFalse);
    });
  });

  group('측정', () {
    test('첫 프레임은 비교 대상이 없다', () {
      final ContinuityMonitor m = ContinuityMonitor(configWith());
      expect(m.add(frame(), 0), isNull);
      expect(m.samples, 0);
    });

    test('가만히 있으면 점프가 거의 0이다', () {
      final ContinuityMonitor m = ContinuityMonitor(configWith());
      m.add(frame(), 0);
      final ContinuitySample s = m.add(frame(), 66)!;
      expect(s.scaleJump, closeTo(1.0, 1e-6));
      expect(s.wristJump, closeTo(0.0, 1e-6));
    });

    test('손 크기가 두 배면 scaleJump가 2다', () {
      final ContinuityMonitor m = ContinuityMonitor(configWith());
      m.add(frame(), 0);
      expect(m.add(frame(scale: 2.0), 66)!.scaleJump, closeTo(2.0, 1e-6));
    });

    test('작아져도 같은 크기로 본다 (방향 무관)', () {
      // 화면을 들이밀든 치우든 둘 다 튄 것이다.
      final ContinuityMonitor m = ContinuityMonitor(configWith());
      m.add(frame(scale: 2.0), 0);
      expect(m.add(frame(), 66)!.scaleJump, closeTo(2.0, 1e-6));
    });

    test('손목 이동은 손 크기로 나눈다 (카메라 거리 무관)', () {
      double jumpAt(double scale) {
        final ContinuityMonitor m = ContinuityMonitor(configWith());
        m.add(frame(scale: scale), 0);
        // 손 크기의 1배만큼 옮긴다
        return m.add(frame(scale: scale, at: <double>[scale, 0, 0]), 66)!
            .wristJump;
      }

      expect(jumpAt(1.0), closeTo(jumpAt(0.4), 1e-6));
    });

    test('최대값을 모은다 (임계값 도출용)', () {
      final ContinuityMonitor m = ContinuityMonitor(configWith());
      m.add(frame(), 0);
      m.add(frame(scale: 1.1), 66);
      m.add(frame(scale: 1.8), 132);
      m.add(frame(scale: 1.9), 198);

      expect(m.samples, 3);
      expect(m.maxScaleJump, greaterThan(1.5));
      expect(m.summary(), contains('scaleJumpMax='));
      expect(m.summary(), contains('gate=off'));
    });

    test('끊긴 뒤에는 비교 기준을 버린다', () {
      // 끊김 전후를 비교하면 당연히 튄다. 그건 SESSION_BROKEN이 볼 일이다.
      final ContinuityMonitor m = ContinuityMonitor(configWith());
      m.add(frame(), 0);
      m.resetReference();
      expect(m.add(frame(scale: 5.0), 2000), isNull);
    });
  });

  group('켜면 판정한다', () {
    ChallengeConfig armed({double scale = 1.5, double wrist = 0.5}) =>
        configWith(<String, dynamic>{
          'continuity': <String, dynamic>{
            'enabled': true,
            'maxScaleJumpRatio': scale,
            'maxWristJumpRatio': wrist,
          },
        });

    test('임계값이 둘 다 있으면 켜진다', () {
      expect(ContinuityMonitor(armed()).enabled, isTrue);
    });

    test('손 크기가 튀면 끊는다', () {
      final ContinuityMonitor m = ContinuityMonitor(armed());
      m.add(frame(), 0);
      expect(m.breaksSession(m.add(frame(scale: 2.0), 66)), isTrue);
    });

    test('손목이 튀면 끊는다', () {
      final ContinuityMonitor m = ContinuityMonitor(armed());
      m.add(frame(), 0);
      expect(m.breaksSession(m.add(frame(at: <double>[1.0, 0, 0]), 66)), isTrue);
    });

    test('임계값 안이면 통과한다', () {
      final ContinuityMonitor m = ContinuityMonitor(armed());
      m.add(frame(), 0);
      expect(m.breaksSession(m.add(frame(scale: 1.05), 66)), isFalse);
    });
  });
}

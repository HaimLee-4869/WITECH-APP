/// 인증 세션이 서버와 주고받는 규약.
///
/// Challenge와 제스처 수집이 한 컨트롤러로 합쳐지면서, 예전 `auth_flow_test`가
/// 지키던 것들(전송 좌표 무가공, tMs 원본, 업로드 실패 안내)을 여기서 본다.
/// 단계 규칙 자체는 `test/challenge/`가 본다.
library;

import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:signid/challenge/challenge_config.dart';
import 'package:signid/core/config.dart';
import 'package:signid/models/api_error.dart';
import 'package:signid/models/camera_info.dart';
import 'package:signid/models/landmark.dart';
import 'package:signid/models/verify.dart';
import 'package:signid/services/mock_api_client.dart';
import 'package:signid/state/auth_session_controller.dart';
import 'package:signid/state/providers.dart';

import 'challenge/session_harness.dart';

void main() {
  late ScriptedSource source;
  late ChallengeConfig config;

  setUp(() {
    source = ScriptedSource();
    config = oneStepConfig();
  });

  tearDown(() => source.dispose());

  const VerifyResponse passed = VerifyResponse(
    score: 0.91,
    threshold: 0.3423501253128052,
    passed: true,
    latencyMs: 50,
    gestureId: 'G1',
    gestureScore: 0.97,
    gestureThreshold: 0.9020317792892456,
  );

  ProviderContainer open(StubApi api, {String? userId}) {
    final ProviderContainer c = sessionContainer(source, config, api);
    addTearDown(c.dispose);
    if (userId != null) {
      c.read(selectedUserIdProvider.notifier).select(userId);
    }
    return c;
  }

  group('전송 좌표에 어떤 가공도 적용되지 않는다 (SPEC 원칙 A)', () {
    test('전송된 HandFrame은 소스가 흘린 객체와 같은 인스턴스다', () async {
      // 미러링·정규화·리샘플링이 있었다면 새 객체가 만들어졌을 것이다.
      // 화면 표시용 회전·거울은 판정에만 쓰고 전송에는 닿지 않아야 한다.
      final StubApi api = StubApi((_) async => passed);
      final ProviderContainer c = open(api);

      final List<HandFrame> emitted = <HandFrame>[];
      final StreamSubscription<HandFrame> srcSub =
          source.frames.listen(emitted.add);
      addTearDown(srcSub.cancel);

      await runSession(c, source, config);

      expect(c.read(authSessionProvider).phase, SessionPhase.done,
          reason: c.read(authSessionProvider).notice ?? '');
      final List<HandFrame> sent = api.lastRequest!.frames;
      expect(sent, isNotEmpty);
      for (final HandFrame frame in sent) {
        expect(
          emitted.any((HandFrame e) => identical(e, frame)),
          isTrue,
          reason: '전송 프레임이 소스 원본 인스턴스가 아니다 = 중간에 가공됐다',
        );
      }
    }, timeout: const Timeout(Duration(seconds: 60)));

    test('tMs는 소스 타임스탬프 그대로다 (앱이 다시 계산하지 않는다)', () async {
      final StubApi api = StubApi((_) async => passed);
      final ProviderContainer c = open(api);

      await runSession(c, source, config);

      final VerifyRequest req = api.lastRequest!;
      expect(req.frames.length, greaterThanOrEqualTo(kMinFramesForVerify));
      expect(req.nominalFps, kNominalFps);

      // 인덱스×33이었다면 간격이 전부 같았을 것이다. 하네스는 일부러
      // 들쭉날쭉한 타임스탬프를 흘린다.
      final Set<int> gaps = <int>{
        for (int i = 1; i < req.frames.length; i++)
          req.frames[i].tMs - req.frames[i - 1].tMs,
      };
      expect(gaps.length, greaterThan(1),
          reason: 'tMs가 계산된 값이 아니라 소스 타임스탬프여야 한다');

      // 좌표가 [0,1] 원본 범위 안이다 = 전처리가 없었다.
      for (final HandFrame f in req.frames) {
        expect(f.landmarks.length, 21);
        for (final Landmark lm in f.landmarks) {
          expect(lm.x, inInclusiveRange(0.0, 1.0));
          expect(lm.y, inInclusiveRange(0.0, 1.0));
        }
      }
    }, timeout: const Timeout(Duration(seconds: 60)));

    test('tMs가 뒤로 가거나 겹치지 않는다', () async {
      // 카메라 구독이 새면 같은 프레임이 두 번 실린다. 서버에 닿기 전에 막는다.
      final StubApi api = StubApi((_) async => passed);
      final ProviderContainer c = open(api);

      await runSession(c, source, config);

      final List<HandFrame> f = api.lastRequest!.frames;
      for (int i = 1; i < f.length; i++) {
        expect(f[i].tMs, greaterThan(f[i - 1].tMs),
            reason: '$i번째 프레임이 앞 프레임보다 앞서거나 같다');
      }
    }, timeout: const Timeout(Duration(seconds: 60)));
  });

  group('요청의 userId는 이름이 아니라 서버 users.id다', () {
    test('고르지 않으면 목록 첫 사용자의 id를 보낸다', () async {
      final StubApi api = StubApi((_) async => passed);
      await runSession(open(api), source, config);
      expect(api.lastRequest!.userId, 'hong');
    }, timeout: const Timeout(Duration(seconds: 60)));

    test('고른 사용자의 id를 보낸다', () async {
      final StubApi api = StubApi((_) async => passed);
      await runSession(open(api, userId: 'oh'), source, config);
      expect(api.lastRequest!.userId, 'oh');
    }, timeout: const Timeout(Duration(seconds: 60)));
  });

  group('업로드 결과가 화면 문구로 갈린다', () {
    test('통과하면 서버 응답을 그대로 담는다', () async {
      final StubApi api = StubApi((_) async => passed);
      final ProviderContainer c = open(api);
      await runSession(c, source, config);

      final AuthSessionState st = c.read(authSessionProvider);
      expect(st.phase, SessionPhase.done);
      expect(st.response!.passed, isTrue);
      // 임계값은 서버 응답에서 온 값이다. 앱 상수가 아니다.
      expect(st.response!.threshold, 0.3423501253128052);
      expect(st.notice, isNull);
    }, timeout: const Timeout(Duration(seconds: 60)));

    test('판정에서 떨어져도 세션은 완료다 (결과 화면이 사유를 받는다)', () async {
      final StubApi api = StubApi(
        (_) async => const VerifyResponse(
          score: 0.40,
          threshold: 0.72,
          passed: false,
          latencyMs: 1200,
        ),
      );
      final ProviderContainer c = open(api);
      await runSession(c, source, config);

      final AuthSessionState st = c.read(authSessionProvider);
      expect(st.phase, SessionPhase.done);
      expect(st.notice, isNull);
      expect(st.response!.passed, isFalse);
      expect(st.response!.threshold, 0.72);
    }, timeout: const Timeout(Duration(seconds: 60)));

    test('타임아웃이면 네트워크 안내를 띄운다', () async {
      final StubApi api = StubApi((_) async => throw TimeoutException('no response'));
      final ProviderContainer c = open(api);
      await runSession(c, source, config);

      final AuthSessionState st = c.read(authSessionProvider);
      expect(st.phase, SessionPhase.failed);
      expect(st.response, isNull);
      expect(st.notice, contains('서버 응답이 없습니다'));
    }, timeout: const Timeout(Duration(seconds: 60)));

    test('일반 오류면 타임아웃과 다른 안내를 띄운다', () async {
      final StubApi api = StubApi((_) async => throw StateError('boom'));
      final ProviderContainer c = open(api);
      await runSession(c, source, config);

      final AuthSessionState st = c.read(authSessionProvider);
      expect(st.phase, SessionPhase.failed);
      expect(st.notice, contains('인증 요청을 보내지 못했습니다'));
      expect(st.notice, isNot(contains('서버 응답이 없습니다')));
    }, timeout: const Timeout(Duration(seconds: 60)));
  });

  test('소스를 켜지 못하면(권한 거부 등) 이유를 문구로 알린다', () async {
    final DeniedSource denied = DeniedSource();
    addTearDown(denied.dispose);
    final StubApi api = StubApi((_) async => passed);
    final ProviderContainer c = sessionContainer(denied, config, api);
    addTearDown(c.dispose);

    await startSession(c);

    final AuthSessionState st = c.read(authSessionProvider);
    expect(st.phase, SessionPhase.unavailable);
    expect(st.notice, contains('카메라 권한이 없습니다'));
  });

  group('목 API는 서버처럼 굴어야 한다 (오프라인 개발용)', () {
    test('프레임이 부족하면 서버처럼 422 사유 코드로 거절한다', () async {
      // 시드를 고정해 5% 타임아웃에 걸리지 않게 한다.
      final MockApiClient api = MockApiClient(seed: 7);
      final Future<VerifyResponse> call = api.verify(
        VerifyRequest(
          userId: 'kim',
          gestureId: 'G1',
          camera: const CameraInfo(width: 720, height: 1280),
          capturedAt: DateTime(2026, 8, 24),
          nominalFps: kNominalFps,
          durationMs: 2000,
          frames: const <HandFrame>[],
        ),
      );
      await expectLater(
        call,
        throwsA(
          isA<ApiException>()
              .having((ApiException e) => e.reason, 'reason',
                  'insufficient_valid_frames')
              .having((ApiException e) => e.statusCode, 'statusCode', 422)
              .having((ApiException e) => e.userMessage, 'userMessage',
                  '손이 잘 보이도록 다시 시도해주세요.'),
        ),
      );
    });

    test('응답 지연을 흉내 낸다', () async {
      final MockApiClient api = MockApiClient(seed: 7);
      final Stopwatch sw = Stopwatch()..start();
      await api.fetchAuthLogs();
      sw.stop();
      expect(sw.elapsedMilliseconds, greaterThan(300));
    });

    test('타임아웃을 던지는 경우가 있다', () async {
      // 5% 확률이므로 여러 번 돌려 최소 한 번은 나오는지 본다.
      int timeouts = 0;
      for (int seed = 0; seed < 60; seed++) {
        try {
          await MockApiClient(seed: seed).verify(
            VerifyRequest(
              userId: 'kim',
              gestureId: 'G1',
              camera: const CameraInfo(width: 720, height: 1280),
              capturedAt: DateTime(2026, 8, 24),
              nominalFps: kNominalFps,
              durationMs: 2000,
              frames: const <HandFrame>[],
            ),
          );
        } on Object {
          timeouts++;
        }
      }
      expect(timeouts, greaterThan(0), reason: '에러 UI를 확인할 경로가 있어야 한다');
    }, timeout: const Timeout(Duration(seconds: 180)));
  });
}

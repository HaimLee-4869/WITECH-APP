import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:signid/core/theme.dart';
import 'package:signid/models/auth_log.dart';
import 'package:signid/models/enroll.dart';
import 'package:signid/models/landmark.dart';
import 'package:signid/models/verify.dart';
import 'package:signid/screens/auth_screen.dart';
import 'package:signid/services/api_client.dart';
import 'package:signid/services/landmark_source.dart';
import 'package:signid/state/auth_flow_controller.dart';
import 'package:signid/state/providers.dart';

import 'test_helpers.dart';

/// SPEC 11장 완료 기준 중 코드로 확인할 수 있는 항목들을 직접 검증한다.

class _StubApi implements ApiClient {
  final Future<VerifyResponse> Function(VerifyRequest) onVerify;

  _StubApi(this.onVerify);

  VerifyRequest? lastRequest;

  @override
  Future<VerifyResponse> verify(VerifyRequest req) {
    lastRequest = req;
    return onVerify(req);
  }

  @override
  Future<EnrollResponse> enroll(_) => throw UnimplementedError();
  @override
  Future<List<AuthLog>> fetchAuthLogs() => throw UnimplementedError();
  @override
  Future<List<MonthlyStat>> fetchMonthlyStats() => throw UnimplementedError();
}

/// 카메라 권한이 거부된 상황을 흉내 내는 소스.
class _DeniedSource implements LandmarkSource {
  final _controller = StreamController<HandFrame>.broadcast();

  @override
  Stream<HandFrame> get frames => _controller.stream;

  @override
  Future<void> start() async {
    _controller.addError(
      const LandmarkSourceException(
        '카메라 권한이 없습니다. 설정 > 앱 > Sign-ID에서 카메라 접근을 허용해주세요.',
      ),
    );
  }

  @override
  Future<void> stop() async {}
  @override
  void resetClock() {}
  @override
  void dispose() => _controller.close();
  @override
  Widget? buildPreview() => null;
  @override
  LandmarkTransform get transform => const LandmarkTransform();
}

Future<ProviderContainer> _runToDone(
  _StubApi api, {
  Duration limit = const Duration(seconds: 25),
}) async {
  final container = ProviderContainer(
    overrides: [
        apiClientProvider.overrideWithValue(api),
        fakeLandmarkSourceOverride,
      ],
  );
  final sub = container.listen(authFlowProvider, (_, _) {});
  addTearDown(sub.close);
  addTearDown(container.dispose);

  final controller = container.read(authFlowProvider.notifier);
  await controller.attach();
  controller.start();

  final deadline = DateTime.now().add(limit);
  while (container.read(authFlowProvider).phase == AuthPhase.handSearching ||
      container.read(authFlowProvider).phase == AuthPhase.handReady ||
      container.read(authFlowProvider).phase == AuthPhase.recording ||
      container.read(authFlowProvider).phase == AuthPhase.uploading) {
    if (DateTime.now().isAfter(deadline)) {
      fail('흐름이 끝나지 않았다: ${container.read(authFlowProvider).phase}');
    }
    await Future<void>.delayed(const Duration(milliseconds: 50));
  }
  return container;
}

void main() {
  group('서버 전송 좌표에 어떤 가공도 적용되지 않는다 (SPEC 원칙 A)', () {
    test('전송된 HandFrame은 소스가 흘린 객체와 동일한 인스턴스다', () async {
      final api = _StubApi(
        (_) async => const VerifyResponse(
          score: 0.9,
          threshold: 0.72,
          passed: true,
          latencyMs: 1,
        ),
      );
      final container = ProviderContainer(
        overrides: [
        apiClientProvider.overrideWithValue(api),
        fakeLandmarkSourceOverride,
      ],
      );
      final sub = container.listen(authFlowProvider, (_, _) {});
      addTearDown(sub.close);
      addTearDown(container.dispose);

      // 소스가 실제로 흘린 프레임을 그대로 붙잡아 둔다.
      final emitted = <HandFrame>[];
      final srcSub = container
          .read(landmarkSourceProvider)
          .frames
          .listen(emitted.add);
      addTearDown(srcSub.cancel);

      final controller = container.read(authFlowProvider.notifier);
      await controller.attach();
      controller.start();

      final deadline = DateTime.now().add(const Duration(seconds: 25));
      while (container.read(authFlowProvider).phase != AuthPhase.done) {
        if (DateTime.now().isAfter(deadline)) fail('done까지 도달하지 못했다');
        await Future<void>.delayed(const Duration(milliseconds: 50));
      }

      final sent = api.lastRequest!.frames;
      expect(sent, isNotEmpty);

      // 미러링·정규화·리샘플링이 있었다면 새 객체가 만들어졌을 것이다.
      // 동일 인스턴스라는 것은 좌표에 아무 손도 대지 않았다는 뜻이다.
      for (final frame in sent) {
        expect(
          emitted.any((e) => identical(e, frame)),
          isTrue,
          reason: '전송 프레임이 소스 원본 인스턴스가 아니다 = 중간에 가공됐다',
        );
      }
    }, timeout: const Timeout(Duration(seconds: 60)));
  });

  group('목 API의 지연·실패·타임아웃이 각각 다르게 반영된다 (SPEC 11장)', () {
    test('타임아웃이면 idle로 돌아가고 네트워크 안내를 띄운다', () async {
      final api = _StubApi((_) async {
        throw TimeoutException('no response');
      });
      final container = await _runToDone(api);
      final state = container.read(authFlowProvider);

      expect(state.phase, AuthPhase.idle);
      expect(state.response, isNull);
      expect(state.notice, contains('서버 응답이 없습니다'));
      expect(state.message, state.notice);
    }, timeout: const Timeout(Duration(seconds: 60)));

    test('일반 오류면 타임아웃과 다른 안내를 띄운다', () async {
      final api = _StubApi((_) async => throw StateError('boom'));
      final container = await _runToDone(api);
      final state = container.read(authFlowProvider);

      expect(state.phase, AuthPhase.idle);
      expect(state.notice, contains('인증 요청을 보내지 못했습니다'));
      expect(state.notice, isNot(contains('서버 응답이 없습니다')));
    }, timeout: const Timeout(Duration(seconds: 60)));

    test('판정 실패면 done으로 가서 결과 화면이 사유를 받는다', () async {
      final api = _StubApi(
        (_) async => const VerifyResponse(
          score: 0.40,
          threshold: 0.72,
          passed: false,
          latencyMs: 1200,
        ),
      );
      final container = await _runToDone(api);
      final state = container.read(authFlowProvider);

      expect(state.phase, AuthPhase.done);
      expect(state.notice, isNull);
      expect(state.response!.passed, isFalse);
      // threshold는 서버 응답에서 온 값이다. 앱 상수가 아니다.
      expect(state.response!.threshold, 0.72);
    }, timeout: const Timeout(Duration(seconds: 60)));
  });

  test('소스를 켜지 못하면(권한 거부 등) 이유를 문구로 알린다', () async {
    final container = ProviderContainer(
      overrides: [
        landmarkSourceProvider.overrideWith((ref) => _DeniedSource()),
      ],
    );
    final sub = container.listen(authFlowProvider, (_, _) {});
    addTearDown(sub.close);
    addTearDown(container.dispose);

    await container.read(authFlowProvider.notifier).attach();
    await Future<void>.delayed(const Duration(milliseconds: 100));

    final state = container.read(authFlowProvider);
    expect(state.phase, AuthPhase.idle);
    expect(state.notice, contains('카메라 권한이 없습니다'));
    // 화면에 그대로 표시되는 문구여야 한다.
    expect(state.message, state.notice);
  });

  group('6개 상태가 모두 화면에 반영된다 (SPEC 11장)', () {
    test('상태마다 안내 문구가 다르다', () {
      const cases = <AuthPhase, String>{
        AuthPhase.idle: '수어 암호를 입력하세요',
        AuthPhase.handSearching: '손을 원 안에 위치시켜 주세요',
        AuthPhase.handReady: '3초 후 시작합니다',
        AuthPhase.recording: '동작을 수행하세요',
        AuthPhase.uploading: '확인 중입니다',
        AuthPhase.done: '확인이 끝났습니다',
      };
      for (final entry in cases.entries) {
        expect(AuthFlowState(phase: entry.key).message, entry.value);
      }
      // 모든 상태가 서로 다른 문구를 갖는다.
      expect(cases.values.toSet().length, AuthPhase.values.length);
    });

    test('인증 버튼은 idle에서만 활성, 취소는 진행 중에만 의미가 있다', () {
      expect(const AuthFlowState(phase: AuthPhase.idle).canStart, isTrue);
      for (final p in AuthPhase.values.where((p) => p != AuthPhase.idle)) {
        expect(AuthFlowState(phase: p).canStart, isFalse);
      }
      expect(
        const AuthFlowState(phase: AuthPhase.recording).isRunning,
        isTrue,
      );
      expect(const AuthFlowState(phase: AuthPhase.idle).isRunning, isFalse);
      expect(
        const AuthFlowState(phase: AuthPhase.uploading).isRunning,
        isFalse,
      );
    });

    testWidgets('인증 화면이 상태 문구와 버튼 활성을 실제로 그린다', (tester) async {
      final view = tester.view;
      view.physicalSize = const Size(1080, 2340);
      view.devicePixelRatio = 3.0;
      addTearDown(() {
        view.resetPhysicalSize();
        view.resetDevicePixelRatio();
      });

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiClientProvider.overrideWithValue(
              _StubApi(
                (_) async => const VerifyResponse(
                  score: 0.9,
                  threshold: 0.72,
                  passed: true,
                  latencyMs: 1,
                ),
              ),
            ),
          ],
          child: MaterialApp(theme: buildAppTheme(), home: const AuthScreen()),
        ),
      );

      // idle
      expect(find.text('수어 암호를 입력하세요'), findsOneWidget);
      final button = tester.widget<InkWell>(
        find
            .descendant(
              of: find.byType(Material),
              matching: find.byType(InkWell),
            )
            .first,
      );
      expect(button.onTap, isNotNull, reason: 'idle에서 인증 버튼은 활성이어야 한다');

      // 인증 → handSearching
      await tester.tap(find.text('인증'));
      await tester.pump();
      expect(find.text('손을 원 안에 위치시켜 주세요'), findsOneWidget);

      // 흐름을 정리해 남은 타이머를 없앤다.
      await tester.pumpWidget(const SizedBox());
      await tester.pump(const Duration(seconds: 1));
    });
  });
}

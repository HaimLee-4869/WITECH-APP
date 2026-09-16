import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:signid/models/app_user.dart';
import 'package:signid/core/config.dart';
import 'package:signid/models/api_error.dart';
import 'package:signid/models/camera_info.dart';
import 'package:signid/models/server_config.dart';
import 'package:signid/models/verify.dart';
import 'package:signid/services/api_client.dart';
import 'package:signid/services/mock_api_client.dart';
import 'package:signid/state/auth_flow_controller.dart';
import 'package:signid/state/providers.dart';

import 'test_helpers.dart';

/// 항상 통과를 돌려주는 API. 상태 머신 검증에 무작위성이 끼어들면 안 된다.
class _AlwaysPassApi implements ApiClient {
  VerifyRequest? lastRequest;

  @override
  Future<ServerConfig> fetchConfig() async => ServerConfig.fallback;

  @override
  Future<AppUser> createUser({
    required String id,
    required String name,
    String? department,
  }) async => AppUser(id: id, name: name, department: department);

  @override
  Future<List<AppUser>> fetchUsers() async => const [
    AppUser(id: 'hong', name: '홍길동', department: '개발팀'),
    AppUser(id: 'kim', name: '김길동', department: '인사팀'),
    AppUser(id: 'oh', name: '오박사', department: '영업팀'),
  ];

  @override
  Future<VerifyResponse> verify(VerifyRequest req) async {
    lastRequest = req;
    await Future<void>.delayed(const Duration(milliseconds: 50));
    return const VerifyResponse(
      score: 0.91,
      threshold: 0.3423501253128052,
      passed: true,
      latencyMs: 50,
      gestureId: 'G1',
      gestureScore: 0.97,
      gestureThreshold: 0.9020317792892456,
    );
  }

  @override
  Future<Never> enroll(_) => throw UnimplementedError();
  @override
  Future<Never> fetchAuthLogs() => throw UnimplementedError();
  @override
  Future<Never> fetchMonthlyStats() => throw UnimplementedError();

  /// 디버그 로그는 테스트에서 쓰지 않는다. 받기만 하고 버린다.
  @override
  Future<void> sendChallengeDebug({
    required String sessionId,
    required List<String> lines,
  }) async {}
}

void main() {
  test('kUseFakeLandmarks 경로로 idle→done 전체 흐름이 끝까지 진행된다', () async {
    final api = _AlwaysPassApi();
    final container = ProviderContainer(
      overrides: [
        apiClientProvider.overrideWithValue(api),
        fakeLandmarkSourceOverride,
      ],
    );
    addTearDown(container.dispose);

    final seen = <AuthPhase>[];
    container.listen(
      authFlowProvider.select((s) => s.phase),
      (_, next) => seen.add(next),
      fireImmediately: true,
    );

    final controller = container.read(authFlowProvider.notifier);
    await controller.attach();

    expect(container.read(authFlowProvider).phase, AuthPhase.idle);
    expect(container.read(authFlowProvider).message, '수어 암호를 입력하세요');

    controller.start();
    expect(container.read(authFlowProvider).phase, AuthPhase.handSearching);

    // handSearching → handReady → 카운트다운 → recording → uploading → done
    final deadline = DateTime.now().add(const Duration(seconds: 20));
    while (container.read(authFlowProvider).phase != AuthPhase.done) {
      if (DateTime.now().isAfter(deadline)) {
        fail('흐름이 done까지 도달하지 못했다. 마지막 상태: '
            '${container.read(authFlowProvider).phase}');
      }
      await Future<void>.delayed(const Duration(milliseconds: 50));
    }

    // 6개 상태를 모두 거쳤는지.
    expect(seen, containsAllInOrder(<AuthPhase>[
      AuthPhase.idle,
      AuthPhase.handSearching,
      AuthPhase.handReady,
      AuthPhase.recording,
      AuthPhase.uploading,
      AuthPhase.done,
    ]));

    final res = container.read(authFlowProvider).response;
    expect(res, isNotNull);
    expect(res!.passed, isTrue);
    // threshold는 응답에서 온 값이어야 한다.
    expect(res.threshold, 0.3423501253128052);
  }, timeout: const Timeout(Duration(seconds: 40)));

  test('전송 요청의 tMs가 실제 경과 시간이고 균등 간격이 아니다', () async {
    final api = _AlwaysPassApi();
    final container = ProviderContainer(
      overrides: [
        apiClientProvider.overrideWithValue(api),
        fakeLandmarkSourceOverride,
      ],
    );
    addTearDown(container.dispose);

    // authFlowProvider는 autoDispose라 구독자가 없으면 바로 폐기된다.
    // 실제 앱에서는 화면이 watch하므로 살아 있지만, 테스트에서는 명시적으로
    // 구독을 잡아 줘야 타이머가 유지된다.
    final sub = container.listen(authFlowProvider, (_, _) {});
    addTearDown(sub.close);

    final controller = container.read(authFlowProvider.notifier);
    await controller.attach();
    controller.start();

    final deadline = DateTime.now().add(const Duration(seconds: 20));
    while (container.read(authFlowProvider).phase != AuthPhase.done) {
      if (DateTime.now().isAfter(deadline)) fail('done까지 도달하지 못했다');
      await Future<void>.delayed(const Duration(milliseconds: 50));
    }

    final req = api.lastRequest;
    expect(req, isNotNull);
    expect(req!.frames.length, greaterThanOrEqualTo(kMinFramesForVerify));
    expect(req.nominalFps, kNominalFps);
    expect(req.durationMs, kRecordDuration.inMilliseconds);

    // 녹화 시작 시점을 0으로 다시 잡았으므로 첫 프레임은 0에 가깝다.
    expect(req.frames.first.tMs, lessThan(200));
    // 마지막 프레임은 녹화 길이를 넘지 않는다.
    expect(req.frames.last.tMs,
        lessThanOrEqualTo(kRecordDuration.inMilliseconds + 100));

    // 인덱스×33이었다면 간격이 전부 33으로 같았을 것이다.
    final gaps = <int>{
      for (var i = 1; i < req.frames.length; i++)
        req.frames[i].tMs - req.frames[i - 1].tMs,
    };
    expect(gaps.length, greaterThan(1),
        reason: 'tMs가 계산된 값이 아니라 실제 타임스탬프여야 한다');

    // 좌표가 [0,1] 원본 범위를 벗어나지 않았는지 = 전처리가 없었는지.
    for (final f in req.frames) {
      expect(f.landmarks.length, 21);
      for (final lm in f.landmarks) {
        expect(lm.x, inInclusiveRange(0.0, 1.0));
        expect(lm.y, inInclusiveRange(0.0, 1.0));
      }
    }
  }, timeout: const Timeout(Duration(seconds: 40)));

  test('목 API는 프레임이 부족하면 서버처럼 422 사유 코드로 거절한다', () async {
    // 시드를 고정해 5% 타임아웃에 걸리지 않게 한다.
    final api = MockApiClient(seed: 7);
    final call = api.verify(
      VerifyRequest(
        userId: 'kim',
        gestureId: 'G1',
        camera: const CameraInfo(width: 720, height: 1280),
        capturedAt: DateTime(2026, 8, 24),
        nominalFps: kNominalFps,
        durationMs: 2000,
        frames: const [],
      ),
    );
    await expectLater(
      call,
      throwsA(
        isA<ApiException>()
            .having((e) => e.reason, 'reason', 'insufficient_valid_frames')
            .having((e) => e.statusCode, 'statusCode', 422)
            .having((e) => e.userMessage, 'userMessage', '손이 잘 보이도록 다시 시도해주세요.'),
      ),
    );
  });

  test('목 API는 응답 지연을 흉내 낸다', () async {
    final api = MockApiClient(seed: 7);
    final sw = Stopwatch()..start();
    await api.fetchAuthLogs();
    sw.stop();
    expect(sw.elapsedMilliseconds, greaterThan(300));
  });

  test('목 API가 타임아웃을 던지는 경우가 있다', () async {
    // 5% 확률이므로 여러 번 돌려 최소 한 번은 나오는지 본다.
    var timeouts = 0;
    for (var seed = 0; seed < 60; seed++) {
      try {
        await MockApiClient(seed: seed).verify(
          VerifyRequest(
            userId: 'kim',
            gestureId: 'G1',
            camera: const CameraInfo(width: 720, height: 1280),
            capturedAt: DateTime(2026, 8, 24),
            nominalFps: kNominalFps,
            durationMs: 2000,
            frames: const [],
          ),
        );
      } on Object {
        timeouts++;
      }
    }
    expect(timeouts, greaterThan(0), reason: '에러 UI를 확인할 경로가 있어야 한다');
  }, timeout: const Timeout(Duration(seconds: 180)));
}

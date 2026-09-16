import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:signid/core/config.dart';
import 'package:signid/models/enroll.dart';
import 'package:signid/models/server_config.dart';
import 'package:signid/models/verify.dart';
import 'package:signid/services/api_client.dart';
import 'package:signid/state/enroll_controller.dart';
import 'package:signid/state/providers.dart';

import 'test_helpers.dart';

class _RecordingApi implements ApiClient {
  EnrollRequest? lastEnroll;

  @override
  Future<ServerConfig> fetchConfig() async => ServerConfig.fallback;

  @override
  Future<EnrollResponse> enroll(EnrollRequest req) async {
    lastEnroll = req;
    return EnrollResponse(
      enrolled: true,
      userId: req.userId,
      gestureId: req.gestureId,
      takeCount: req.takes.length,
      required: req.takes.length,
      modelVersion: 'test',
    );
  }

  @override
  Future<VerifyResponse> verify(_) => throw UnimplementedError();
  @override
  Future<Never> fetchAuthLogs() => throw UnimplementedError();
  @override
  Future<Never> fetchMonthlyStats() => throw UnimplementedError();
}

void main() {
  test('등록은 서버가 정한 회차만큼 모아 한 번에 전송한다', () async {
    final api = _RecordingApi();
    final container = ProviderContainer(
      overrides: [
        apiClientProvider.overrideWithValue(api),
        fakeLandmarkSourceOverride,
      ],
    );
    addTearDown(container.dispose);

    // autoDispose라 구독이 없으면 폐기된다. 실제 앱에서는 화면이 watch한다.
    final sub = container.listen(enrollProvider, (_, _) {});
    addTearDown(sub.close);

    final controller = container.read(enrollProvider.notifier);
    await controller.attach();
    controller.start();

    // 회차당 대략 (탐색 + 카운트다운 3s + 녹화 2s + 대기 1.5s).
    final deadline = DateTime.now().add(const Duration(seconds: 90));
    while (container.read(enrollProvider).phase != EnrollPhase.done) {
      if (DateTime.now().isAfter(deadline)) {
        fail('등록이 완료되지 않았다. 마지막 상태: '
            '${container.read(enrollProvider).phase} '
            '완료 회차: ${container.read(enrollProvider).completedTakes}');
      }
      await Future<void>.delayed(const Duration(milliseconds: 100));
    }

    final req = api.lastEnroll;
    expect(req, isNotNull);
    expect(req!.takes.length, kDefaultEnrollTakes);
    // takeNo는 1..N이 모두 있어야 서버가 받아들인다.
    expect(
      req.takes.map((t) => t.takeNo).toList(),
      List<int>.generate(kDefaultEnrollTakes, (i) => i + 1),
    );
    expect(req.gestureId, kDefaultGestureId);
    expect(req.camera.width, greaterThan(0));
    expect(req.camera.height, greaterThan(0));
    for (final take in req.takes) {
      expect(take.frames.length, greaterThanOrEqualTo(kMinFramesForVerify));
      // 회차마다 tMs가 0부터 다시 시작해야 한다.
      expect(take.frames.first.tMs, lessThan(200));
      expect(
        take.frames.last.tMs,
        lessThanOrEqualTo(kRecordDuration.inMilliseconds + 100),
      );
    }

    final state = container.read(enrollProvider);
    expect(state.completedTakes, kDefaultEnrollTakes);
    expect(state.response?.enrolled, isTrue);
  }, timeout: const Timeout(Duration(seconds: 120)));
}

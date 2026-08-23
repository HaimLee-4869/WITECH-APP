import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:signid/core/config.dart';
import 'package:signid/models/enroll.dart';
import 'package:signid/models/verify.dart';
import 'package:signid/services/api_client.dart';
import 'package:signid/state/enroll_controller.dart';
import 'package:signid/state/providers.dart';

class _RecordingApi implements ApiClient {
  EnrollRequest? lastEnroll;

  @override
  Future<EnrollResponse> enroll(EnrollRequest req) async {
    lastEnroll = req;
    return EnrollResponse(
      enrolled: true,
      acceptedTakes: req.takes.length,
      templateId: 'tpl_test',
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
  test('등록은 같은 제스처를 5회 모아 한 번에 전송한다', () async {
    final api = _RecordingApi();
    final container = ProviderContainer(
      overrides: [apiClientProvider.overrideWithValue(api)],
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
    expect(req!.takes.length, kEnrollRepeatCount);
    for (final take in req.takes) {
      expect(take.length, greaterThanOrEqualTo(kMinFramesForVerify));
      // 회차마다 tMs가 0부터 다시 시작해야 한다.
      expect(take.first.tMs, lessThan(200));
      expect(
        take.last.tMs,
        lessThanOrEqualTo(kRecordDuration.inMilliseconds + 100),
      );
    }

    final state = container.read(enrollProvider);
    expect(state.completedTakes, kEnrollRepeatCount);
    expect(state.response?.enrolled, isTrue);
  }, timeout: const Timeout(Duration(seconds: 120)));
}

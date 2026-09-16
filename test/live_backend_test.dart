import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:signid/core/config.dart';
import 'package:signid/models/api_error.dart';
import 'package:signid/models/camera_info.dart';
import 'package:signid/models/enroll.dart';
import 'package:signid/models/landmark.dart';
import 'package:signid/models/verify.dart';
import 'package:signid/services/http_api_client.dart';

/// 실제로 띄운 백엔드에 붙어보는 연결 확인. 기본은 건너뛴다.
///
/// ```
/// flutter test test/live_backend_test.dart \
///   --dart-define=SIGNID_LIVE_TEST=1 \
///   --dart-define=SIGNID_API_BASE=http://127.0.0.1:8765
/// ```
///
/// 서버에 `kim` 사용자가 있어야 한다. (`POST /users`)
const bool _live = bool.fromEnvironment('SIGNID_LIVE_TEST');

List<HandFrame> _frames({int seed = 0, int n = 40, int spanMs = 2000}) {
  final rnd = Random(seed);
  final base = List<List<double>>.generate(
    21,
    (_) => [0.3 + rnd.nextDouble() * 0.4, 0.3 + rnd.nextDouble() * 0.4, rnd.nextDouble() * 0.02],
  );
  return [
    for (var i = 0; i < n; i++)
      HandFrame(
        tMs: (i * spanMs / (n - 1)).round(),
        landmarks: [
          for (final p in base)
            Landmark(
              p[0] + 0.05 * sin(i / 5),
              p[1] + 0.03 * cos(i / 6),
              p[2],
            ),
        ],
        score: 0.95,
      ),
  ];
}

void main() {
  final api = HttpApiClient(baseUrl: kApiBaseUrl);
  const camera = CameraInfo(width: 720, height: 1280);
  const gesture = 'G3';

  test('GET /config', () async {
    final config = await api.fetchConfig();
    expect(config.enrollmentTakes, greaterThan(0));
    expect(config.modelVersion, isNotEmpty);
    // ignore: avoid_print
    print('config: takes=${config.enrollmentTakes} hand=${config.handRequired} '
        'model=${config.modelVersion}');
  }, skip: !_live);

  test('등록 → 같은 입력으로 인증하면 통과한다', () async {
    final config = await api.fetchConfig();
    final enrolled = await api.enroll(
      EnrollRequest(
        userId: 'kim',
        gestureId: gesture,
        camera: camera,
        takes: [
          for (var i = 1; i <= config.enrollmentTakes; i++)
            EnrollTake(
              takeNo: i,
              capturedAt: DateTime.now(),
              nominalFps: kNominalFps,
              durationMs: 2000,
              frames: _frames(), // 3회 모두 같은 입력
            ),
        ],
      ),
    );
    expect(enrolled.enrolled, isTrue);
    expect(enrolled.takeCount, config.enrollmentTakes);

    final res = await api.verify(
      VerifyRequest(
        userId: 'kim',
        gestureId: gesture,
        camera: camera,
        capturedAt: DateTime.now(),
        nominalFps: kNominalFps,
        durationMs: 2000,
        frames: _frames(),
      ),
    );
    // ignore: avoid_print
    print('verify: score=${res.score} passed=${res.passed} '
        'predicted=${res.predictedGesture} threshold=${res.threshold} '
        'model=${res.modelVersion} ${res.latencyMs}ms');
    expect(res.passed, isTrue);
    expect(res.score, closeTo(1.0, 1e-4));
    expect(res.gestureId, gesture);
  }, skip: !_live);

  test('무관한 입력은 거부되고 score가 채워진다', () async {
    final res = await api.verify(
      VerifyRequest(
        userId: 'kim',
        gestureId: gesture,
        camera: camera,
        capturedAt: DateTime.now(),
        nominalFps: kNominalFps,
        durationMs: 2000,
        frames: _frames(seed: 99),
      ),
    );
    // ignore: avoid_print
    print('unrelated: score=${res.score} passed=${res.passed} reason=${res.reason}');
    expect(res.passed, isFalse);
    expect(res.reason, 'below_threshold');
  }, skip: !_live);

  test('등록 안 한 수어 암호는 no_template, score는 null', () async {
    final res = await api.verify(
      VerifyRequest(
        userId: 'kim',
        gestureId: 'G5',
        camera: camera,
        capturedAt: DateTime.now(),
        nominalFps: kNominalFps,
        durationMs: 2000,
        frames: _frames(),
      ),
    );
    expect(res.reason, 'no_template');
    expect(res.score, isNull);
  }, skip: !_live);

  test('프레임이 모자라면 422 사유 코드로 온다', () async {
    await expectLater(
      api.verify(
        VerifyRequest(
          userId: 'kim',
          gestureId: gesture,
          camera: camera,
          capturedAt: DateTime.now(),
          nominalFps: kNominalFps,
          durationMs: 400,
          frames: _frames(n: 5, spanMs: 400),
        ),
      ),
      throwsA(
        isA<ApiException>().having((e) => e.reason, 'reason', 'too_few_frames'),
      ),
    );
  }, skip: !_live);

  test('왼손 프레임은 wrong_hand로 거절된다', () async {
    final left = [
      for (final f in _frames())
        HandFrame(
          tMs: f.tMs,
          landmarks: f.landmarks,
          handedness: 'Left',
          score: f.score,
        ),
    ];
    await expectLater(
      api.verify(
        VerifyRequest(
          userId: 'kim',
          gestureId: gesture,
          camera: camera,
          capturedAt: DateTime.now(),
          nominalFps: kNominalFps,
          durationMs: 2000,
          frames: left,
        ),
      ),
      throwsA(
        isA<ApiException>()
            .having((e) => e.reason, 'reason', 'wrong_hand')
            .having((e) => e.userMessage, 'userMessage', contains('오른손')),
      ),
    );
  }, skip: !_live);

  test('camera를 빼면 서버가 missing_camera_size로 거절한다', () async {
    // 앱은 항상 보내지만, 서버 계약을 확인한다.
    final api2 = HttpApiClient(baseUrl: kApiBaseUrl);
    await expectLater(
      api2.verify(
        VerifyRequest(
          userId: 'kim',
          gestureId: gesture,
          camera: const CameraInfo(width: 0, height: 0),
          capturedAt: DateTime.now(),
          nominalFps: kNominalFps,
          durationMs: 2000,
          frames: _frames(),
        ),
      ),
      throwsA(
        isA<ApiException>().having((e) => e.reason, 'reason', 'missing_camera_size'),
      ),
    );
  }, skip: !_live);
}

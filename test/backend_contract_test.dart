import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:signid/core/config.dart';
import 'package:signid/models/api_error.dart';
import 'package:signid/models/camera_info.dart';
import 'package:signid/models/enroll.dart';
import 'package:signid/models/landmark.dart';
import 'package:signid/models/server_config.dart';
import 'package:signid/models/verify.dart';
import 'package:signid/services/http_api_client.dart';

/// 백엔드 규격(backend/README 4·5장)과 앱 직렬화가 어긋나지 않는지 고정한다.
///
/// 서버를 띄우지 않고 [http.Client]를 가로채 요청 본문을 직접 본다.

List<HandFrame> _frames({String? handedness}) => [
  for (var i = 0; i < 10; i++)
    HandFrame(
      tMs: i * 100,
      landmarks: List<Landmark>.generate(21, (j) => Landmark(0.4 + j * 0.01, 0.5, 0.0)),
      handedness: handedness,
      score: 0.9,
    ),
];

/// 요청을 기록하고 정해진 응답을 돌려주는 가짜 전송 계층.
class _FakeClient extends http.BaseClient {
  final int statusCode;
  final Object body;

  http.BaseRequest? lastRequest;
  String? lastBody;

  _FakeClient({this.statusCode = 200, this.body = const <String, dynamic>{}});

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    lastRequest = request;
    if (request is http.Request) lastBody = request.body;
    return http.StreamedResponse(
      Stream.value(utf8.encode(jsonEncode(body))),
      statusCode,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );
  }
}

void main() {
  group('요청 직렬화', () {
    test('/verify 본문이 백엔드 스키마와 일치한다', () async {
      final fake = _FakeClient(
        body: {
          'score': 0.71,
          'threshold': 0.6275163888931274,
          'passed': true,
          'reason': null,
          'predictedGesture': 'G2',
          'gestureConfidence': 0.81,
          'gestureId': 'G3',
          'modelVersion': 'handonly-supcon-v1.0.0',
          'latencyMs': 42,
        },
      );
      final api = HttpApiClient(baseUrl: 'http://server:8000', client: fake);

      final res = await api.verify(
        VerifyRequest(
          userId: 'kim',
          gestureId: 'G3',
          camera: const CameraInfo(width: 720, height: 1280),
          capturedAt: DateTime.utc(2026, 9, 16, 1, 39, 1),
          nominalFps: kNominalFps,
          durationMs: 2000,
          frames: _frames(),
        ),
      );

      // 경로에 /v1 접두사가 없어야 한다.
      expect(fake.lastRequest!.url.path, '/verify');
      final sent = jsonDecode(fake.lastBody!) as Map<String, dynamic>;
      expect(sent['userId'], 'kim');
      expect(sent['gestureId'], 'G3');
      expect(sent['camera'], {'width': 720, 'height': 1280});
      expect(sent['nominalFps'], kNominalFps);
      expect(sent['durationMs'], 2000);
      final frames = sent['frames'] as List<dynamic>;
      expect(frames.length, 10);
      final first = frames.first as Map<String, dynamic>;
      expect(first['tMs'], 0);
      expect((first['lm'] as List<dynamic>).length, 21);
      expect((first['lm'] as List<dynamic>).first, hasLength(3));

      expect(res.score, 0.71);
      expect(res.gestureId, 'G3');
      expect(res.predictedGesture, 'G2');
      expect(res.modelVersion, 'handonly-supcon-v1.0.0');
    });

    test('handedness를 모르면 프레임에서 키 자체를 빼고 보낸다', () async {
      final fake = _FakeClient(body: {'passed': false, 'latencyMs': 1});
      final api = HttpApiClient(baseUrl: 'http://server:8000', client: fake);

      await api.verify(
        VerifyRequest(
          userId: 'kim',
          gestureId: 'G1',
          camera: const CameraInfo(width: 720, height: 1280),
          capturedAt: DateTime.utc(2026, 9, 16),
          nominalFps: kNominalFps,
          durationMs: 2000,
          frames: _frames(), // handedness: null
        ),
      );

      final sent = jsonDecode(fake.lastBody!) as Map<String, dynamic>;
      final first = (sent['frames'] as List<dynamic>).first as Map<String, dynamic>;
      // 'Right'로 채워 보내면 실제 왼손을 오른손으로 위장하게 된다. 모르면 안 보낸다.
      expect(first.containsKey('handedness'), isFalse);
    });

    test('플러그인이 handedness를 주면 그대로 실어 보낸다', () async {
      final fake = _FakeClient(body: {'passed': true, 'latencyMs': 1});
      final api = HttpApiClient(baseUrl: 'http://server:8000', client: fake);

      await api.verify(
        VerifyRequest(
          userId: 'kim',
          gestureId: 'G1',
          camera: const CameraInfo(width: 720, height: 1280),
          capturedAt: DateTime.utc(2026, 9, 16),
          nominalFps: kNominalFps,
          durationMs: 2000,
          frames: _frames(handedness: 'Right'),
        ),
      );

      final sent = jsonDecode(fake.lastBody!) as Map<String, dynamic>;
      final first = (sent['frames'] as List<dynamic>).first as Map<String, dynamic>;
      expect(first['handedness'], 'Right');
    });

    test('capturedAt은 오프셋을 포함해 보낸다', () {
      final withOffset = iso8601WithOffset(
        DateTime.parse('2026-09-16T10:39:01+09:00').toLocal(),
      );
      expect(withOffset, matches(r'[+-]\d{2}:\d{2}$'));
    });

    test('/enroll 본문이 takeNo 1..N을 포함한다', () async {
      final fake = _FakeClient(
        body: {
          'enrolled': true,
          'userId': 'kim',
          'gestureId': 'G3',
          'takeCount': 3,
          'required': 3,
          'modelVersion': 'handonly-supcon-v1.0.0',
        },
      );
      final api = HttpApiClient(baseUrl: 'http://server:8000', client: fake);

      final res = await api.enroll(
        EnrollRequest(
          userId: 'kim',
          gestureId: 'G3',
          camera: const CameraInfo(width: 720, height: 1280),
          takes: [
            for (var i = 1; i <= 3; i++)
              EnrollTake(
                takeNo: i,
                capturedAt: DateTime.utc(2026, 9, 16),
                nominalFps: kNominalFps,
                durationMs: 2000,
                frames: _frames(),
              ),
          ],
        ),
      );

      expect(fake.lastRequest!.url.path, '/enroll');
      final sent = jsonDecode(fake.lastBody!) as Map<String, dynamic>;
      expect(sent['gestureId'], 'G3');
      expect(sent['camera'], {'width': 720, 'height': 1280});
      final takes = sent['takes'] as List<dynamic>;
      expect(takes.map((t) => (t as Map<String, dynamic>)['takeNo']), [1, 2, 3]);
      expect((takes.first as Map<String, dynamic>)['durationMs'], 2000);
      expect(res.takeCount, 3);
      expect(res.required, 3);
    });
  });

  group('응답 처리', () {
    test('score가 null이어도 파싱된다 (비교를 하지 않은 경우)', () {
      final res = VerifyResponse.fromJson(const {
        'score': null,
        'threshold': 0.6275163888931274,
        'passed': false,
        'reason': 'no_template',
        'predictedGesture': 'G2',
        'gestureConfidence': 0.9,
        'gestureId': 'G1',
        'modelVersion': 'handonly-supcon-v1.0.0',
        'latencyMs': 7,
      });
      expect(res.score, isNull);
      expect(res.threshold, isNotNull);
      expect(res.reason, 'no_template');
    });

    test('422 응답은 사유 코드를 담은 ApiException이 된다', () async {
      final fake = _FakeClient(
        statusCode: 422,
        body: {
          'detail': {
            'code': 'invalid_sequence',
            'reason': 'wrong_hand',
            'message': '오른손을 사용해주세요. 이 모델은 오른손 동작만 인식합니다.',
          },
        },
      );
      final api = HttpApiClient(baseUrl: 'http://server:8000', client: fake);

      await expectLater(
        api.verify(
          VerifyRequest(
            userId: 'kim',
            gestureId: 'G1',
            camera: const CameraInfo(width: 720, height: 1280),
            capturedAt: DateTime.utc(2026, 9, 16),
            nominalFps: kNominalFps,
            durationMs: 2000,
            frames: _frames(handedness: 'Left'),
          ),
        ),
        throwsA(
          isA<ApiException>()
              .having((e) => e.reason, 'reason', 'wrong_hand')
              .having((e) => e.userMessage, 'userMessage', contains('오른손을 사용해주세요'))
              .having((e) => e.isRetryableCapture, 'isRetryableCapture', isTrue),
        ),
      );
    });

    test('등록 422는 몇 회차가 문제인지 안내에 담는다', () {
      const e = ApiException(
        code: 'invalid_sequence',
        reason: 'too_few_frames',
        serverMessage: '촬영된 프레임이 너무 적습니다.',
        takeNo: 2,
        statusCode: 422,
      );
      expect(e.userMessage, startsWith('2회차: '));
    });

    test('사유 코드별 안내 문구가 backend README 5장과 맞는다', () {
      expect(messageForReason('wrong_hand'), contains('오른손을 사용해주세요'));
      expect(messageForReason('insufficient_valid_frames'), '손이 잘 보이도록 다시 시도해주세요.');
      expect(messageForReason('duration_too_short'), '조금 더 천천히 동작해주세요.');
      for (final reason in const [
        'too_few_frames',
        'non_monotonic_timestamps',
        'missing_camera_size',
        'malformed_landmarks',
        'gesture_id_required',
        'take_count_mismatch',
        'unknown_gesture',
        'user_not_found',
        'model_version_mismatch',
        'no_active_threshold',
      ]) {
        expect(messageForReason(reason), isNotNull, reason: '$reason 안내 문구 없음');
      }
      // 모르는 코드는 서버 문구로 대체된다.
      expect(messageForReason('brand_new_reason'), isNull);
      const unknown = ApiException(
        code: 'invalid_sequence',
        reason: 'brand_new_reason',
        serverMessage: '서버가 준 설명',
        statusCode: 422,
      );
      expect(unknown.userMessage, '서버가 준 설명');
    });

    test('/config를 파싱해 등록 회차 수를 얻는다', () async {
      final fake = _FakeClient(
        body: {
          'enrollmentTakes': 3,
          'enrollmentGestures': 1,
          'captureDurationMs': 2000,
          'handRequired': 'right',
          'modelVersion': 'handonly-supcon-v1.0.0',
        },
      );
      final api = HttpApiClient(baseUrl: 'http://server:8000', client: fake);
      final config = await api.fetchConfig();

      expect(fake.lastRequest!.url.path, '/config');
      expect(config.enrollmentTakes, 3);
      expect(config.requiresRightHand, isTrue);
      expect(config.modelVersion, 'handonly-supcon-v1.0.0');
    });

    test('/logs와 /stats/monthly를 관리자 화면 모델로 바꾼다', () async {
      final logs = _FakeClient(
        body: {
          'items': [
            {
              'id': 3,
              'userId': 'kim',
              'userName': '김길동',
              'department': '인사팀',
              'passed': false,
              'failReason': 'below_threshold',
              'createdAt': '2026-09-16T01:39:01.123456+00:00',
            },
          ],
          'total': 1,
          'limit': 100,
          'offset': 0,
        },
      );
      final api = HttpApiClient(baseUrl: 'http://server:8000', client: logs);
      final rows = await api.fetchAuthLogs();
      expect(logs.lastRequest!.url.path, '/logs');
      expect(rows.single.userName, '김길동');
      expect(rows.single.failReason, 'below_threshold');
      expect(rows.single.timestamp.isUtc, isFalse); // 로컬 시각으로 변환

      final stats = _FakeClient(
        body: [
          {'month': '2026-08', 'total': 54, 'passed': 42, 'failed': 12},
          {'month': '2026-09', 'total': 35, 'passed': 32, 'failed': 3},
        ],
      );
      final api2 = HttpApiClient(baseUrl: 'http://server:8000', client: stats);
      final monthly = await api2.fetchMonthlyStats();
      expect(stats.lastRequest!.url.path, '/stats/monthly');
      expect(monthly.last.month, '2026-09');
      expect(monthly.last.monthNumber, 9);
      expect(monthly.last.total, 35);
    });
  });

  test('서버 주소가 없으면 무엇을 해야 하는지 알려준다', () async {
    final api = HttpApiClient(baseUrl: '', client: _FakeClient());
    await expectLater(
      api.fetchConfig(),
      throwsA(
        isA<ApiNotConfiguredException>().having(
          (e) => e.message,
          'message',
          contains('SIGNID_API_BASE'),
        ),
      ),
    );
  });

  test('ServerConfig 기본값은 앱 상수와 같다', () {
    expect(ServerConfig.fallback.enrollmentTakes, kDefaultEnrollTakes);
    expect(ServerConfig.fallback.requiresRightHand, isTrue);
  });
}

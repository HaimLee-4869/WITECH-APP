import 'dart:async';
import 'dart:math';

import '../core/config.dart';
import '../models/auth_log.dart';
import '../models/enroll.dart';
import '../models/verify.dart';
import 'api_client.dart';

/// 서버 응답을 흉내 내는 목 구현. (SPEC 9장)
///
/// 즉시 반환하면 로딩 UI를 테스트할 수 없으므로 반드시 지연을 넣는다.
class MockApiClient implements ApiClient {
  /// 흉내 낼 네트워크 왕복 시간.
  static const Duration _latency = Duration(milliseconds: 1200);

  /// 서버가 소유하는 판정 임계값.
  ///
  /// **앱 코드 어디에서도 이 값을 읽어 판정하지 않는다.** 오직 응답에 실어
  /// 보내기만 하고, 판정 결과는 서버(여기서는 목)가 계산한 `passed`를 쓴다.
  /// 운영 중 조정 가능해야 하기 때문이다. (SPEC 6/9장)
  static const double _serverThreshold = 0.72;

  /// 에러 UI를 확인할 수 있도록 이 확률로 타임아웃을 던진다. (SPEC 9장)
  static const double _timeoutRate = 0.05;

  final Random _random;

  /// [seed]를 주면 결정적으로 동작한다. 테스트에서 사용.
  MockApiClient({int? seed}) : _random = Random(seed);

  @override
  Future<VerifyResponse> verify(VerifyRequest req) async {
    await Future<void>.delayed(_latency);

    if (_random.nextDouble() < _timeoutRate) {
      throw TimeoutException('서버 응답이 없습니다', _latency);
    }

    // 프레임 수가 너무 적으면 실패. 컨트롤러에서도 걸러내지만, 서버가 최종
    // 책임을 지는 구조라 여기서도 검사한다.
    if (req.frames.length < kMinFramesForVerify) {
      return VerifyResponse(
        score: 0.0,
        threshold: _serverThreshold,
        passed: false,
        latencyMs: _latency.inMilliseconds,
        reason: 'insufficient_frames',
      );
    }

    final score = 0.55 + _random.nextDouble() * 0.40;
    return VerifyResponse(
      score: score,
      threshold: _serverThreshold,
      passed: score >= _serverThreshold,
      latencyMs: _latency.inMilliseconds,
    );
  }

  @override
  Future<EnrollResponse> enroll(EnrollRequest req) async {
    await Future<void>.delayed(_latency);

    if (_random.nextDouble() < _timeoutRate) {
      throw TimeoutException('서버 응답이 없습니다', _latency);
    }

    // 회차마다 최소 프레임 수를 만족해야 유효한 샘플로 친다.
    final accepted = req.takes
        .where((take) => take.length >= kMinFramesForVerify)
        .length;

    if (accepted < req.takes.length) {
      return EnrollResponse(
        enrolled: false,
        acceptedTakes: accepted,
        reason: 'insufficient_frames',
      );
    }

    return EnrollResponse(
      enrolled: true,
      acceptedTakes: accepted,
      templateId: 'tpl_${req.userId}_${req.capturedAt.millisecondsSinceEpoch}',
    );
  }

  @override
  Future<List<AuthLog>> fetchAuthLogs() async {
    await Future<void>.delayed(const Duration(milliseconds: 600));
    return _mockLogs;
  }

  @override
  Future<List<MonthlyStat>> fetchMonthlyStats() async {
    await Future<void>.delayed(const Duration(milliseconds: 600));
    return _mockMonthly;
  }
}

/// 목업 표의 행. 스크롤이 되는지 확인하려고 12행 이상 넣었다. (SPEC 8.5)
final List<AuthLog> _mockLogs = <AuthLog>[
  _log('홍길동', '개발팀', '2026-08-24 10:38:55', true),
  _log('김길동', '인사팀', '2026-08-24 10:38:55', true),
  _log('오박사', '개발팀', '2026-08-24 10:39:01', true),
  _log('둘리', '영업팀', '2026-08-24 10:39:01', false),
  _log('또치', '개발팀', '2026-08-24 10:39:01', true),
  _log('고길동', '개발팀', '2026-08-24 10:39:01', true),
  _log('홍길동', '개발팀', '2026-08-24 10:41:12', true),
  _log('둘리', '영업팀', '2026-08-24 10:42:03', false),
  _log('마이콜', '영업팀', '2026-08-24 10:43:27', true),
  _log('김길동', '인사팀', '2026-08-24 10:44:10', true),
  _log('또치', '개발팀', '2026-08-24 10:45:38', false),
  _log('오박사', '개발팀', '2026-08-24 10:47:02', true),
  _log('고길동', '개발팀', '2026-08-24 10:48:19', true),
  _log('마이콜', '영업팀', '2026-08-24 10:51:44', true),
];

AuthLog _log(String name, String dept, String ts, bool passed) => AuthLog(
  userName: name,
  department: dept,
  timestamp: DateTime.parse(ts),
  passed: passed,
);

/// 목업 차트의 1~5월 데이터. Y축 0~500 범위에 들어가도록 잡았다. (SPEC 8.5)
const List<MonthlyStat> _mockMonthly = <MonthlyStat>[
  MonthlyStat(month: 1, count: 120),
  MonthlyStat(month: 2, count: 180),
  MonthlyStat(month: 3, count: 240),
  MonthlyStat(month: 4, count: 285),
  MonthlyStat(month: 5, count: 330),
];

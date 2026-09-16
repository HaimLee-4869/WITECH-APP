import 'dart:async';
import 'dart:math';

import '../core/config.dart';
import '../models/api_error.dart';
import '../models/app_user.dart';
import '../models/auth_log.dart';
import '../models/enroll.dart';
import '../models/server_config.dart';
import '../models/verify.dart';
import 'api_client.dart';

/// 서버 응답을 흉내 내는 목 구현. (SPEC 9장)
///
/// 실제 백엔드와 **같은 형태**로 응답한다. 실패도 200이 아니라 [ApiException]으로
/// 던져서, 앱의 사유 코드 분기를 목 단계에서도 검증할 수 있게 한다.
///
/// 즉시 반환하면 로딩 UI를 테스트할 수 없으므로 반드시 지연을 넣는다.
class MockApiClient implements ApiClient {
  /// 흉내 낼 네트워크 왕복 시간.
  static const Duration _latency = Duration(milliseconds: 1200);

  /// 서버가 소유하는 판정 임계값. 실제 백엔드의 default 운영점과 같은 값.
  ///
  /// **앱 코드 어디에서도 이 값을 읽어 판정하지 않는다.** 응답에 실어 보내기만 하고,
  /// 판정은 서버(여기서는 목)가 계산한 `passed`를 쓴다. (SPEC 6/9장)
  static const double _userThreshold = 0.3423501253128052;    // Tu
  static const double _gestureThreshold = 0.9020317792892456; // Tg

  /// 에러 UI를 확인할 수 있도록 이 확률로 타임아웃을 던진다. (SPEC 9장)
  static const double _timeoutRate = 0.05;

  final Random _random;

  /// [seed]를 주면 결정적으로 동작한다. 테스트에서 사용.
  MockApiClient({int? seed}) : _random = Random(seed);

  @override
  Future<ServerConfig> fetchConfig() async {
    await Future<void>.delayed(const Duration(milliseconds: 300));
    return const ServerConfig(
      enrollmentTakes: kDefaultEnrollTakes,
      enrollmentGestures: 1,
      captureDurationMs: kRecordDurationMs,
      handRequired: 'right',
      modelVersion: 'mock-v0',
    );
  }

  @override
  Future<List<AppUser>> fetchUsers() async {
    await Future<void>.delayed(const Duration(milliseconds: 300));
    return List<AppUser>.unmodifiable(_mockUsers);
  }

  @override
  Future<AppUser> createUser({
    required String id,
    required String name,
    String? department,
  }) async {
    await Future<void>.delayed(const Duration(milliseconds: 400));
    if (_mockUsers.any((u) => u.id == id)) {
      // 실제 서버와 같은 형태로 던져서 앱의 재시도 경로를 목에서도 검증한다.
      throw const ApiException(
        code: 'conflict',
        reason: 'user_exists',
        serverMessage: '이미 존재하는 사용자 ID입니다.',
        statusCode: 409,
      );
    }
    final user = AppUser(id: id, name: name, department: department);
    _mockUsers.add(user);
    return user;
  }

  @override
  Future<VerifyResponse> verify(VerifyRequest req) async {
    await Future<void>.delayed(_latency);

    if (_random.nextDouble() < _timeoutRate) {
      throw TimeoutException('서버 응답이 없습니다', _latency);
    }

    // 프레임 수가 너무 적으면 서버가 422로 거절한다. 컨트롤러에서도 걸러내지만,
    // 서버가 최종 책임을 지는 구조라 여기서도 같은 형태로 던진다.
    if (req.frames.length < kMinFramesForVerify) {
      throw const ApiException(
        code: 'invalid_sequence',
        reason: 'insufficient_valid_frames',
        serverMessage: '손이 충분히 인식되지 않았습니다. 다시 시도해주세요.',
        statusCode: 422,
      );
    }

    // dual-head: 두 관문을 모두 넘어야 통과한다.
    final userScore = 0.20 + _random.nextDouble() * 0.75;
    final gestureScore = 0.80 + _random.nextDouble() * 0.20;
    final userPassed = userScore >= _userThreshold;
    final gesturePassed = gestureScore >= _gestureThreshold;
    return VerifyResponse(
      score: userScore,
      threshold: _userThreshold,
      gestureScore: gestureScore,
      gestureThreshold: _gestureThreshold,
      passed: userPassed && gesturePassed,
      latencyMs: _latency.inMilliseconds,
      reason: gesturePassed
          ? (userPassed ? null : 'below_threshold')
          : 'gesture_gate',
      gestureId: req.gestureId,
      modelVersion: 'mock-dual-head',
    );
  }

  @override
  Future<EnrollResponse> enroll(EnrollRequest req) async {
    await Future<void>.delayed(_latency);

    if (_random.nextDouble() < _timeoutRate) {
      throw TimeoutException('서버 응답이 없습니다', _latency);
    }

    // 회차 하나라도 부실하면 전체 거절. 부분 등록은 없다. (backend/README 4.3)
    for (final take in req.takes) {
      if (take.frames.length < kMinFramesForVerify) {
        throw ApiException(
          code: 'invalid_sequence',
          reason: 'too_few_frames',
          serverMessage: '촬영된 프레임이 너무 적습니다. 다시 시도해주세요.',
          takeNo: take.takeNo,
          statusCode: 422,
        );
      }
    }

    return EnrollResponse(
      enrolled: true,
      userId: req.userId,
      gestureId: req.gestureId,
      takeCount: req.takes.length,
      required: req.takes.length,
      modelVersion: 'mock-v0',
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

/// 목 사용자. id는 백엔드 `scripts/seed_demo_data.py`의 팀 사용자와 같다.
///
/// `createUser()`가 여기에 추가하므로 const가 아니다. 목 클라이언트 인스턴스마다
/// 공유되지만, 목 모드는 한 프로세스에 하나뿐이라 문제가 되지 않는다.
final List<AppUser> _mockUsers = <AppUser>[
  const AppUser(id: 'geonju', name: '김건주', department: '개발팀'),
  const AppUser(id: 'taerin', name: '김태린', department: 'AI팀'),
  const AppUser(id: 'seungyeon', name: '승연', department: 'AI팀'),
  const AppUser(id: 'hyemin', name: '황혜민', department: '개발팀'),
  const AppUser(id: 'eunjung', name: '이은정', department: '개발팀'),
];

/// 목업 표의 행. 스크롤이 되는지 확인하려고 12행 이상 넣었다. (SPEC 8.5)
final List<AuthLog> _mockLogs = <AuthLog>[
  _log('홍길동', '개발팀', '2026-08-24 10:38:55', true),
  _log('김길동', '인사팀', '2026-08-24 10:38:55', true),
  _log('오박사', '개발팀', '2026-08-24 10:39:01', true),
  _log('둘리', '영업팀', '2026-08-24 10:39:01', false, 'below_threshold'),
  _log('또치', '개발팀', '2026-08-24 10:39:01', true),
  _log('고길동', '개발팀', '2026-08-24 10:39:01', true),
  _log('홍길동', '개발팀', '2026-08-24 10:41:12', true),
  _log('둘리', '영업팀', '2026-08-24 10:42:03', false, 'no_template'),
  _log('마이콜', '영업팀', '2026-08-24 10:43:27', true),
  _log('김길동', '인사팀', '2026-08-24 10:44:10', true),
  _log('또치', '개발팀', '2026-08-24 10:45:38', false, 'invalid_input'),
  _log('오박사', '개발팀', '2026-08-24 10:47:02', true),
  _log('고길동', '개발팀', '2026-08-24 10:48:19', true),
  _log('마이콜', '영업팀', '2026-08-24 10:51:44', true),
];

AuthLog _log(
  String name,
  String dept,
  String ts,
  bool passed, [
  String? failReason,
]) => AuthLog(
  userName: name,
  department: dept,
  timestamp: DateTime.parse(ts),
  passed: passed,
  failReason: failReason,
);

/// 목업 차트 데이터. 서버 `GET /stats/monthly`와 같은 형태(YYYY-MM). (SPEC 8.5)
const List<MonthlyStat> _mockMonthly = <MonthlyStat>[
  MonthlyStat(month: '2026-01', total: 120, passed: 104, failed: 16),
  MonthlyStat(month: '2026-02', total: 180, passed: 158, failed: 22),
  MonthlyStat(month: '2026-03', total: 240, passed: 211, failed: 29),
  MonthlyStat(month: '2026-04', total: 285, passed: 255, failed: 30),
  MonthlyStat(month: '2026-05', total: 330, passed: 299, failed: 31),
];

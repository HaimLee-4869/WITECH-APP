import '../models/app_user.dart';
import '../models/auth_log.dart';
import '../models/enroll.dart';
import '../models/server_config.dart';
import '../models/verify.dart';

/// 서버 통신 추상 인터페이스. (SPEC 원칙 C)
///
/// 목 구현([MockApiClient])과 실제 구현([HttpApiClient])이 동일하게 구현한다.
/// 전환은 `config.dart`의 `kUseMockApi` 하나로만 이루어진다.
///
/// 실패는 [ApiException](서버가 사유 코드를 준 경우)이나 [TimeoutException]으로
/// 던진다. 호출자는 사유 코드로 안내 문구를 고른다. (backend/README 5장)
abstract class ApiClient {
  /// 앱 시작 시 호출해 등록 화면 구성값을 받아온다. (`GET /config`)
  Future<ServerConfig> fetchConfig();

  /// 홈 화면 사용자 선택 목록. (`GET /users`)
  ///
  /// 요청에는 [AppUser.id]를, 화면에는 [AppUser.name]을 쓴다.
  Future<List<AppUser>> fetchUsers();

  /// 사용자를 만든다. (`POST /users`)
  ///
  /// 로그인이 없으므로 [id]는 앱이 만들어 넘긴다([newUserId]). 이미 있는 ID면
  /// 서버가 409 `user_exists`를 주므로 호출자가 다시 만들어 재시도한다.
  Future<AppUser> createUser({
    required String id,
    required String name,
    String? department,
  });

  /// 수집한 제스처로 본인 여부를 판정한다.
  Future<VerifyResponse> verify(VerifyRequest req);

  /// 제스처를 등록한다.
  Future<EnrollResponse> enroll(EnrollRequest req);

  /// 관리자 화면 인증 이력.
  Future<List<AuthLog>> fetchAuthLogs();

  /// 관리자 화면 "월별 인증 현황" 차트 데이터.
  Future<List<MonthlyStat>> fetchMonthlyStats();

  /// Challenge 판정 로그를 서버에 남긴다 (개발용).
  ///
  /// 실패해도 Challenge를 막지 않는다. 호출자가 예외를 삼킨다.
  Future<void> sendChallengeDebug({
    required String sessionId,
    required List<String> lines,
  });
}

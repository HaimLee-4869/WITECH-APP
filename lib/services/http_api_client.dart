import '../models/auth_log.dart';
import '../models/enroll.dart';
import '../models/verify.dart';
import 'api_client.dart';

/// 실제 AI 서버 연동 구현. **아직 스텁이다.** (SPEC 9장)
///
/// `kUseMockApi = false`로 바꾸면 이 구현이 주입된다. 서버 스펙이 확정되면
/// 각 메서드 본문만 채우면 되고, 화면·컨트롤러 코드는 손대지 않는다.
///
/// 서버 주소와 키는 코드에 넣지 않는다. (SPEC 13장)
/// `--dart-define=SIGNID_API_BASE=https://...` 같은 빌드 시 주입으로 받는다.
class HttpApiClient implements ApiClient {
  /// 빌드 시 주입되는 API 베이스 URL. 기본값은 비워 둔다.
  static const String baseUrl = String.fromEnvironment('SIGNID_API_BASE');

  const HttpApiClient();

  @override
  Future<VerifyResponse> verify(VerifyRequest req) {
    // TODO(server): POST $baseUrl/v1/verify
    //   body = req.toJson() (SPEC 6장 전송 JSON 스키마)
    //   200 → VerifyResponse.fromJson, 4xx/5xx → 예외
    //   threshold는 반드시 응답에서 읽는다. 앱에서 만들지 않는다.
    throw UnimplementedError('AI 서버 연동 대기 중');
  }

  @override
  Future<EnrollResponse> enroll(EnrollRequest req) {
    // TODO(server): POST $baseUrl/v1/enroll
    //   body = req.toJson() — takes 배열 스키마는 서버 팀과 확정 필요
    throw UnimplementedError('AI 서버 연동 대기 중');
  }

  @override
  Future<List<AuthLog>> fetchAuthLogs() {
    // TODO(server): GET $baseUrl/v1/auth-logs
    throw UnimplementedError('AI 서버 연동 대기 중');
  }

  @override
  Future<List<MonthlyStat>> fetchMonthlyStats() {
    // TODO(server): GET $baseUrl/v1/stats/monthly
    throw UnimplementedError('AI 서버 연동 대기 중');
  }
}

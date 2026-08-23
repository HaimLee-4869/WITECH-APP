import '../models/auth_log.dart';
import '../models/enroll.dart';
import '../models/verify.dart';

/// 서버 통신 추상 인터페이스. (SPEC 원칙 C)
///
/// 목 구현([MockApiClient])과 실제 구현([HttpApiClient])이 동일하게 구현한다.
/// 전환은 `config.dart`의 `kUseMockApi` 하나로만 이루어진다.
abstract class ApiClient {
  /// 수집한 제스처로 본인 여부를 판정한다.
  ///
  /// 네트워크 지연·타임아웃을 던질 수 있다. 호출자는 [TimeoutException]과
  /// 그 외 예외를 구분해서 처리해야 한다.
  Future<VerifyResponse> verify(VerifyRequest req);

  /// 제스처를 등록한다.
  Future<EnrollResponse> enroll(EnrollRequest req);

  /// 관리자 화면 인증 이력.
  Future<List<AuthLog>> fetchAuthLogs();

  /// 관리자 화면 "월별 인증 현황" 차트 데이터.
  Future<List<MonthlyStat>> fetchMonthlyStats();
}

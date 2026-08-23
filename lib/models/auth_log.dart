/// 관리자 화면 인증 이력 1건.
class AuthLog {
  final String userName;
  final String department;
  final DateTime timestamp;
  final bool passed;

  const AuthLog({
    required this.userName,
    required this.department,
    required this.timestamp,
    required this.passed,
  });

  factory AuthLog.fromJson(Map<String, dynamic> json) => AuthLog(
    userName: json['userName'] as String,
    department: json['department'] as String,
    timestamp: DateTime.parse(json['timestamp'] as String),
    passed: json['passed'] as bool,
  );
}

/// 관리자 화면 "월별 인증 현황" 차트의 한 점.
///
/// SPEC 8.5가 차트 데이터의 출처를 목 API로 지정했으므로 모델을 하나 둔다.
class MonthlyStat {
  /// 1~12.
  final int month;

  /// 해당 월 인증 건수.
  final int count;

  const MonthlyStat({required this.month, required this.count});
}

/// 관리자 화면 인증 이력 1건. (backend/README 4.5 `GET /logs`)
class AuthLog {
  final String userName;
  final String department;

  /// 서버 `createdAt`(UTC). 화면에는 로컬 시각으로 변환해 표시한다.
  final DateTime timestamp;

  final bool passed;

  /// 실패 사유 코드. 통과했으면 null.
  final String? failReason;

  const AuthLog({
    required this.userName,
    required this.department,
    required this.timestamp,
    required this.passed,
    this.failReason,
  });

  factory AuthLog.fromJson(Map<String, dynamic> json) => AuthLog(
    userName: json['userName'] as String? ?? '(알 수 없음)',
    department: json['department'] as String? ?? '-',
    timestamp: DateTime.parse(json['createdAt'] as String).toLocal(),
    passed: json['passed'] as bool? ?? false,
    failReason: json['failReason'] as String?,
  );
}

/// 관리자 화면 "월별 인증 현황" 차트의 한 점. (backend/README 4.5)
class MonthlyStat {
  /// `YYYY-MM` (KST 기준).
  final String month;

  /// 그 달의 전체 인증 시도 수.
  final int total;

  final int passed;
  final int failed;

  const MonthlyStat({
    required this.month,
    required this.total,
    required this.passed,
    required this.failed,
  });

  factory MonthlyStat.fromJson(Map<String, dynamic> json) => MonthlyStat(
    month: json['month'] as String? ?? '',
    total: (json['total'] as num?)?.toInt() ?? 0,
    passed: (json['passed'] as num?)?.toInt() ?? 0,
    failed: (json['failed'] as num?)?.toInt() ?? 0,
  );

  /// 차트 X축 라벨용 월 숫자(1~12). 형식이 다르면 0.
  int get monthNumber {
    final parts = month.split('-');
    if (parts.length != 2) return 0;
    return int.tryParse(parts[1]) ?? 0;
  }
}

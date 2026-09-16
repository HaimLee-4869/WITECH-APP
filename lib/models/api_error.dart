/// 서버 에러 응답. `{"detail": {"code", "reason", "message"}}` (backend/README 5장)
///
/// 앱은 [reason]으로 분기하고 사용자에게는 [userMessage]를 보여준다.
/// 서버도 한국어 문구를 주지만, 앱 화면 맥락에 맞는 문구를 우선한다.
library;

/// 서버 주소가 주입되지 않은 채 실서버 모드로 띄운 경우.
///
/// 일반 오류와 구분해야 "네트워크 문제"가 아니라 "빌드 설정 문제"라고 안내할 수 있다.
class ApiNotConfiguredException implements Exception {
  final String message;

  const ApiNotConfiguredException(this.message);

  @override
  String toString() => 'ApiNotConfiguredException: $message';
}

class ApiException implements Exception {
  /// invalid_sequence | invalid_request | not_found | conflict | service_unavailable
  final String code;

  /// 세부 사유 코드. 앱은 이걸로 분기한다.
  final String reason;

  /// 서버가 준 문구.
  final String serverMessage;

  /// 등록에서 어느 회차가 문제였는지. 없으면 null.
  final int? takeNo;

  final int statusCode;

  const ApiException({
    required this.code,
    required this.reason,
    required this.serverMessage,
    required this.statusCode,
    this.takeNo,
  });

  /// `{"detail": {...}}` 형태를 파싱한다. 형태가 다르면 서버 본문을 그대로 담는다.
  factory ApiException.fromResponse(int statusCode, dynamic body) {
    if (body is Map && body['detail'] is Map) {
      final detail = body['detail'] as Map;
      return ApiException(
        code: (detail['code'] ?? 'unknown').toString(),
        reason: (detail['reason'] ?? 'unknown').toString(),
        serverMessage: (detail['message'] ?? '').toString(),
        takeNo: detail['takeNo'] is num ? (detail['takeNo'] as num).toInt() : null,
        statusCode: statusCode,
      );
    }
    return ApiException(
      code: 'unknown',
      reason: 'unknown',
      serverMessage: body?.toString() ?? '',
      statusCode: statusCode,
    );
  }

  /// 사용자에게 보여줄 문구. 사과하지 않고 다음 행동을 말한다. (SPEC 5장)
  String get userMessage {
    final base = messageForReason(reason) ?? _fallback;
    if (takeNo != null) return '$takeNo회차: $base';
    return base;
  }

  String get _fallback =>
      serverMessage.isNotEmpty ? serverMessage : '요청을 처리하지 못했습니다. 다시 시도해주세요.';

  /// 재촬영하면 해결될 수 있는 사유인지. (촬영 문제 vs 설정·계정 문제)
  bool get isRetryableCapture => _captureReasons.contains(reason);

  @override
  String toString() => 'ApiException($statusCode $code/$reason: $serverMessage)';
}

const Set<String> _captureReasons = <String>{
  'too_few_frames',
  'insufficient_valid_frames',
  'duration_too_short',
  'non_monotonic_timestamps',
  'malformed_landmarks',
  'wrong_hand',
  'invalid_sequence',
};

/// 사유 코드 → 앱 안내 문구. (backend/README 5장)
///
/// 모르는 코드는 null을 돌려주고 호출자가 서버 문구로 대체한다. 서버가 사유를
/// 추가해도 앱이 빈 화면을 띄우지 않도록.
String? messageForReason(String reason) => _messages[reason];

const Map<String, String> _messages = <String, String>{
  // --- 입력 거절 (code: invalid_sequence) ---
  'wrong_hand': '오른손을 사용해주세요. 이 모델은 오른손 동작만 인식합니다.',
  'insufficient_valid_frames': '손이 잘 보이도록 다시 시도해주세요.',
  'duration_too_short': '조금 더 천천히 동작해주세요.',
  'too_few_frames': '동작이 충분히 기록되지 않았습니다. 다시 시도해주세요.',
  'non_monotonic_timestamps': '촬영 시간 정보가 올바르지 않습니다. 다시 시도해주세요.',
  'missing_camera_size': '카메라 정보를 읽지 못했습니다. 앱을 다시 실행해주세요.',
  'malformed_landmarks': '손 좌표를 읽지 못했습니다. 다시 시도해주세요.',
  'invalid_sequence': '입력을 처리하지 못했습니다. 다시 시도해주세요.',
  // --- 요청 형식 (code: invalid_request) — 앱 버그이므로 사용자에게는 짧게 ---
  'schema_validation': '앱이 잘못된 형식으로 요청했습니다. 앱을 업데이트해주세요.',
  'gesture_id_required': '수어 암호를 먼저 선택해주세요.',
  'take_count_mismatch': '등록 회차 수가 맞지 않습니다. 처음부터 다시 등록해주세요.',
  'unknown_gesture': '선택한 수어 암호를 서버가 모릅니다. 다른 암호를 선택해주세요.',
  // --- 인증 거부 (200 응답의 reason) ---
  'gesture_gate': '등록한 동작과 다릅니다. 등록할 때와 같은 수어 동작을 해주세요.',
  'below_threshold': '등록된 동작과 일치하지 않습니다. 다시 시도해주세요.',
  'no_template': '이 수어 암호로 등록된 동작이 없습니다. 먼저 등록해주세요.',
  // --- 조회 실패 ---
  'user_not_found': '등록되지 않은 사용자입니다. 관리자에게 문의해주세요.',
  'threshold_not_found': '서버 설정이 올바르지 않습니다. 관리자에게 문의해주세요.',
  'user_exists': '이미 존재하는 사용자입니다.',
  // --- 서버 상태 ---
  'model_version_mismatch': '서버가 인증 모델을 교체하는 중입니다. 잠시 후 다시 시도해주세요.',
  'no_active_threshold': '서버 인증 기준값이 설정되지 않았습니다. 관리자에게 문의해주세요.',
  'no_active_model': '서버 인증 모델이 설정되지 않았습니다. 관리자에게 문의해주세요.',
};

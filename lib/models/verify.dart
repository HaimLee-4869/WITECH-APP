import 'landmark.dart';

/// 인증 요청. 수집된 원본 랜드마크를 그대로 담는다.
class VerifyRequest {
  final String userId;
  final DateTime capturedAt;

  /// 카메라에 요청한 명목 fps. 실제 프레임 간격은 [HandFrame.tMs]가 정답이다.
  final double nominalFps;
  final int durationMs;
  final List<HandFrame> frames;

  const VerifyRequest({
    required this.userId,
    required this.capturedAt,
    required this.nominalFps,
    required this.durationMs,
    required this.frames,
  });

  /// SPEC 6장 "전송 JSON 스키마"와 필드명·형태가 일치해야 한다.
  ///
  /// `capturedAt`은 오프셋을 포함한 ISO-8601로 보낸다. `toIso8601String()`은
  /// 로컬 시각일 때 오프셋을 빼먹으므로 직접 붙인다.
  Map<String, dynamic> toJson() => <String, dynamic>{
    'userId': userId,
    'capturedAt': _iso8601WithOffset(capturedAt),
    'nominalFps': nominalFps,
    'durationMs': durationMs,
    'frames': frames.map((f) => f.toJson()).toList(),
  };
}

/// `2026-08-24T10:39:01+09:00` 형태로 직렬화한다.
String _iso8601WithOffset(DateTime dt) {
  if (dt.isUtc) return dt.toIso8601String();
  final base = dt.toIso8601String(); // 오프셋 없음
  final offset = dt.timeZoneOffset;
  final sign = offset.isNegative ? '-' : '+';
  final abs = offset.abs();
  final hh = abs.inHours.toString().padLeft(2, '0');
  final mm = (abs.inMinutes % 60).toString().padLeft(2, '0');
  return '$base$sign$hh:$mm';
}

/// 인증 응답.
class VerifyResponse {
  /// 0.0 ~ 1.0 유사도.
  final double score;

  /// 판정 임계값. **서버가 소유한다.** 앱에 하드코딩하지 않는다. (SPEC 6/9장)
  final double threshold;

  final bool passed;
  final int latencyMs;

  /// 실패 사유 (예: "insufficient_frames"). 성공 시 null.
  final String? reason;

  const VerifyResponse({
    required this.score,
    required this.threshold,
    required this.passed,
    required this.latencyMs,
    this.reason,
  });

  factory VerifyResponse.fromJson(Map<String, dynamic> json) => VerifyResponse(
    score: (json['score'] as num).toDouble(),
    threshold: (json['threshold'] as num).toDouble(),
    passed: json['passed'] as bool,
    latencyMs: (json['latencyMs'] as num).toInt(),
    reason: json['reason'] as String?,
  );
}

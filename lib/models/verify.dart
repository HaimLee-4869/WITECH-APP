import 'camera_info.dart';
import 'landmark.dart';

/// 인증 요청. 수집된 원본 랜드마크를 그대로 담는다.
///
/// 필드와 형태는 backend/README 4.2 `POST /verify`와 일치해야 한다.
class VerifyRequest {
  final String userId;

  /// 앱이 주장하는 수어 암호. 서버가 이 키로 템플릿을 조회한다.
  ///
  /// 운영 설정(`USE_GESTURE_CLASSIFIER=false`)에서는 필수다. 없으면 422
  /// `gesture_id_required`. 서버의 제스처 분류 결과는 기록만 되고 판정에 쓰이지 않는다.
  final String gestureId;

  /// MediaPipe에 넣은 이미지 해상도. 필수.
  final CameraInfo camera;

  final DateTime capturedAt;

  /// 카메라에 요청한 명목 fps. 실제 프레임 간격은 [HandFrame.tMs]가 정답이다.
  final double nominalFps;
  final int durationMs;
  final List<HandFrame> frames;

  const VerifyRequest({
    required this.userId,
    required this.gestureId,
    required this.camera,
    required this.capturedAt,
    required this.nominalFps,
    required this.durationMs,
    required this.frames,
  });

  /// `capturedAt`은 오프셋을 포함한 ISO-8601로 보낸다. `toIso8601String()`은
  /// 로컬 시각일 때 오프셋을 빼먹으므로 직접 붙인다. 오프셋이 없으면 서버가
  /// UTC로 간주한다. (backend/README 4.1)
  Map<String, dynamic> toJson() => <String, dynamic>{
    'userId': userId,
    'gestureId': gestureId,
    'camera': camera.toJson(),
    'capturedAt': iso8601WithOffset(capturedAt),
    'nominalFps': nominalFps,
    'durationMs': durationMs,
    'frames': frames.map((f) => f.toJson()).toList(),
  };
}

/// `2026-08-24T10:39:01+09:00` 형태로 직렬화한다.
String iso8601WithOffset(DateTime dt) {
  if (dt.isUtc) return dt.toIso8601String();
  final base = dt.toIso8601String(); // 오프셋 없음
  final offset = dt.timeZoneOffset;
  final sign = offset.isNegative ? '-' : '+';
  final abs = offset.abs();
  final hh = abs.inHours.toString().padLeft(2, '0');
  final mm = (abs.inMinutes % 60).toString().padLeft(2, '0');
  return '$base$sign$hh:$mm';
}

/// 인증 응답. (backend/README 4.2)
class VerifyResponse {
  /// **user 관문** 유사도 (본인인지). 0.0 ~ 1.0.
  ///
  /// **null일 수 있다.** `no_template`처럼 서버가 비교를 하지 않은 경우다. 0.0으로
  /// 채우면 "비교를 안 했다"와 "유사도가 0"이 구분되지 않아 서버가 null을 준다.
  final double? score;

  /// user 관문 임계값 Tu. **서버가 소유한다.** 앱에 하드코딩하지 않는다.
  final double? threshold;

  /// **gesture 관문** 유사도 (등록한 동작인지). dual-head(v1.1.1)부터 생겼다.
  final double? gestureScore;

  /// gesture 관문 임계값 Tg.
  final double? gestureThreshold;

  final bool passed;
  final int latencyMs;

  /// 실패 사유 코드. 통과 시 null.
  ///
  /// `gesture_gate`   등록한 동작이 아니다 (본인이어도 거부)
  /// `below_threshold` 동작은 맞지만 본인이 아니다
  /// `no_template`     이 수어 암호로 등록된 것이 없다
  final String? reason;

  /// 서버가 템플릿 조회에 쓴 제스처.
  final String? gestureId;

  final String? modelVersion;

  const VerifyResponse({
    required this.score,
    required this.threshold,
    required this.passed,
    required this.latencyMs,
    this.gestureScore,
    this.gestureThreshold,
    this.reason,
    this.gestureId,
    this.modelVersion,
  });

  /// 두 관문 중 어디서 막혔는지. 통과했거나 비교를 안 했으면 null.
  bool get blockedByGesture => reason == 'gesture_gate';

  factory VerifyResponse.fromJson(Map<String, dynamic> json) => VerifyResponse(
    score: (json['score'] as num?)?.toDouble(),
    threshold: (json['threshold'] as num?)?.toDouble(),
    gestureScore: (json['gestureScore'] as num?)?.toDouble(),
    gestureThreshold: (json['gestureThreshold'] as num?)?.toDouble(),
    passed: json['passed'] as bool? ?? false,
    latencyMs: (json['latencyMs'] as num?)?.toInt() ?? 0,
    reason: json['reason'] as String?,
    gestureId: json['gestureId'] as String?,
    modelVersion: json['modelVersion'] as String?,
  );
}

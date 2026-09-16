import '../core/config.dart';

/// `GET /config` 응답. 앱은 이 값으로 등록 화면을 그린다. (backend/README 4.4)
///
/// 등록 횟수 같은 값을 앱에 박아두면 운영 중 조정이 불가능하다. 서버가 소유한다.
class ServerConfig {
  /// 제스처당 등록 회차 수.
  final int enrollmentTakes;

  /// 등록할 제스처 개수. 현재 릴리스 기준 1개.
  final int enrollmentGestures;

  /// 한 회차 촬영 시간(ms).
  final int captureDurationMs;

  /// 'right' | 'left' | 'any'.
  final String handRequired;

  /// 서버가 쓰는 인증 모델 버전. 화면 표시·디버깅용.
  final String modelVersion;

  const ServerConfig({
    required this.enrollmentTakes,
    required this.enrollmentGestures,
    required this.captureDurationMs,
    required this.handRequired,
    required this.modelVersion,
  });

  /// 서버 응답을 받기 전/실패했을 때 쓰는 기본값.
  ///
  /// 값을 못 받았다고 등록 화면을 막지는 않는다. 다만 회차 수가 서버와 다르면
  /// 등록이 422 `take_count_mismatch`로 거절되므로, 실패 시에는 화면에 알린다.
  static const ServerConfig fallback = ServerConfig(
    enrollmentTakes: kDefaultEnrollTakes,
    enrollmentGestures: 1,
    captureDurationMs: kRecordDurationMs,
    handRequired: 'right',
    modelVersion: 'unknown',
  );

  factory ServerConfig.fromJson(Map<String, dynamic> json) => ServerConfig(
    enrollmentTakes: (json['enrollmentTakes'] as num?)?.toInt() ??
        fallback.enrollmentTakes,
    enrollmentGestures: (json['enrollmentGestures'] as num?)?.toInt() ??
        fallback.enrollmentGestures,
    captureDurationMs: (json['captureDurationMs'] as num?)?.toInt() ??
        fallback.captureDurationMs,
    handRequired: json['handRequired'] as String? ?? fallback.handRequired,
    modelVersion: json['modelVersion'] as String? ?? fallback.modelVersion,
  );

  /// 오른손만 허용하는지. 화면 안내 문구를 띄울지 결정한다.
  bool get requiresRightHand => handRequired == 'right';

  Duration get captureDuration => Duration(milliseconds: captureDurationMs);
}

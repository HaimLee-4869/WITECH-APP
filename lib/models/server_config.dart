import '../challenge/challenge_config.dart';
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

  /// 안티스푸핑 Challenge 판정값.
  ///
  /// **null이면 Challenge를 시작할 수 없다.** 임계값을 앱에 박아두지 않기로 했으므로
  /// 대체값이 없다. 서버가 오래된 버전이거나 응답을 못 받은 경우다.
  final ChallengeConfig? challenge;

  const ServerConfig({
    required this.enrollmentTakes,
    required this.enrollmentGestures,
    required this.captureDurationMs,
    required this.handRequired,
    required this.modelVersion,
    this.challenge,
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
    // 형태가 예상과 다르면 null로 두고 Challenge를 막는다. 임계값을 추측해서
    // 채우면 도출과 다른 기준으로 판정하게 된다.
    challenge: switch (json['challenge']) {
      final Map<String, dynamic> c => _tryChallenge(c),
      _ => null,
    },
  );

  static ChallengeConfig? _tryChallenge(Map<String, dynamic> json) {
    try {
      return ChallengeConfig.fromJson(json);
    } catch (_) {
      return null;
    }
  }

  /// Challenge 설정만 갈아끼운 사본. 테스트에서 주입할 때 쓴다.
  ServerConfig copyWithChallenge(ChallengeConfig? challenge) => ServerConfig(
    enrollmentTakes: enrollmentTakes,
    enrollmentGestures: enrollmentGestures,
    captureDurationMs: captureDurationMs,
    handRequired: handRequired,
    modelVersion: modelVersion,
    challenge: challenge,
  );

  /// 오른손만 허용하는지. 화면 안내 문구를 띄울지 결정한다.
  bool get requiresRightHand => handRequired == 'right';

  Duration get captureDuration => Duration(milliseconds: captureDurationMs);
}

/// 테스트용 [ChallengeConfig] 만들기.
///
/// 임계값을 테스트 파일에 또 적지 않는다. 실제로 서버가 내려주는 값
/// (`backend/app/default_challenge_config.json`)을 읽어서 쓰고, 검증하려는 규칙에
/// 필요한 값만 덮어쓴다. 원본이 바뀌면 테스트가 같이 움직인다.
library;

import 'dart:convert';
import 'dart:io';

import 'package:signid/challenge/challenge_config.dart';

/// 서버 기본 설정 원본. `flutter test`는 패키지 루트에서 돈다.
final Map<String, dynamic> _defaults = jsonDecode(
  File('backend/app/default_challenge_config.json').readAsStringSync(),
) as Map<String, dynamic>;

/// [overrides]를 깊은 병합한 설정.
///
/// 예: `configWith(<String, dynamic>{'escapeFrames': 0})`
ChallengeConfig configWith([Map<String, dynamic> overrides = const {}]) {
  return ChallengeConfig.fromJson(_deepMerge(_defaults, overrides));
}

/// 부분 병합하면 안 되는 키. 서버 `PATCH /admin/config`와 같은 규칙이다.
/// 방향 하나만 바뀐 표가 생기면 나머지가 옛 도출값으로 남아 조용히 어긋난다.
const Set<String> _replaceWhole = <String>{'directionMap'};

/// 테스트 픽스처끼리 겹쳐 쓸 때. `configWith`와 같은 규칙이다.
Map<String, dynamic> deepMergeMaps(
  Map<String, dynamic> base,
  Map<String, dynamic> patch,
) =>
    _deepMerge(base, patch);

Map<String, dynamic> _deepMerge(
  Map<String, dynamic> base,
  Map<String, dynamic> patch,
) {
  final Map<String, dynamic> out = Map<String, dynamic>.of(base);
  patch.forEach((String key, dynamic value) {
    final dynamic current = out[key];
    if (!_replaceWhole.contains(key) &&
        value is Map<String, dynamic> &&
        current is Map<String, dynamic>) {
      out[key] = _deepMerge(current, value);
    } else {
      out[key] = value;
    }
  });
  return out;
}

/// 합성 손 각도로 검증할 때 쓰는 설정.
///
/// 실제 도출값(펴짐 135.9도)은 합성 손의 각도 범위와 겹쳐 경계 검증이 어렵다.
/// 패턴 매칭 **규칙**을 보는 테스트는 이 값을 쓴다. Python 테스트의
/// `TEST_CONFIG`와 같은 값이다.
ChallengeConfig get synthConfig => configWith(<String, dynamic>{
      'angleSpace': 'world',
      'fingerExtendedAngle': <String, dynamic>{'thumb': 150.0, 'others': 160.0},
      'shapeConfidenceMarginDeg': 20.0,
      'fistMaxTipWristRatio': null,
    });

/// Python 테스트와 같은 합성 손 각도.
const double kExtendedAngle = 175.0;
const double kCurledAngle = 60.0;

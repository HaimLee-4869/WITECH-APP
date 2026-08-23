import 'landmark.dart';

/// 제스처 등록 요청. 같은 동작을 여러 회차 반복 수집한 결과를 한 번에 보낸다.
class EnrollRequest {
  final String userId;
  final DateTime capturedAt;
  final double nominalFps;

  /// 회차별 프레임 목록. 길이 = 실제 수집된 회차 수.
  final List<List<HandFrame>> takes;

  const EnrollRequest({
    required this.userId,
    required this.capturedAt,
    required this.nominalFps,
    required this.takes,
  });

  /// SPEC에 등록용 JSON 스키마가 명시되지 않아, 6장의 인증 스키마를 회차 배열로
  /// 확장한 형태로 정했다. 서버 팀과 확정되면 이 부분만 고치면 된다.
  Map<String, dynamic> toJson() => <String, dynamic>{
    'userId': userId,
    'capturedAt': capturedAt.toIso8601String(),
    'nominalFps': nominalFps,
    'takeCount': takes.length,
    'takes': takes
        .map((take) => take.map((f) => f.toJson()).toList())
        .toList(),
  };
}

/// 등록 응답.
class EnrollResponse {
  final bool enrolled;

  /// 서버가 실제로 받아들인 회차 수.
  final int acceptedTakes;

  /// 등록된 템플릿 식별자. 실패 시 null.
  final String? templateId;

  /// 실패 사유. 성공 시 null.
  final String? reason;

  const EnrollResponse({
    required this.enrolled,
    required this.acceptedTakes,
    this.templateId,
    this.reason,
  });

  factory EnrollResponse.fromJson(Map<String, dynamic> json) => EnrollResponse(
    enrolled: json['enrolled'] as bool,
    acceptedTakes: (json['acceptedTakes'] as num).toInt(),
    templateId: json['templateId'] as String?,
    reason: json['reason'] as String?,
  );
}

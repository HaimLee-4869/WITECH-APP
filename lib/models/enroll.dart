import 'camera_info.dart';
import 'landmark.dart';
import 'verify.dart' show iso8601WithOffset;

/// 등록 회차 하나. (backend/README 4.3 `takes[]`)
class EnrollTake {
  /// 1부터 시작하는 회차 번호. 서버는 1..N이 모두 있어야 받아들인다.
  final int takeNo;
  final DateTime capturedAt;
  final double nominalFps;
  final int durationMs;
  final List<HandFrame> frames;

  const EnrollTake({
    required this.takeNo,
    required this.capturedAt,
    required this.nominalFps,
    required this.durationMs,
    required this.frames,
  });

  Map<String, dynamic> toJson() => <String, dynamic>{
    'takeNo': takeNo,
    'capturedAt': iso8601WithOffset(capturedAt),
    'nominalFps': nominalFps,
    'durationMs': durationMs,
    'frames': frames.map((f) => f.toJson()).toList(),
  };
}

/// 제스처 등록 요청. 같은 동작을 여러 회차 반복 수집한 결과를 한 번에 보낸다.
///
/// 회차가 하나라도 불량이면 서버가 **전체를 422로 거절하고 아무것도 저장하지 않는다.**
/// 같은 `(userId, gestureId)`로 다시 보내면 기존 등록을 대체한다.
class EnrollRequest {
  final String userId;

  /// 등록할 수어 암호.
  final String gestureId;

  /// MediaPipe에 넣은 이미지 해상도. take 공통이라 최상위에 한 번 보낸다.
  final CameraInfo camera;

  final List<EnrollTake> takes;

  const EnrollRequest({
    required this.userId,
    required this.gestureId,
    required this.camera,
    required this.takes,
  });

  Map<String, dynamic> toJson() => <String, dynamic>{
    'userId': userId,
    'gestureId': gestureId,
    'camera': camera.toJson(),
    'takes': takes.map((t) => t.toJson()).toList(),
  };
}

/// 등록 응답. (backend/README 4.3)
///
/// 실패는 200 + `enrolled: false`가 아니라 **422 에러 응답**으로 온다.
/// 그래서 이 객체는 성공 경로에서만 만들어진다.
class EnrollResponse {
  final bool enrolled;
  final String userId;
  final String gestureId;

  /// 서버가 저장한 회차 수.
  final int takeCount;

  /// 서버가 요구하는 회차 수.
  final int required;

  final String? modelVersion;

  const EnrollResponse({
    required this.enrolled,
    required this.userId,
    required this.gestureId,
    required this.takeCount,
    required this.required,
    this.modelVersion,
  });

  factory EnrollResponse.fromJson(Map<String, dynamic> json) => EnrollResponse(
    enrolled: json['enrolled'] as bool? ?? false,
    userId: json['userId'] as String? ?? '',
    gestureId: json['gestureId'] as String? ?? '',
    takeCount: (json['takeCount'] as num?)?.toInt() ?? 0,
    required: (json['required'] as num?)?.toInt() ?? 0,
    modelVersion: json['modelVersion'] as String?,
  );
}

import 'package:flutter/widgets.dart';

import '../models/camera_info.dart';
import '../models/landmark.dart';

/// 오버레이 좌표 변환에 필요한 파라미터 묶음.
///
/// 소스마다 회전·미러·화면비가 다르므로 소스가 직접 알려준다. 화면은 이 값을
/// 그대로 [HandOverlayPainter]에 넘기기만 하고 스스로 계산하지 않는다.
/// (SPEC 8.2 — 변환 파라미터를 생성자로 받는다)
@immutable
class LandmarkTransform {
  /// 좌표를 시계방향으로 돌려야 하는 각도(0/90/180/270).
  final int rotationDegrees;

  /// 표시할 때 좌우 반전할지. **전송 좌표에는 적용되지 않는다.**
  final bool mirror;

  /// 원본 이미지의 가로/세로 비. null이면 캔버스를 꽉 채우도록 늘린다.
  final double? sourceAspectRatio;

  const LandmarkTransform({
    this.rotationDegrees = 0,
    this.mirror = false,
    this.sourceAspectRatio,
  });
}

/// 소스를 켤 수 없을 때 [LandmarkSource.frames]로 흘려보내는 오류.
///
/// 권한 거부나 카메라 부재는 사용자가 조치할 수 있는 문제이므로, 조용히 멈추지
/// 말고 화면에 무엇을 해야 하는지 띄워야 한다. [message]는 그대로 사용자에게
/// 보여줄 수 있는 문장이다. (SPEC 5장 카피 원칙)
class LandmarkSourceException implements Exception {
  final String message;

  const LandmarkSourceException(this.message);

  @override
  String toString() => 'LandmarkSourceException: $message';
}

/// 랜드마크 공급자 추상 인터페이스. (SPEC 원칙 B)
///
/// 나중에 "서버에서 영상을 받아 추출"하는 방식으로 바뀔 수 있으므로 UI와
/// 컨트롤러는 이 인터페이스에만 의존한다. 구현체는 DI로 주입한다.
///
/// 구현체가 흘리는 [HandFrame]의 좌표는 **MediaPipe 원본 그대로**여야 한다.
/// 미러링·정규화 같은 가공을 여기서 하면 안 된다. (SPEC 원칙 A)
abstract class LandmarkSource {
  /// 검출된 프레임 스트림. 손이 없는 프레임은 흘리지 않는다.
  ///
  /// 브로드캐스트 스트림이어야 한다. 오버레이와 컨트롤러가 함께 듣는다.
  Stream<HandFrame> get frames;

  /// 캡처를 시작한다. 이미 시작된 상태면 아무 일도 하지 않는다.
  Future<void> start();

  /// 캡처를 멈춘다. [start]로 다시 시작할 수 있어야 한다.
  Future<void> stop();

  /// 자원을 해제한다. 이후 이 인스턴스는 재사용할 수 없다.
  void dispose();

  /// 원 안에 깔 프리뷰 위젯. 프리뷰가 없는 소스(Fake 등)는 null을 준다.
  ///
  /// 서비스 계층이 위젯을 돌려주는 것이 이상적이진 않지만, 대안은 화면이
  /// `source is OnDeviceLandmarkSource`로 구현체를 캐스팅하는 것이라
  /// 원칙 B(구현체를 모르게 한다)를 더 크게 어긴다. 둘 중 덜 나쁜 쪽을 골랐다.
  Widget? buildPreview();

  /// 오버레이 좌표 변환 파라미터.
  LandmarkTransform get transform;

  /// [HandFrame.score]가 **실제로 측정된 검출 신뢰도**인지.
  ///
  /// false면 값이 있어도 그것은 하한값이다. `hand_landmarker` 3.0.1은 신뢰도를
  /// 주지 않아서, 앱은 플러그인에 설정한 `minHandDetectionConfidence`(0.6)를
  /// "이 값 이상"이라는 뜻으로 기록한다.
  ///
  /// **하한값을 임계값과 비교하면 안 된다.** 안티스푸핑 Challenge의
  /// `minDetectionScore`(0.938)는 실제 검출 신뢰도 분포의 p5에서 나온 값이라,
  /// 0.6과 비교하면 모든 프레임이 미달이 된다(실기기에서 `TRACKING_UNSTABLE`이
  /// 계속 뜬 원인이다). 이 값이 false면 신뢰도 관문 자체를 걸지 않는다.
  ///
  /// 플러그인이 진짜 신뢰도를 주게 되면 true로 바꾸면 관문이 살아난다.
  bool get providesDetectionScore;

  /// **검출에 넣은 이미지**의 해상도. 아직 모르면 null.
  ///
  /// 서버가 학습 때와 같은 종횡비 보정을 하려면 이 값이 필요하다. 없으면 422
  /// `missing_camera_size`로 거절된다. 프리뷰 크기가 아니라 MediaPipe에 넘긴
  /// 프레임의 크기여야 한다. (backend/README 4.1)
  CameraInfo? get imageSize;

  /// 프레임 타임스탬프의 기준 시각을 0으로 리셋한다.
  ///
  /// [HandFrame.tMs]는 "캡처 시작 시점부터의 경과 시간"이므로, 녹화를 시작하는
  /// 순간 기준점을 다시 잡아야 한다. (SPEC 6장)
  void resetClock();
}

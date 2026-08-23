import '../models/landmark.dart';

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

  /// 프리뷰 위젯을 화면에 띄울 필요가 있는지.
  ///
  /// 실기기 소스는 true(카메라 프리뷰가 있어야 함), Fake 소스는 false.
  /// 인증 화면이 원 안에 무엇을 그릴지 결정하는 데 쓴다.
  bool get hasPreview;

  /// 프레임 타임스탬프의 기준 시각을 0으로 리셋한다.
  ///
  /// [HandFrame.tMs]는 "캡처 시작 시점부터의 경과 시간"이므로, 녹화를 시작하는
  /// 순간 기준점을 다시 잡아야 한다. (SPEC 6장)
  void resetClock();
}

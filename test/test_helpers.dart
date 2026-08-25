import 'package:signid/services/fake_landmark_source.dart';
import 'package:signid/state/providers.dart';

/// 테스트에서 항상 [FakeLandmarkSource]를 쓰도록 강제하는 override.
///
/// `config.dart`의 `kUseFakeLandmarks` 값에 테스트가 좌우되면 안 된다. 실기기
/// 배포를 위해 그 플래그를 false로 바꾸는 순간 테스트가 실제 카메라를 열려다
/// 전부 깨지기 때문이다. 랜드마크 소스는 테스트가 명시적으로 주입한다.
///
/// 하나의 값을 여러 컨테이너가 공유해도 된다. override는 "어떻게 만들지"에 대한
/// 설명일 뿐이고, 생성 함수는 컨테이너마다 따로 실행되어 각자의 소스를 갖는다.
///
/// 타입을 명시하지 않은 이유: riverpod의 `Override` 타입을 flutter_riverpod이
/// 내보내지 않아서 이름을 적을 수가 없다. 추론에 맡긴다.
final fakeLandmarkSourceOverride = landmarkSourceProvider.overrideWith((ref) {
  final source = FakeLandmarkSource();
  ref.onDispose(source.dispose);
  return source;
});

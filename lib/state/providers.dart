/// DI 지점 모음.
///
/// SPEC 3장 "과하게 추상화하지 말 것"에 따라 provider는 필요한 것만 둔다.
/// 화면과 컨트롤러는 구현체가 아니라 [ApiClient]/[LandmarkSource] 인터페이스만
/// 본다. (SPEC 원칙 B, C)
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/config.dart';
import '../services/api_client.dart';
import '../services/fake_landmark_source.dart';
import '../services/http_api_client.dart';
import '../services/landmark_source.dart';
import '../services/mock_api_client.dart';
import '../services/on_device_landmark_source.dart';

/// 목 ↔ 실제 서버 전환 지점. `kUseMockApi` 하나로 결정된다.
final apiClientProvider = Provider<ApiClient>((ref) {
  return kUseMockApi ? MockApiClient() : const HttpApiClient();
});

/// Fake ↔ 실기기 랜드마크 소스 전환 지점.
///
/// 화면이 떠 있는 동안만 살아 있어야 하므로 autoDispose로 두고, 폐기될 때
/// 네이티브 자원을 반드시 해제한다. (SPEC 8.2 — 화면 이탈 시 dispose)
final landmarkSourceProvider = Provider.autoDispose<LandmarkSource>((ref) {
  final LandmarkSource source =
      kUseFakeLandmarks ? FakeLandmarkSource() : OnDeviceLandmarkSource();
  ref.onDispose(source.dispose);
  return source;
});

/// 홈 화면에서 선택한 사용자. 로그인을 구현하지 않으므로 이것이 신원이다.
/// (SPEC 8.1)
final selectedUserProvider = NotifierProvider<SelectedUser, String>(
  SelectedUser.new,
);

class SelectedUser extends Notifier<String> {
  @override
  String build() => kMockUsers.first;

  void select(String user) => state = user;
}

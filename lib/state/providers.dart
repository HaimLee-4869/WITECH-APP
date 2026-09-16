/// DI 지점 모음.
///
/// SPEC 3장 "과하게 추상화하지 말 것"에 따라 provider는 필요한 것만 둔다.
/// 화면과 컨트롤러는 구현체가 아니라 [ApiClient]/[LandmarkSource] 인터페이스만
/// 본다. (SPEC 원칙 B, C)
library;

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/config.dart';
import '../models/server_config.dart';
import '../services/api_client.dart';
import '../services/fake_landmark_source.dart';
import '../services/http_api_client.dart';
import '../services/landmark_source.dart';
import '../services/mock_api_client.dart';
import '../services/on_device_landmark_source.dart';

/// 목 ↔ 실제 서버 전환 지점. `kUseMockApi` 하나로 결정된다.
final apiClientProvider = Provider<ApiClient>((ref) {
  return kUseMockApi ? MockApiClient() : HttpApiClient();
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

/// 등록·인증에 쓸 수어 암호(제스처) ID.
///
/// 서버는 이 값으로 템플릿을 조회한다. 지금은 G1~G5이고, AI팀이 개인 제스처 ID
/// 방식을 주면 [kGestureIds]의 값만 바뀐다. (backend/README 2장)
final selectedGestureProvider = NotifierProvider<SelectedGesture, String>(
  SelectedGesture.new,
);

class SelectedGesture extends Notifier<String> {
  @override
  String build() => kDefaultGestureId;

  void select(String gestureId) => state = gestureId;
}

/// 서버 설정(`GET /config`). 앱 시작 시 한 번 불러온다.
///
/// 응답 전/실패 시에는 [ServerConfig.fallback]을 쓰되 [ServerConfigState.loaded]가
/// false로 남는다. 등록 회차 수가 서버와 다르면 등록이 422로 거절되므로 화면이
/// 이 값을 보고 안내할 수 있어야 한다.
final serverConfigProvider =
    NotifierProvider<ServerConfigController, ServerConfigState>(
      ServerConfigController.new,
    );

@immutable
class ServerConfigState {
  final ServerConfig config;

  /// 서버에서 실제로 받아왔는지. false면 [config]는 기본값이다.
  final bool loaded;

  /// 불러오기 실패 사유. 성공했거나 아직 시도 전이면 null.
  final String? error;

  const ServerConfigState({
    required this.config,
    this.loaded = false,
    this.error,
  });

  static const ServerConfigState initial = ServerConfigState(
    config: ServerConfig.fallback,
  );
}

class ServerConfigController extends Notifier<ServerConfigState> {
  @override
  ServerConfigState build() {
    // build 중에 상태를 바꾸지 않도록 다음 마이크로태스크에서 불러온다.
    Future.microtask(load);
    return ServerConfigState.initial;
  }

  Future<void> load() async {
    final api = ref.read(apiClientProvider);
    try {
      final config = await api.fetchConfig();
      if (!ref.mounted) return;
      state = ServerConfigState(config: config, loaded: true);
    } catch (e) {
      if (!ref.mounted) return;
      // 설정을 못 받아도 앱은 뜬다. 기본값으로 진행하되 상태에 남긴다.
      state = ServerConfigState(
        config: ServerConfig.fallback,
        loaded: false,
        error: '서버 설정을 불러오지 못했습니다. 기본값으로 진행합니다.',
      );
      debugPrint('SignID/config load failed: $e');
    }
  }
}

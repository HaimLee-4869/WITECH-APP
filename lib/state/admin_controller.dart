import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/auth_log.dart';
import 'providers.dart';

/// 관리자 화면에 필요한 데이터 묶음.
@immutable
class AdminData {
  final List<AuthLog> logs;
  final List<MonthlyStat> monthly;

  const AdminData({required this.logs, required this.monthly});
}

/// 인증 이력과 월별 통계를 함께 불러온다.
///
/// 둘 다 화면에 동시에 보이므로 따로 로딩 상태를 관리할 이유가 없다. 하나로
/// 묶어 [AsyncValue]가 로딩/에러/데이터를 그대로 표현하게 둔다. (SPEC 3장 —
/// 과하게 추상화하지 말 것)
class AdminController extends AsyncNotifier<AdminData> {
  @override
  Future<AdminData> build() async {
    final api = ref.watch(apiClientProvider);
    final results = await Future.wait([
      api.fetchAuthLogs(),
      api.fetchMonthlyStats(),
    ]);
    return AdminData(
      logs: results[0] as List<AuthLog>,
      monthly: results[1] as List<MonthlyStat>,
    );
  }

  /// 당겨서 새로고침.
  Future<void> refresh() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(build);
  }
}

final adminProvider = AsyncNotifierProvider<AdminController, AdminData>(
  AdminController.new,
);

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:signid/models/app_user.dart';
import 'package:signid/core/theme.dart';
import 'package:signid/models/auth_log.dart';
import 'package:signid/models/enroll.dart';
import 'package:signid/models/server_config.dart';
import 'package:signid/models/verify.dart';
import 'package:signid/screens/admin_screen.dart';
import 'package:signid/screens/challenge_screen.dart';
import 'package:signid/screens/enroll_screen.dart';
import 'package:signid/screens/home_screen.dart';
import 'package:signid/screens/result_screen.dart';
import 'package:signid/services/api_client.dart';
import 'package:signid/state/providers.dart';

import 'test_helpers.dart';

/// 지연 없이 즉시 응답하는 API. 위젯 테스트에서 타이머를 기다리지 않기 위함.
class _InstantApi implements ApiClient {
  @override
  Future<ServerConfig> fetchConfig() async => ServerConfig.fallback;

  @override
  Future<AppUser> createUser({
    required String id,
    required String name,
    String? department,
  }) async => AppUser(id: id, name: name, department: department);

  @override
  Future<List<AppUser>> fetchUsers() async => const [
    AppUser(id: 'hong', name: '홍길동', department: '개발팀'),
    AppUser(id: 'kim', name: '김길동', department: '인사팀'),
    AppUser(id: 'oh', name: '오박사', department: '영업팀'),
  ];

  @override
  Future<VerifyResponse> verify(_) async => const VerifyResponse(
    score: 0.9,
    threshold: 0.72,
    passed: true,
    latencyMs: 1,
  );

  @override
  Future<EnrollResponse> enroll(_) async =>
      const EnrollResponse(
        enrolled: true,
        userId: 'kim',
        gestureId: 'G1',
        takeCount: 3,
        required: 3,
      );

  @override
  Future<List<AuthLog>> fetchAuthLogs() async => [
    AuthLog(
      userName: '홍길동',
      department: '개발팀',
      timestamp: DateTime(2026, 8, 24, 10, 38, 55),
      passed: true,
    ),
    AuthLog(
      userName: '둘리',
      department: '영업팀',
      timestamp: DateTime(2026, 8, 24, 10, 39, 1),
      passed: false,
    ),
  ];

  @override
  Future<List<MonthlyStat>> fetchMonthlyStats() async => const [
    MonthlyStat(month: '2026-01', total: 120, passed: 104, failed: 16),
    MonthlyStat(month: '2026-02', total: 180, passed: 158, failed: 22),
    MonthlyStat(month: '2026-03', total: 240, passed: 211, failed: 29),
    MonthlyStat(month: '2026-04', total: 285, passed: 255, failed: 30),
    MonthlyStat(month: '2026-05', total: 330, passed: 299, failed: 31),
  ];

  /// 디버그 로그는 테스트에서 쓰지 않는다. 받기만 하고 버린다.
  @override
  Future<void> sendChallengeDebug({
    required String sessionId,
    required List<String> lines,
  }) async {}

}

Widget _app() => ProviderScope(
  overrides: [
    apiClientProvider.overrideWithValue(_InstantApi()),
    fakeLandmarkSourceOverride,
  ],
  child: MaterialApp(theme: buildAppTheme(), home: const HomeScreen()),
);

void main() {
  /// 세로 폰 크기로 테스트한다. 기본 테스트 화면(800x600)은 가로가 더 길어서
  /// 세로 고정 앱의 실제 레이아웃과 다르다.
  setUp(() {
    final view = TestWidgetsFlutterBinding.ensureInitialized().platformDispatcher
        .views
        .first;
    view.physicalSize = const Size(1080, 2340);
    view.devicePixelRatio = 3.0;
  });

  tearDown(() {
    final view = TestWidgetsFlutterBinding.ensureInitialized().platformDispatcher
        .views
        .first;
    view.resetPhysicalSize();
    view.resetDevicePixelRatio();
  });

  testWidgets('홈에서 인증을 누르면 동작 확인(Challenge) 화면이 먼저 나온다', (tester) async {
    // 인증은 Challenge부터 시작한다. 통과하면 같은 화면에서 촬영으로
    // 이어지므로, 별도의 인증 화면으로 넘어가지 않는다.
    await tester.pumpWidget(_app());
    await tester.pump(); // GET /users 응답 반영
    expect(find.byType(HomeScreen), findsOneWidget);
    expect(find.text('Sign-ID'), findsOneWidget);

    await tester.tap(find.text('인증하기'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    expect(find.byType(ChallengeScreen), findsOneWidget);
    // Challenge와 촬영이 한 화면에서 이어진다는 것을 제목이 말한다.
    expect(find.text('동작 확인 후 수어 암호'), findsOneWidget);
    expect(find.text('취소'), findsOneWidget);

    await tester.tap(find.text('취소'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.byType(HomeScreen), findsOneWidget);
  });

  testWidgets('홈에서 등록 화면으로 이동한다', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pump(); // GET /users 응답 반영
    await tester.tap(find.text('제스처 등록'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    expect(find.byType(EnrollScreen), findsOneWidget);
    expect(find.textContaining('0 / 3 회차 완료'), findsOneWidget);
  });

  testWidgets('홈에서 관리자 화면으로 이동하고 표와 차트가 렌더링된다', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pump(); // GET /users 응답 반영
    await tester.tap(find.text('인증 이력'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    expect(find.byType(AdminScreen), findsOneWidget);
    expect(find.text('인증 이력 조회'), findsOneWidget);
    // 표 헤더 4개 컬럼.
    expect(find.text('사용자'), findsOneWidget);
    expect(find.text('부서'), findsOneWidget);
    expect(find.text('인증시간'), findsOneWidget);
    expect(find.text('결과'), findsOneWidget);
    // 목 데이터 행.
    expect(
      find.descendant(
        of: find.byType(AdminScreen),
        matching: find.text('홍길동'),
      ),
      findsOneWidget,
    );
    // 차트 카드.
    expect(find.text('월별 인증 현황'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('월별 차트 라벨이 실제 월 이름으로 나온다 (0월~4월 아님)', (tester) async {
    await tester.pumpWidget(_app());
    await tester.tap(find.text('인증 이력'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 800));

    // 서버는 'YYYY-MM'을 주고 화면은 '1월'~'12월'로 보여준다.
    expect(find.text('1월'), findsWidgets);
    expect(find.text('5월'), findsWidgets);
    // X값(순번)을 그대로 쓰면 0월이 생긴다.
    expect(find.text('0월'), findsNothing);
  });

  testWidgets('결과 화면은 성공/실패를 다르게 보여준다', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: buildAppTheme(),
          home: const ResultScreen(
            response: VerifyResponse(
              score: 0.88,
              threshold: 0.34,
              gestureScore: 0.97,
              gestureThreshold: 0.90,
              passed: true,
              latencyMs: 1200,
            ),
          ),
        ),
      ),
    );
    expect(find.text('인증되었습니다'), findsOneWidget);
    // threshold는 응답에서 읽은 값이 그대로 보여야 한다. dual-head는 관문이 둘이다.
    expect(find.text('본인 0.880 / 0.34'), findsOneWidget);
    expect(find.text('동작 0.970 / 0.90'), findsOneWidget);
    // 2.5초 자동 복귀 타이머가 남지 않도록 소진시킨다.
    await tester.pump(const Duration(seconds: 3));

    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: buildAppTheme(),
          home: const ResultScreen(
            response: VerifyResponse(
              score: 0.91,
              threshold: 0.34,
              gestureScore: 0.41,
              gestureThreshold: 0.90,
              passed: false,
              latencyMs: 1200,
              reason: 'gesture_gate',   // 본인이지만 등록과 다른 동작
            ),
          ),
        ),
      ),
    );
    expect(find.text('인증에 실패했습니다'), findsOneWidget);
    // 어느 관문에서 막혔는지 문구로 구분된다.
    expect(find.textContaining('등록할 때와 같은 수어 동작'), findsOneWidget);
    expect(find.text('동작 0.410 / 0.90'), findsOneWidget);
    expect(find.text('다시 시도'), findsOneWidget);
    expect(find.text('홈으로'), findsOneWidget);
  });

  testWidgets('사용자 드롭다운으로 인증 대상을 바꾼다', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pump(); // GET /users 응답 반영
    expect(find.text('홍길동'), findsOneWidget);

    await tester.tap(find.byType(DropdownButton<String>).first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('오박사').last);
    await tester.pumpAndSettle();

    expect(find.text('오박사'), findsOneWidget);
  });

  testWidgets('사용자 목록을 받기 전에는 인증·등록을 시작할 수 없다', (tester) async {
    await tester.pumpWidget(_app());
    expect(find.text('사용자 목록을 불러오는 중…'), findsOneWidget);

    await tester.tap(find.text('인증하기'));
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.byType(ChallengeScreen), findsNothing);

    await tester.pump();
    expect(find.text('홍길동'), findsOneWidget);
  });
}

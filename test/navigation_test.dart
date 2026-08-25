import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:signid/core/theme.dart';
import 'package:signid/models/auth_log.dart';
import 'package:signid/models/enroll.dart';
import 'package:signid/models/verify.dart';
import 'package:signid/screens/admin_screen.dart';
import 'package:signid/screens/auth_screen.dart';
import 'package:signid/screens/enroll_screen.dart';
import 'package:signid/screens/home_screen.dart';
import 'package:signid/screens/result_screen.dart';
import 'package:signid/services/api_client.dart';
import 'package:signid/state/providers.dart';

import 'test_helpers.dart';

/// 지연 없이 즉시 응답하는 API. 위젯 테스트에서 타이머를 기다리지 않기 위함.
class _InstantApi implements ApiClient {
  @override
  Future<VerifyResponse> verify(_) async => const VerifyResponse(
    score: 0.9,
    threshold: 0.72,
    passed: true,
    latencyMs: 1,
  );

  @override
  Future<EnrollResponse> enroll(_) async =>
      const EnrollResponse(enrolled: true, acceptedTakes: 5);

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
    MonthlyStat(month: 1, count: 120),
    MonthlyStat(month: 2, count: 180),
    MonthlyStat(month: 3, count: 240),
    MonthlyStat(month: 4, count: 285),
    MonthlyStat(month: 5, count: 330),
  ];
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

  testWidgets('홈에서 인증 화면으로 이동한다', (tester) async {
    await tester.pumpWidget(_app());
    expect(find.byType(HomeScreen), findsOneWidget);
    expect(find.text('Sign-ID'), findsOneWidget);

    await tester.tap(find.text('인증하기'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    expect(find.byType(AuthScreen), findsOneWidget);
    expect(find.text('수어 암호를 입력하세요'), findsOneWidget);
    expect(find.text('인증'), findsOneWidget);
    expect(find.text('취소'), findsOneWidget);
  });

  testWidgets('홈에서 등록 화면으로 이동한다', (tester) async {
    await tester.pumpWidget(_app());
    await tester.tap(find.text('제스처 등록'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    expect(find.byType(EnrollScreen), findsOneWidget);
    expect(find.text('0 / 5 회차 완료'), findsOneWidget);
  });

  testWidgets('홈에서 관리자 화면으로 이동하고 표와 차트가 렌더링된다', (tester) async {
    await tester.pumpWidget(_app());
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

  testWidgets('결과 화면은 성공/실패를 다르게 보여준다', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: buildAppTheme(),
          home: const ResultScreen(
            response: VerifyResponse(
              score: 0.88,
              threshold: 0.72,
              passed: true,
              latencyMs: 1200,
            ),
          ),
        ),
      ),
    );
    expect(find.text('인증되었습니다'), findsOneWidget);
    // threshold는 응답에서 읽은 값이 그대로 보여야 한다.
    expect(find.text('기준 0.72'), findsOneWidget);
    // 2.5초 자동 복귀 타이머가 남지 않도록 소진시킨다.
    await tester.pump(const Duration(seconds: 3));

    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: buildAppTheme(),
          home: const ResultScreen(
            response: VerifyResponse(
              score: 0.0,
              threshold: 0.72,
              passed: false,
              latencyMs: 1200,
              reason: 'insufficient_frames',
            ),
          ),
        ),
      ),
    );
    expect(find.text('인증에 실패했습니다'), findsOneWidget);
    expect(find.text('다시 시도'), findsOneWidget);
    expect(find.text('홈으로'), findsOneWidget);
  });

  testWidgets('사용자 드롭다운으로 인증 대상을 바꾼다', (tester) async {
    await tester.pumpWidget(_app());
    expect(find.text('홍길동'), findsOneWidget);

    await tester.tap(find.byType(DropdownButton<String>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('오박사').last);
    await tester.pumpAndSettle();

    expect(find.text('오박사'), findsOneWidget);
  });
}

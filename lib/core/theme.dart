import 'package:flutter/material.dart';

/// 목업의 다크 테마 색상 토큰. (SPEC 5장)
///
/// 여기 없는 색을 화면에서 즉석으로 만들지 말 것. 필요하면 토큰을 먼저 추가한다.
class AppColors {
  const AppColors._();

  static const bg = Color(0xFF121417); // 화면 배경 (거의 검정)
  static const surface = Color(0xFF1C1F24); // 카드/패널
  static const surfaceAlt = Color(0xFF23272D); // 표 헤더, 보조 버튼
  static const primary = Color(0xFF2F80ED); // 인증 버튼 (파랑)
  static const ring = Color(0xFF3DDC97); // 손 가이드 원 (민트)
  static const landmark = Color(0xFF22D3EE); // 랜드마크 점 (시안)
  static const connection = Color(0xFF0E7490); // 뼈대 선 (어두운 청록)
  static const success = Color(0xFF34D399);
  static const danger = Color(0xFFEF4444);
  static const textPrimary = Color(0xFFFFFFFF);
  static const textSecondary = Color(0xFF9AA0A6);
  static const divider = Color(0xFF2A2E34);
}

/// 타이포그래피 토큰. (SPEC 5장)
///
/// Pretendard를 쓰지 않고 Flutter 기본 폰트로 가되, 웨이트와 자간을 명시한다.
/// 폰트 파일을 추가하지 않는 것은 SPEC 5장의 명시적 지시.
class AppText {
  const AppText._();

  /// 로고 "Sign-ID".
  static const displayTitle = TextStyle(
    fontSize: 24,
    fontWeight: FontWeight.w600,
    letterSpacing: 0.5,
    color: AppColors.textPrimary,
  );

  /// 화면 제목.
  static const screenTitle = TextStyle(
    fontSize: 20,
    fontWeight: FontWeight.w600,
    color: AppColors.textPrimary,
  );

  static const body = TextStyle(
    fontSize: 15,
    fontWeight: FontWeight.w400,
    color: AppColors.textPrimary,
  );

  static const caption = TextStyle(
    fontSize: 13,
    fontWeight: FontWeight.w400,
    color: AppColors.textSecondary,
  );

  static const tableCell = TextStyle(
    fontSize: 13,
    fontWeight: FontWeight.w400,
    color: AppColors.textPrimary,
  );

  static const buttonLabel = TextStyle(
    fontSize: 16,
    fontWeight: FontWeight.w600,
    color: AppColors.textPrimary,
  );
}

/// 모양 토큰. (SPEC 5장)
class AppShape {
  const AppShape._();

  static const double primaryButtonHeight = 52;
  static const double primaryButtonRadius = 26; // 완전 알약형
  static const double secondaryButtonHeight = 44;
  static const double secondaryButtonRadius = 22;
  static const double cardRadius = 12;
  static const double dividerWidth = 1;

  /// 화면 좌우 기본 여백.
  static const double screenPadding = 20;
}

/// 앱 전역 테마. 다크 고정이며 라이트 테마는 만들지 않는다. (SPEC 5장)
ThemeData buildAppTheme() {
  const scheme = ColorScheme.dark(
    primary: AppColors.primary,
    surface: AppColors.surface,
    error: AppColors.danger,
    onPrimary: AppColors.textPrimary,
    onSurface: AppColors.textPrimary,
    onError: AppColors.textPrimary,
  );

  return ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    colorScheme: scheme,
    scaffoldBackgroundColor: AppColors.bg,
    canvasColor: AppColors.surface,
    dividerColor: AppColors.divider,
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.bg,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      centerTitle: false,
      titleTextStyle: AppText.screenTitle,
      iconTheme: IconThemeData(color: AppColors.textPrimary),
    ),
    textTheme: const TextTheme(
      headlineMedium: AppText.displayTitle,
      titleLarge: AppText.screenTitle,
      bodyMedium: AppText.body,
      bodySmall: AppText.caption,
      labelLarge: AppText.buttonLabel,
    ),
    dividerTheme: const DividerThemeData(
      color: AppColors.divider,
      thickness: AppShape.dividerWidth,
      space: AppShape.dividerWidth,
    ),
    progressIndicatorTheme: const ProgressIndicatorThemeData(
      color: AppColors.ring,
    ),
  );
}

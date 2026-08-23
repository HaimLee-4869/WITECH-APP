import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/config.dart';
import '../core/theme.dart';
import '../state/providers.dart';
import '../widgets/primary_button.dart';
import '../widgets/secondary_button.dart';
import '../widgets/status_chip.dart';
import 'admin_screen.dart';
import 'auth_screen.dart';
import 'enroll_screen.dart';

/// 홈 화면. (SPEC 8.1)
///
/// 로그인은 구현하지 않는다. 사용자 선택 드롭다운이 신원을 대신한다.
class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selected = ref.watch(selectedUserProvider);

    return Scaffold(
      backgroundColor: AppColors.bg,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: AppShape.screenPadding,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 24),
              const Text('Sign-ID', style: AppText.displayTitle),
              const SizedBox(height: 8),
              const Text('수어 제스처로 출입을 인증합니다', style: AppText.caption),
              const Spacer(flex: 2),
              const Text('인증할 사용자', style: AppText.caption),
              const SizedBox(height: 8),
              _UserDropdown(selected: selected),
              const SizedBox(height: 32),
              PrimaryButton(
                label: '인증하기',
                onPressed: () => _push(context, const AuthScreen()),
              ),
              const SizedBox(height: 12),
              SecondaryButton(
                label: '제스처 등록',
                onPressed: () => _push(context, const EnrollScreen()),
              ),
              const SizedBox(height: 12),
              SecondaryButton(
                label: '인증 이력',
                onPressed: () => _push(context, const AdminScreen()),
              ),
              const Spacer(flex: 3),
              // 지금 어떤 모드로 도는지 한눈에 보이게 한다. 목/실서버, 가짜/실카메라를
              // 헷갈린 채로 테스트하면 원인을 엉뚱한 데서 찾게 된다.
              const Center(child: _ModeChips()),
              const SizedBox(height: 20),
            ],
          ),
        ),
      ),
    );
  }

  static void _push(BuildContext context, Widget screen) {
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => screen));
  }
}

class _UserDropdown extends ConsumerWidget {
  final String selected;

  const _UserDropdown({required this.selected});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppShape.cardRadius),
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<String>(
          value: selected,
          isExpanded: true,
          dropdownColor: AppColors.surfaceAlt,
          borderRadius: BorderRadius.circular(AppShape.cardRadius),
          style: AppText.body,
          icon: const Icon(
            Icons.keyboard_arrow_down,
            color: AppColors.textSecondary,
          ),
          items: [
            for (final user in kMockUsers)
              DropdownMenuItem(value: user, child: Text(user)),
          ],
          onChanged: (value) {
            if (value != null) {
              ref.read(selectedUserProvider.notifier).select(value);
            }
          },
        ),
      ),
    );
  }
}

/// 현재 빌드가 목 API인지, 가짜 랜드마크인지 표시한다.
class _ModeChips extends StatelessWidget {
  const _ModeChips();

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 8,
      children: [
        StatusChip(
          label: kUseMockApi ? '목 API' : '실서버',
          color: kUseMockApi ? AppColors.textSecondary : AppColors.success,
          icon: Icons.cloud_outlined,
        ),
        StatusChip(
          label: kUseFakeLandmarks ? '가짜 랜드마크' : '카메라',
          color: kUseFakeLandmarks
              ? AppColors.textSecondary
              : AppColors.success,
          icon: Icons.back_hand_outlined,
        ),
      ],
    );
  }
}

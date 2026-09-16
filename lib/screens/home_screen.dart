import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/config.dart';
import '../core/theme.dart';
import '../models/app_user.dart';
import '../state/providers.dart';
import '../widgets/primary_button.dart';
import '../widgets/secondary_button.dart';
import '../widgets/status_chip.dart';
import 'add_user_sheet.dart';
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
    final users = ref.watch(usersProvider);
    final selected = ref.watch(selectedUserProvider);
    final gesture = ref.watch(selectedGestureProvider);
    // 앱 시작 시 GET /config를 불러 등록 회차 수 등을 받아온다. (backend/README 4.4)
    final configState = ref.watch(serverConfigProvider);

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
              _UserDropdown(users: users, selected: selected),
              const SizedBox(height: 8),
              const _AddUserButton(),
              const SizedBox(height: 16),
              const Text('수어 암호', style: AppText.caption),
              const SizedBox(height: 8),
              _GestureDropdown(selected: gesture),
              const SizedBox(height: 32),
              PrimaryButton(
                label: '인증하기',
                onPressed: selected == null
                    ? null
                    : () => _push(context, const AuthScreen()),
              ),
              const SizedBox(height: 12),
              SecondaryButton(
                label: '제스처 등록',
                onPressed: selected == null
                    ? null
                    : () => _push(context, const EnrollScreen()),
              ),
              const SizedBox(height: 12),
              SecondaryButton(
                label: '인증 이력',
                onPressed: () => _push(context, const AdminScreen()),
              ),
              const Spacer(flex: 3),
              if (configState.error != null) ...[
                Text(
                  configState.error!,
                  textAlign: TextAlign.center,
                  style: AppText.caption.copyWith(color: AppColors.danger),
                ),
                const SizedBox(height: 8),
              ],
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

/// 사용자 추가 진입점.
///
/// 실제 서비스라면 회원가입 뒤 제스처를 등록한다. 지금은 로그인이 없어 홈에서
/// 사용자를 고르는 구조라, 그 사이를 이 버튼이 메운다. 추가하면 바로 선택되고
/// 제스처 등록으로 이어갈 수 있다.
class _AddUserButton extends ConsumerWidget {
  const _AddUserButton();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Align(
      alignment: Alignment.centerLeft,
      child: TextButton.icon(
        onPressed: () => _addUser(context),
        icon: const Icon(Icons.person_add_alt, size: 18),
        label: const Text('사용자 추가'),
        style: TextButton.styleFrom(
          foregroundColor: AppColors.ring,
          padding: const EdgeInsets.symmetric(horizontal: 8),
        ),
      ),
    );
  }

  Future<void> _addUser(BuildContext context) async {
    final created = await AddUserSheet.show(context);
    if (created == null || !context.mounted) return;

    // 추가 직후 바로 등록으로 이어질 수 있게 안내한다. 자동으로 넘기지는 않는다.
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Text('${created.name} 추가됨. 수어 암호를 등록해주세요.'),
          action: SnackBarAction(
            label: '제스처 등록',
            onPressed: () => HomeScreen._push(context, const EnrollScreen()),
          ),
          duration: const Duration(seconds: 6),
        ),
      );
  }
}

/// 서버 사용자 목록(`GET /users`)에서 인증 대상을 고른다.
///
/// 화면에는 이름을 보여주고, 값(선택 키)은 서버 `users.id`다. 요청에 실리는 것도 id다.
class _UserDropdown extends ConsumerWidget {
  final AsyncValue<List<AppUser>> users;
  final AppUser? selected;

  const _UserDropdown({required this.users, required this.selected});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final list = users.value ?? const <AppUser>[];

    final Widget content;
    if (users.hasError && list.isEmpty) {
      content = _UserListMessage(
        text: '사용자 목록을 불러오지 못했습니다',
        color: AppColors.danger,
        onRetry: () => ref.invalidate(usersProvider),
      );
    } else if (users.isLoading && list.isEmpty) {
      content = const _UserListMessage(text: '사용자 목록을 불러오는 중…');
    } else if (list.isEmpty) {
      content = _UserListMessage(
        text: '서버에 등록된 사용자가 없습니다',
        onRetry: () => ref.invalidate(usersProvider),
      );
    } else {
      content = DropdownButtonHideUnderline(
        child: DropdownButton<String>(
          value: selected?.id,
          isExpanded: true,
          dropdownColor: AppColors.surfaceAlt,
          borderRadius: BorderRadius.circular(AppShape.cardRadius),
          style: AppText.body,
          icon: const Icon(
            Icons.keyboard_arrow_down,
            color: AppColors.textSecondary,
          ),
          items: [
            for (final user in list)
              DropdownMenuItem(value: user.id, child: Text(user.name)),
          ],
          onChanged: (id) {
            if (id != null) {
              ref.read(selectedUserIdProvider.notifier).select(id);
            }
          },
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppShape.cardRadius),
      ),
      child: content,
    );
  }
}

class _UserListMessage extends StatelessWidget {
  final String text;
  final Color color;
  final VoidCallback? onRetry;

  const _UserListMessage({
    required this.text,
    this.color = AppColors.textSecondary,
    this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 48,
      child: Row(
        children: [
          Expanded(
            child: Text(text, style: AppText.body.copyWith(color: color)),
          ),
          if (onRetry != null)
            TextButton(onPressed: onRetry, child: const Text('다시 시도')),
        ],
      ),
    );
  }
}

/// 등록·인증에 쓸 수어 암호 선택.
///
/// 서버는 이 값(gestureId)으로 템플릿을 조회한다. 지금은 G1~G5이고, AI팀이 개인
/// 제스처 ID 방식을 주면 [kGestureIds]의 값만 바뀐다. (backend/README 2장)
class _GestureDropdown extends ConsumerWidget {
  final String selected;

  const _GestureDropdown({required this.selected});

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
          dropdownColor: AppColors.surface,
          style: AppText.body,
          items: [
            for (final id in kGestureIds)
              DropdownMenuItem(value: id, child: Text('수어 암호 $id')),
          ],
          onChanged: (value) {
            if (value != null) {
              ref.read(selectedGestureProvider.notifier).select(value);
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

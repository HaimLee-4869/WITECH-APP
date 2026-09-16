import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/theme.dart';
import '../models/api_error.dart';
import '../models/app_user.dart';
import '../state/providers.dart';
import '../widgets/primary_button.dart';

/// 사용자 추가 시트. 이름·부서를 받아 `POST /users`로 만든다.
///
/// 로그인이 없는 구조라 "회원가입 → 제스처 등록" 사이를 메우는 화면이다.
/// 성공하면 만들어진 사용자를 돌려주고, 홈 화면이 그 사용자를 선택 상태로 바꾼다.
///
/// ID는 앱이 만든다([newUserId]). 이름이 한글이라 그대로 ID로 쓸 수 없다.
class AddUserSheet extends ConsumerStatefulWidget {
  const AddUserSheet({super.key});

  /// 바텀시트를 띄우고 만들어진 사용자를 돌려준다. 취소하면 null.
  static Future<AppUser?> show(BuildContext context) {
    return showModalBottomSheet<AppUser>(
      context: context,
      isScrollControlled: true, // 키보드가 올라와도 입력칸이 가려지지 않게
      backgroundColor: AppColors.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (_) => const AddUserSheet(),
    );
  }

  @override
  ConsumerState<AddUserSheet> createState() => _AddUserSheetState();
}

class _AddUserSheetState extends ConsumerState<AddUserSheet> {
  /// 서버가 ID 충돌(409)을 알리면 새 ID로 다시 시도하는 횟수.
  static const int _idRetries = 3;

  final _name = TextEditingController();
  final _department = TextEditingController();

  bool _submitting = false;
  String? _error;

  @override
  void dispose() {
    _name.dispose();
    _department.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final name = _name.text.trim();
    if (name.isEmpty) {
      setState(() => _error = '이름을 입력해주세요.');
      return;
    }

    setState(() {
      _submitting = true;
      _error = null;
    });

    final api = ref.read(apiClientProvider);
    final department = _department.text.trim();

    try {
      AppUser? created;
      for (var attempt = 0; attempt < _idRetries; attempt++) {
        try {
          created = await api.createUser(
            id: newUserId(),
            name: name,
            department: department.isEmpty ? null : department,
          );
          break;
        } on ApiException catch (e) {
          // 만들어낸 ID가 이미 있으면 다른 ID로 다시. 그 외 사유는 그대로 보여준다.
          if (e.reason != 'user_exists' || attempt == _idRetries - 1) rethrow;
        }
      }
      if (!mounted || created == null) return;
      // 목록을 다시 불러야 새 사용자가 드롭다운에 나온다.
      ref.invalidate(usersProvider);
      ref.read(selectedUserIdProvider.notifier).select(created.id);
      Navigator.of(context).pop(created);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.userMessage);
    } on ApiNotConfiguredException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (_) {
      if (mounted) setState(() => _error = '사용자를 추가하지 못했습니다. 잠시 후 다시 시도해주세요.');
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      // 키보드 높이만큼 밀어 올린다.
      padding: EdgeInsets.only(
        left: AppShape.screenPadding,
        right: AppShape.screenPadding,
        top: 20,
        bottom: MediaQuery.viewInsetsOf(context).bottom + 20,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text('사용자 추가', style: AppText.screenTitle),
          const SizedBox(height: 4),
          const Text('추가한 뒤 수어 암호를 등록하면 인증할 수 있습니다', style: AppText.caption),
          const SizedBox(height: 20),
          _Field(
            controller: _name,
            label: '이름',
            hint: '김건주',
            autofocus: true,
            enabled: !_submitting,
            onSubmitted: (_) => _submitting ? null : _submit(),
          ),
          const SizedBox(height: 12),
          _Field(
            controller: _department,
            label: '부서 (선택)',
            hint: '개발팀',
            enabled: !_submitting,
            onSubmitted: (_) => _submitting ? null : _submit(),
          ),
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(
              _error!,
              style: AppText.caption.copyWith(color: AppColors.danger),
            ),
          ],
          const SizedBox(height: 20),
          PrimaryButton(
            label: _submitting ? '추가하는 중…' : '추가',
            onPressed: _submitting ? null : _submit,
          ),
          const SizedBox(height: 8),
          TextButton(
            onPressed: _submitting ? null : () => Navigator.of(context).pop(),
            child: const Text('취소'),
          ),
        ],
      ),
    );
  }
}

class _Field extends StatelessWidget {
  final TextEditingController controller;
  final String label;
  final String hint;
  final bool autofocus;
  final bool enabled;
  final ValueChanged<String>? onSubmitted;

  const _Field({
    required this.controller,
    required this.label,
    required this.hint,
    required this.enabled,
    this.autofocus = false,
    this.onSubmitted,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: AppText.caption),
        const SizedBox(height: 6),
        TextField(
          controller: controller,
          autofocus: autofocus,
          enabled: enabled,
          textInputAction: TextInputAction.done,
          onSubmitted: onSubmitted,
          style: AppText.body,
          decoration: InputDecoration(
            hintText: hint,
            hintStyle: AppText.body.copyWith(color: AppColors.textSecondary),
            filled: true,
            fillColor: AppColors.surfaceAlt,
            contentPadding: const EdgeInsets.symmetric(
              horizontal: 16,
              vertical: 14,
            ),
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(AppShape.cardRadius),
              borderSide: BorderSide.none,
            ),
          ),
        ),
      ],
    );
  }
}

import 'package:flutter/material.dart';

import '../core/theme.dart';

/// 주 버튼. 높이 52, 완전 알약형, 배경 primary. (SPEC 5장)
///
/// [onPressed]가 null이면 비활성 상태로 흐리게 표시한다.
class PrimaryButton extends StatelessWidget {
  final String label;
  final VoidCallback? onPressed;

  const PrimaryButton({super.key, required this.label, this.onPressed});

  @override
  Widget build(BuildContext context) {
    final enabled = onPressed != null;
    return SizedBox(
      width: double.infinity,
      height: AppShape.primaryButtonHeight,
      child: Material(
        color: enabled
            ? AppColors.primary
            : AppColors.primary.withValues(alpha: 0.35),
        borderRadius: BorderRadius.circular(AppShape.primaryButtonRadius),
        child: InkWell(
          onTap: onPressed,
          borderRadius: BorderRadius.circular(AppShape.primaryButtonRadius),
          child: Center(
            child: Text(
              label,
              style: AppText.buttonLabel.copyWith(
                color: enabled
                    ? AppColors.textPrimary
                    : AppColors.textPrimary.withValues(alpha: 0.6),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

import 'package:flutter/material.dart';

import '../core/theme.dart';

/// 보조 버튼. 높이 44, 배경 surfaceAlt, 텍스트 textSecondary. (SPEC 5장)
class SecondaryButton extends StatelessWidget {
  final String label;
  final VoidCallback? onPressed;

  /// 목업의 "취소"처럼 폭을 내용에 맞추고 가운데 두고 싶을 때 사용.
  final double? width;

  const SecondaryButton({
    super.key,
    required this.label,
    this.onPressed,
    this.width,
  });

  @override
  Widget build(BuildContext context) {
    final enabled = onPressed != null;
    return SizedBox(
      width: width ?? double.infinity,
      height: AppShape.secondaryButtonHeight,
      child: Material(
        color: enabled
            ? AppColors.surfaceAlt
            : AppColors.surfaceAlt.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(AppShape.secondaryButtonRadius),
        child: InkWell(
          onTap: onPressed,
          borderRadius: BorderRadius.circular(AppShape.secondaryButtonRadius),
          child: Center(
            child: Text(
              label,
              style: AppText.buttonLabel.copyWith(
                color: enabled
                    ? AppColors.textSecondary
                    : AppColors.textSecondary.withValues(alpha: 0.5),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

import 'package:flutter/material.dart';

import '../core/theme.dart';

/// 작은 상태 배지. 개발용 정보(점수·상태명 등)를 절제해서 보여준다.
class StatusChip extends StatelessWidget {
  final String label;
  final Color color;

  /// 앞에 붙일 아이콘. 없으면 텍스트만.
  final IconData? icon;

  const StatusChip({
    super.key,
    required this.label,
    required this.color,
    this.icon,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        // 배경은 같은 색을 옅게 깔아 토큰 밖의 새 색을 만들지 않는다.
        color: color.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 14, color: color),
            const SizedBox(width: 6),
          ],
          Text(label, style: AppText.caption.copyWith(color: color)),
        ],
      ),
    );
  }
}

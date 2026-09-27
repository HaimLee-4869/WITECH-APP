import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/theme.dart';
import '../state/providers.dart';

/// "오른손을 사용해주세요" 안내. 인증·등록 화면 공통.
///
/// 현재 모델은 오른손 기준이다. AI 모듈은 handedness가 Left면 오른손으로 좌우 반전해
/// 받지만, 플러그인이 좌/우를 주지 않아 앱은 handedness를 보내지 못한다. 그래서 왼손
/// 입력은 거절도 반전도 되지 않고 오른손처럼 처리되어 점수만 조용히 떨어진다.
/// **화면 안내가 유일한 방어선**이다.
/// 서버가 `handRequired`를 바꾸면(`any`) 이 안내는 자동으로 사라진다.
/// (backend/README 4.1, backend/ai/README.md)
class HandGuideNotice extends ConsumerWidget {
  const HandGuideNotice({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final config = ref.watch(serverConfigProvider.select((s) => s.config));
    if (!config.requiresRightHand) return const SizedBox.shrink();

    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        const Icon(
          Icons.back_hand_outlined,
          size: 16,
          color: AppColors.textSecondary,
        ),
        const SizedBox(width: 6),
        Text('오른손을 사용해주세요', style: AppText.caption),
      ],
    );
  }
}

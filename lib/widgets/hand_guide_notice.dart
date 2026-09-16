import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/theme.dart';
import '../state/providers.dart';

/// "오른손을 사용해주세요" 안내. 인증·등록 화면 공통.
///
/// 현재 모델은 오른손 캡처만 학습했고, 플러그인이 좌/우를 주지 않아 서버가
/// 왼손을 자동으로 걸러낼 수 없다. 그래서 **화면 안내가 유일한 방어선**이다.
/// 서버가 `handRequired`를 바꾸면(`any`) 이 안내는 자동으로 사라진다.
/// (backend/README 4.1, ai/AI_RELEASE_README.md)
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

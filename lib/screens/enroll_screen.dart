import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/config.dart';
import '../core/theme.dart';
import '../state/enroll_controller.dart';
import '../state/providers.dart';
import '../widgets/capture_ring.dart';
import '../widgets/hand_overlay_painter.dart';
import '../widgets/primary_button.dart';
import '../widgets/secondary_button.dart';

/// 제스처 등록 화면. (SPEC 8.4)
///
/// 인증 화면과 같은 캡처 UI를 쓰되, 같은 제스처를 [kEnrollRepeatCount]회 반복
/// 수집하고 상단에 진행 인디케이터(점)를 둔다.
class EnrollScreen extends ConsumerStatefulWidget {
  const EnrollScreen({super.key});

  @override
  ConsumerState<EnrollScreen> createState() => _EnrollScreenState();
}

class _EnrollScreenState extends ConsumerState<EnrollScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) ref.read(enrollProvider.notifier).attach();
    });
  }

  @override
  Widget build(BuildContext context) {
    final diameter = captureRingDiameter(MediaQuery.sizeOf(context));
    final phase = ref.watch(enrollProvider.select((s) => s.phase));

    return Scaffold(
      backgroundColor: AppColors.bg,
      appBar: AppBar(title: const Text('제스처 등록')),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: AppShape.screenPadding,
          ),
          child: phase == EnrollPhase.done
              ? const _EnrollDone()
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const SizedBox(height: 8),
                    const _TakeIndicator(),
                    const Spacer(flex: 2),
                    Center(child: _CaptureArea(diameter: diameter)),
                    const Spacer(flex: 2),
                    const _MessageText(),
                    const SizedBox(height: 24),
                    const _ActionButtons(),
                    const SizedBox(height: 24),
                  ],
                ),
        ),
      ),
    );
  }
}

/// 회차 진행 인디케이터. 점 [kEnrollRepeatCount]개. (SPEC 8.4)
class _TakeIndicator extends ConsumerWidget {
  const _TakeIndicator();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final done = ref.watch(enrollProvider.select((s) => s.completedTakes));

    return Column(
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: List.generate(kEnrollRepeatCount, (i) {
            final filled = i < done;
            return Container(
              width: 10,
              height: 10,
              margin: const EdgeInsets.symmetric(horizontal: 6),
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: filled ? AppColors.ring : AppColors.surfaceAlt,
              ),
            );
          }),
        ),
        const SizedBox(height: 8),
        Text('$done / $kEnrollRepeatCount 회차 완료', style: AppText.caption),
      ],
    );
  }
}

class _CaptureArea extends ConsumerWidget {
  final double diameter;

  const _CaptureArea({required this.diameter});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final phase = ref.watch(enrollProvider.select((s) => s.phase));
    final progress = ref.watch(enrollProvider.select((s) => s.progress));
    final source = ref.watch(landmarkSourceProvider);

    return CaptureRing(
      diameter: diameter,
      borderColor: phase == EnrollPhase.handSearching
          ? AppColors.textSecondary
          : AppColors.ring,
      progress: phase == EnrollPhase.recording ? progress : null,
      child: Stack(
        fit: StackFit.expand,
        children: [
          ?source.buildPreview(),
          const _Overlay(),
          if (phase == EnrollPhase.handReady) const _Countdown(),
          if (phase == EnrollPhase.uploading)
            const Center(
              child: SizedBox(
                width: 44,
                height: 44,
                child: CircularProgressIndicator(
                  strokeWidth: 3,
                  color: AppColors.ring,
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _Overlay extends ConsumerWidget {
  const _Overlay();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final frame = ref.watch(enrollProvider.select((s) => s.latestFrame));
    final transform = ref.watch(landmarkSourceProvider).transform;

    return CustomPaint(
      painter: HandOverlayPainter(
        frame: frame,
        rotationDegrees: transform.rotationDegrees,
        mirror: transform.mirror,
        sourceAspectRatio: transform.sourceAspectRatio,
      ),
    );
  }
}

class _Countdown extends ConsumerWidget {
  const _Countdown();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final n = ref.watch(enrollProvider.select((s) => s.countdown));
    return Center(
      child: Text(
        '$n',
        style: const TextStyle(
          fontSize: 72,
          fontWeight: FontWeight.w600,
          color: AppColors.ring,
        ),
      ),
    );
  }
}

class _MessageText extends ConsumerWidget {
  const _MessageText();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final message = ref.watch(enrollProvider.select((s) => s.message));
    final hasNotice = ref.watch(
      enrollProvider.select((s) => s.notice != null),
    );

    return SizedBox(
      height: 52,
      child: Center(
        child: Text(
          message,
          textAlign: TextAlign.center,
          style: AppText.body.copyWith(
            color: hasNotice ? AppColors.danger : AppColors.textPrimary,
          ),
        ),
      ),
    );
  }
}

class _ActionButtons extends ConsumerWidget {
  const _ActionButtons();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(enrollProvider);
    final controller = ref.read(enrollProvider.notifier);

    return Column(
      children: [
        PrimaryButton(
          label: state.completedTakes == 0 ? '등록 시작' : '계속',
          onPressed: state.canStart ? controller.start : null,
        ),
        const SizedBox(height: 12),
        SecondaryButton(
          label: '취소',
          width: 160,
          onPressed: state.phase == EnrollPhase.uploading
              ? null
              : () {
                  if (state.isRunning) {
                    controller.cancel();
                  } else {
                    Navigator.of(context).maybePop();
                  }
                },
        ),
      ],
    );
  }
}

/// 등록 완료 화면.
class _EnrollDone extends ConsumerWidget {
  const _EnrollDone();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final res = ref.watch(enrollProvider.select((s) => s.response));

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Spacer(flex: 3),
        const Icon(
          Icons.verified_outlined,
          size: 112,
          color: AppColors.success,
        ),
        const SizedBox(height: 24),
        const Text(
          '수어 암호가 등록되었습니다',
          textAlign: TextAlign.center,
          style: AppText.screenTitle,
        ),
        const SizedBox(height: 12),
        Text(
          '${res?.acceptedTakes ?? 0}회차가 등록되었습니다. 이제 인증에 사용할 수 있습니다.',
          textAlign: TextAlign.center,
          style: AppText.caption,
        ),
        const Spacer(flex: 4),
        PrimaryButton(
          label: '확인',
          onPressed: () => Navigator.of(context).maybePop(),
        ),
        const SizedBox(height: 24),
      ],
    );
  }
}

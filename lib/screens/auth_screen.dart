import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/theme.dart';
import '../state/auth_flow_controller.dart';
import '../state/providers.dart';
import '../widgets/capture_ring.dart';
import '../widgets/hand_overlay_painter.dart';
import '../widgets/primary_button.dart';
import '../widgets/secondary_button.dart';
import 'result_screen.dart';

/// 인증 화면. (SPEC 8.2)
///
/// 레이아웃은 목업 왼쪽 화면을 따른다.
/// 로고 → 가이드 원(프리뷰 + 오버레이) → 안내 문구 → 인증 버튼 → 취소 버튼.
class AuthScreen extends ConsumerStatefulWidget {
  const AuthScreen({super.key});

  @override
  ConsumerState<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends ConsumerState<AuthScreen> {
  @override
  void initState() {
    super.initState();
    // build 중에 provider를 건드리면 안 되므로 첫 프레임 뒤에 소스를 켠다.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) ref.read(authFlowProvider.notifier).attach();
    });
  }

  @override
  Widget build(BuildContext context) {
    // done이 되면 결과 화면으로 넘긴다. 화면 전환은 화면의 책임이라
    // 컨트롤러가 아니라 여기서 처리한다.
    ref.listen(authFlowProvider.select((s) => s.phase), (_, phase) {
      if (phase == AuthPhase.done) _goToResult();
    });

    final diameter = captureRingDiameter(MediaQuery.sizeOf(context));

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
              const SizedBox(height: 12),
              const Align(
                alignment: Alignment.centerLeft,
                child: Text('Sign-ID', style: AppText.displayTitle),
              ),
              const Spacer(flex: 2),
              Center(child: _CaptureArea(diameter: diameter)),
              const Spacer(flex: 2),
              const _MessageText(),
              const SizedBox(height: 28),
              const _ActionButtons(),
              const SizedBox(height: 24),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _goToResult() async {
    final response = ref.read(authFlowProvider).response;
    if (response == null || !mounted) return;

    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ResultScreen(response: response),
      ),
    );
    // 결과 화면에서 "재시도"로 돌아온 경우를 위해 상태를 처음으로 되돌린다.
    if (mounted) ref.read(authFlowProvider.notifier).reset();
  }
}

/// 가이드 원 + 프리뷰 + 오버레이.
///
/// 프레임은 30fps로 바뀌므로 화면 전체를 다시 그리지 않도록 이 위젯만
/// 프레임을 구독한다.
class _CaptureArea extends ConsumerWidget {
  final double diameter;

  const _CaptureArea({required this.diameter});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final phase = ref.watch(authFlowProvider.select((s) => s.phase));
    final progress = ref.watch(authFlowProvider.select((s) => s.progress));
    final source = ref.watch(landmarkSourceProvider);

    return CaptureRing(
      diameter: diameter,
      borderColor: _borderColorFor(phase),
      // recording일 때만 테두리를 진행률 아크로 그린다. (SPEC 8.2)
      progress: phase == AuthPhase.recording ? progress : null,
      child: Stack(
        fit: StackFit.expand,
        children: [
          // 카메라가 있는 소스만 프리뷰를 깐다. Fake 소스는 null을 준다.
          ?source.buildPreview(),
          const _Overlay(),
          if (phase == AuthPhase.handReady) const _Countdown(),
          if (phase == AuthPhase.uploading) const _UploadingIndicator(),
        ],
      ),
    );
  }

  /// 상태별 원 테두리 색. (SPEC 8.2)
  static Color _borderColorFor(AuthPhase phase) => switch (phase) {
    // 손을 찾는 중에는 아직 준비가 안 됐다는 뜻으로 회색.
    AuthPhase.handSearching => AppColors.textSecondary,
    // idle은 목업과 같이 민트 원을 그대로 보여준다.
    AuthPhase.idle ||
    AuthPhase.handReady ||
    AuthPhase.recording ||
    AuthPhase.uploading ||
    AuthPhase.done => AppColors.ring,
  };
}

/// 손 뼈대 오버레이만 담당. 프레임 변화에 이 위젯만 반응한다.
class _Overlay extends ConsumerWidget {
  const _Overlay();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final frame = ref.watch(authFlowProvider.select((s) => s.latestFrame));
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

/// 3 → 2 → 1 카운트다운. (SPEC 8.2 handReady)
class _Countdown extends ConsumerWidget {
  const _Countdown();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final n = ref.watch(authFlowProvider.select((s) => s.countdown));
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

/// 전송 중 원 안에 표시하는 인디케이터. (SPEC 8.2 uploading)
class _UploadingIndicator extends StatelessWidget {
  const _UploadingIndicator();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: SizedBox(
        width: 44,
        height: 44,
        child: CircularProgressIndicator(
          strokeWidth: 3,
          color: AppColors.ring,
        ),
      ),
    );
  }
}

/// 상태에 따라 바뀌는 안내 문구.
class _MessageText extends ConsumerWidget {
  const _MessageText();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final message = ref.watch(authFlowProvider.select((s) => s.message));
    final hasNotice = ref.watch(
      authFlowProvider.select((s) => s.notice != null),
    );

    return SizedBox(
      // 문구 길이에 따라 원이 위아래로 움직이지 않도록 높이를 고정한다.
      height: 52,
      child: Center(
        child: Text(
          message,
          textAlign: TextAlign.center,
          style: AppText.body.copyWith(
            // 문제 상황은 danger로 구분해 보여준다.
            color: hasNotice ? AppColors.danger : AppColors.textPrimary,
          ),
        ),
      ),
    );
  }
}

/// 인증 / 취소 버튼.
class _ActionButtons extends ConsumerWidget {
  const _ActionButtons();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(authFlowProvider);
    final controller = ref.read(authFlowProvider.notifier);

    return Column(
      children: [
        PrimaryButton(
          label: '인증',
          // idle에서만 누를 수 있다. 진행 중에는 비활성. (SPEC 8.2)
          onPressed: state.canStart ? controller.start : null,
        ),
        const SizedBox(height: 12),
        SecondaryButton(
          label: '취소',
          width: 160,
          // 진행 중이면 흐름 취소, 아니면 화면을 닫는다.
          onPressed: state.phase == AuthPhase.uploading
              ? null // 전송 중에는 끊을 수 없다
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

/// 안티스푸핑 Challenge 화면. 인증 화면 **앞에** 붙는다.
///
/// 통과해야 제스처 인증(`AuthScreen`)으로 넘어간다. 실패하면 `/verify`를 호출하지
/// 않는다. 녹화 영상을 재생하는 replay attack을 막는 것이 목적이므로, 여기서
/// 막힌 시도는 인증 서버에 도달할 이유가 없다.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../challenge/challenge_config.dart';
import '../challenge/challenge_state_machine.dart';
import '../core/theme.dart';
import '../models/challenge_messages.dart';
import '../state/challenge_controller.dart';
import '../state/providers.dart';
import '../widgets/capture_ring.dart';
import '../widgets/challenge_guide.dart';
import '../widgets/challenge_move_debug.dart';
import '../widgets/hand_guide_notice.dart';
import '../widgets/hand_overlay_painter.dart';
import '../widgets/primary_button.dart';
import '../widgets/secondary_button.dart';
import 'auth_screen.dart';

/// 검출된 손 모양을 화면에 띄울지. 개발용이라 시연 전에 끈다.
const bool kShowChallengeDebug = false;

class ChallengeScreen extends ConsumerStatefulWidget {
  const ChallengeScreen({super.key});

  @override
  ConsumerState<ChallengeScreen> createState() => _ChallengeScreenState();
}

class _ChallengeScreenState extends ConsumerState<ChallengeScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) return;
      await ref.read(challengeControllerProvider.notifier).begin();
      // 카메라 초기화가 끝나야 buildPreview()가 위젯을 돌려준다.
      if (mounted) setState(() {});
    });
  }

  @override
  Widget build(BuildContext context) {
    ref.listen(challengeControllerProvider.select((s) => s.phase), (_, phase) {
      if (phase == ChallengePhase.passed) _goToAuth();
    });

    return Scaffold(
      backgroundColor: AppColors.bg,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: AppShape.screenPadding,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              const SizedBox(height: 12),
              const Align(
                alignment: Alignment.centerLeft,
                child: Text('Sign-ID', style: AppText.displayTitle),
              ),
              const SizedBox(height: 4),
              const Text('동작 확인', style: AppText.caption),
              const SizedBox(height: 12),
              const _StepIndicator(),
              const SizedBox(height: 12),
              // 원이 남은 세로 공간을 전부 쓴다. 이동 단계에서 손을 움직일
              // 공간이 좁으면 변위 관문을 넘기기 어렵다.
              Expanded(
                child: LayoutBuilder(
                  builder: (context, constraints) => Center(
                    child: _CaptureArea(
                      diameter: captureRingDiameterIn(constraints),
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              const _TimeBar(),
              const SizedBox(height: 12),
              const _Prompt(),
              const SizedBox(height: 8),
              const HandGuideNotice(),
              if (kShowChallengeDebug) ...<Widget>[
                const SizedBox(height: 8),
                const _DebugLine(),
              ],
              const SizedBox(height: 12),
              const _Actions(),
              const SizedBox(height: 24),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _goToAuth() async {
    if (!mounted) return;
    // Challenge 화면을 스택에서 빼고 인증으로 간다. 뒤로 가기로 통과한 Challenge에
    // 되돌아오면 같은 통과를 다시 쓰게 된다.
    await Navigator.of(context).pushReplacement(
      MaterialPageRoute<void>(builder: (_) => const AuthScreen()),
    );
  }
}

/// 3단계 진행 표시. 지나온 단계는 채우고, 지금 단계는 강조한다.
class _StepIndicator extends ConsumerWidget {
  const _StepIndicator();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ChallengeFlowState flow = ref.watch(challengeControllerProvider);
    final ChallengeConfig? config = ref.watch(
      serverConfigProvider.select((s) => s.config.challenge),
    );
    if (config == null || flow.actions.isEmpty) {
      return const SizedBox(height: 92);
    }

    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceEvenly,
      children: <Widget>[
        for (final (int i, String action) in flow.actions.indexed)
          Column(
            children: <Widget>[
              ChallengeGuide(
                action: action,
                config: config,
                size: 64,
                dimmed: i != flow.stepIndex,
              ),
              const SizedBox(height: 4),
              Text(
                '${i + 1}',
                style: AppText.caption.copyWith(
                  color: switch (i.compareTo(flow.stepIndex)) {
                    < 0 => AppColors.success, // 통과한 단계
                    0 => AppColors.ring, // 지금 단계
                    _ => AppColors.textSecondary,
                  },
                ),
              ),
            ],
          ),
      ],
    );
  }
}

/// 가이드 원 + 프리뷰 + 오버레이 + 지금 단계 큰 그림.
class _CaptureArea extends ConsumerWidget {
  final double diameter;

  const _CaptureArea({required this.diameter});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ChallengeFlowState flow = ref.watch(challengeControllerProvider);
    final source = ref.watch(landmarkSourceProvider);

    return CaptureRing(
      diameter: diameter,
      borderColor: switch (flow.phase) {
        ChallengePhase.failed || ChallengePhase.unavailable => AppColors.danger,
        ChallengePhase.passed => AppColors.success,
        ChallengePhase.running => AppColors.ring,
        ChallengePhase.idle => AppColors.textSecondary,
      },
      // 손 모양 유지 진행도를 테두리 아크로 보여준다. 얼마나 더 있어야 하는지
      // 모르면 사용자가 손을 먼저 내린다.
      progress: flow.status?.holdProgress,
      child: Stack(
        fit: StackFit.expand,
        children: <Widget>[
          ?source.buildPreview(),
          const _Overlay(),
        ],
      ),
    );
  }
}

class _Overlay extends ConsumerWidget {
  const _Overlay();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // 오버레이는 인증 화면과 같은 규칙으로 그린다. 좌표 변환은 소스가 알려준다.
    // 반전은 화면 전용이다. 판정에 들어가는 좌표는 원본이다.
    final frame =
        ref.watch(challengeControllerProvider.select((s) => s.latestFrame));
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

/// 남은 시간 바. 이탈 관문 대기 중에는 멈춘 것을 드러낸다.
class _TimeBar extends ConsumerWidget {
  const _TimeBar();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final Status? status =
        ref.watch(challengeControllerProvider.select((s) => s.status));
    final ChallengeConfig? config = ref.watch(
      serverConfigProvider.select((s) => s.config.challenge),
    );
    if (status == null || config == null) return const SizedBox(height: 6);

    final double total = config.timing.perActionTimeoutMs;
    final double ratio =
        total <= 0 ? 0.0 : (status.remainingMs / total).clamp(0.0, 1.0);
    final bool paused = status.awaitingEscape;

    return ClipRRect(
      borderRadius: BorderRadius.circular(3),
      child: LinearProgressIndicator(
        value: paused ? 1.0 : ratio,
        minHeight: 6,
        backgroundColor: AppColors.surfaceAlt,
        // 관문 대기 중에는 시계가 멈춘다. 색을 바꿔 "멈췄다"를 보여준다.
        color: paused
            ? AppColors.textSecondary
            : (ratio < 0.3 ? AppColors.danger : AppColors.ring),
      ),
    );
  }
}

class _Prompt extends ConsumerWidget {
  const _Prompt();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ChallengeFlowState flow = ref.watch(challengeControllerProvider);

    final (String text, Color color) = switch (flow.phase) {
      ChallengePhase.unavailable => (
          flow.notice ?? '동작 확인을 시작할 수 없습니다.',
          AppColors.danger,
        ),
      ChallengePhase.failed => (
          challengeFailMessage(flow.status?.failReason),
          AppColors.danger,
        ),
      ChallengePhase.passed => ('동작 확인 완료', AppColors.success),
      ChallengePhase.idle => ('준비 중입니다…', AppColors.textSecondary),
      ChallengePhase.running => (
          flow.status == null
              ? '원 안에 손을 들어주세요'
              : challengePrompt(flow.status!),
          flow.status?.awaitingEscape ?? false
              ? AppColors.textSecondary
              : AppColors.textPrimary,
        ),
    };

    return Text(
      text,
      textAlign: TextAlign.center,
      style: AppText.body.copyWith(color: color),
    );
  }
}

/// 개발용 진단 표시. [kShowChallengeDebug]로 끈다.
///
/// 이동 단계에서는 두 관문의 값을 그대로 보여준다. 임계값을 짐작해서 바꾸기 전에
/// 무엇이 막고 있는지부터 눈으로 본다
/// (challenge_response/scripts/run_challenge.py의 진단 패널과 같은 형식).
class _DebugLine extends ConsumerWidget {
  const _DebugLine();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ChallengeFlowState flow = ref.watch(challengeControllerProvider);
    final ChallengeConfig? config = ref.watch(
      serverConfigProvider.select((s) => s.config.challenge),
    );
    final Status? status = flow.status;
    if (status == null || config == null) return const SizedBox.shrink();

    final MoveProbe? probe = status.moveProbe;
    if (probe != null) {
      return ChallengeMoveDebug(
        probe: probe,
        config: config,
        requested: status.currentAction,
        observedFps: flow.observedFps,
        lastFrameGapMs: flow.lastFrameGapMs,
        lostInjections: flow.lostInjections,
      );
    }

    // 손 모양 단계는 한 줄이면 충분하다.
    final StringBuffer buffer = StringBuffer()
      ..write('검출: ${challengeShapeLabel(flow.debugShape)}');
    if (status.shapeConfidence > 0) {
      buffer.write(' (${status.shapeConfidence.toStringAsFixed(2)})');
    }
    if (status.awaitingEscape) {
      buffer.write(' / 이탈 ${(status.escapeProgress * 100).round()}%');
    }
    if (flow.observedFps > 0) {
      buffer.write(' / ${flow.observedFps.toStringAsFixed(1)}fps');
    }

    return Text(
      buffer.toString(),
      textAlign: TextAlign.center,
      style: AppText.caption.copyWith(color: AppColors.textSecondary),
    );
  }
}

class _Actions extends ConsumerWidget {
  const _Actions();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ChallengeFlowState flow = ref.watch(challengeControllerProvider);
    final ChallengeController controller =
        ref.read(challengeControllerProvider.notifier);

    final bool canRetry =
        flow.phase == ChallengePhase.failed && flow.retriesLeft > 0;

    return Column(
      children: <Widget>[
        if (canRetry)
          PrimaryButton(
            label: '다시 시도 (${flow.retriesLeft}회 남음)',
            onPressed: controller.retry,
          ),
        if (flow.phase == ChallengePhase.failed && !canRetry)
          Text(
            '재시도 횟수를 모두 사용했습니다.',
            textAlign: TextAlign.center,
            style: AppText.caption.copyWith(color: AppColors.danger),
          ),
        const SizedBox(height: 12),
        SecondaryButton(
          label: '취소',
          onPressed: () {
            controller.cancel();
            Navigator.of(context).pop();
          },
        ),
      ],
    );
  }
}

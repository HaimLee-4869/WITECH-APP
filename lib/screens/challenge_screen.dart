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
import '../models/verify.dart';
import '../state/auth_session_controller.dart';
import '../state/providers.dart';
import '../widgets/capture_ring.dart';
import '../widgets/challenge_guide.dart';
import '../widgets/challenge_move_debug.dart';
import '../widgets/hand_guide_notice.dart';
import '../widgets/hand_overlay_painter.dart';
import '../widgets/primary_button.dart';
import '../widgets/secondary_button.dart';
import 'result_screen.dart';

/// 검출된 손 모양·관문 값을 **화면에** 띄울지. 시연 중에는 끈다.
const bool kShowChallengeDebug = false;

/// 판정 로그를 **서버로** 보낼지 (`POST /debug/challenge`).
///
/// 화면 패널과 따로 둔다. 시연 화면은 깔끔해야 하지만, 로그는 나중에 문제를
/// 되짚고 **연속성 임계값을 도출하는 근거**라 계속 모아야 한다
/// (`ContinuityMonitor`의 scaleJump/wristJump 분포).
///
/// 전송에 실패해도 인증은 그대로 진행된다(fire and forget).
const bool kSendChallengeLog = true;

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
      await ref.read(authSessionProvider.notifier).begin();
      // 카메라 초기화가 끝나야 buildPreview()가 위젯을 돌려준다.
      if (mounted) setState(() {});
    });
  }

  @override
  Widget build(BuildContext context) {
    ref.listen(authSessionProvider.select((s) => s.phase), (_, phase) {
      if (phase == SessionPhase.done) _goToResult();
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
              const Text('동작 확인 후 수어 암호', style: AppText.caption),
              const SizedBox(height: 8),
              const _KeepHandBanner(),
              const SizedBox(height: 8),
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

  /// 인증 응답을 받으면 결과 화면으로.
  ///
  /// Challenge → 인증으로 **화면이 바뀌지 않는다.** 한 화면 안에서 단계만 바뀐다.
  /// 화면을 옮기면 카메라가 재생성되어 연속성이 끊긴다.
  Future<void> _goToResult() async {
    final VerifyResponse? response = ref.read(authSessionProvider).response;
    if (response == null || !mounted) return;
    await Navigator.of(context).push(
      MaterialPageRoute<void>(builder: (_) => ResultScreen(response: response)),
    );
    if (mounted) ref.read(authSessionProvider.notifier).cancel();
  }
}

/// 3단계 진행 표시. 지나온 단계는 채우고, 지금 단계는 강조한다.
class _StepIndicator extends ConsumerWidget {
  const _StepIndicator();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AuthSessionState flow = ref.watch(authSessionProvider);
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
                    < 0 => AppColors.progress, // 통과한 단계
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
    final AuthSessionState flow = ref.watch(authSessionProvider);
    final source = ref.watch(landmarkSourceProvider);

    return CaptureRing(
      diameter: diameter,
      borderColor: switch (flow.phase) {
        SessionPhase.failed || SessionPhase.unavailable => AppColors.danger,
        SessionPhase.done => AppColors.progress,
        // 제스처 수집 중에는 촬영 중이라는 뜻으로 민트. 진행률 아크는 보라다.
        SessionPhase.recording || SessionPhase.uploading => AppColors.ring,
        // 손을 찾는 중에는 아직 준비가 안 됐다는 뜻으로 회색.
        // **초록은 PASS 배지에만 쓴다.** 진행 중인 것에 초록을 쓰면 "통과했다"로
        // 읽혀서, 정작 통과했을 때 보여줄 신호가 남지 않는다. 나머지는 보라.
        SessionPhase.challenge => switch (flow.status) {
          null => AppColors.textSecondary,
          // 결과 표시가 가장 우선이다. 방금 맞았는지 틀렸는지를 먼저 알려준다.
          final Status s when s.stepResult == StepOutcome.pass =>
            AppColors.success,
          final Status s when s.stepResult == StepOutcome.fail =>
            AppColors.danger,
          final Status s when s.awaitingHand => AppColors.textSecondary,
          final Status s when s.preparing => AppColors.progress,
          _ => AppColors.ring,
        },
        SessionPhase.idle => AppColors.textSecondary,
      },
      // 대기 중에는 손이 얼마나 연속으로 잡혔는지, 판정 중에는 손 모양 유지
      // 진행도를 테두리 아크로 보여준다. 얼마나 더 있어야 하는지 모르면
      // 사용자가 손을 먼저 내린다.
      progress: switch (flow.phase) {
        // 제스처 수집 중에는 촬영 진행도(보라 아크).
        SessionPhase.recording => flow.recordProgress,
        SessionPhase.challenge => flow.status == null
            ? null
            : (flow.status!.awaitingHand
                ? flow.status!.handReadyProgress
                : flow.status!.holdProgress),
        _ => null,
      },
      child: Stack(
        fit: StackFit.expand,
        children: <Widget>[
          ?source.buildPreview(),
          const _Overlay(),
          const _ResultBadge(),
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
        ref.watch(authSessionProvider.select((s) => s.latestFrame));
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
        ref.watch(authSessionProvider.select((s) => s.status));
    final ChallengeConfig? config = ref.watch(
      serverConfigProvider.select((s) => s.config.challenge),
    );
    if (status == null || config == null) return const SizedBox(height: 6);

    final double total = config.timing.perActionTimeoutMs;
    final double ratio =
        total <= 0 ? 0.0 : (status.remainingMs / total).clamp(0.0, 1.0);
    // 손을 기다리는 중, 결과 표시 중, 준비 시간 중, 이탈 관문 대기 중에는
    // 제한 시간이 흐르지 않는다.
    final bool paused = status.awaitingEscape ||
        status.awaitingHand ||
        status.preparing ||
        status.stepResult != null;

    if (status.stepResult != null) {
      // 결과를 보는 동안에는 시간 바를 비워 둔다. 시간이 흐르지 않는다는 뜻이다.
      return const SizedBox(height: 6);
    }

    if (status.preparing) {
      // 준비 시간이 줄어드는 것을 보여준다. 제한 시간이 아니라는 뜻으로 색을 바꾼다.
      final double left = config.timing.stepPrepareMs <= 0
          ? 0.0
          : (status.prepareRemainingMs / config.timing.stepPrepareMs)
              .clamp(0.0, 1.0);
      return ClipRRect(
        borderRadius: BorderRadius.circular(3),
        child: LinearProgressIndicator(
          value: 1.0 - left,
          minHeight: 6,
          backgroundColor: AppColors.surfaceAlt,
          color: AppColors.progress,
        ),
      );
    }

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
    final AuthSessionState flow = ref.watch(authSessionProvider);

    final (String text, Color color) = switch (flow.phase) {
      SessionPhase.unavailable => (
          flow.notice ?? '동작 확인을 시작할 수 없습니다.',
          AppColors.danger,
        ),
      SessionPhase.failed => (
          challengeFailMessage(flow.status?.failReason),
          AppColors.danger,
        ),
      SessionPhase.done => ('인증 요청을 보냈습니다', AppColors.progress),
      SessionPhase.idle => ('준비 중입니다…', AppColors.textSecondary),
      // 여기서 손을 내리면 세션이 끊긴다. 계속 붙잡아 둬야 한다.
      SessionPhase.recording => (
          '손을 그대로 둔 채 수어 암호를 수행하세요',
          AppColors.textPrimary,
        ),
      SessionPhase.uploading => ('확인 중입니다…', AppColors.textSecondary),
      SessionPhase.challenge => (
          flow.status == null
              ? '손을 원 안에 위치시켜 주세요'
              : challengePrompt(flow.status!),
          (flow.status?.awaitingEscape ?? false) ||
                  (flow.status?.awaitingHand ?? true)
              ? AppColors.textSecondary
              : ((flow.status?.preparing ?? false)
                  ? AppColors.progress // 단계 완료는 진행 색으로
                  : AppColors.textPrimary),
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
    final AuthSessionState flow = ref.watch(authSessionProvider);
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
    final StringBuffer buffer = StringBuffer();
    if (status.awaitingHand) {
      buffer.write('대기 ${(status.handReadyProgress * 100).round()}% / ');
    }
    buffer.write('검출: ${challengeShapeLabel(flow.debugShape)}');
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
    final AuthSessionState flow = ref.watch(authSessionProvider);
    final AuthSessionController controller =
        ref.read(authSessionProvider.notifier);

    final bool canRetry =
        flow.phase == SessionPhase.failed && flow.retriesLeft > 0;

    return Column(
      children: <Widget>[
        if (canRetry)
          PrimaryButton(
            label: '다시 시도 (${flow.retriesLeft}회 남음)',
            onPressed: controller.retry,
          ),
        if (flow.phase == SessionPhase.failed && !canRetry)
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

/// 단계 결과(PASS/FAIL)를 원 위에 크게 띄운다.
///
/// 동작을 맞게 해도 순식간에 넘어가면 제대로 한 건지 인지가 안 된다.
/// 끝난 세션(통과·실패)에도 같은 배지를 보여준다.
class _ResultBadge extends ConsumerWidget {
  const _ResultBadge();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AuthSessionState flow = ref.watch(authSessionProvider);
    final Status? status = flow.status;

    final (bool pass, FailReason? reason)? shown = switch (flow.phase) {
      SessionPhase.done => (true, null),
      SessionPhase.failed => (false, status?.failReason),
      _ => switch (status?.stepResult) {
        StepOutcome.pass => (true, null),
        StepOutcome.fail => (false, status?.stepResultReason),
        null => null,
      },
    };
    if (shown == null) return const SizedBox.shrink();

    final Color color = shown.$1 ? AppColors.success : AppColors.danger;

    return ColoredBox(
      color: AppColors.bg.withValues(alpha: 0.55),
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Icon(
              shown.$1 ? Icons.check_circle_outline : Icons.cancel_outlined,
              size: 64,
              color: color,
            ),
            const SizedBox(height: 8),
            Text(
              shown.$1 ? 'PASS' : 'FAIL',
              style: AppText.displayTitle.copyWith(color: color),
            ),
            if (!shown.$1) ...<Widget>[
              const SizedBox(height: 8),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Text(
                  challengeFailMessage(shown.$2),
                  textAlign: TextAlign.center,
                  style: AppText.caption.copyWith(color: AppColors.textPrimary),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// "손을 유지하세요" 안내.
///
/// 연속 세션이라 손이 한 번이라도 사라지면 전체가 실패한다. 사람은 통과 표시를
/// 보면 손을 내리게 돼 있어서, 작은 글씨로는 부족하다. 세션 내내 눈에 띄게 둔다.
class _KeepHandBanner extends ConsumerWidget {
  const _KeepHandBanner();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AuthSessionState flow = ref.watch(authSessionProvider);
    if (flow.finished) return const SizedBox.shrink();

    // 손을 아직 안 들었으면 "들어주세요"가 먼저다. 들고 나면 "유지하세요".
    final bool keeping = flow.mustKeepHand;
    // 촬영 구간에서는 한 단계 더 세게 말한다. 동작 확인이 끝나서 다 끝난
    // 줄 알고 손을 내리는 자리가 여기다.
    final bool capturing = flow.phase == SessionPhase.recording ||
        flow.phase == SessionPhase.uploading;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: (keeping ? AppColors.ring : AppColors.surfaceAlt)
            .withValues(alpha: keeping ? 0.18 : 1.0),
        border: Border.all(
          color: keeping ? AppColors.ring : AppColors.divider,
        ),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: <Widget>[
          Icon(
            capturing
                ? Icons.do_not_touch_outlined
                : (keeping ? Icons.pan_tool_outlined : Icons.front_hand_outlined),
            size: 20,
            color: keeping ? AppColors.ring : AppColors.textSecondary,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              capturing
                  ? challengeRecordingKeepHandNotice
                  : (keeping
                      ? challengeKeepHandNotice
                      : '손을 원 안에 올리면 시작합니다'),
              style: AppText.body.copyWith(
                color: keeping ? AppColors.textPrimary : AppColors.textSecondary,
                fontWeight: keeping ? FontWeight.w600 : FontWeight.w400,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

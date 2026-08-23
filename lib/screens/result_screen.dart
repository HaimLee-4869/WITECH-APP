import 'dart:async';

import 'package:flutter/material.dart';

import '../core/theme.dart';
import '../models/verify.dart';
import '../widgets/primary_button.dart';
import '../widgets/secondary_button.dart';
import '../widgets/status_chip.dart';

/// 인증 결과 화면. (SPEC 8.3)
///
/// 성공하면 2.5초 뒤 자동으로 홈까지 되돌아간다. 실패했을 때는 자동 이동하지
/// 않는다. 왜 실패했는지 읽을 시간을 줘야 하기 때문이다.
class ResultScreen extends StatefulWidget {
  final VerifyResponse response;

  const ResultScreen({super.key, required this.response});

  @override
  State<ResultScreen> createState() => _ResultScreenState();
}

class _ResultScreenState extends State<ResultScreen> {
  static const Duration _autoCloseDelay = Duration(milliseconds: 2500);

  Timer? _autoClose;

  @override
  void initState() {
    super.initState();
    if (widget.response.passed) {
      _autoClose = Timer(_autoCloseDelay, _goHome);
    }
  }

  @override
  void dispose() {
    _autoClose?.cancel();
    super.dispose();
  }

  /// 인증 화면까지 걷어내고 홈으로 되돌아간다.
  void _goHome() {
    if (!mounted) return;
    Navigator.of(context).popUntil((route) => route.isFirst);
  }

  /// 결과 화면만 닫아 인증 화면으로 돌아간다. 재시도용.
  void _retry() {
    _autoClose?.cancel();
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    final res = widget.response;
    final passed = res.passed;
    final color = passed ? AppColors.success : AppColors.danger;

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
              const Spacer(flex: 3),
              Icon(
                passed ? Icons.check_circle_outline : Icons.cancel_outlined,
                size: 112,
                color: color,
              ),
              const SizedBox(height: 24),
              Text(
                passed ? '인증되었습니다' : '인증에 실패했습니다',
                textAlign: TextAlign.center,
                style: AppText.screenTitle,
              ),
              const SizedBox(height: 12),
              Text(
                _detailFor(res),
                textAlign: TextAlign.center,
                style: AppText.caption,
              ),
              const SizedBox(height: 20),
              // 개발용 점수 표시. 운영 빌드에서는 빼야 할 정보라서 눈에 띄지 않게
              // 작은 칩으로만 둔다. (SPEC 8.3 — "유사도 점수 표시(개발용)")
              Center(child: _ScoreChip(response: res)),
              const Spacer(flex: 4),
              if (passed) ...[
                PrimaryButton(label: '확인', onPressed: _goHome),
                const SizedBox(height: 12),
                const Text(
                  '잠시 후 자동으로 처음 화면으로 돌아갑니다',
                  textAlign: TextAlign.center,
                  style: AppText.caption,
                ),
              ] else ...[
                PrimaryButton(label: '다시 시도', onPressed: _retry),
                const SizedBox(height: 12),
                SecondaryButton(label: '홈으로', onPressed: _goHome),
              ],
              const SizedBox(height: 24),
            ],
          ),
        ),
      ),
    );
  }

  /// 실패 사유를 사람이 읽을 수 있는 문장으로. 사과하지 않고 다음 행동을 말한다.
  /// (SPEC 5장 카피 원칙)
  static String _detailFor(VerifyResponse res) {
    if (res.passed) return '출입이 허용되었습니다.';
    return switch (res.reason) {
      'insufficient_frames' =>
        '동작이 충분히 기록되지 않았습니다. 손 전체가 원 안에 보이도록 하고 다시 시도해주세요.',
      null => '등록된 수어 암호와 동작이 일치하지 않습니다. 같은 동작을 다시 수행해주세요.',
      final r => '인증이 거부되었습니다. ($r)',
    };
  }
}

/// 유사도와 서버 임계값을 나란히 보여준다.
///
/// threshold는 응답에서 읽은 값을 그대로 표시한다. 앱에 상수로 두지 않는다.
/// (SPEC 6/9장)
class _ScoreChip extends StatelessWidget {
  final VerifyResponse response;

  const _ScoreChip({required this.response});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        StatusChip(
          label: '유사도 ${response.score.toStringAsFixed(3)}',
          color: response.passed ? AppColors.success : AppColors.danger,
          icon: Icons.analytics_outlined,
        ),
        const SizedBox(width: 8),
        StatusChip(
          label: '기준 ${response.threshold.toStringAsFixed(2)}',
          color: AppColors.textSecondary,
        ),
        const SizedBox(width: 8),
        StatusChip(
          label: '${response.latencyMs}ms',
          color: AppColors.textSecondary,
        ),
      ],
    );
  }
}

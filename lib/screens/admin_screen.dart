import 'dart:async';

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../core/theme.dart';
import '../models/auth_log.dart';
import '../state/admin_controller.dart';

/// 관리자 / 인증 이력 조회 화면. (SPEC 8.5)
///
/// 목업 오른쪽 화면. 제목 + 현재 시각 + 이력 표 + 월별 인증 현황 차트.
class AdminScreen extends ConsumerWidget {
  const AdminScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final data = ref.watch(adminProvider);

    return Scaffold(
      backgroundColor: AppColors.bg,
      appBar: AppBar(title: const Text('인증 이력 조회')),
      body: SafeArea(
        child: data.when(
          loading: () => const Center(
            child: CircularProgressIndicator(color: AppColors.ring),
          ),
          error: (e, _) => _ErrorView(
            onRetry: () => ref.read(adminProvider.notifier).refresh(),
          ),
          data: (d) => RefreshIndicator(
            color: AppColors.ring,
            backgroundColor: AppColors.surface,
            onRefresh: () => ref.read(adminProvider.notifier).refresh(),
            child: ListView(
              padding: const EdgeInsets.symmetric(
                horizontal: AppShape.screenPadding,
                vertical: 8,
              ),
              children: [
                const Align(
                  alignment: Alignment.centerRight,
                  child: _CurrentTime(),
                ),
                const SizedBox(height: 16),
                if (d.logs.isEmpty)
                  const _EmptyLogs()
                else
                  _LogTable(logs: d.logs),
                const SizedBox(height: 24),
                _MonthlyChartCard(stats: d.monthly),
                const SizedBox(height: 24),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// 우측 상단 현재 시각. `2026-08-24 10:39:13 KST` 형식. (SPEC 8.5)
class _CurrentTime extends StatefulWidget {
  const _CurrentTime();

  @override
  State<_CurrentTime> createState() => _CurrentTimeState();
}

class _CurrentTimeState extends State<_CurrentTime> {
  late Timer _timer;
  DateTime _now = DateTime.now();

  @override
  void initState() {
    super.initState();
    // 초 단위까지 표시하므로 1초마다 갱신한다.
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() => _now = DateTime.now());
    });
  }

  @override
  void dispose() {
    _timer.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final formatted = DateFormat('yyyy-MM-dd HH:mm:ss').format(_now);
    return Text('$formatted ${_timeZoneLabel(_now)}', style: AppText.caption);
  }

  /// 기기의 타임존 약어를 쓴다. 한국 기기에서는 "KST"가 나온다.
  ///
  /// 약어 대신 긴 이름("대한민국 표준시")을 주는 플랫폼도 있어서, 길면 UTC
  /// 오프셋 표기로 대체한다. 목업의 "KST"를 코드에 박아 두면 다른 지역에서
  /// 시각이 틀리게 보인다.
  static String _timeZoneLabel(DateTime dt) {
    final name = dt.timeZoneName;
    if (name.length <= 5) return name;
    final offset = dt.timeZoneOffset;
    final sign = offset.isNegative ? '-' : '+';
    final abs = offset.abs();
    final hh = abs.inHours.toString().padLeft(2, '0');
    final mm = (abs.inMinutes % 60).toString().padLeft(2, '0');
    return 'UTC$sign$hh:$mm';
  }
}

/// 인증 이력 표. 헤더 배경 surfaceAlt, 행 구분선 divider. (SPEC 5/8.5장)
class _LogTable extends StatelessWidget {
  final List<AuthLog> logs;

  const _LogTable({required this.logs});

  /// 컬럼 폭 비율. 인증시간이 가장 넓어야 하고 결과는 아이콘 하나뿐이라 좁다.
  static const _columnWidths = <int, TableColumnWidth>{
    0: FlexColumnWidth(2.2), // 사용자
    1: FlexColumnWidth(2.2), // 부서
    2: FlexColumnWidth(2.6), // 인증시간
    3: FlexColumnWidth(1.4), // 결과
  };

  @override
  Widget build(BuildContext context) {
    final timeFormat = DateFormat('HH:mm:ss');

    return ClipRRect(
      borderRadius: BorderRadius.circular(AppShape.cardRadius),
      child: Table(
        columnWidths: _columnWidths,
        border: TableBorder.symmetric(
          inside: const BorderSide(
            color: AppColors.divider,
            width: AppShape.dividerWidth,
          ),
        ),
        children: [
          const TableRow(
            decoration: BoxDecoration(color: AppColors.surfaceAlt),
            children: [
              _HeaderCell('사용자'),
              _HeaderCell('부서'),
              _HeaderCell('인증시간'),
              _HeaderCell('결과'),
            ],
          ),
          for (final log in logs)
            TableRow(
              decoration: const BoxDecoration(color: AppColors.surface),
              children: [
                _BodyCell(log.userName),
                _BodyCell(log.department),
                _BodyCell(timeFormat.format(log.timestamp)),
                // 결과는 텍스트 대신 아이콘으로. (SPEC 8.5)
                TableCell(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    child: Icon(
                      log.passed ? Icons.check : Icons.close,
                      size: 18,
                      color: log.passed ? AppColors.success : AppColors.danger,
                    ),
                  ),
                ),
              ],
            ),
        ],
      ),
    );
  }
}

class _HeaderCell extends StatelessWidget {
  final String text;

  const _HeaderCell(this.text);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 8),
      child: Text(
        text,
        textAlign: TextAlign.center,
        style: AppText.tableCell.copyWith(fontWeight: FontWeight.w600),
      ),
    );
  }
}

class _BodyCell extends StatelessWidget {
  final String text;

  const _BodyCell(this.text);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 8),
      child: Text(text, textAlign: TextAlign.center, style: AppText.tableCell),
    );
  }
}

/// 빈 화면은 다음 행동을 안내한다. (SPEC 5장 카피 원칙)
class _EmptyLogs extends StatelessWidget {
  const _EmptyLogs();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 48, horizontal: 24),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppShape.cardRadius),
      ),
      child: const Column(
        children: [
          Text('아직 인증 기록이 없습니다', style: AppText.body),
          SizedBox(height: 8),
          Text(
            '제스처를 등록하고 인증을 한 번 수행하면 여기에 나타납니다.',
            textAlign: TextAlign.center,
            style: AppText.caption,
          ),
        ],
      ),
    );
  }
}

/// 하단 "월별 인증 현황" 꺾은선 차트 카드. (SPEC 8.5)
class _MonthlyChartCard extends StatelessWidget {
  final List<MonthlyStat> stats;

  const _MonthlyChartCard({required this.stats});

  /// Y축 최대값. 목업 기준 0~500. (SPEC 8.5)
  static const double _maxY = 500;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 16, 20, 12),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppShape.cardRadius),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('월별 인증 현황', style: AppText.body),
          const SizedBox(height: 20),
          SizedBox(
            height: 180,
            child: stats.isEmpty
                ? const Center(
                    child: Text('표시할 통계가 없습니다', style: AppText.caption),
                  )
                : LineChart(_chartData()),
          ),
        ],
      ),
    );
  }

  LineChartData _chartData() {
    final spots = [
      for (final s in stats) FlSpot(s.month.toDouble(), s.count.toDouble()),
    ];

    return LineChartData(
      minX: spots.first.x,
      maxX: spots.last.x,
      minY: 0,
      maxY: _maxY,
      gridData: FlGridData(
        show: true,
        drawVerticalLine: false,
        horizontalInterval: _maxY / 4,
        getDrawingHorizontalLine: (_) => const FlLine(
          color: AppColors.divider,
          strokeWidth: 1,
        ),
      ),
      borderData: FlBorderData(show: false),
      titlesData: FlTitlesData(
        topTitles: const AxisTitles(),
        rightTitles: const AxisTitles(),
        leftTitles: AxisTitles(
          sideTitles: SideTitles(
            showTitles: true,
            interval: _maxY / 4,
            reservedSize: 36,
            getTitlesWidget: (value, _) => Text(
              value.toInt().toString(),
              style: AppText.caption.copyWith(fontSize: 11),
            ),
          ),
        ),
        bottomTitles: AxisTitles(
          sideTitles: SideTitles(
            showTitles: true,
            interval: 1,
            reservedSize: 28,
            getTitlesWidget: (value, _) => Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                '${value.toInt()}월',
                style: AppText.caption.copyWith(fontSize: 11),
              ),
            ),
          ),
        ),
      ),
      // 목업에 없는 화려한 요소는 넣지 않는다. 터치 툴팁도 끈다. (SPEC 13장)
      lineTouchData: const LineTouchData(enabled: false),
      lineBarsData: [
        LineChartBarData(
          spots: spots,
          isCurved: true,
          color: AppColors.landmark,
          barWidth: 2.5,
          // 데이터 포인트에 작은 원 표시. (SPEC 8.5)
          dotData: FlDotData(
            show: true,
            getDotPainter: (spot, percent, bar, index) => FlDotCirclePainter(
              radius: 3.5,
              color: AppColors.landmark,
              strokeWidth: 0,
            ),
          ),
          // 선 아래 옅은 그라데이션 영역. (SPEC 8.5)
          belowBarData: BarAreaData(
            show: true,
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [
                AppColors.landmark.withValues(alpha: 0.32),
                AppColors.landmark.withValues(alpha: 0.0),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _ErrorView extends StatelessWidget {
  final VoidCallback onRetry;

  const _ErrorView({required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('인증 이력을 불러오지 못했습니다', style: AppText.body),
            const SizedBox(height: 8),
            const Text(
              '네트워크 상태를 확인하고 다시 시도해주세요.',
              textAlign: TextAlign.center,
              style: AppText.caption,
            ),
            const SizedBox(height: 20),
            TextButton(
              onPressed: onRetry,
              child: const Text(
                '다시 시도',
                style: TextStyle(color: AppColors.primary),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

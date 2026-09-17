/// Challenge 판정 설정. **서버 `GET /config`의 `challenge` 블록**에서 온다.
///
/// 이 파일에 기본값은 없다. 임계값을 앱에 두면 자유 제스처 데이터로 재도출했을 때
/// 앱을 다시 배포해야 한다. 설정을 못 받았으면 Challenge를 시작하지 않는다.
///
/// 원본은 `challenge_response/configs/challenge_config.json`이고 도출 근거(`_source`)가
/// 거기 들어 있다. 서버 쪽 기본값은 `backend/app/default_challenge_config.json`.
library;

/// 손가락이 '펴졌다'고 볼 최소 관절 각도(도).
class FingerExtendedAngle {
  final double thumb;
  final double others;

  const FingerExtendedAngle({required this.thumb, required this.others});

  factory FingerExtendedAngle.fromJson(Map<String, dynamic> json) =>
      FingerExtendedAngle(
        thumb: (json['thumb'] as num).toDouble(),
        others: (json['others'] as num).toDouble(),
      );
}

/// 축과 부호의 짝. `directionMap`의 값이다.
class AxisSign {
  /// 'x' | 'y'.
  final String axis;

  /// +1 | -1.
  final int sign;

  const AxisSign(this.axis, this.sign);

  @override
  bool operator ==(Object other) =>
      other is AxisSign && other.axis == axis && other.sign == sign;

  @override
  int get hashCode => Object.hash(axis, sign);

  @override
  String toString() => '($axis, $sign)';
}

class MovementConfig {
  /// 이동을 판정할 때 훑는 시간 창.
  final double windowMs;

  /// 손 크기 대비 이 값 미만으로 움직이면 이동이 아니다 (제자리 흔들기 거름).
  final double minDisplacementRatio;

  /// 주축 변위 / 부축 변위가 이 값 미만이면 이동이 아니다 (대각선 거름).
  final double axisDominanceRatio;

  final double maxDurationMs;

  /// '정지 상태'로 보는 변위비. 촬영 방식 판별용이고 실시간 판정에는 쓰지 않는다.
  final double restDisplacementRatio;

  /// 방향 라벨 → (축, 부호). 추측이 아니라 영상에서 도출한 값이다.
  final Map<String, AxisSign> directionMap;

  const MovementConfig({
    required this.windowMs,
    required this.minDisplacementRatio,
    required this.axisDominanceRatio,
    required this.maxDurationMs,
    required this.restDisplacementRatio,
    required this.directionMap,
  });

  factory MovementConfig.fromJson(Map<String, dynamic> json) => MovementConfig(
        windowMs: (json['windowMs'] as num).toDouble(),
        minDisplacementRatio: (json['minDisplacementRatio'] as num).toDouble(),
        axisDominanceRatio: (json['axisDominanceRatio'] as num).toDouble(),
        maxDurationMs: (json['maxDurationMs'] as num).toDouble(),
        restDisplacementRatio: (json['restDisplacementRatio'] as num).toDouble(),
        directionMap: <String, AxisSign>{
          for (final MapEntry<String, dynamic> e
              in (json['directionMap'] as Map<String, dynamic>).entries)
            e.key: AxisSign(
              (e.value as List<dynamic>)[0] as String,
              ((e.value as List<dynamic>)[1] as num).toInt(),
            ),
        },
      );

  /// (축, 부호) → 방향 라벨. 판정은 이 방향으로 조회한다.
  Map<AxisSign, String> get byAxisSign => <AxisSign, String>{
        for (final MapEntry<String, AxisSign> e in directionMap.entries)
          e.value: e.key,
      };
}

class TimingConfig {
  /// 한 단계 제한 시간. 이탈 관문이 닫혀 있는 동안은 소모되지 않는다.
  final double perActionTimeoutMs;
  final double totalTimeoutMs;

  /// 단계 실패 시 다시 시도할 횟수. 측정값이 아니라 프로토콜 정책이다.
  final int maxRetries;

  /// 손이 이만큼 연속으로 잡혀야 1단계를 시작한다.
  ///
  /// 그 전에는 [perActionTimeoutMs]도 [totalTimeoutMs]도 흐르지 않고 재시도도
  /// 차감되지 않는다. 화면이 뜨자마자 판정이 시작되면 손을 들기도 전에 시간이
  /// 지나간다. 앱 인증 화면의 `kHandReadyDuration`과 같은 값이다.
  final double waitHandReadyMs;

  /// 손을 아예 들지 않을 때 대기를 끝내는 시간.
  ///
  /// 판정 제한이 아니라 화면이 영원히 멈춰 있지 않게 하는 안전장치다.
  final double waitHandTimeoutMs;

  const TimingConfig({
    required this.perActionTimeoutMs,
    required this.totalTimeoutMs,
    required this.maxRetries,
    required this.waitHandReadyMs,
    required this.waitHandTimeoutMs,
  });

  factory TimingConfig.fromJson(Map<String, dynamic> json) => TimingConfig(
        perActionTimeoutMs: (json['perActionTimeoutMs'] as num).toDouble(),
        totalTimeoutMs: (json['totalTimeoutMs'] as num).toDouble(),
        maxRetries: (json['maxRetries'] as num).toInt(),
        // 설정에 없으면 대기 없음(옛 동작). 서버는 항상 값을 준다.
        waitHandReadyMs: (json['waitHandReadyMs'] as num?)?.toDouble() ?? 0.0,
        waitHandTimeoutMs:
            (json['waitHandTimeoutMs'] as num?)?.toDouble() ?? 15000.0,
      );
}

class TrackingConfig {
  /// 손을 이만큼(프레임) 넘게 놓치면 실패. 기준 fps 기준 시간으로 환산해 쓴다.
  final int maxLostFrames;

  /// 검출 신뢰도 하한.
  ///
  /// ⚠️ 앱에서는 사실상 꺼져 있다. `hand_landmarker` 3.0.1이 신뢰도를 주지 않아
  /// [HandFrame.score]가 항상 null이고, 판정은 값이 있을 때만 이 관문을 본다.
  final double minDetectionScore;

  /// 최근 프레임 간격의 중앙값에 이 배수를 곱한 값이 '손 없음' 판단 기준이 된다.
  ///
  /// 고정 상수(100ms)를 쓰다가 실기기에서 터졌다. 14fps면 간격이 71ms라 여유가
  /// 29ms뿐이고, 한 프레임만 늦어도(110~170ms 관측) 이동 윈도우가 비워져
  /// 550ms를 채울 기회가 없었다. 측정값이 아니라 정책값이다.
  final double frameStaleFactor;
  final int frameStaleMinMs;
  final int frameStaleMaxMs;

  const TrackingConfig({
    required this.maxLostFrames,
    required this.minDetectionScore,
    required this.frameStaleFactor,
    required this.frameStaleMinMs,
    required this.frameStaleMaxMs,
  });

  factory TrackingConfig.fromJson(Map<String, dynamic> json) => TrackingConfig(
        maxLostFrames: (json['maxLostFrames'] as num).toInt(),
        minDetectionScore: (json['minDetectionScore'] as num).toDouble(),
        frameStaleFactor:
            (json['frameStaleFactor'] as num?)?.toDouble() ?? 3.0,
        frameStaleMinMs: (json['frameStaleMinMs'] as num?)?.toInt() ?? 150,
        frameStaleMaxMs: (json['frameStaleMaxMs'] as num?)?.toInt() ?? 800,
      );

  /// 프레임 간격 중앙값 [medianGapMs]에서 '손 없음' 판단 기준을 유도한다.
  ///
  /// 아직 표본이 없으면([medianGapMs]가 0 이하) 하한을 쓴다.
  Duration staleThreshold(double medianGapMs) {
    final double derived =
        medianGapMs > 0 ? medianGapMs * frameStaleFactor : frameStaleMinMs.toDouble();
    final double clamped =
        derived.clamp(frameStaleMinMs.toDouble(), frameStaleMaxMs.toDouble());
    return Duration(milliseconds: clamped.round());
  }
}

/// 단계 구성. 기본은 손 모양 2 + 이동 1의 3단계다.
class StepsConfig {
  final int numShapes;
  final int numMoves;

  const StepsConfig({required this.numShapes, required this.numMoves});

  int get total => numShapes + numMoves;

  factory StepsConfig.fromJson(Map<String, dynamic> json) => StepsConfig(
        numShapes: (json['numShapes'] as num).toInt(),
        numMoves: (json['numMoves'] as num).toInt(),
      );
}

class ChallengeConfig {
  /// 판정 규칙 버전. 결과를 집계할 때 규칙 변경 전후를 가른다.
  final String ruleVersion;

  /// 'image_iso' | 'world'. image_iso는 종횡비 보정을 거친 화면 좌표다.
  final String angleSpace;

  /// 'mirrored' | 'raw'. mirrored면 방향 **라벨**의 좌우를 뒤집는다.
  /// 좌표를 뒤집는 것이 아니다 (README 좌표계 규칙).
  final String coordinateFrame;

  /// 프레임 수로 적힌 값들(shapeHoldFrames 등)을 잰 영상의 fps.
  /// 실기기는 13~16fps라 프레임 수를 그대로 쓰면 안 되고 시간으로 환산한다.
  final double frameReferenceFps;

  final FingerExtendedAngle fingerExtendedAngle;

  /// FIST 패턴이어도 손끝이 손목에서 이 비율 이상 떨어져 있으면 반쯤 쥔 손으로 본다.
  /// **null이면 이 게이트를 끈다** (도출 실패 시 임의 값을 넣지 않는다).
  final double? fistMaxTipWristRatio;

  final int shapeHoldFrames;

  /// 신뢰도 1.0에 해당하는 각도 여유.
  final double shapeConfidenceMarginDeg;

  /// **null이면 신뢰도 게이트를 끈다.** 분포가 겹쳐 도출하지 못한 값이다.
  final double? shapeConfidenceMin;

  /// 이전 단계의 손 모양에서 벗어나야 하는 연속 길이(프레임). 0이면 관문을 끈다.
  final int escapeFrames;

  final MovementConfig movement;
  final TimingConfig timing;
  final TrackingConfig tracking;
  final StepsConfig steps;
  final List<String> shapePool;
  final List<String> movePool;

  const ChallengeConfig({
    required this.ruleVersion,
    required this.angleSpace,
    required this.coordinateFrame,
    required this.frameReferenceFps,
    required this.fingerExtendedAngle,
    required this.fistMaxTipWristRatio,
    required this.shapeHoldFrames,
    required this.shapeConfidenceMarginDeg,
    required this.shapeConfidenceMin,
    required this.escapeFrames,
    required this.movement,
    required this.timing,
    required this.tracking,
    required this.steps,
    required this.shapePool,
    required this.movePool,
  });

  factory ChallengeConfig.fromJson(Map<String, dynamic> json) => ChallengeConfig(
        ruleVersion: json['ruleVersion'] as String? ?? '',
        angleSpace: json['angleSpace'] as String,
        coordinateFrame: json['coordinateFrame'] as String,
        frameReferenceFps: (json['frameReferenceFps'] as num).toDouble(),
        fingerExtendedAngle: FingerExtendedAngle.fromJson(
          json['fingerExtendedAngle'] as Map<String, dynamic>,
        ),
        fistMaxTipWristRatio: (json['fistMaxTipWristRatio'] as num?)?.toDouble(),
        shapeHoldFrames: (json['shapeHoldFrames'] as num).toInt(),
        shapeConfidenceMarginDeg:
            (json['shapeConfidenceMarginDeg'] as num).toDouble(),
        shapeConfidenceMin: (json['shapeConfidenceMin'] as num?)?.toDouble(),
        escapeFrames: (json['escapeFrames'] as num).toInt(),
        movement:
            MovementConfig.fromJson(json['movement'] as Map<String, dynamic>),
        timing: TimingConfig.fromJson(json['timing'] as Map<String, dynamic>),
        tracking:
            TrackingConfig.fromJson(json['tracking'] as Map<String, dynamic>),
        steps: StepsConfig.fromJson(json['steps'] as Map<String, dynamic>),
        shapePool: (json['shapePool'] as List<dynamic>).cast<String>(),
        movePool: (json['movePool'] as List<dynamic>).cast<String>(),
      );

  /// 기준 fps에서 한 프레임이 차지하는 시간.
  double get frameMs => 1000.0 / frameReferenceFps;

  /// "N프레임 연속"을 시간으로. 타임스탬프 흔들림에 대비해 반 프레임 여유를 둔다.
  ///
  /// 기준 fps로 들어오면 프레임 수로 센 것과 결과가 같고, 실기기처럼 fps가
  /// 낮아도 **도출 때와 같은 시간**을 요구하게 된다.
  double consecutiveMs(int frames) =>
      (frames - 1.5).clamp(0.0, double.infinity) * frameMs;

  /// 신뢰도 게이트가 켜져 있는지. null이면 조건을 걸지 않는다.
  bool get hasConfidenceGate => shapeConfidenceMin != null;
}

/// Challenge 순서·시간 관리 상태 머신.
/// `challenge_response/core/challenge_state_machine.py`의 이식이다.
///
///     IDLE -> WAIT_HAND -> ACTION(1) -> ACTION(2) -> ACTION(3) -> PASS
///                              |            |            |
///                              +------------+------------+--> FAIL(사유)
///
/// UI 프레임워크에 의존하지 않는 순수 Dart다. 화면은 [Status]만 읽는다.
///
/// **프레임 수가 아니라 시간으로 잰다.** 설정의 프레임 값들은 30fps 파일럿 영상에서
/// 센 것이고 실기기는 13~16fps다. 프레임 수로 세면 같은 조건이 두 배 넘게 길어진다.
library;

import 'challenge_config.dart';
import 'challenge_generator.dart';
import 'geometry.dart';
import 'hand_action_detector.dart';
import 'movement_detector.dart';

enum ChallengeState { idle, waitHand, action, passed, failed }

enum FailReason {
  handNotFound,
  wrongShape,
  wrongDirection,
  wrongOrder,
  actionTimeout,
  totalTimeout,
  handLost,
  trackingUnstable,
}

/// 결과 집계용 문자열. Python `FailReason` 값과 같아야 비교할 수 있다.
extension FailReasonCode on FailReason {
  String get code => switch (this) {
        FailReason.handNotFound => 'HAND_NOT_FOUND',
        FailReason.wrongShape => 'WRONG_SHAPE',
        FailReason.wrongDirection => 'WRONG_DIRECTION',
        FailReason.wrongOrder => 'WRONG_ORDER',
        FailReason.actionTimeout => 'ACTION_TIMEOUT',
        FailReason.totalTimeout => 'TOTAL_TIMEOUT',
        FailReason.handLost => 'HAND_LOST',
        FailReason.trackingUnstable => 'TRACKING_UNSTABLE',
      };
}

/// 재시도로 회복할 수 있는 사유. 손이 사라지거나 순서를 어긴 건 대상이 아니다.
const Set<FailReason> kRetryableReasons = <FailReason>{
  FailReason.wrongShape,
  FailReason.wrongDirection,
  FailReason.actionTimeout,
};

/// "N프레임 연속"을 프레임 수가 아니라 관측 시각으로 잰다.
///
/// 설정의 프레임 수는 [ChallengeConfig.frameReferenceFps] 영상에서 센 값이다.
/// 실시간 fps가 다르면 같은 프레임 수가 다른 시간이 된다(20fps에서 7프레임은
/// 233ms가 아니라 350ms). 도출과 같은 기준이 되도록 기준 fps에서의 시간으로 본다.
class FrameSpan {
  final int frames;
  final double requiredMs;

  double? _startMs;
  double? _lastMs;

  FrameSpan(this.frames, ChallengeConfig config)
      : requiredMs = config.consecutiveMs(frames);

  /// 조건을 만족한 프레임 하나. 연속 구간이 요구 길이에 닿았으면 true.
  bool hit(double timestampMs) {
    _startMs ??= timestampMs;
    _lastMs = timestampMs;
    return done;
  }

  void reset() {
    _startMs = null;
    _lastMs = null;
  }

  bool get active => _startMs != null;

  double get elapsedMs => _startMs == null ? 0.0 : _lastMs! - _startMs!;

  bool get done => frames > 0 && active && elapsedMs >= requiredMs;

  double get progress {
    if (!active) return 0.0;
    if (requiredMs <= 0) return 1.0;
    final double p = elapsedMs / requiredMs;
    return p > 1.0 ? 1.0 : p;
  }
}

/// 이동 판정 윈도우. 기준 fps에서 windowFrames가 차지하는 시간만큼 담는다.
class TimeWindow {
  final int windowFrames;

  /// 이보다 오래된 프레임은 버린다.
  final double keepMs;

  /// 이만큼 차면 판정한다.
  final double requiredMs;

  final List<double> _t = <double>[];
  final List<List<double>> centers = <List<double>>[];
  final List<double> scales = <double>[];

  TimeWindow(this.windowFrames, ChallengeConfig config)
      : keepMs = (windowFrames - 0.5) * config.frameMs,
        requiredMs = (windowFrames - 1.5) * config.frameMs;

  void add(double timestampMs, List<double> center, double scale) {
    _t.add(timestampMs);
    centers.add(center);
    scales.add(scale);
    while (_t.isNotEmpty && timestampMs - _t.first > keepMs) {
      _t.removeAt(0);
      centers.removeAt(0);
      scales.removeAt(0);
    }
  }

  void clear() {
    _t.clear();
    centers.clear();
    scales.clear();
  }

  double get spanMs => _t.length >= 2 ? _t.last - _t.first : 0.0;

  bool get ready => _t.length >= 2 && spanMs >= requiredMs;

  int get length => _t.length;
}

/// 프레임 1개의 관측값. 좌표계 변환은 호출자가 끝내서 넘긴다.
class Observation {
  final double timestampMs;
  final bool handFound;

  /// 검출 신뢰도. **앱에서는 거의 항상 null이다** (플러그인이 주지 않는다).
  /// null이면 추적 안정성 관문을 건너뛴다.
  final double? detectionScore;

  /// 설정의 angleSpace 좌표.
  final Coords? angleCoords;

  /// 종횡비 보정이 끝난 화면 좌표.
  final Coords? screenCoords;

  const Observation({
    required this.timestampMs,
    required this.handFound,
    this.detectionScore,
    this.angleCoords,
    this.screenCoords,
  });
}

/// 이동 판정 한 번의 중간값. 어느 관문에서 막혔는지 화면에 보여주려고 남긴다.
class MoveProbe {
  final int framesFilled;
  final int framesNeeded;
  final double displacementRatio;
  final double axisRatio;
  final String axis;
  final int sign;
  final String label;
  final String reason;
  final double spanMs;
  final double spanNeededMs;
  final bool windowReady;

  const MoveProbe({
    this.framesFilled = 0,
    this.framesNeeded = 0,
    this.displacementRatio = double.nan,
    this.axisRatio = double.nan,
    this.axis = 'none',
    this.sign = 0,
    this.label = kNoMove,
    this.reason = 'NO_DATA',
    this.spanMs = 0.0,
    this.spanNeededMs = 0.0,
    this.windowReady = false,
  });

  /// 1번 관문(변위 크기)을 통과했는지.
  bool get displacementOk => const <String>{
        MoveReason.notAxisDominant,
        MoveReason.unmappedAxis,
        MoveReason.ok,
      }.contains(reason);

  /// 2번 관문(주축 지배력)을 통과했는지.
  bool get axisOk =>
      reason == MoveReason.unmappedAxis || reason == MoveReason.ok;
}

/// 한 단계의 결과.
class StepResult {
  final String action;
  bool passed = false;
  FailReason? failReason;
  double elapsedMs = 0.0;
  int retriesUsed = 0;

  StepResult(this.action);
}

/// [ChallengeStateMachine.update]가 돌려주는 상태 스냅샷.
class Status {
  final ChallengeState state;
  final int stepIndex;
  final String? currentAction;
  final String detectedShape;
  final String detectedMove;
  final double shapeConfidence;

  /// 손 모양 유지 진행도 0.0~1.0.
  final double holdProgress;

  final double remainingMs;
  final FailReason? failReason;
  final List<StepResult> steps;

  /// 이동 단계에서만 채워진다.
  final MoveProbe? moveProbe;

  /// 벗어나야 하는 이전 손 모양. null이면 관문이 열려 있다.
  final String? escapeFrom;

  /// 0.0~1.0, 1.0이면 관문이 열렸다.
  final double escapeProgress;

  const Status({
    required this.state,
    required this.stepIndex,
    required this.currentAction,
    required this.detectedShape,
    required this.detectedMove,
    required this.shapeConfidence,
    required this.holdProgress,
    required this.remainingMs,
    required this.failReason,
    required this.steps,
    required this.moveProbe,
    required this.escapeFrom,
    required this.escapeProgress,
  });

  /// 이탈 관문이 닫혀 있어 대기 중인지. 이 동안 제한 시간은 흐르지 않는다.
  bool get awaitingEscape => escapeFrom != null && escapeProgress < 1.0;

  bool get finished =>
      state == ChallengeState.passed || state == ChallengeState.failed;

  int get totalSteps => steps.length;
}

class ChallengeStateMachine {
  final ChallengeConfig config;
  final Challenge challenge;
  final HandActionDetector shapeDetector;
  final MovementDetector movementDetector;

  ChallengeState state = ChallengeState.idle;
  int stepIndex = 0;
  FailReason? failReason;
  final List<StepResult> steps;

  final double _perActionTimeoutMs;
  final double _totalTimeoutMs;
  final int _maxRetries;
  final double _minDetectionScore;

  /// null이면 신뢰도 게이트를 끈다.
  final double? _shapeConfidenceMin;

  final TimeWindow _window;
  final FrameSpan _hold;
  final FrameSpan _wrong;
  final FrameSpan _escape;
  final FrameSpan _lost;
  final FrameSpan _unstable;

  double? _startedMs;
  double? _stepStartedMs;
  double _nowMs = 0.0;
  double _frameDeltaMs = 0.0;

  String? _wrongLabel;

  /// 제한 시간 동안 사용자가 '확실히' 수행한 다른 동작. 타임아웃 때 사유를 정한다.
  String? _sustainedWrong;

  /// 마지막으로 검출된 손 모양.
  String? _lastShape;

  /// 벗어나야 하는 모양.
  String? _escapeFrom;

  int _retriesLeft;

  ChallengeStateMachine({
    required this.config,
    required this.challenge,
    required double fps,
  })  : shapeDetector = HandActionDetector(config),
        movementDetector = MovementDetector(config),
        steps = <StepResult>[
          for (final String a in challenge.actions) StepResult(a),
        ],
        _perActionTimeoutMs = config.timing.perActionTimeoutMs,
        _totalTimeoutMs = config.timing.totalTimeoutMs,
        _maxRetries = config.timing.maxRetries,
        _minDetectionScore = config.tracking.minDetectionScore,
        _shapeConfidenceMin = config.shapeConfidenceMin,
        _retriesLeft = config.timing.maxRetries,
        _window = TimeWindow(
          MovementDetector(config).windowFrames(config.frameReferenceFps),
          config,
        ),
        _hold = FrameSpan(config.shapeHoldFrames, config),
        _wrong = FrameSpan(config.shapeHoldFrames, config),
        _escape = FrameSpan(config.escapeFrames, config),
        // 기존 규칙은 '연속 N프레임 초과'에서 실패였다 = N+1프레임 연속
        _lost = FrameSpan(config.tracking.maxLostFrames + 1, config),
        _unstable = FrameSpan(config.tracking.maxLostFrames + 1, config);

  String? get currentAction =>
      stepIndex < challenge.actions.length ? challenge.actions[stepIndex] : null;

  void start(double timestampMs) {
    state = ChallengeState.waitHand;
    _startedMs = timestampMs;
    _stepStartedMs = timestampMs;
    _nowMs = timestampMs;
  }

  Status update(Observation obs) {
    if (state == ChallengeState.passed || state == ChallengeState.failed) {
      return _status();
    }
    if (state == ChallengeState.idle) {
      start(obs.timestampMs);
    }
    // 이탈 관문이 닫혀 있는 동안 시계를 멈추려면 프레임 간격이 필요하다.
    final double delta = obs.timestampMs - _nowMs;
    _frameDeltaMs = delta > 0.0 ? delta : 0.0;
    _nowMs = obs.timestampMs;

    if (obs.timestampMs - _startedMs! > _totalTimeoutMs) {
      return _fail(FailReason.totalTimeout, obs.timestampMs);
    }

    final Status? tracking = _updateTracking(obs);
    if (tracking != null) return tracking;

    if (state == ChallengeState.waitHand) {
      state = ChallengeState.action;
      _stepStartedMs = obs.timestampMs;
      _hold.reset();
    }

    final String? action = currentAction;
    if (action == null) return _status();

    final Status status = challenge.isShapeAction(action)
        ? _updateShape(obs, action)
        : _updateMove(obs, action);

    if (!status.finished && state == ChallengeState.action) {
      final double elapsed = obs.timestampMs - _stepStartedMs!;
      if (elapsed > _perActionTimeoutMs) {
        return _failStep(_timeoutReason(action), obs.timestampMs);
      }
    }
    return status;
  }

  // ------------------------------------------------------------ 내부

  /// 손 소실/추적 불안정 처리. 실패면 Status, 아니면 null.
  Status? _updateTracking(Observation obs) {
    if (!obs.handFound) {
      _hold.reset();
      _window.clear();
      if (_lost.hit(obs.timestampMs)) {
        return _fail(
          state == ChallengeState.waitHand
              ? FailReason.handNotFound
              : FailReason.handLost,
          obs.timestampMs,
        );
      }
      return _status();
    }

    _lost.reset();
    final double? score = obs.detectionScore;
    // 앱의 hand_landmarker는 신뢰도를 주지 않는다. null이면 이 관문을 건너뛴다.
    if (score != null && score.isFinite && score < _minDetectionScore) {
      _hold.reset();
      if (_unstable.hit(obs.timestampMs)) {
        return _fail(FailReason.trackingUnstable, obs.timestampMs);
      }
      return _status();
    }

    _unstable.reset();
    return null;
  }

  Status _updateShape(Observation obs, String action) {
    final ShapeResult result = shapeDetector.detect(obs.angleCoords!);
    final bool confident =
        _shapeConfidenceMin == null || result.confidence >= _shapeConfidenceMin;
    _lastShape = result.label;

    // --- 이전 손 모양 이탈 관문 ---
    // 이동은 손바닥을 편 채로 하므로, 이동 다음 단계가 OPEN_PALM이면 손이 이미 그
    // 모양이라 아무것도 안 해도 통과된다. 요청에 반응했는지를 확인하지 못하게
    // 되므로 보안 문제다. 이전 모양에서 실제로 벗어난 뒤에 판정한다.
    if (_escapePending) {
      if (result.label != _escapeFrom) {
        _escape.hit(obs.timestampMs);
      } else {
        _escape.reset();
      }
      // 관문이 닫혀 있는 동안은 제한 시간을 소모하지 않는다. 단계 제한과 전체
      // 제한을 같이 미뤄야 한다. 전체 제한만 흐르게 두면 마지막 단계에 관문이
      // 걸릴 때 TOTAL_TIMEOUT으로 죽는다.
      _stepStartedMs = obs.timestampMs;
      if (_startedMs != null) _startedMs = _startedMs! + _frameDeltaMs;
      if (_escapePending) {
        return _status(
          detectedShape: result.label,
          confidence: result.confidence,
        );
      }
      _escapeFrom = null;
    }

    if (result.label == action && confident) {
      _wrongLabel = null;
      _wrong.reset();
      if (_hold.hit(obs.timestampMs)) {
        return _advance(obs.timestampMs);
      }
      return _status(detectedShape: result.label, confidence: result.confidence);
    }

    _hold.reset();
    if (!confident || result.label == kUnknownShape) {
      _wrongLabel = null;
      _wrong.reset();
      return _status(detectedShape: result.label, confidence: result.confidence);
    }

    // 틀린 모양도 유지 조건을 채워야 실패로 본다. 한 프레임 오검출로 세션을
    // 끝내면, 측정상 최대 8프레임까지 나오는 순간 오검출에 정상 시도가 죽는다.
    if (result.label != _wrongLabel) {
      _wrongLabel = result.label;
      _wrong.reset();
    }
    if (!_wrong.hit(obs.timestampMs)) {
      return _status(detectedShape: result.label, confidence: result.confidence);
    }

    // 여기서 바로 실패시키면 사용자가 화면의 요청을 읽고 손 모양을 바꿀 시간이
    // 없다. 손을 든 순간의 모양이 요청과 다르다는 이유로 0.3초 만에 끝나버린다.
    // 무엇을 하고 있었는지만 기록하고 제한 시간까지 기다린다.
    _sustainedWrong = result.label;
    return _status(detectedShape: result.label, confidence: result.confidence);
  }

  Status _updateMove(Observation obs, String action) {
    // 이동 중의 손 모양을 계속 기억해 둔다. 이동이 끝난 시점의 이 값이
    // 다음 단계의 escapeFrom이 된다.
    if (obs.angleCoords != null) {
      _lastShape = shapeDetector.detect(obs.angleCoords!).label;
    }

    final Coords coords = obs.screenCoords!;
    _window.add(obs.timestampMs, palmCenter(coords), handScale(coords));

    if (!_window.ready) {
      return _status(
        moveProbe: MoveProbe(
          framesFilled: _window.length,
          framesNeeded: _window.windowFrames,
          spanMs: _window.spanMs,
          spanNeededMs: _window.requiredMs,
          windowReady: false,
        ),
      );
    }

    final MoveResult result =
        movementDetector.detectFromTracks(_window.centers, _window.scales);
    final MoveProbe probe = MoveProbe(
      framesFilled: _window.length,
      framesNeeded: _window.windowFrames,
      spanMs: _window.spanMs,
      spanNeededMs: _window.requiredMs,
      windowReady: true,
      displacementRatio: result.displacementRatio,
      axisRatio: result.axisRatio,
      axis: result.axis,
      sign: result.sign,
      label: result.label,
      reason: result.reason,
    );

    if (result.label == action) {
      return _advance(obs.timestampMs);
    }
    if (result.label == kOppositeDirection[action]) {
      // 요청과 같은 축의 반대 방향이 먼저 확정되면 즉시 실패시킨다(재시도는 허용).
      // 그대로 두면 이동 한 번의 '되돌아오는 획'이 반대 방향 요청을 통과시킨다
      // (정상 이동 영상에 반대 방향 요청 시 80% 통과 → 이 규칙으로 30%).
      // 요청 방향이 먼저 잡히면 그 순간 통과하므로 그 뒤의 획은 상관없다.
      return _failStep(FailReason.wrongDirection, obs.timestampMs);
    }
    if (result.label != kNoMove) {
      // 수직 방향은 즉시 실패시키지 않고 제한 시간까지 기다린다. 사유만 기억한다.
      _sustainedWrong = result.label;
    }
    return _status(detectedMove: result.label, moveProbe: probe);
  }

  /// 제한 시간이 지났을 때, 그동안 한 동작으로 실패 사유를 정한다.
  FailReason _timeoutReason(String action) {
    final String? wrong = _sustainedWrong;
    if (wrong == null) return FailReason.actionTimeout;
    if (challenge.actions.sublist(stepIndex + 1).contains(wrong)) {
      return FailReason.wrongOrder;
    }
    return challenge.isShapeAction(action)
        ? FailReason.wrongShape
        : FailReason.wrongDirection;
  }

  bool get _escapePending => _escapeFrom != null && !_escape.done;

  double get _escapeProgress => _escapePending ? _escape.progress : 1.0;

  /// 다음 단계가 손 모양이면, 방금 끝난 시점의 손 모양에서 벗어나게 한다.
  ///
  /// 이동 단계에는 걸지 않는다. 이동은 단계 전환 때 윈도우를 비우므로 정지한
  /// 손으로는 변위가 나오지 않는다.
  void _armEscapeGate() {
    final String? action = currentAction;
    _escape.reset();
    if (config.escapeFrames > 0 &&
        action != null &&
        challenge.isShapeAction(action) &&
        _lastShape != null) {
      _escapeFrom = _lastShape;
    } else {
      _escapeFrom = null;
    }
  }

  Status _advance(double timestampMs) {
    final StepResult step = steps[stepIndex];
    step.passed = true;
    step.elapsedMs = timestampMs - _stepStartedMs!;
    stepIndex += 1;
    _hold.reset();
    _wrongLabel = null;
    _wrong.reset();
    _sustainedWrong = null;
    _window.clear();
    _retriesLeft = _maxRetries;
    if (stepIndex >= challenge.actions.length) {
      state = ChallengeState.passed;
    } else {
      _stepStartedMs = timestampMs;
      _armEscapeGate();
    }
    return _status();
  }

  /// 재시도가 남아 있으면 현재 단계를 다시 시작한다.
  Status _failStep(FailReason reason, double timestampMs) {
    if (kRetryableReasons.contains(reason) && _retriesLeft > 0) {
      _retriesLeft -= 1;
      steps[stepIndex].retriesUsed += 1;
      _stepStartedMs = timestampMs;
      _hold.reset();
      _wrongLabel = null;
      _wrong.reset();
      _sustainedWrong = null;
      _window.clear();
      return _status();
    }
    return _fail(reason, timestampMs);
  }

  Status _fail(FailReason reason, double timestampMs) {
    state = ChallengeState.failed;
    failReason = reason;
    if (stepIndex < steps.length) {
      final StepResult step = steps[stepIndex];
      step.passed = false;
      step.failReason = reason;
      if (_stepStartedMs != null) {
        step.elapsedMs = timestampMs - _stepStartedMs!;
      }
    }
    return _status();
  }

  Status _status({
    String detectedShape = kUnknownShape,
    double confidence = 0.0,
    String detectedMove = kNoMove,
    MoveProbe? moveProbe,
  }) {
    double remaining = 0.0;
    if (_stepStartedMs != null && state == ChallengeState.action) {
      remaining = _perActionTimeoutMs - (_nowMs - _stepStartedMs!);
      if (remaining < 0.0) remaining = 0.0;
    }
    return Status(
      state: state,
      stepIndex: stepIndex,
      currentAction: currentAction,
      detectedShape: detectedShape,
      detectedMove: detectedMove,
      shapeConfidence: confidence,
      holdProgress: _hold.progress,
      remainingMs: remaining,
      failReason: failReason,
      steps: List<StepResult>.of(steps),
      moveProbe: moveProbe,
      escapeFrom: _escapePending ? _escapeFrom : null,
      escapeProgress: _escapeProgress,
    );
  }
}

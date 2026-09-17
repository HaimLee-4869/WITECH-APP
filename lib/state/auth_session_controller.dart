/// 한 번의 촬영으로 Challenge와 제스처 인증을 끊김 없이 수행한다.
///
/// ```
/// 카메라 켜짐 ─ Challenge 1 ─ 2 ─ 3 ─ 그대로 이어서 제스처 4초 ─ 전송
///               (손 추적이 한 번도 끊기지 않아야 한다)
/// ```
///
/// **왜 하나로 묶는가.** 촬영을 둘로 나누면 "Challenge는 본인 손으로 통과하고
/// 인증만 피해자 영상으로 재생"하는 공격을 막지 못한다. Challenge는 *살아 있는
/// 손이 있다*는 것만 증명하지, 그 손이 인증한 손과 같다는 것은 증명하지 못한다.
///
/// 그래서 이 컨트롤러가 **소스를 세션 내내 한 번만 잡고 놓지 않는다.** 화면
/// 전환마다 stop/start 하던 구조에서는 그 사이가 비었고, 구독이 누수되어 프레임이
/// 두 배로 수집되는 버그도 거기서 났다.
///
/// 판정을 멈추는 구간(결과 표시·다음 단계 준비)에도 **추적은 유지한다.**
/// 손이 사라지면 `SESSION_BROKEN`으로 전체를 실패시킨다.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../challenge/challenge_config.dart';
import '../challenge/challenge_debug_format.dart';
import '../challenge/challenge_generator.dart';
import '../challenge/challenge_state_machine.dart';
import '../challenge/continuity_monitor.dart';
import '../challenge/geometry.dart';
import '../core/config.dart';
import '../core/screen_rotation.dart';
import '../models/api_error.dart';
import '../models/camera_info.dart';
import '../models/challenge_messages.dart';
import '../models/landmark.dart';
import '../models/verify.dart';
import '../screens/challenge_screen.dart' show kSendChallengeLog;
import '../services/api_client.dart';
import '../services/challenge_debug_sink.dart';
import '../services/landmark_source.dart';
import 'providers.dart';

/// 세션이 지금 어느 구간인지.
enum SessionPhase {
  /// 아직 시작하지 않음.
  idle,

  /// 손을 기다리고 Challenge를 수행하는 중.
  challenge,

  /// Challenge를 통과하고 **그대로 이어서** 제스처를 수집하는 중.
  recording,

  /// 서버 왕복 중.
  uploading,

  /// 인증 응답을 받았다. 결과 화면으로 넘어간다.
  done,

  /// 세션이 끊겼거나 Challenge에 실패했다.
  failed,

  /// 설정을 못 받았거나 카메라를 못 켰다.
  unavailable,
}

@immutable
class AuthSessionState {
  final SessionPhase phase;

  /// Challenge 상태 머신의 마지막 스냅샷.
  final Status? status;

  final Challenge? challenge;

  /// 제스처 수집 진행도 0.0~1.0.
  final double recordProgress;

  /// 인증 응답. [SessionPhase.done]에서만 채워진다.
  final VerifyResponse? response;

  /// 사용자에게 보여줄 문제 설명.
  final String? notice;

  /// 남은 재시도 횟수(세션 전체).
  final int retriesLeft;

  final HandFrame? latestFrame;
  final String debugShape;
  final double observedFps;
  final int lostInjections;
  final int lastFrameGapMs;

  const AuthSessionState({
    this.phase = SessionPhase.idle,
    this.status,
    this.challenge,
    this.recordProgress = 0.0,
    this.response,
    this.notice,
    this.retriesLeft = 0,
    this.latestFrame,
    this.debugShape = '',
    this.observedFps = 0.0,
    this.lostInjections = 0,
    this.lastFrameGapMs = 0,
  });

  AuthSessionState copyWith({
    SessionPhase? phase,
    Status? status,
    Challenge? challenge,
    double? recordProgress,
    VerifyResponse? response,
    String? notice,
    bool clearNotice = false,
    int? retriesLeft,
    HandFrame? latestFrame,
    String? debugShape,
    double? observedFps,
    int? lostInjections,
    int? lastFrameGapMs,
  }) {
    return AuthSessionState(
      phase: phase ?? this.phase,
      status: status ?? this.status,
      challenge: challenge ?? this.challenge,
      recordProgress: recordProgress ?? this.recordProgress,
      response: response ?? this.response,
      notice: clearNotice ? null : (notice ?? this.notice),
      retriesLeft: retriesLeft ?? this.retriesLeft,
      latestFrame: latestFrame ?? this.latestFrame,
      debugShape: debugShape ?? this.debugShape,
      observedFps: observedFps ?? this.observedFps,
      lostInjections: lostInjections ?? this.lostInjections,
      lastFrameGapMs: lastFrameGapMs ?? this.lastFrameGapMs,
    );
  }

  List<String> get actions => challenge?.actions ?? const <String>[];

  int get stepIndex => status?.stepIndex ?? 0;

  bool get finished =>
      phase == SessionPhase.done ||
      phase == SessionPhase.failed ||
      phase == SessionPhase.unavailable;

  /// 손을 화면 안에 유지해야 하는 구간인지.
  ///
  /// 이 동안 손이 사라지면 세션 전체가 실패한다. 화면이 안내를 계속 띄운다.
  bool get mustKeepHand =>
      phase == SessionPhase.recording ||
      (phase == SessionPhase.challenge &&
          !(status?.awaitingHand ?? true));
}

/// 세션 전체에서 허용할 재시도 횟수.
const int kSessionRetries = 1;

final authSessionProvider =
    NotifierProvider<AuthSessionController, AuthSessionState>(
  AuthSessionController.new,
);

class AuthSessionController extends Notifier<AuthSessionState> {
  /// 손이 없는 프레임을 만들어 넣는 주기.
  static const Duration _watchdogPeriod = Duration(milliseconds: 33);

  /// 최근 프레임 간격을 이만큼 모아 중앙값을 낸다.
  static const int _gapWindow = 15;

  late LandmarkSource _source;
  late ApiClient _api;
  ChallengeConfig? _config;
  String _userId = '';
  String _gestureId = kDefaultGestureId;
  Duration _recordDuration = kRecordDuration;

  ChallengeStateMachine? _machine;
  ContinuityMonitor? _continuity;
  StreamSubscription<HandFrame>? _sub;
  Timer? _watchdog;
  Timer? _recordTimer;

  final Stopwatch _clock = Stopwatch();
  final Stopwatch _sinceLastFrame = Stopwatch();
  final Stopwatch _recordClock = Stopwatch();
  final List<HandFrame> _buffer = <HandFrame>[];

  /// 버퍼에 마지막으로 넣은 tMs. 서버는 엄격히 증가해야 받는다.
  int _lastBufferedTMs = -1;

  final List<int> _gaps = <int>[];
  double _observedFps = 0.0;
  int _frameCount = 0;
  int _lostInjections = 0;
  int _lastFrameGapMs = 0;
  HandFrame? _latestFrame;

  ChallengeDebugSink? _sink;
  int _loggedStep = 0;

  @override
  AuthSessionState build() {
    _source = ref.watch(landmarkSourceProvider);
    _api = ref.watch(apiClientProvider);
    _config = ref.watch(serverConfigProvider.select((s) => s.config.challenge));
    _recordDuration = ref.watch(
      serverConfigProvider.select((s) => s.config.captureDuration),
    );
    _gestureId = ref.watch(selectedGestureProvider);
    ref.listen(
      selectedUserProvider,
      (_, user) => _userId = user?.id ?? '',
      fireImmediately: true,
    );
    ref.onDispose(_teardown);
    return const AuthSessionState(retriesLeft: kSessionRetries);
  }

  /// 세션을 시작한다. 카메라는 여기서 한 번만 켠다.
  Future<void> begin() async {
    final ChallengeConfig? config = _config;
    if (config == null) {
      _unavailable('서버에서 Challenge 설정을 받지 못했습니다. '
          '네트워크를 확인하고 앱을 다시 실행해주세요.');
      return;
    }
    if (config.angleSpace != 'image_iso') {
      _unavailable('이 앱은 angleSpace=image_iso만 지원합니다 '
          '(서버 설정: ${config.angleSpace}).');
      return;
    }
    if (_userId.isEmpty) {
      _unavailable('사용자 목록을 불러오지 못했습니다. 홈에서 사용자를 선택해주세요.');
      return;
    }

    _teardown();
    _machine = ChallengeStateMachine(
      config: config,
      challenge: ChallengeGenerator().generate(config),
      fps: _observedFps > 0 ? _observedFps : config.frameReferenceFps,
    );
    _continuity = ContinuityMonitor(config);
    _resetCounters();

    if (kSendChallengeLog) {
      _sink = ChallengeDebugSink(
        _api,
        sessionId: _machine!.challenge.challengeId.split('-').first,
      )..add(formatBeginLine(_machine!.challenge, config));
    }

    state = AuthSessionState(
      phase: SessionPhase.challenge,
      challenge: _machine!.challenge,
      retriesLeft: state.retriesLeft,
    );

    try {
      await _source.start();
    } catch (error) {
      _unavailable(error is LandmarkSourceException
          ? error.message
          : '카메라를 시작하지 못했습니다. 앱을 다시 실행해주세요.');
      return;
    }

    _sub = _source.frames.listen(_onFrame, onError: (Object e) {
      _unavailable(e is LandmarkSourceException
          ? e.message
          : '카메라에서 오류가 발생했습니다.');
    });
    _watchdog = Timer.periodic(_watchdogPeriod, (_) => _onWatchdogTick());
  }

  /// 실패 후 처음부터 다시. 카메라는 다시 잡는다(세션이 끝났으므로).
  Future<void> retry() async {
    if (state.retriesLeft <= 0) return;
    state = state.copyWith(retriesLeft: state.retriesLeft - 1);
    await begin();
  }

  /// 화면을 떠날 때.
  void cancel() {
    _teardown();
    state = AuthSessionState(retriesLeft: state.retriesLeft);
  }

  // ─── 프레임 ─────────────────────────────────────────────────────

  void _onFrame(HandFrame frame) {
    if (state.finished) return;
    _frameCount++;
    _lastFrameGapMs = _sinceLastFrame.elapsedMilliseconds;
    _recordGap(_lastFrameGapMs);
    _sinceLastFrame
      ..reset()
      ..start();
    _latestFrame = frame;

    final CameraInfo? camera = _source.imageSize;
    final int? width = camera?.width;
    final int? height = camera?.height;
    if (width == null || height == null) {
      _push(_lostObservation());
      return;
    }

    // ⚠️ 좌표계: 판정 입력은 **회전만**, 거울은 넣지 않는다.
    //   서버로 가는 좌표(_buffer)는 회전도 넣지 않은 원본이다.
    final int rotation = _source.transform.rotationDegrees;
    final Coords rotated = <List<double>>[
      for (final Landmark p in frame.landmarks)
        () {
          final r = rotateNormalizedPoint(p.x, p.y, rotation);
          return <double>[r.x, r.y, p.z];
        }(),
    ];
    final size = rotatedFrameSize(width, height, rotation);
    final Coords screen = toIsotropic(rotated, size.width, size.height);

    // 제스처 수집 중이면 원본 좌표를 그대로 모은다.
    if (state.phase == SessionPhase.recording) {
      if (frame.tMs > _lastBufferedTMs) {
        _buffer.add(frame);
        _lastBufferedTMs = frame.tMs;
      }
      _syncRecordProgress();
    }

    // 손이 바뀌었는지(화면을 들이밀었는지) 잰다. 판정은 설정이 켜져 있을 때만.
    final ContinuitySample? sample =
        _continuity?.add(screen, _clock.elapsedMilliseconds.toDouble());
    if (_continuity?.breaksSession(sample) ?? false) {
      _breakSession(FailReason.sessionBroken);
      return;
    }

    _push(Observation(
      timestampMs: _clock.elapsedMilliseconds.toDouble(),
      handFound: true,
      detectionScore: _source.providesDetectionScore ? frame.score : null,
      angleCoords: screen,
      screenCoords: screen,
    ));
  }

  void _onWatchdogTick() {
    if (state.finished) return;
    if (_sinceLastFrame.elapsed < _staleThreshold) return;
    _lostInjections++;
    // 끊긴 뒤의 프레임을 직전 프레임과 비교하면 당연히 튄다.
    _continuity?.resetReference();
    _push(_lostObservation());
  }

  Observation _lostObservation() => Observation(
        timestampMs: _clock.elapsedMilliseconds.toDouble(),
        handFound: false,
      );

  void _push(Observation obs) {
    switch (state.phase) {
      case SessionPhase.challenge:
        _pushChallenge(obs);
      case SessionPhase.recording:
        // Challenge가 끝난 뒤에도 손이 계속 잡혀야 한다.
        if (!obs.handFound && _recordLostSpan.hit(obs.timestampMs)) {
          _breakSession(FailReason.sessionBroken);
          return;
        }
        if (obs.handFound) _recordLostSpan.reset();
        state = state.copyWith(
          latestFrame: _latestFrame,
          observedFps: _observedFps,
          lostInjections: _lostInjections,
          lastFrameGapMs: _lastFrameGapMs,
        );
      case _:
        break;
    }
  }

  void _pushChallenge(Observation obs) {
    final ChallengeStateMachine? machine = _machine;
    if (machine == null) return;

    final Status status = machine.update(obs);
    _log(machine, status, obs);

    state = state.copyWith(
      status: status,
      latestFrame: _latestFrame,
      debugShape: obs.handFound ? status.detectedShape : '—',
      observedFps: _observedFps,
      lostInjections: _lostInjections,
      lastFrameGapMs: _lastFrameGapMs,
    );

    if (status.state == ChallengeState.failed) {
      _finishLog(status);
      _stopCapture();
      state = state.copyWith(phase: SessionPhase.failed);
      return;
    }
    if (status.state == ChallengeState.passed) {
      _finishLog(status);
      // ⚠️ 카메라를 놓지 않는다. 손이 잡힌 채로 제스처 수집으로 이어진다.
      _beginRecording();
    }
  }

  // ─── 제스처 수집 ────────────────────────────────────────────────

  late FrameSpan _recordLostSpan;

  void _beginRecording() {
    final ChallengeConfig config = _config!;
    _recordLostSpan = FrameSpan(config.tracking.maxLostFrames + 1, config);
    _buffer.clear();
    _lastBufferedTMs = -1;
    _source.resetClock();
    _recordClock
      ..reset()
      ..start();
    _recordTimer = Timer(_recordDuration, _finishRecording);
    state = state.copyWith(
      phase: SessionPhase.recording,
      recordProgress: 0.0,
    );
    _sink?.add('$kDebugPrefix record start durationMs='
        '${_recordDuration.inMilliseconds} fps=${_observedFps.toStringAsFixed(1)}');
  }

  void _syncRecordProgress() {
    final double p = _recordDuration.inMilliseconds == 0
        ? 1.0
        : _recordClock.elapsedMilliseconds / _recordDuration.inMilliseconds;
    state = state.copyWith(recordProgress: p > 1.0 ? 1.0 : p);
  }

  void _finishRecording() {
    _recordTimer = null;
    _recordClock.stop();
    final List<HandFrame> frames = List<HandFrame>.of(_buffer);
    _sink?.add('$kDebugPrefix record done frames=${frames.length} '
        '${_continuity?.summary() ?? ''}');
    _stopCapture();

    if (frames.length < kMinFramesForVerify) {
      state = state.copyWith(
        phase: SessionPhase.failed,
        notice: '손 움직임이 충분히 기록되지 않았습니다. '
            '손 전체가 원 안에 보이도록 하고 다시 시도해주세요.',
      );
      return;
    }
    unawaited(_upload(frames));
  }

  Future<void> _upload(List<HandFrame> frames) async {
    final CameraInfo? camera = _source.imageSize;
    if (camera == null) {
      state = state.copyWith(
        phase: SessionPhase.failed,
        notice: '카메라 정보를 읽지 못했습니다. 화면을 나갔다가 다시 시도해주세요.',
      );
      return;
    }
    state = state.copyWith(phase: SessionPhase.uploading);

    // 전송 좌표는 **MediaPipe 원본 그대로**다. 회전도 미러도 넣지 않는다.
    // 등록과 인증이 같은 규약을 쓰고 있어 바꾸면 기존 템플릿이 무효가 된다.
    final VerifyRequest req = VerifyRequest(
      userId: _userId,
      gestureId: _gestureId,
      camera: camera,
      capturedAt: DateTime.now(),
      nominalFps: kNominalFps,
      durationMs: _recordDuration.inMilliseconds,
      frames: frames,
    );

    try {
      final VerifyResponse res = await _api.verify(req);
      if (!ref.mounted) return;
      state = state.copyWith(phase: SessionPhase.done, response: res);
    } on ApiException catch (e) {
      _uploadFailed(e.userMessage);
    } on TimeoutException {
      _uploadFailed('서버 응답이 없습니다. 네트워크 상태를 확인하고 다시 시도해주세요.');
    } on ApiNotConfiguredException catch (e) {
      _uploadFailed(e.message);
    } catch (_) {
      _uploadFailed('인증 요청을 보내지 못했습니다. 잠시 후 다시 시도해주세요.');
    }
  }

  void _uploadFailed(String notice) {
    if (!ref.mounted) return;
    state = state.copyWith(phase: SessionPhase.failed, notice: notice);
  }

  // ─── 세션 종료 ──────────────────────────────────────────────────

  void _breakSession(FailReason reason) {
    _sink?.add('$kDebugPrefix session broken reason=${reason.code} '
        'phase=${state.phase.name} ${_continuity?.summary() ?? ''}');
    unawaited(_sink?.close());
    _sink = null;
    _stopCapture();
    state = state.copyWith(
      phase: SessionPhase.failed,
      notice: challengeSessionBrokenNotice,
      status: state.status,
    );
  }

  void _unavailable(String notice) {
    _sink?.add(formatUnavailableLine(notice));
    _stopCapture();
    state = state.copyWith(phase: SessionPhase.unavailable, notice: notice);
  }

  void _stopCapture() {
    _watchdog?.cancel();
    _watchdog = null;
    _recordTimer?.cancel();
    _recordTimer = null;
    _sub?.cancel();
    _sub = null;
    _clock.stop();
    _sinceLastFrame.stop();
    _recordClock.stop();
    unawaited(_source.stop());
  }

  void _teardown() {
    _stopCapture();
    final ChallengeDebugSink? sink = _sink;
    _sink = null;
    if (sink != null) unawaited(sink.close());
    _machine = null;
    _continuity = null;
  }

  void _resetCounters() {
    _frameCount = 0;
    _gaps.clear();
    _lostInjections = 0;
    _lastFrameGapMs = 0;
    _loggedStep = 0;
    _buffer.clear();
    _lastBufferedTMs = -1;
    _latestFrame = null;
    _clock
      ..reset()
      ..start();
    _sinceLastFrame
      ..reset()
      ..start();
  }

  // ─── fps·공백 ──────────────────────────────────────────────────

  void _recordGap(int gapMs) {
    if (_frameCount <= 1 || gapMs <= 0) return;
    _gaps.add(gapMs);
    if (_gaps.length > _gapWindow) _gaps.removeAt(0);
    final double median = _medianGapMs;
    if (median > 0) _observedFps = 1000.0 / median;
  }

  double get _medianGapMs {
    if (_gaps.isEmpty) return 0.0;
    final List<int> sorted = List<int>.of(_gaps)..sort();
    final int n = sorted.length;
    return n.isOdd
        ? sorted[n ~/ 2].toDouble()
        : (sorted[n ~/ 2 - 1] + sorted[n ~/ 2]) / 2.0;
  }

  Duration get _staleThreshold {
    final ChallengeConfig? config = _config;
    if (config == null) return const Duration(milliseconds: 150);
    return config.tracking.staleThreshold(_medianGapMs);
  }

  // ─── 로그 ──────────────────────────────────────────────────────

  void _log(ChallengeStateMachine machine, Status status, Observation obs) {
    final ChallengeDebugSink? sink = _sink;
    if (sink == null) return;

    while (_loggedStep < status.stepIndex && _loggedStep < status.steps.length) {
      sink.add(formatStepLine(
        _loggedStep,
        status.steps.length,
        status.steps[_loggedStep],
      ));
      _loggedStep++;
    }

    if (obs.handFound) {
      final MoveProbe? probe = status.moveProbe;
      if (probe != null) {
        sink.add(formatMoveLine(
          probe,
          machine.config,
          requested: status.currentAction,
          lostInjections: _lostInjections,
          observedFps: _observedFps,
          frameGapMs: _lastFrameGapMs,
        ));
      } else if (obs.angleCoords != null) {
        sink.add(formatShapeLine(
          status,
          machine.shapeDetector.detect(obs.angleCoords!),
          machine.config,
          lostInjections: _lostInjections,
          observedFps: _observedFps,
          frameGapMs: _lastFrameGapMs,
        ));
      }
    }
  }

  void _finishLog(Status status) {
    final ChallengeDebugSink? sink = _sink;
    if (sink == null) return;
    if (_loggedStep < status.steps.length &&
        status.steps[_loggedStep].failReason != null) {
      sink.add(formatStepLine(_loggedStep, status.steps.length,
          status.steps[_loggedStep]));
    }
    sink.add(formatResultLine(
      status,
      elapsedMs: _clock.elapsedMilliseconds,
      lostInjections: _lostInjections,
      observedFps: _observedFps,
    ));
    // 연속성 측정값. 이 분포로 임계값을 도출한다.
    sink.add('$kDebugPrefix continuity ${_continuity?.summary() ?? ''}');
  }
}

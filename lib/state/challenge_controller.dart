/// Challenge 화면의 상태 관리.
///
/// [ChallengeStateMachine]은 순수 Dart이고 프레임을 하나씩 받는다. 이 컨트롤러는
/// 카메라 스트림과 워치독을 그 입력으로 바꿔주는 얇은 층이다. 판정 규칙은 여기
/// 없다 — 규칙을 두 군데 두면 갈라진다.
///
/// **판정은 앱에서 한다.** 서버 왕복 지연으로는 남은 시간·현재 손 모양 같은
/// 실시간 피드백을 줄 수 없기 때문이다. 앱을 조작해 "통과했다"고 보낼 수 있다는
/// 한계가 있다 (README 알려진 한계).
library;

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../challenge/challenge_config.dart';
import '../challenge/challenge_debug_format.dart';
import '../challenge/challenge_generator.dart';
import '../challenge/challenge_state_machine.dart';
import '../challenge/geometry.dart';
import '../core/screen_rotation.dart';
import '../models/camera_info.dart';
import '../models/landmark.dart';
import '../screens/challenge_screen.dart' show kShowChallengeDebug;
import '../services/api_client.dart';
import '../services/challenge_debug_sink.dart';
import '../services/landmark_source.dart';
import 'providers.dart';

/// 화면이 보는 단계.
enum ChallengePhase {
  /// 아직 시작하지 않음.
  idle,

  /// 진행 중.
  running,

  /// 통과. 제스처 인증으로 넘어간다.
  passed,

  /// 실패. 재시도하거나 홈으로 돌아간다.
  failed,

  /// 설정을 못 받았거나 카메라를 못 켰다.
  unavailable,
}

@immutable
class ChallengeFlowState {
  final ChallengePhase phase;

  /// 상태 머신이 준 마지막 스냅샷. 시작 전이면 null.
  final Status? status;

  final Challenge? challenge;

  /// 남은 재시도 횟수(세션 전체 기준). 실패하면 하나 쓴다.
  final int retriesLeft;

  /// 사용자에게 보여줄 문제 설명. unavailable이나 카메라 오류일 때만 채운다.
  final String? notice;

  /// 마지막 프레임의 검출 손 모양(디버그 표시용).
  final String debugShape;

  /// 오버레이에 그릴 마지막 프레임. 화면이 스트림을 따로 구독하면 소스가
  /// 이중으로 붙으므로 여기서 들고 있는다.
  final HandFrame? latestFrame;

  /// 프레임 도착 간격에서 추정한 실측 fps. 진단 표시용.
  ///
  /// 임계값은 30fps 파일럿 영상에서 도출됐다. 실기기가 몇 fps로 도는지 같이
  /// 보여줘야 판정이 이상할 때 조건 차이를 의심할 수 있다.
  final double observedFps;

  /// 워치독이 '손 없음'을 만들어 넣은 횟수(현재 단계 기준).
  ///
  /// 손 없음 관측은 이동 판정 윈도우를 **비운다.** 실제로 손이 보이는데도 이 수가
  /// 계속 올라간다면, 프레임 간격이 [ChallengeController]의 신선도 기준을 넘어선
  /// 것이다. 그 경우 윈도우가 찰 기회가 없어 이동이 영영 확정되지 않는다.
  final int lostInjections;

  /// 마지막 프레임 사이 간격(ms). 실측 프레임 간격이다.
  final int lastFrameGapMs;

  const ChallengeFlowState({
    this.phase = ChallengePhase.idle,
    this.status,
    this.challenge,
    this.retriesLeft = 0,
    this.notice,
    this.debugShape = '',
    this.latestFrame,
    this.observedFps = 0.0,
    this.lostInjections = 0,
    this.lastFrameGapMs = 0,
  });

  ChallengeFlowState copyWith({
    ChallengePhase? phase,
    Status? status,
    Challenge? challenge,
    int? retriesLeft,
    String? notice,
    bool clearNotice = false,
    String? debugShape,
    HandFrame? latestFrame,
    double? observedFps,
    int? lostInjections,
    int? lastFrameGapMs,
  }) {
    return ChallengeFlowState(
      phase: phase ?? this.phase,
      status: status ?? this.status,
      challenge: challenge ?? this.challenge,
      retriesLeft: retriesLeft ?? this.retriesLeft,
      notice: clearNotice ? null : (notice ?? this.notice),
      debugShape: debugShape ?? this.debugShape,
      latestFrame: latestFrame ?? this.latestFrame,
      observedFps: observedFps ?? this.observedFps,
      lostInjections: lostInjections ?? this.lostInjections,
      lastFrameGapMs: lastFrameGapMs ?? this.lastFrameGapMs,
    );
  }

  /// 요청 동작 목록. 시작 전이면 빈 목록.
  List<String> get actions => challenge?.actions ?? const <String>[];

  int get stepIndex => status?.stepIndex ?? 0;

  bool get finished =>
      phase == ChallengePhase.passed || phase == ChallengePhase.failed;
}

/// 세션 전체에서 허용할 재시도 횟수.
///
/// 단계 하나를 다시 하는 [ChallengeConfig.timing]의 `maxRetries`와 다르다.
/// 이건 Challenge 전체를 처음부터 다시 도는 횟수다.
const int kChallengeSessionRetries = 1;

final challengeControllerProvider =
    NotifierProvider<ChallengeController, ChallengeFlowState>(
  ChallengeController.new,
);

class ChallengeController extends Notifier<ChallengeFlowState> {
  /// 손이 없는 프레임을 만들어 넣는 주기.
  ///
  /// [LandmarkSource.frames]는 **손이 없는 프레임을 흘리지 않는다.** 상태 머신은
  /// 손 소실을 세려면 `handFound: false` 관측이 필요하므로 여기서 만들어 넣는다.
  static const Duration _watchdogPeriod = Duration(milliseconds: 33);

  /// 프레임 간격을 이만큼 모아 중앙값을 낸다. 순간 fps와 '손 없음' 기준의 근거다.
  ///
  /// 너무 짧으면 한 번 튄 값에 흔들리고, 너무 길면 fps가 변해도 따라가지 못한다.
  static const int _gapWindow = 15;

  late LandmarkSource _source;
  late ApiClient _api;
  ChallengeConfig? _config;

  ChallengeStateMachine? _machine;
  StreamSubscription<HandFrame>? _sub;
  Timer? _watchdog;
  final Stopwatch _clock = Stopwatch();
  final Stopwatch _sinceLastFrame = Stopwatch();

  /// 최근 프레임 간격(ms). 순간 fps와 '손 없음' 판단 기준을 여기서 뽑는다.
  final List<int> _gaps = <int>[];

  /// 최근 간격 기준 순간 fps. 세션 누적 평균이 아니다.
  ///
  /// 누적 평균을 쓰다가 실기기에서 2.5, 5.6처럼 나왔다. 카메라가 올라오기 전
  /// 구간까지 섞여서다. 실제로는 12~14fps였다.
  double _observedFps = 0.0;
  int _frameCount = 0;
  int _lostInjections = 0;
  int _lastFrameGapMs = 0;

  /// 판정 로그를 서버로 흘리는 곳. [kShowChallengeDebug]가 false면 null이다.
  ChallengeDebugSink? _sink;

  /// 마지막으로 기록한 단계. 단계 전환을 한 줄로 남기려고 들고 있는다.
  int _loggedStep = 0;

  @override
  ChallengeFlowState build() {
    _source = ref.watch(landmarkSourceProvider);
    _api = ref.watch(apiClientProvider);
    _config = ref.watch(
      serverConfigProvider.select((s) => s.config.challenge),
    );
    ref.onDispose(_teardown);
    return ChallengeFlowState(retriesLeft: kChallengeSessionRetries);
  }

  /// 새 Challenge를 뽑아 시작한다.
  Future<void> begin() async {
    final ChallengeConfig? config = _config;
    if (config == null) {
      state = state.copyWith(
        phase: ChallengePhase.unavailable,
        notice: '서버에서 Challenge 설정을 받지 못했습니다. '
            '네트워크를 확인하고 앱을 다시 실행해주세요.',
      );
      return;
    }
    if (config.angleSpace != 'image_iso') {
      // world 좌표는 플러그인이 주지 않는다. 조용히 틀린 각도로 판정하지 않는다.
      state = state.copyWith(
        phase: ChallengePhase.unavailable,
        notice: '이 앱은 angleSpace=image_iso만 지원합니다 '
            '(서버 설정: ${config.angleSpace}).',
      );
      return;
    }

    _teardown();
    _machine = ChallengeStateMachine(
      config: config,
      challenge: ChallengeGenerator().generate(config),
      // 실측 fps를 모르는 동안은 기준 fps로 윈도우를 잡는다. 판정 자체는
      // 프레임 수가 아니라 시간으로 하므로 이 값이 정확하지 않아도 된다.
      fps: _observedFps > 0 ? _observedFps : config.frameReferenceFps,
    );
    _frameCount = 0;
    _gaps.clear();
    _lostInjections = 0;
    _lastFrameGapMs = 0;
    _loggedStep = 0;
    if (kShowChallengeDebug) {
      _sink = ChallengeDebugSink(
        _api,
        sessionId: _machine!.challenge.challengeId.split('-').first,
      )..add(formatBeginLine(_machine!.challenge, config));
    }
    _clock
      ..reset()
      ..start();
    _sinceLastFrame
      ..reset()
      ..start();

    state = ChallengeFlowState(
      phase: ChallengePhase.running,
      challenge: _machine!.challenge,
      retriesLeft: state.retriesLeft,
    );

    try {
      await _source.start();
    } catch (error) {
      _fail(
        error is LandmarkSourceException
            ? error.message
            : '카메라를 시작하지 못했습니다. 앱을 다시 실행해주세요.',
      );
      return;
    }

    _sub = _source.frames.listen(_onFrame, onError: (Object e) {
      _fail(e is LandmarkSourceException
          ? e.message
          : '카메라에서 오류가 발생했습니다.');
    });
    _watchdog = Timer.periodic(_watchdogPeriod, (_) => _onWatchdogTick());
  }

  /// 실패 후 다시 시도한다. 남은 횟수가 없으면 아무 일도 하지 않는다.
  Future<void> retry() async {
    if (state.retriesLeft <= 0) return;
    state = state.copyWith(retriesLeft: state.retriesLeft - 1);
    await begin();
  }

  /// 화면을 떠날 때. 카메라를 놓고 상태를 되돌린다.
  void cancel() {
    _teardown();
    state = ChallengeFlowState(retriesLeft: state.retriesLeft);
  }

  // ─── 프레임 처리 ────────────────────────────────────────────────

  void _onFrame(HandFrame frame) {
    final ChallengeStateMachine? machine = _machine;
    if (machine == null || state.finished) return;

    _frameCount++;
    _lastFrameGapMs = _sinceLastFrame.elapsedMilliseconds;
    _recordGap(_lastFrameGapMs);
    _sinceLastFrame
      ..reset()
      ..start();

    final CameraInfo? camera = _source.imageSize;
    final int? width = camera?.width;
    final int? height = camera?.height;
    if (width == null || height == null) {
      // 해상도를 모르면 종횡비 보정을 못 한다. 각도가 왜곡되므로 판정하지 않고
      // '손 없음'으로 흘린다(그 상태가 오래 가면 HAND_NOT_FOUND로 끝난다).
      _push(machine, _lostObservation());
      return;
    }

    // ⚠️ 좌표계 규칙
    //   MediaPipe 입력: 원본 / **서버 전송: 원본** / 화면·오버레이: 회전 + 거울
    //   판정 입력: 회전만. 거울은 넣지 않는다.
    //
    // 회전은 반드시 넣어야 한다. 센서는 가로(720×480)인데 폰은 세로라, 회전을
    // 빼면 x와 y가 통째로 바뀐다. 각도는 회전에 불변이라 손 모양은 맞지만
    // 이동 방향은 90도 돌아간다(2026-09-18 실기기: req=MOVE_UP → label=MOVE_RIGHT).
    //
    // 거울은 넣지 않는다. MovementDetector가 coordinateFrame=mirrored일 때
    // **라벨만** 뒤집는다. 좌표까지 뒤집으면 반전이 상쇄된다.
    //
    // 서버로 가는 /verify·/enroll 좌표는 이 변환을 거치지 않는다. 등록과 인증이
    // 같은 규약(원본)을 쓰고 있어 건드리면 기존 템플릿이 무효가 된다.
    final int rotation = _source.transform.rotationDegrees;
    final Coords rotated = <List<double>>[
      for (final Landmark p in frame.landmarks)
        () {
          final r = rotateNormalizedPoint(p.x, p.y, rotation);
          return <double>[r.x, r.y, p.z];
        }(),
    ];
    // 90·270도에서는 가로·세로가 바뀐다. 회전 전 크기로 보정하면 다시 왜곡된다.
    final size = rotatedFrameSize(width, height, rotation);
    final Coords screen = toIsotropic(rotated, size.width, size.height);

    _latestFrame = frame;
    _push(
      machine,
      Observation(
        timestampMs: _clock.elapsedMilliseconds.toDouble(),
        handFound: true,
        // ⚠️ 측정된 신뢰도일 때만 넘긴다.
        //
        // OnDeviceLandmarkSource는 신뢰도를 측정하지 못하면서도 score에
        // minHandDetectionConfidence(0.6)를 **하한값으로** 채워 넣는다.
        // 그 0.6을 minDetectionScore(0.938, 실제 신뢰도 분포의 p5)와 비교하면
        // 매 프레임 미달이 되어 실기기에서 TRACKING_UNSTABLE만 떴다.
        //
        // "0.6 이상"과 "0.6"은 다른 말이다. 측정하지 않은 값으로 관문을 통과시킬
        // 수도, 떨어뜨릴 수도 없다. null을 주면 상태 머신이 관문을 건너뛴다.
        detectionScore: _source.providesDetectionScore ? frame.score : null,
        angleCoords: screen, // angleSpace=image_iso
        screenCoords: screen,
      ),
    );
  }

  void _onWatchdogTick() {
    final ChallengeStateMachine? machine = _machine;
    if (machine == null || state.finished) return;
    if (_sinceLastFrame.elapsed < _staleThreshold) return;
    // 손이 실제로 없는 경우와, 프레임이 늦어 신선도 기준을 넘긴 경우를 여기서는
    // 구분할 수 없다. 둘 다 윈도우를 비우므로 횟수를 세어 화면에 드러낸다.
    _lostInjections++;
    _push(machine, _lostObservation());
  }

  Observation _lostObservation() => Observation(
        timestampMs: _clock.elapsedMilliseconds.toDouble(),
        handFound: false,
      );

  HandFrame? _latestFrame;

  void _push(ChallengeStateMachine machine, Observation obs) {
    final Status status = machine.update(obs);
    _log(machine, status, obs);
    final ChallengePhase phase = switch (status.state) {
      ChallengeState.passed => ChallengePhase.passed,
      ChallengeState.failed => ChallengePhase.failed,
      _ => ChallengePhase.running,
    };
    state = state.copyWith(
      phase: phase,
      status: status,
      debugShape: obs.handFound ? status.detectedShape : '—',
      latestFrame: _latestFrame,
      observedFps: _observedFps,
      lostInjections: _lostInjections,
      lastFrameGapMs: _lastFrameGapMs,
    );
    if (status.finished) _stopCapture();
  }

  /// 판정 상황을 한 줄씩 남긴다. 화면 패널과 **같은 값**을 쓴다.
  void _log(ChallengeStateMachine machine, Status status, Observation obs) {
    final ChallengeDebugSink? sink = _sink;
    if (sink == null) return;

    // 단계가 넘어갔으면 그 결과를 먼저 남긴다.
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

    if (status.finished) {
      // 실패한 단계도 기록에 남긴다.
      if (_loggedStep < status.steps.length &&
          status.steps[_loggedStep].failReason != null) {
        sink.add(formatStepLine(
          _loggedStep,
          status.steps.length,
          status.steps[_loggedStep],
        ));
      }
      sink.add(formatResultLine(
        status,
        elapsedMs: _clock.elapsedMilliseconds,
        lostInjections: _lostInjections,
        observedFps: _observedFps,
      ));
      // 마지막 줄까지 보내고 닫는다. 한 세션을 통째로 볼 수 있어야 한다.
      unawaited(sink.close());
      _sink = null;
    }
  }

  /// 프레임 간격을 모아 순간 fps를 낸다.
  void _recordGap(int gapMs) {
    // 첫 프레임의 '간격'은 카메라가 올라오는 시간이라 근거가 못 된다.
    if (_frameCount <= 1 || gapMs <= 0) return;
    _gaps.add(gapMs);
    if (_gaps.length > _gapWindow) _gaps.removeAt(0);
    final double median = _medianGapMs;
    if (median > 0) _observedFps = 1000.0 / median;
  }

  /// 최근 프레임 간격의 중앙값. 표본이 없으면 0.
  ///
  /// 평균이 아니라 중앙값이다. 한 번 크게 튄 프레임에 기준이 끌려가면 안 된다.
  double get _medianGapMs {
    if (_gaps.isEmpty) return 0.0;
    final List<int> sorted = List<int>.of(_gaps)..sort();
    final int n = sorted.length;
    return n.isOdd
        ? sorted[n ~/ 2].toDouble()
        : (sorted[n ~/ 2 - 1] + sorted[n ~/ 2]) / 2.0;
  }

  /// '손 없음'으로 볼 프레임 공백. **실측 간격에서 유도한다.**
  ///
  /// 고정 100ms를 쓰다가 실기기에서 터졌다. 14fps면 간격이 71ms라 여유가 29ms뿐이고,
  /// 한 프레임만 늦어도(110~170ms 관측) 손 없음이 주입돼 이동 윈도우가 비워졌다.
  /// 배수와 상·하한은 서버 설정에서 온다.
  Duration get _staleThreshold {
    final ChallengeConfig? config = _config;
    if (config == null) return const Duration(milliseconds: 150);
    return config.tracking.staleThreshold(_medianGapMs);
  }

  void _fail(String notice) {
    _sink?.add(formatUnavailableLine(notice));
    _stopCapture();
    state = state.copyWith(phase: ChallengePhase.unavailable, notice: notice);
  }

  void _stopCapture() {
    _watchdog?.cancel();
    _watchdog = null;
    _sub?.cancel();
    _sub = null;
    _clock.stop();
    _sinceLastFrame.stop();
    // 소스 자체의 dispose는 landmarkSourceProvider가 책임진다.
    unawaited(_source.stop());
  }

  void _teardown() {
    _stopCapture();
    final ChallengeDebugSink? sink = _sink;
    _sink = null;
    if (sink != null) unawaited(sink.close());
    _machine = null;
  }
}

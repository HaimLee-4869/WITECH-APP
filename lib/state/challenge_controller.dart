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
import '../challenge/challenge_generator.dart';
import '../challenge/challenge_state_machine.dart';
import '../challenge/geometry.dart';
import '../models/camera_info.dart';
import '../models/landmark.dart';
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

  /// 이 시간 안에 프레임이 왔으면 손이 있는 것으로 본다. 워치독이 만든 '손 없음'이
  /// 정상 프레임 사이의 지터를 손 소실로 오인하지 않게 한다.
  static const Duration _frameFreshness = Duration(milliseconds: 100);

  late LandmarkSource _source;
  ChallengeConfig? _config;

  ChallengeStateMachine? _machine;
  StreamSubscription<HandFrame>? _sub;
  Timer? _watchdog;
  final Stopwatch _clock = Stopwatch();
  final Stopwatch _sinceLastFrame = Stopwatch();

  /// 프레임이 실제로 도착한 간격에서 추정한 fps. 이동 윈도우 크기에 쓴다.
  double _observedFps = 0.0;
  int _frameCount = 0;
  int _lostInjections = 0;
  int _lastFrameGapMs = 0;

  @override
  ChallengeFlowState build() {
    _source = ref.watch(landmarkSourceProvider);
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
    _lostInjections = 0;
    _lastFrameGapMs = 0;
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
    _updateFps();
    _lastFrameGapMs = _sinceLastFrame.elapsedMilliseconds;
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

    // ⚠️ 좌표계 규칙: **원본 좌표를 그대로 넣는다.**
    //   MediaPipe 입력: 원본 / 서버 전송: 원본 / 화면·오버레이: 거울
    //   방향 판정의 좌우 반전은 MovementDetector가 **라벨에만** 적용한다.
    //   여기서 x를 뒤집으면 이중 반전이 되어 좌우가 도로 맞아버린다.
    final Coords raw = <List<double>>[
      for (final Landmark p in frame.landmarks) <double>[p.x, p.y, p.z],
    ];
    final Coords screen = toIsotropic(raw, width, height);

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
    if (_sinceLastFrame.elapsed < _frameFreshness) return;
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

  void _updateFps() {
    // 첫 몇 프레임은 카메라가 안정되기 전이라 쓰지 않는다.
    if (_frameCount < 5) return;
    final int elapsed = _clock.elapsedMilliseconds;
    if (elapsed > 0) _observedFps = _frameCount / (elapsed / 1000.0);
  }

  void _fail(String notice) {
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
    _machine = null;
  }
}

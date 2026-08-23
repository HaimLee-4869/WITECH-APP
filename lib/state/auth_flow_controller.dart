import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/config.dart';
import '../models/landmark.dart';
import '../models/verify.dart';
import '../services/api_client.dart';
import '../services/landmark_source.dart';
import 'providers.dart';

/// 인증 화면의 상태. (SPEC 8.2 상태 머신)
enum AuthPhase {
  /// 카메라만 켜져 있고 대기 중. 인증 버튼 활성.
  idle,

  /// 인증 버튼을 누른 직후. 손을 찾는 중.
  handSearching,

  /// 손이 연속으로 검출되어 카운트다운 중.
  handReady,

  /// 실제로 프레임을 수집하는 중.
  recording,

  /// 서버 전송 중.
  uploading,

  /// 응답을 받아 결과 화면으로 넘어갈 준비가 됨.
  done,
}

@immutable
class AuthFlowState {
  final AuthPhase phase;

  /// 오버레이에 그릴 최신 프레임. 원본 좌표 그대로다.
  final HandFrame? latestFrame;

  /// [AuthPhase.handReady]에서 3 → 2 → 1.
  final int countdown;

  /// [AuthPhase.recording] 진행률 0.0~1.0.
  final double progress;

  /// [AuthPhase.done]일 때의 서버 응답.
  final VerifyResponse? response;

  /// 사용자에게 보여줄 오류/재시도 안내. 정상 흐름에서는 null.
  ///
  /// 사과하지 않고 무엇이 잘못됐는지와 어떻게 고치는지를 담는다. (SPEC 5장)
  final String? notice;

  const AuthFlowState({
    this.phase = AuthPhase.idle,
    this.latestFrame,
    this.countdown = kCountdownSeconds,
    this.progress = 0.0,
    this.response,
    this.notice,
  });

  AuthFlowState copyWith({
    AuthPhase? phase,
    HandFrame? latestFrame,
    int? countdown,
    double? progress,
    VerifyResponse? response,
    String? notice,
    bool clearNotice = false,
    bool clearResponse = false,
    bool clearFrame = false,
  }) {
    return AuthFlowState(
      phase: phase ?? this.phase,
      latestFrame: clearFrame ? null : (latestFrame ?? this.latestFrame),
      countdown: countdown ?? this.countdown,
      progress: progress ?? this.progress,
      response: clearResponse ? null : (response ?? this.response),
      notice: clearNotice ? null : (notice ?? this.notice),
    );
  }

  /// 원 아래에 표시할 안내 문구. 상태에서 파생되므로 화면이 계산하지 않는다.
  String get message {
    final n = notice;
    if (n != null) return n;
    return switch (phase) {
      AuthPhase.idle => '수어 암호를 입력하세요',
      AuthPhase.handSearching => '손을 원 안에 위치시켜 주세요',
      AuthPhase.handReady => '$countdown초 후 시작합니다',
      AuthPhase.recording => '동작을 수행하세요',
      AuthPhase.uploading => '확인 중입니다',
      AuthPhase.done => '확인이 끝났습니다',
    };
  }

  /// 인증 버튼을 누를 수 있는 상태인지.
  bool get canStart => phase == AuthPhase.idle;

  /// 진행 중이라 취소가 의미 있는 상태인지.
  bool get isRunning =>
      phase == AuthPhase.handSearching ||
      phase == AuthPhase.handReady ||
      phase == AuthPhase.recording;
}

/// 인증 흐름 상태 머신.
///
/// Riverpod 3에서 `StateNotifierProvider`는 `legacy.dart`로 분리된 레거시 API라
/// 지금 쓰면 곧 갈아엎어야 하는 코드가 된다. 그래서 동등한 최신 API인
/// [Notifier]를 쓴다. SPEC 3장의 의도는 "과하게 추상화하지 말 것"이므로
/// 코드 생성 없이 단순한 [NotifierProvider] 하나로 유지한다.
class AuthFlowController extends Notifier<AuthFlowState> {
  /// 명목 프레임 간격(ms).
  static const double _frameIntervalMs = 1000.0 / kNominalFps;

  /// 지터 허용치. 이보다 적게 비면 연속 검출이 끊긴 것으로 치지 않는다.
  ///
  /// 소스는 손이 있을 때만 프레임을 흘리므로 "사라진 프레임"을 직접 셀 수가
  /// 없다. 그래서 마지막 프레임 이후 흐른 시간을 프레임 수로 환산해서 센다.
  static const int _jitterToleranceFrames = 2;

  /// 감시 타이머 주기. 프레임 간격보다 촘촘해봐야 낭비다.
  static const Duration _watchdogPeriod = Duration(milliseconds: 33);

  /// 진행률 아크 갱신 주기. 60fps까지 갈 이유가 없어 20fps로 둔다.
  static const Duration _progressPeriod = Duration(milliseconds: 50);

  late final LandmarkSource _source;
  late final ApiClient _api;

  StreamSubscription<HandFrame>? _sub;
  Timer? _watchdog;
  Timer? _countdownTimer;
  Timer? _progressTimer;
  Timer? _recordTimer;

  /// 수집 버퍼. **원본 좌표 그대로** 쌓는다. (SPEC 원칙 A)
  final List<HandFrame> _buffer = <HandFrame>[];

  final _sinceLastFrame = Stopwatch();
  final _recordClock = Stopwatch();

  int _consecutiveDetected = 0;
  String _userId = '';

  @override
  AuthFlowState build() {
    _source = ref.watch(landmarkSourceProvider);
    _api = ref.watch(apiClientProvider);
    _userId = ref.watch(selectedUserProvider);
    ref.onDispose(_teardown);
    return const AuthFlowState();
  }

  /// 화면 진입 시 호출. 소스를 켜고 오버레이를 살린다.
  Future<void> attach() async {
    if (_sub != null) return;
    _sub = _source.frames.listen(_onFrame);
    _sinceLastFrame
      ..reset()
      ..start();
    _watchdog = Timer.periodic(_watchdogPeriod, (_) => _onWatchdogTick());
    await _source.start();
  }

  /// 인증 버튼. `idle`에서만 의미가 있다.
  void start() {
    if (state.phase != AuthPhase.idle) return;
    _buffer.clear();
    _consecutiveDetected = 0;
    state = state.copyWith(
      phase: AuthPhase.handSearching,
      progress: 0.0,
      countdown: kCountdownSeconds,
      clearNotice: true,
      clearResponse: true,
    );
  }

  /// 취소 버튼. 진행 중이던 모든 타이머를 끊고 `idle`로 돌아간다.
  void cancel() {
    _cancelFlowTimers();
    _buffer.clear();
    _consecutiveDetected = 0;
    state = state.copyWith(
      phase: AuthPhase.idle,
      progress: 0.0,
      countdown: kCountdownSeconds,
      clearNotice: true,
      clearResponse: true,
    );
  }

  /// 결과 화면에서 돌아왔을 때 처음 상태로 되돌린다.
  void reset() => cancel();

  // ─── 프레임 처리 ────────────────────────────────────────────────

  void _onFrame(HandFrame frame) {
    _sinceLastFrame
      ..reset()
      ..start();
    _consecutiveDetected++;

    // recording 중에만 버퍼에 쌓는다. 다른 상태의 프레임은 오버레이 표시용이다.
    if (state.phase == AuthPhase.recording && _isFreshForRecording(frame)) {
      _buffer.add(frame);
    }

    state = state.copyWith(latestFrame: frame);

    if (state.phase == AuthPhase.handSearching &&
        _consecutiveDetected >= kHandReadyFrameThreshold) {
      _enterHandReady();
    }
  }

  /// 녹화 시작 직전에 만들어진 "묵은" 프레임인지 판별한다.
  ///
  /// 소스의 스트림은 비동기라, `resetClock()` 직전에 생성된 프레임이 phase가
  /// recording으로 바뀐 뒤에 도착할 수 있다. 그런 프레임은 리셋 전 시계로
  /// 찍힌 tMs(예: 3300ms)를 달고 있어서, 그대로 버퍼에 넣으면 첫 프레임의
  /// 타임스탬프가 통째로 어긋나고 서버 리샘플링이 망가진다.
  ///
  /// 정상 프레임의 tMs는 녹화 경과 시간과 거의 같으므로, 한 프레임 간격 남짓
  /// 이상 앞서 있는 값은 리셋 전 프레임으로 보고 버린다.
  bool _isFreshForRecording(HandFrame frame) {
    final elapsed = _recordClock.elapsedMilliseconds;
    return frame.tMs <= elapsed + (_frameIntervalMs * 2);
  }

  void _onWatchdogTick() {
    final gapFrames = _sinceLastFrame.elapsedMilliseconds / _frameIntervalMs;

    // 지터 정도로 비었으면 연속 검출이 끊긴 게 아니다.
    if (gapFrames >= _jitterToleranceFrames) {
      _consecutiveDetected = 0;
    }

    // 손을 오래 놓치면 오버레이에 낡은 뼈대가 남으므로 지운다.
    if (gapFrames >= kHandLostFrameThreshold && state.latestFrame != null) {
      state = state.copyWith(clearFrame: true);
    }

    switch (state.phase) {
      case AuthPhase.handReady:
        // 카운트다운 도중 손이 사라지면 다시 찾는 단계로 되돌린다.
        // SPEC은 recording 중 이탈만 명시하지만, 손이 없는 채로 카운트다운이
        // 끝나 빈 수집이 시작되는 것을 막으려면 여기서도 되돌려야 한다.
        if (gapFrames >= kHandLostFrameThreshold) {
          _backToSearching('손이 화면을 벗어났습니다. 손 전체가 원 안에 들어오도록 해주세요.');
        }
      case AuthPhase.recording:
        // 15프레임 이상 연속으로 사라지면 수집을 버리고 처음부터. (SPEC 8.2)
        if (gapFrames >= kHandLostFrameThreshold) {
          _backToSearching('손이 화면을 벗어났습니다. 다시 시도해주세요.');
        }
      case AuthPhase.idle:
      case AuthPhase.handSearching:
      case AuthPhase.uploading:
      case AuthPhase.done:
        break;
    }
  }

  // ─── 상태 전이 ──────────────────────────────────────────────────

  void _enterHandReady() {
    _countdownTimer?.cancel();
    state = state.copyWith(
      phase: AuthPhase.handReady,
      countdown: kCountdownSeconds,
      clearNotice: true,
    );
    _countdownTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      final next = state.countdown - 1;
      if (next <= 0) {
        timer.cancel();
        _enterRecording();
        return;
      }
      state = state.copyWith(countdown: next);
    });
  }

  void _enterRecording() {
    _buffer.clear();
    // tMs는 "캡처 시작 시점부터의 경과 시간"이므로 여기서 기준점을 다시 잡는다.
    _source.resetClock();
    _recordClock
      ..reset()
      ..start();

    state = state.copyWith(
      phase: AuthPhase.recording,
      progress: 0.0,
      clearNotice: true,
    );

    _progressTimer = Timer.periodic(_progressPeriod, (_) {
      final p =
          _recordClock.elapsedMilliseconds / kRecordDuration.inMilliseconds;
      state = state.copyWith(progress: p.clamp(0.0, 1.0));
    });

    _recordTimer = Timer(kRecordDuration, _finishRecording);
  }

  void _finishRecording() {
    _progressTimer?.cancel();
    _recordTimer?.cancel();
    _recordClock.stop();

    final frames = List<HandFrame>.unmodifiable(_buffer);

    // 프레임이 너무 적으면 서버로 보내지 않고 재시도를 안내한다. (SPEC 8.2)
    if (frames.length < kMinFramesForVerify) {
      _buffer.clear();
      _consecutiveDetected = 0;
      state = state.copyWith(
        phase: AuthPhase.idle,
        progress: 0.0,
        countdown: kCountdownSeconds,
        notice: '손 움직임이 충분히 기록되지 않았습니다. '
            '손 전체가 원 안에 보이도록 하고 다시 시도해주세요.',
      );
      return;
    }

    _upload(frames);
  }

  Future<void> _upload(List<HandFrame> frames) async {
    state = state.copyWith(
      phase: AuthPhase.uploading,
      progress: 1.0,
      clearNotice: true,
    );

    // 전송용 요청. 좌표에 미러링·정규화·특징추출을 일절 적용하지 않는다.
    // 화면의 오버레이는 좌우 반전되어 있지만 그건 렌더링 전용 변환이고,
    // 여기 담기는 frames는 MediaPipe 원본 좌표 그대로다. (SPEC 원칙 A, 8.2)
    final req = VerifyRequest(
      userId: _userId,
      capturedAt: DateTime.now(),
      nominalFps: kNominalFps,
      durationMs: kRecordDuration.inMilliseconds,
      frames: frames,
    );

    try {
      final res = await _api.verify(req);
      if (!ref.mounted) return;
      state = state.copyWith(phase: AuthPhase.done, response: res);
    } on TimeoutException {
      if (!ref.mounted) return;
      _failToIdle('서버 응답이 없습니다. 네트워크 상태를 확인하고 다시 시도해주세요.');
    } on UnimplementedError {
      if (!ref.mounted) return;
      // kUseMockApi = false인데 서버 연동이 아직 안 된 경우.
      _failToIdle('AI 서버가 아직 연결되지 않았습니다. config.dart의 kUseMockApi를 확인해주세요.');
    } catch (_) {
      if (!ref.mounted) return;
      _failToIdle('인증 요청을 보내지 못했습니다. 잠시 후 다시 시도해주세요.');
    }
  }

  void _failToIdle(String notice) {
    _buffer.clear();
    _consecutiveDetected = 0;
    state = state.copyWith(
      phase: AuthPhase.idle,
      progress: 0.0,
      countdown: kCountdownSeconds,
      notice: notice,
      clearResponse: true,
    );
  }

  void _backToSearching(String notice) {
    _cancelFlowTimers();
    _buffer.clear();
    _consecutiveDetected = 0;
    state = state.copyWith(
      phase: AuthPhase.handSearching,
      progress: 0.0,
      countdown: kCountdownSeconds,
      notice: notice,
    );
  }

  void _cancelFlowTimers() {
    _countdownTimer?.cancel();
    _countdownTimer = null;
    _progressTimer?.cancel();
    _progressTimer = null;
    _recordTimer?.cancel();
    _recordTimer = null;
    _recordClock.stop();
  }

  void _teardown() {
    _cancelFlowTimers();
    _watchdog?.cancel();
    _watchdog = null;
    _sub?.cancel();
    _sub = null;
    _sinceLastFrame.stop();
    // 소스 자체의 dispose는 landmarkSourceProvider가 책임진다.
  }
}

/// 화면을 벗어나면 컨트롤러와 소스가 함께 정리되도록 autoDispose로 둔다.
/// (SPEC 8.2 — 화면 이탈 시 카메라와 랜드마커를 반드시 dispose)
final authFlowProvider =
    NotifierProvider.autoDispose<AuthFlowController, AuthFlowState>(
      AuthFlowController.new,
    );

import 'dart:async';

import '../core/config.dart';
import '../models/landmark.dart';
import '../services/landmark_source.dart';

/// 캡처 진행 단계. 인증과 등록이 공유한다.
enum CapturePhase {
  /// 대기 중. 시작 버튼을 누를 수 있다.
  idle,

  /// 손을 찾는 중.
  handSearching,

  /// 손이 연속 검출되어 카운트다운 중.
  handReady,

  /// 프레임을 수집하는 중.
  recording,
}

/// "손을 찾고 → 카운트다운하고 → 정해진 시간만큼 프레임을 모으는" 한 번의 캡처.
///
/// 인증(1회)과 등록(5회 반복)이 똑같은 절차를 쓰기 때문에 여기로 뺐다. 상태
/// 머신 전체를 두 컨트롤러에 복사해 두면 타이머 처리 같은 미묘한 부분이 한쪽만
/// 고쳐져서 서서히 어긋난다.
///
/// 이 클래스는 Riverpod을 모른다. 변화는 [onChanged]로 알리고, 판단(재시도할지,
/// 서버로 보낼지)은 전적으로 호출자가 한다.
class CaptureSession {
  final LandmarkSource source;

  /// 표시용 상태가 바뀔 때마다 호출된다.
  final void Function() onChanged;

  /// 수집이 끝났을 때 원본 프레임을 넘긴다. **가공되지 않은 좌표다.**
  final void Function(List<HandFrame> frames) onCaptured;

  /// 손을 놓쳐 처음부터 다시 해야 할 때. 세션은 스스로 handSearching으로 돌아간다.
  final void Function(String notice) onAborted;

  /// 명목 프레임 간격(ms).
  static const double _frameIntervalMs = 1000.0 / kNominalFps;

  /// 지터 허용치. 이보다 적게 비면 연속 검출이 끊긴 것으로 치지 않는다.
  ///
  /// 소스는 손이 있을 때만 프레임을 흘리므로 "사라진 프레임"을 직접 셀 수가
  /// 없다. 그래서 마지막 프레임 이후 흐른 시간을 프레임 수로 환산해서 센다.
  static const int _jitterToleranceFrames = 2;

  static const Duration _watchdogPeriod = Duration(milliseconds: 33);

  /// 진행률 아크 갱신 주기. 60fps까지 갈 이유가 없어 20fps로 둔다.
  static const Duration _progressPeriod = Duration(milliseconds: 50);

  CaptureSession({
    required this.source,
    required this.onChanged,
    required this.onCaptured,
    required this.onAborted,
  });

  // ─── 외부에서 읽는 상태 ──────────────────────────────────────────

  CapturePhase phase = CapturePhase.idle;
  int countdown = kCountdownSeconds;
  double progress = 0.0;

  /// 오버레이에 그릴 최신 프레임. 원본 좌표 그대로다.
  HandFrame? latestFrame;

  // ─── 내부 ──────────────────────────────────────────────────────

  StreamSubscription<HandFrame>? _sub;
  Timer? _watchdog;
  Timer? _countdownTimer;
  Timer? _progressTimer;
  Timer? _recordTimer;

  final List<HandFrame> _buffer = <HandFrame>[];
  final _sinceLastFrame = Stopwatch();
  final _recordClock = Stopwatch();

  int _consecutiveDetected = 0;

  /// 소스를 켜고 프레임 구독을 시작한다. 화면 진입 시 한 번 호출한다.
  Future<void> attach() async {
    if (_sub != null) return;
    _sub = source.frames.listen(_onFrame, onError: _onSourceError);
    _sinceLastFrame
      ..reset()
      ..start();
    _watchdog = Timer.periodic(_watchdogPeriod, (_) => _onWatchdogTick());
    await source.start();
  }

  /// 한 번의 캡처를 시작한다. `idle`에서만 의미가 있다.
  void begin() {
    if (phase != CapturePhase.idle) return;
    _buffer.clear();
    _consecutiveDetected = 0;
    phase = CapturePhase.handSearching;
    progress = 0.0;
    countdown = kCountdownSeconds;
    onChanged();
  }

  /// 진행 중인 캡처를 접고 `idle`로 돌아간다.
  void cancel() {
    _cancelFlowTimers();
    _buffer.clear();
    _consecutiveDetected = 0;
    phase = CapturePhase.idle;
    progress = 0.0;
    countdown = kCountdownSeconds;
    onChanged();
  }

  void dispose() {
    _cancelFlowTimers();
    _watchdog?.cancel();
    _watchdog = null;
    _sub?.cancel();
    _sub = null;
    _sinceLastFrame.stop();
    // 소스 자체의 dispose는 landmarkSourceProvider가 책임진다.
  }

  // ─── 프레임 처리 ────────────────────────────────────────────────

  void _onFrame(HandFrame frame) {
    _sinceLastFrame
      ..reset()
      ..start();
    _consecutiveDetected++;

    // recording 중에만 버퍼에 쌓는다. 다른 단계의 프레임은 오버레이 표시용이다.
    if (phase == CapturePhase.recording && _isFreshForRecording(frame)) {
      _buffer.add(frame);
    }

    latestFrame = frame;

    if (phase == CapturePhase.handSearching &&
        _consecutiveDetected >= kHandReadyFrameThreshold) {
      _enterHandReady();
      return;
    }
    onChanged();
  }

  /// 소스를 켜지 못했을 때(권한 거부, 카메라 점유 등).
  ///
  /// 이걸 흘려보내면 화면이 "손을 찾는 중" 상태로 영원히 멈춰 있고 사용자는
  /// 이유를 알 수 없다. 캡처를 접고 무엇을 해야 하는지 문구로 띄운다.
  void _onSourceError(Object error) {
    _cancelFlowTimers();
    _buffer.clear();
    _consecutiveDetected = 0;
    phase = CapturePhase.idle;
    progress = 0.0;
    countdown = kCountdownSeconds;
    latestFrame = null;
    onChanged();
    onAborted(
      error is LandmarkSourceException
          ? error.message
          : '카메라를 시작하지 못했습니다. 앱을 다시 실행해주세요.',
    );
  }

  /// 녹화 시작 직전에 만들어진 "묵은" 프레임인지 판별한다.
  ///
  /// 소스의 스트림은 비동기라, `resetClock()` 직전에 생성된 프레임이 단계가
  /// recording으로 바뀐 뒤에 도착할 수 있다. 그런 프레임은 리셋 전 시계로 찍힌
  /// tMs(예: 3300ms)를 달고 있어서, 그대로 버퍼에 넣으면 첫 프레임의 타임스탬프가
  /// 통째로 어긋나고 서버 리샘플링이 망가진다.
  ///
  /// 정상 프레임의 tMs는 녹화 경과 시간과 거의 같으므로, 한 프레임 간격 남짓
  /// 이상 앞서 있는 값은 리셋 전 프레임으로 보고 버린다.
  bool _isFreshForRecording(HandFrame frame) {
    return frame.tMs <= _recordClock.elapsedMilliseconds + _frameIntervalMs * 2;
  }

  void _onWatchdogTick() {
    final gapFrames = _sinceLastFrame.elapsedMilliseconds / _frameIntervalMs;

    // 지터 정도로 비었으면 연속 검출이 끊긴 게 아니다.
    if (gapFrames >= _jitterToleranceFrames) {
      _consecutiveDetected = 0;
    }

    // 손을 오래 놓치면 오버레이에 낡은 뼈대가 남으므로 지운다.
    if (gapFrames >= kHandLostFrameThreshold && latestFrame != null) {
      latestFrame = null;
      onChanged();
    }

    switch (phase) {
      case CapturePhase.handReady:
        // 카운트다운 도중 손이 사라지면 다시 찾는 단계로 되돌린다.
        // SPEC은 recording 중 이탈만 명시하지만, 손이 없는 채로 카운트다운이
        // 끝나 빈 수집이 시작되는 것을 막으려면 여기서도 되돌려야 한다.
        if (gapFrames >= kHandLostFrameThreshold) {
          _abort('손이 화면을 벗어났습니다. 손 전체가 원 안에 들어오도록 해주세요.');
        }
      case CapturePhase.recording:
        // 15프레임 이상 연속으로 사라지면 수집을 버리고 처음부터. (SPEC 8.2)
        if (gapFrames >= kHandLostFrameThreshold) {
          _abort('손이 화면을 벗어났습니다. 다시 시도해주세요.');
        }
      case CapturePhase.idle:
      case CapturePhase.handSearching:
        break;
    }
  }

  // ─── 단계 전이 ──────────────────────────────────────────────────

  void _enterHandReady() {
    _countdownTimer?.cancel();
    phase = CapturePhase.handReady;
    countdown = kCountdownSeconds;
    onChanged();

    _countdownTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      final next = countdown - 1;
      if (next <= 0) {
        timer.cancel();
        _enterRecording();
        return;
      }
      countdown = next;
      onChanged();
    });
  }

  void _enterRecording() {
    _buffer.clear();
    // tMs는 "캡처 시작 시점부터의 경과 시간"이므로 여기서 기준점을 다시 잡는다.
    source.resetClock();
    _recordClock
      ..reset()
      ..start();

    phase = CapturePhase.recording;
    progress = 0.0;
    onChanged();

    _progressTimer = Timer.periodic(_progressPeriod, (_) {
      progress =
          (_recordClock.elapsedMilliseconds / kRecordDuration.inMilliseconds)
              .clamp(0.0, 1.0);
      onChanged();
    });

    _recordTimer = Timer(kRecordDuration, _finishRecording);
  }

  void _finishRecording() {
    _cancelFlowTimers();
    final frames = List<HandFrame>.unmodifiable(_buffer);
    _buffer.clear();
    _consecutiveDetected = 0;
    phase = CapturePhase.idle;
    progress = 1.0;
    onChanged();
    onCaptured(frames);
  }

  void _abort(String notice) {
    _cancelFlowTimers();
    _buffer.clear();
    _consecutiveDetected = 0;
    phase = CapturePhase.handSearching;
    progress = 0.0;
    countdown = kCountdownSeconds;
    onChanged();
    onAborted(notice);
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
}

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/config.dart';
import '../models/landmark.dart';
import '../models/verify.dart';
import '../services/api_client.dart';
import 'capture_session.dart';
import 'providers.dart';

/// 인증 화면의 상태. (SPEC 8.2 상태 머신)
///
/// 앞의 네 단계는 [CapturePhase]와 1:1로 대응하고, 뒤의 둘은 서버 왕복 단계다.
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
/// 손을 찾고 수집하는 부분은 [CaptureSession]이 맡고, 이 컨트롤러는 그 결과를
/// 어떻게 처리할지(재시도 안내 / 서버 전송 / 결과 보관)만 결정한다.
///
/// Riverpod 3에서 `StateNotifierProvider`는 `legacy.dart`로 분리된 레거시 API라
/// 지금 쓰면 곧 갈아엎어야 하는 코드가 된다. 그래서 동등한 최신 API인
/// [Notifier]를 쓴다. SPEC 3장의 의도는 "과하게 추상화하지 말 것"이므로
/// 코드 생성 없이 단순한 [NotifierProvider] 하나로 유지한다.
class AuthFlowController extends Notifier<AuthFlowState> {
  late final CaptureSession _session;
  late final ApiClient _api;

  String _userId = '';

  /// 서버 왕복 중인지. 이 동안에는 세션 상태가 아니라 uploading/done을 보여준다.
  AuthPhase? _serverPhase;

  String? _notice;
  VerifyResponse? _response;

  @override
  AuthFlowState build() {
    _api = ref.watch(apiClientProvider);
    _userId = ref.watch(selectedUserProvider);
    _session = CaptureSession(
      source: ref.watch(landmarkSourceProvider),
      onChanged: _syncFromSession,
      onCaptured: _onCaptured,
      onAborted: (notice) {
        _notice = notice;
        _syncFromSession();
      },
    );
    ref.onDispose(_session.dispose);
    return const AuthFlowState();
  }

  /// 화면 진입 시 호출. 소스를 켜고 오버레이를 살린다.
  Future<void> attach() => _session.attach();

  /// 인증 버튼. `idle`에서만 의미가 있다.
  void start() {
    if (state.phase != AuthPhase.idle) return;
    _notice = null;
    _response = null;
    _serverPhase = null;
    _session.begin();
  }

  /// 취소 버튼. 진행 중이던 모든 타이머를 끊고 `idle`로 돌아간다.
  void cancel() {
    _notice = null;
    _response = null;
    _serverPhase = null;
    _session.cancel();
  }

  /// 결과 화면에서 돌아왔을 때 처음 상태로 되돌린다.
  void reset() => cancel();

  /// 세션의 표시용 상태를 그대로 옮겨 담는다.
  void _syncFromSession() {
    final server = _serverPhase;
    state = AuthFlowState(
      phase: server ?? _phaseOf(_session.phase),
      latestFrame: _session.latestFrame,
      countdown: _session.countdown,
      progress: _session.progress,
      response: _response,
      notice: _notice,
    );
  }

  static AuthPhase _phaseOf(CapturePhase p) => switch (p) {
    CapturePhase.idle => AuthPhase.idle,
    CapturePhase.handSearching => AuthPhase.handSearching,
    CapturePhase.handReady => AuthPhase.handReady,
    CapturePhase.recording => AuthPhase.recording,
  };

  void _onCaptured(List<HandFrame> frames) {
    // 프레임이 너무 적으면 서버로 보내지 않고 재시도를 안내한다. (SPEC 8.2)
    if (frames.length < kMinFramesForVerify) {
      _notice = '손 움직임이 충분히 기록되지 않았습니다. '
          '손 전체가 원 안에 보이도록 하고 다시 시도해주세요.';
      _serverPhase = null;
      _syncFromSession();
      return;
    }
    _upload(frames);
  }

  Future<void> _upload(List<HandFrame> frames) async {
    _notice = null;
    _serverPhase = AuthPhase.uploading;
    _syncFromSession();

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
      _response = res;
      _serverPhase = AuthPhase.done;
      _syncFromSession();
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
    _notice = notice;
    _response = null;
    _serverPhase = null;
    _syncFromSession();
  }
}

/// 화면을 벗어나면 컨트롤러와 소스가 함께 정리되도록 autoDispose로 둔다.
/// (SPEC 8.2 — 화면 이탈 시 카메라와 랜드마커를 반드시 dispose)
final authFlowProvider =
    NotifierProvider.autoDispose<AuthFlowController, AuthFlowState>(
      AuthFlowController.new,
    );

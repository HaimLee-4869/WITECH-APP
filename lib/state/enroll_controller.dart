import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/config.dart';
import '../models/api_error.dart';
import '../models/enroll.dart';
import '../models/landmark.dart';
import '../services/api_client.dart';
import '../services/landmark_source.dart';
import 'capture_session.dart';
import 'providers.dart';

/// 등록 화면의 단계. (SPEC 8.4)
///
/// 인증과 달리 같은 제스처를 [kEnrollRepeatCount]회 반복하므로, 회차 사이의
/// 대기 단계([betweenTakes])가 하나 더 있다.
enum EnrollPhase {
  idle,
  handSearching,
  handReady,
  recording,

  /// 한 회차를 마치고 다음 회차를 준비하는 중.
  betweenTakes,

  /// 모든 회차를 서버로 보내는 중.
  uploading,

  /// 등록 완료.
  done,
}

@immutable
class EnrollState {
  final EnrollPhase phase;
  final HandFrame? latestFrame;
  final int countdown;
  final double progress;

  /// 지금까지 성공적으로 수집한 회차 수. 진행 인디케이터(점)에 쓴다.
  final int completedTakes;

  /// 서버가 요구하는 회차 수(`GET /config`의 enrollmentTakes).
  final int requiredTakes;

  /// 등록할 수어 암호.
  final String gestureId;

  /// 서버 응답. [EnrollPhase.done]에서만 채워진다.
  final EnrollResponse? response;

  /// 재시도/오류 안내.
  final String? notice;

  const EnrollState({
    this.phase = EnrollPhase.idle,
    this.latestFrame,
    this.countdown = kCountdownSeconds,
    this.progress = 0.0,
    this.completedTakes = 0,
    this.requiredTakes = kDefaultEnrollTakes,
    this.gestureId = kDefaultGestureId,
    this.response,
    this.notice,
  });

  /// 지금 진행 중인 회차 번호(1-based). 전부 끝났으면 마지막 번호를 유지한다.
  int get currentTake => (completedTakes + 1).clamp(1, requiredTakes);

  /// 안내 문구.
  String get message {
    final n = notice;
    if (n != null) return n;
    return switch (phase) {
      EnrollPhase.idle => completedTakes == 0
          ? '등록할 수어 암호를 준비하고 시작을 누르세요'
          : '$currentTake/$requiredTakes 회차를 시작하려면 계속을 누르세요',
      EnrollPhase.handSearching => '손을 원 안에 위치시켜 주세요',
      EnrollPhase.handReady => '$countdown초 후 시작합니다',
      EnrollPhase.recording => '동작을 수행하세요 ($currentTake/$requiredTakes)',
      EnrollPhase.betweenTakes => '다시 한 번 같은 동작을 해주세요',
      EnrollPhase.uploading => '등록하는 중입니다',
      EnrollPhase.done => '등록이 완료되었습니다',
    };
  }

  bool get canStart => phase == EnrollPhase.idle;

  bool get isRunning =>
      phase == EnrollPhase.handSearching ||
      phase == EnrollPhase.handReady ||
      phase == EnrollPhase.recording ||
      phase == EnrollPhase.betweenTakes;
}

/// 등록 흐름. 같은 제스처를 [kEnrollRepeatCount]회 모아 한 번에 전송한다.
///
/// 손 찾기·카운트다운·수집은 인증과 완전히 같은 절차라 [CaptureSession]을
/// 그대로 쓴다. 이 컨트롤러는 "몇 회차인지"와 "다 모였는지"만 관리한다.
class EnrollController extends Notifier<EnrollState> {
  late final CaptureSession _session;
  late final ApiClient _api;
  late final LandmarkSource _source;

  String _userId = '';
  String _gestureId = kDefaultGestureId;

  /// 서버가 요구하는 회차 수. `GET /config`에서 받는다.
  int _requiredTakes = kDefaultEnrollTakes;

  /// 회차별 수집 결과. 원본 좌표 그대로 보관한다. (SPEC 원칙 A)
  final List<List<HandFrame>> _takes = <List<HandFrame>>[];

  /// 세션 단계로 표현할 수 없는 단계(betweenTakes/uploading/done)를 덮어쓴다.
  EnrollPhase? _overridePhase;

  String? _notice;
  EnrollResponse? _response;
  Timer? _intervalTimer;

  @override
  EnrollState build() {
    _api = ref.watch(apiClientProvider);
    _userId = ref.watch(selectedUserProvider);
    _gestureId = ref.watch(selectedGestureProvider);
    // 등록 회차 수는 서버가 정한다. 앱 상수는 응답 전 기본값일 뿐이다.
    _requiredTakes = ref.watch(
      serverConfigProvider.select((s) => s.config.enrollmentTakes),
    );
    _source = ref.watch(landmarkSourceProvider);
    _session = CaptureSession(
      source: _source,
      onChanged: _sync,
      onCaptured: _onCaptured,
      onAborted: (notice) {
        _notice = notice;
        _sync();
      },
    );
    ref.onDispose(() {
      _intervalTimer?.cancel();
      _session.dispose();
    });
    return EnrollState(requiredTakes: _requiredTakes, gestureId: _gestureId);
  }

  Future<void> attach() => _session.attach();

  /// 시작 / 다음 회차 계속 / 전송 재시도.
  void start() {
    if (state.phase != EnrollPhase.idle) return;
    _notice = null;
    _overridePhase = null;
    // 회차는 다 모았는데 전송만 실패한 경우. 다시 찍게 하지 않고 전송만 재시도한다.
    if (_takes.length >= _requiredTakes) {
      _upload();
      return;
    }
    _session.begin();
  }

  /// 전체 등록을 취소하고 처음부터. 모아 둔 회차도 버린다.
  void cancel() {
    _intervalTimer?.cancel();
    _takes.clear();
    _notice = null;
    _response = null;
    _overridePhase = null;
    _session.cancel();
  }

  void _sync() {
    state = EnrollState(
      phase: _overridePhase ?? _phaseOf(_session.phase),
      latestFrame: _session.latestFrame,
      countdown: _session.countdown,
      progress: _session.progress,
      completedTakes: _takes.length,
      requiredTakes: _requiredTakes,
      gestureId: _gestureId,
      response: _response,
      notice: _notice,
    );
  }

  static EnrollPhase _phaseOf(CapturePhase p) => switch (p) {
    CapturePhase.idle => EnrollPhase.idle,
    CapturePhase.handSearching => EnrollPhase.handSearching,
    CapturePhase.handReady => EnrollPhase.handReady,
    CapturePhase.recording => EnrollPhase.recording,
  };

  void _onCaptured(List<HandFrame> frames) {
    // 회차가 부실하면 그 회차만 다시 받는다. 이미 모은 회차는 버리지 않는다.
    if (frames.length < kMinFramesForVerify) {
      _notice = '이번 회차가 충분히 기록되지 않았습니다. '
          '손 전체가 원 안에 보이도록 하고 다시 시도해주세요.';
      _overridePhase = null;
      _sync();
      return;
    }

    _takes.add(frames);
    _notice = null;

    if (_takes.length >= _requiredTakes) {
      _upload();
      return;
    }

    // 회차 사이의 짧은 확인 시간. 바로 다음 카운트다운이 시작되면 사용자가
    // 손을 내릴 틈이 없어 같은 동작을 반복하기 어렵다. (SPEC 8.4)
    _overridePhase = EnrollPhase.betweenTakes;
    _sync();
    _intervalTimer?.cancel();
    _intervalTimer = Timer(kEnrollInterval, () {
      if (!ref.mounted) return;
      _overridePhase = null;
      _session.begin();
    });
  }

  Future<void> _upload() async {
    _overridePhase = EnrollPhase.uploading;
    _notice = null;
    _sync();

    final camera = _source.imageSize;
    if (camera == null) {
      _fail('카메라 정보를 읽지 못했습니다. 화면을 나갔다가 다시 시도해주세요.');
      return;
    }

    final now = DateTime.now();
    final req = EnrollRequest(
      userId: _userId,
      gestureId: _gestureId,
      camera: camera,
      // 원본 좌표 그대로. 전처리는 서버 책임이다. (SPEC 원칙 A)
      // takeNo는 1..N이 모두 있어야 서버가 받아들인다. (backend/README 4.3)
      takes: <EnrollTake>[
        for (var i = 0; i < _takes.length; i++)
          EnrollTake(
            takeNo: i + 1,
            capturedAt: now,
            nominalFps: kNominalFps,
            durationMs: kRecordDuration.inMilliseconds,
            frames: _takes[i],
          ),
      ],
    );

    try {
      final res = await _api.enroll(req);
      if (!ref.mounted) return;
      _response = res;
      _overridePhase = EnrollPhase.done;
      _sync();
    } on ApiException catch (e) {
      if (!ref.mounted) return;
      // 서버는 회차 하나만 불량해도 전체를 거절하고 아무것도 저장하지 않는다.
      // 어느 회차가 문제인지는 e.takeNo에 담겨 온다. (backend/README 4.3)
      if (e.isRetryableCapture) {
        _takes.clear();
        _fail('${e.userMessage} 처음부터 다시 등록해주세요.');
      } else {
        _fail(e.userMessage);
      }
    } on TimeoutException {
      if (!ref.mounted) return;
      _fail('서버 응답이 없습니다. 네트워크 상태를 확인하고 다시 시도해주세요.');
    } on ApiNotConfiguredException catch (e) {
      if (!ref.mounted) return;
      _fail(e.message);
    } catch (_) {
      if (!ref.mounted) return;
      _fail('등록 요청을 보내지 못했습니다. 잠시 후 다시 시도해주세요.');
    }
  }

  /// 전송에 실패하면 모아 둔 회차는 그대로 두고 재시도만 안내한다.
  /// 5회를 다시 찍게 하는 것은 사용자에게 너무 가혹하다.
  void _fail(String notice) {
    _notice = notice;
    _response = null;
    _overridePhase = null;
    _sync();
  }
}

final enrollProvider =
    NotifierProvider.autoDispose<EnrollController, EnrollState>(
      EnrollController.new,
    );

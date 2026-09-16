import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:signid/core/config.dart';
import 'package:signid/models/camera_info.dart';
import 'package:signid/models/landmark.dart';
import 'package:signid/services/landmark_source.dart';
import 'package:signid/state/capture_session.dart';

/// 캡처 타이밍이 **기기 fps에 좌우되지 않는지** 고정한다.
///
/// 실기기 실측이 13~16fps인데 예전 로직은 프레임 수로 셌다. 명목 30fps 기준
/// "지터 허용 2프레임"(66ms)이 14fps의 정상 간격(71ms)보다 짧아서, 연속 검출
/// 카운터가 매 프레임 초기화돼 handReady가 오지 않거나 들쭉날쭉했다.
class _PacedSource implements LandmarkSource {
  final Duration interval;
  final _controller = StreamController<HandFrame>.broadcast();
  final _clock = Stopwatch();
  Timer? _timer;

  _PacedSource(this.interval);

  @override
  Stream<HandFrame> get frames => _controller.stream;

  @override
  CameraInfo? get imageSize => const CameraInfo(width: 720, height: 1280);

  @override
  LandmarkTransform get transform => const LandmarkTransform();

  @override
  Widget? buildPreview() => null;

  @override
  Future<void> start() async {
    _clock
      ..reset()
      ..start();
    _timer ??= Timer.periodic(interval, (_) => _emit());
  }

  @override
  Future<void> stop() async {
    _timer?.cancel();
    _timer = null;
  }

  /// 손이 사라진 상황: 프레임 공급만 멈춘다.
  void pause() => stop();

  @override
  void resetClock() {
    _clock
      ..reset()
      ..start();
  }

  @override
  void dispose() {
    _timer?.cancel();
    _controller.close();
  }

  void _emit() {
    if (_controller.isClosed) return;
    _controller.add(
      HandFrame(
        tMs: _clock.elapsedMilliseconds,
        landmarks: List<Landmark>.generate(21, (i) => Landmark(0.5, 0.5, 0.0)),
      ),
    );
  }
}

void main() {
  /// 14fps ≈ 71ms 간격. 실기기 실측(25~32프레임 / 2초)에서 나온 값이다.
  const slow = Duration(milliseconds: 71);

  test('14fps에서도 handReady가 kHandReadyDuration 안에 온다', () async {
    final source = _PacedSource(slow);
    addTearDown(source.dispose);

    final phases = <CapturePhase>[];
    late CaptureSession session;
    session = CaptureSession(
      source: source,
      onChanged: () {
        if (phases.isEmpty || phases.last != session.phase) {
          phases.add(session.phase);
        }
      },
      onCaptured: (_) {},
      onAborted: (_) {},
      recordDuration: const Duration(milliseconds: 300),
    );
    addTearDown(session.dispose);

    await session.attach();
    final started = DateTime.now();
    session.begin();

    while (session.phase == CapturePhase.handSearching) {
      if (DateTime.now().difference(started) > const Duration(seconds: 3)) {
        fail('14fps에서 handReady로 넘어가지 못했다 (프레임 수 기준 로직의 증상)');
      }
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }

    final elapsed = DateTime.now().difference(started);
    expect(session.phase, CapturePhase.handReady);
    // 연속 검출 판정 시간 + 워치독/프레임 간격 여유.
    expect(elapsed, lessThan(kHandReadyDuration + const Duration(milliseconds: 500)));
    expect(phases, contains(CapturePhase.handReady));
  });

  test('30fps에서도 같은 시간대에 handReady가 온다 (fps에 좌우되지 않음)', () async {
    final source = _PacedSource(const Duration(milliseconds: 33));
    addTearDown(source.dispose);

    late CaptureSession session;
    session = CaptureSession(
      source: source,
      onChanged: () {},
      onCaptured: (_) {},
      onAborted: (_) {},
      recordDuration: const Duration(milliseconds: 300),
    );
    addTearDown(session.dispose);

    await session.attach();
    final started = DateTime.now();
    session.begin();
    while (session.phase == CapturePhase.handSearching) {
      if (DateTime.now().difference(started) > const Duration(seconds: 3)) {
        fail('30fps에서 handReady로 넘어가지 못했다');
      }
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }
    expect(
      DateTime.now().difference(started),
      lessThan(kHandReadyDuration + const Duration(milliseconds: 500)),
    );
  });

  test('손이 사라지면 kHandLostDuration 뒤에 되돌린다', () async {
    final source = _PacedSource(slow);
    addTearDown(source.dispose);

    String? notice;
    late CaptureSession session;
    session = CaptureSession(
      source: source,
      onChanged: () {},
      onCaptured: (_) {},
      onAborted: (n) => notice = n,
      recordDuration: const Duration(seconds: 5),
    );
    addTearDown(session.dispose);

    await session.attach();
    session.begin();
    while (session.phase == CapturePhase.handSearching) {
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }

    source.pause(); // 손이 화면을 벗어났다
    await Future<void>.delayed(kHandLostDuration + const Duration(milliseconds: 300));

    expect(session.phase, CapturePhase.handSearching);
    expect(notice, isNotNull);
  });

  test('수집 길이는 서버가 준 값을 쓴다', () async {
    final source = _PacedSource(const Duration(milliseconds: 33));
    addTearDown(source.dispose);

    const recordFor = Duration(milliseconds: 600);
    List<HandFrame>? captured;
    late CaptureSession session;
    session = CaptureSession(
      source: source,
      onChanged: () {},
      onCaptured: (f) => captured = f,
      onAborted: (_) {},
      recordDuration: recordFor,
    );
    addTearDown(session.dispose);

    await session.attach();
    session.begin();

    final deadline = DateTime.now().add(const Duration(seconds: 10));
    while (captured == null) {
      if (DateTime.now().isAfter(deadline)) fail('수집이 끝나지 않았다');
      await Future<void>.delayed(const Duration(milliseconds: 50));
    }

    // 마지막 프레임의 tMs가 요청한 길이 근처여야 한다 (앱 상수가 아니라 인자 기준).
    expect(captured!.last.tMs, greaterThan(recordFor.inMilliseconds ~/ 2));
    expect(captured!.last.tMs, lessThanOrEqualTo(recordFor.inMilliseconds + 150));
  });
}

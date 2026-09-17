/// 프레임이 두 번 수집되지 않는지.
///
/// 2026-09-18 실기기 회귀: Challenge를 거친 뒤 인증하면 4초에 119~120프레임이
/// 모였다. Challenge 이전에는 같은 4초에 52~62개였으니 정확히 두 배다.
///
/// **이게 인증을 헐겁게 만든다.** 모델 입력의 절반이 속도 feature인데 같은
/// 프레임이 두 번씩 들어오면 프레임 간 변위가 0이 되어, 손이 거의 안 움직이는
/// 것처럼 보인다. 동작 간 차이도 사람 간 차이도 뭉개진다.
///
/// 원인은 `OnDeviceLandmarkSource.stop()`이 플러그인 구독을 정리하지 않은 것이다.
/// 화면을 옮기며 stop() → start()를 하면 구독이 하나 더 붙어 같은 검출 결과가
/// 두 번 흘렀다.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:signid/models/camera_info.dart';
import 'package:signid/models/landmark.dart';
import 'package:signid/services/landmark_source.dart';
import 'package:signid/state/capture_session.dart';

/// 실기기 플러그인의 문제 상황을 흉내 내는 소스.
///
/// `hand_landmarker`의 검출 스트림은 네이티브 이벤트 채널이라, 구독을 정리하지
/// 않고 다시 `start()`하면 **같은 결과가 구독 수만큼 흘러나온다.**
/// [subscriptions]가 그 개수다.
class RelistenSource implements LandmarkSource {
  final Duration interval;
  final _controller = StreamController<HandFrame>.broadcast();
  final _clock = Stopwatch();
  Timer? _timer;

  /// 정리되지 않고 쌓인 구독 수. 1이면 정상.
  int subscriptions = 0;

  /// [stop]이 구독을 정리하는지. false면 실기기에서 겪은 버그 그대로다.
  final bool stopReleasesSubscription;

  RelistenSource(this.interval, {this.stopReleasesSubscription = true});

  @override
  Stream<HandFrame> get frames => _controller.stream;

  @override
  CameraInfo? get imageSize => const CameraInfo(width: 720, height: 480);

  @override
  LandmarkTransform get transform => const LandmarkTransform();

  @override
  bool get providesDetectionScore => false;

  @override
  Widget? buildPreview() => null;

  @override
  Future<void> start() async {
    subscriptions += 1;
    _clock
      ..reset()
      ..start();
    _timer ??= Timer.periodic(interval, (_) => _emit());
  }

  @override
  Future<void> stop() async {
    if (stopReleasesSubscription) subscriptions = 0;
    _timer?.cancel();
    _timer = null;
    _clock.stop();
  }

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
    final int tMs = _clock.elapsedMilliseconds;
    // 구독이 정리되지 않았으면 같은 검출 결과가 그 수만큼 흘러나온다.
    for (int i = 0; i < subscriptions; i++) {
      _controller.add(HandFrame(
        tMs: tMs,
        landmarks: <Landmark>[
          for (int j = 0; j < 21; j++)
            Landmark(0.5 + j * 0.001 + tMs * 0.00001, 0.5 + j * 0.001, 0.0),
        ],
      ));
    }
  }
}

/// 한 번의 캡처를 끝까지 돌리고 모인 프레임을 돌려준다.
Future<List<HandFrame>> capture(
  RelistenSource source, {
  required Duration record,
}) async {
  final Completer<List<HandFrame>> done = Completer<List<HandFrame>>();
  final CaptureSession session = CaptureSession(
    source: source,
    recordDuration: record,
    onChanged: () {},
    onCaptured: (List<HandFrame> frames) {
      if (!done.isCompleted) done.complete(frames);
    },
    onAborted: (String notice) {
      if (!done.isCompleted) done.completeError(StateError(notice));
    },
  );
  addTearDown(session.dispose);

  await session.attach();
  session.begin();
  // 손 탐색 → 카운트다운 → 녹화가 끝날 때까지.
  return done.future.timeout(const Duration(seconds: 20));
}

void main() {
  const Duration frame = Duration(milliseconds: 66); // 약 15fps (실기기와 비슷)
  const Duration record = Duration(seconds: 4);

  test('구독이 하나면 4초에 프레임이 한 벌만 모인다', () async {
    final RelistenSource source = RelistenSource(frame);
    addTearDown(source.dispose);

    final List<HandFrame> frames = await capture(source, record: record);

    // 4초 / 66ms ≈ 60장. 실기기 실측(52~62)과 같은 범위다.
    expect(frames.length, greaterThan(40));
    expect(frames.length, lessThan(75));
  });

  test('구독이 정리되지 않아도 같은 프레임이 두 번 들어가지 않는다', () async {
    // 실기기 회귀의 재현: Challenge가 stop()했지만 구독이 남고, 인증이 start()해서
    // 구독이 둘이 된다. 고치기 전에는 여기서 119~120장이 모였다.
    final RelistenSource source =
        RelistenSource(frame, stopReleasesSubscription: false);
    addTearDown(source.dispose);

    await source.start(); // Challenge가 켠다
    await source.stop(); // Challenge가 끈다 (구독이 남는다)
    expect(source.subscriptions, 1, reason: '재현 조건이 성립해야 한다');

    final List<HandFrame> frames = await capture(source, record: record);
    expect(source.subscriptions, 2, reason: '인증이 켜서 구독이 둘이 된다');

    // 소스가 두 번 흘려도 수집된 프레임은 한 벌이어야 한다.
    expect(frames.length, lessThan(75),
        reason: '중복이 그대로 들어갔다 (${frames.length}장)');
  });

  test('수집된 tMs는 항상 증가한다', () async {
    // 서버는 tMs가 증가하지 않으면 422 non_monotonic_timestamps로 거절한다.
    // 등록 2회차에서 실제로 났다.
    final RelistenSource source =
        RelistenSource(frame, stopReleasesSubscription: false);
    addTearDown(source.dispose);
    await source.start();
    await source.stop();

    final List<HandFrame> frames = await capture(source, record: record);

    for (int i = 1; i < frames.length; i++) {
      expect(
        frames[i].tMs,
        greaterThan(frames[i - 1].tMs),
        reason: '$i번째에서 tMs가 증가하지 않았다 '
            '(${frames[i - 1].tMs} → ${frames[i].tMs})',
      );
    }
  });

  test('Challenge를 거쳐도 프레임 수가 같다', () async {
    // 사용자가 요청한 재현 조건 그대로.
    final RelistenSource direct = RelistenSource(frame);
    addTearDown(direct.dispose);
    final int withoutChallenge = (await capture(direct, record: record)).length;

    final RelistenSource viaChallenge =
        RelistenSource(frame, stopReleasesSubscription: false);
    addTearDown(viaChallenge.dispose);
    await viaChallenge.start();
    await viaChallenge.stop();
    final int withChallenge =
        (await capture(viaChallenge, record: record)).length;

    // 타이밍 지터로 몇 장 차이는 난다. 두 배가 나면 안 된다.
    expect(
      (withChallenge - withoutChallenge).abs(),
      lessThan(withoutChallenge ~/ 2),
      reason: 'Challenge 없이 $withoutChallenge장, 거쳐서 $withChallenge장',
    );
  });
}

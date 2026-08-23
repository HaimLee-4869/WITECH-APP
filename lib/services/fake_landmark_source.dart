import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/widgets.dart';

import '../models/landmark.dart';
import 'landmark_source.dart';

/// 에뮬레이터·테스트용 가짜 랜드마크 공급자. (SPEC 10장)
///
/// 33ms 간격으로 사인파 기반의 21점 좌표를 생성해 흘린다. 손 모양처럼 보이면
/// 충분하고 해부학적으로 정교할 필요는 없다. 오버레이 렌더링과 상태 머신을
/// 검증하는 것이 목적이다.
class FakeLandmarkSource implements LandmarkSource {
  /// 33ms ≈ 30fps. 실기기 카메라 프레임 간격과 비슷하게 맞췄다.
  static const Duration _tick = Duration(milliseconds: 33);

  /// 이 비율의 프레임에서는 손을 못 찾은 것처럼 아무것도 흘리지 않는다.
  ///
  /// 0이면 `handSearching` 상태가 즉시 지나가버려서 상태 머신을 눈으로 확인할
  /// 수 없다. 아주 낮게 두어 흐름은 진행되되 검색 단계가 보이게 했다.
  static const double _dropoutRate = 0.04;

  final _controller = StreamController<HandFrame>.broadcast();
  final _random = math.Random(42); // 재현 가능하도록 시드 고정
  final _stopwatch = Stopwatch();

  Timer? _timer;
  bool _disposed = false;

  @override
  Stream<HandFrame> get frames => _controller.stream;

  /// Fake 소스는 보여줄 카메라 프리뷰가 없다. 원 안에는 오버레이만 그린다.
  @override
  Widget? buildPreview() => null;

  /// 가짜 좌표는 처음부터 세로 화면 기준으로 만들었으므로 회전·미러가 필요 없다.
  @override
  LandmarkTransform get transform => const LandmarkTransform();

  @override
  Future<void> start() async {
    if (_disposed || _timer != null) return;
    _stopwatch
      ..reset()
      ..start();
    _timer = Timer.periodic(_tick, (_) => _emit());
  }

  @override
  Future<void> stop() async {
    _timer?.cancel();
    _timer = null;
    _stopwatch.stop();
  }

  @override
  void resetClock() {
    _stopwatch
      ..reset()
      ..start();
  }

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    _timer = null;
    _stopwatch.stop();
    _controller.close();
  }

  void _emit() {
    if (_disposed || _controller.isClosed) return;
    if (_random.nextDouble() < _dropoutRate) return; // 손 놓친 프레임 흉내

    // tMs는 Timer 호출 횟수가 아니라 실제 경과 시간에서 읽는다.
    // Timer.periodic은 지연되면 간격이 밀리므로 인덱스×33은 거짓말이 된다.
    // (SPEC 6장 — 균등 간격 가정 금지)
    final tMs = _stopwatch.elapsedMilliseconds;
    _controller.add(
      HandFrame(
        tMs: tMs,
        landmarks: _poseAt(tMs / 1000.0),
        handedness: 'Right',
        score: 0.92 + _random.nextDouble() * 0.06,
      ),
    );
  }

  /// 손목을 기준으로 5개 손가락이 뻗은 기본 자세. (x, y) 정규화 좌표.
  ///
  /// 인덱스는 MediaPipe 표준 순서(0=손목, 1~4 엄지 … 17~20 새끼)를 따른다.
  static const List<List<double>> _restPose = <List<double>>[
    [0.50, 0.88], // 0 wrist
    [0.41, 0.82], [0.35, 0.75], [0.31, 0.69], [0.28, 0.63], // 엄지
    [0.44, 0.62], [0.42, 0.53], [0.41, 0.46], [0.40, 0.40], // 검지
    [0.51, 0.60], [0.51, 0.50], [0.51, 0.43], [0.51, 0.36], // 중지
    [0.58, 0.62], [0.59, 0.52], [0.60, 0.45], [0.61, 0.40], // 약지
    [0.64, 0.66], [0.67, 0.58], [0.69, 0.52], [0.70, 0.47], // 새끼
  ];

  /// 각 랜드마크가 속한 손가락(0=손목, 1=엄지 … 5=새끼)과 마디 순번(0~3).
  ///
  /// 마디 순번이 클수록(= 손끝에 가까울수록) 굽힘 진폭을 크게 줘서 손가락이
  /// 실제로 구부러지는 것처럼 보이게 한다.
  static int _fingerOf(int i) => i == 0 ? 0 : ((i - 1) ~/ 4) + 1;
  static int _jointOf(int i) => i == 0 ? 0 : (i - 1) % 4;

  /// [tSec] 시점의 21점 좌표를 만든다.
  List<Landmark> _poseAt(double tSec) {
    // 손 전체가 좌우로 흔들리는 성분.
    final sway = 0.035 * math.sin(tSec * 1.7);
    // 손 전체가 위아래로 살짝 움직이는 성분.
    final bob = 0.020 * math.sin(tSec * 1.1 + 0.6);

    return List<Landmark>.generate(_restPose.length, (i) {
      final base = _restPose[i];
      final finger = _fingerOf(i);
      final joint = _jointOf(i);

      // 손가락마다 위상을 달리해 순차적으로 굽혔다 펴지는 모양을 만든다.
      final phase = tSec * 2.3 - finger * 0.7;
      final curl = 0.05 * (joint / 3.0) * math.sin(phase);

      final x = base[0] + sway + curl * 0.35;
      // curl이 양수면 손끝이 손목 쪽(아래)으로 내려온다.
      final y = base[1] + bob + curl;

      // z는 손목(0)을 기준으로 한 상대 깊이. 손끝일수록 카메라에 가깝게.
      final z = -0.01 * joint + 0.004 * math.sin(phase + 1.2);

      return Landmark(x.clamp(0.0, 1.0), y.clamp(0.0, 1.0), z);
    });
  }
}

import 'dart:async';

import 'package:camera/camera.dart';
import 'package:flutter/widgets.dart';
import 'package:hand_landmarker/hand_landmarker.dart' as mp;
import 'package:permission_handler/permission_handler.dart';

import '../core/config.dart';
import '../core/hand_connections.dart';
import '../models/landmark.dart';
import 'landmark_source.dart';

/// 실기기용 랜드마크 공급자. 카메라 + MediaPipe(JNI)로 21점을 뽑는다.
///
/// hand_landmarker 3.0.1 기준으로 구현했다. 3.0.0에서 동기 `detect()`가 사라지고
/// `processFrame()`(fire-and-forget) + `landmarkStream`(비동기 수신) 구조로
/// 바뀌었으므로, SPEC에 적힌 API 추정치가 아니라 실제 패키지를 따랐다.
/// (SPEC 0장 — 패키지 쪽을 정답으로 삼는다)
class OnDeviceLandmarkSource implements LandmarkSource {
  /// 인증에는 손 하나만 필요하다. 여러 손을 찾으면 어느 쪽을 쓸지 모호해진다.
  static const int _numHands = 1;

  /// 이보다 낮은 신뢰도의 검출은 플러그인이 버린다.
  static const double _minDetectionConfidence = 0.6;

  final _controller = StreamController<HandFrame>.broadcast();
  final _stopwatch = Stopwatch();

  CameraController? _camera;
  mp.HandLandmarkerPlugin? _plugin;
  StreamSubscription<List<mp.Hand>>? _sub;

  bool _starting = false;
  bool _running = false;
  bool _disposed = false;

  @override
  Stream<HandFrame> get frames => _controller.stream;

  @override
  Future<void> start() async {
    if (_disposed || _running || _starting) return;
    _starting = true;
    try {
      // 권한이 없으면 프레임이 한 장도 안 오는데 원인이 화면에 드러나지 않는다.
      // 그래서 여기서 먼저 요청하고, 거부되면 스트림에 에러로 알린다.
      final status = await Permission.camera.request();
      if (!status.isGranted) {
        _controller.addError(
          const LandmarkSourceException(
            '카메라 권한이 없습니다. 설정 > 앱 > Sign-ID에서 카메라 접근을 허용해주세요.',
          ),
        );
        return;
      }

      final cameras = await availableCameras();
      if (cameras.isEmpty) {
        _controller.addError(
          const LandmarkSourceException(
            '사용할 수 있는 카메라가 없습니다. 카메라가 있는 기기에서 실행해주세요.',
          ),
        );
        return;
      }

      // 인증은 사용자가 화면을 보면서 하므로 전면 카메라를 쓴다. (SPEC 8.2)
      final description = cameras.firstWhere(
        (c) => c.lensDirection == CameraLensDirection.front,
        orElse: () => cameras.first,
      );

      final camera = CameraController(
        description,
        ResolutionPreset.medium,
        enableAudio: false,
        // processFrame()이 Y/U/V 3개 평면을 직접 읽으므로 YUV420이어야 한다.
        // JPEG이나 BGRA로 두면 planes[1] 접근에서 깨진다.
        imageFormatGroup: ImageFormatGroup.yuv420,
      );
      await camera.initialize();
      _camera = camera;

      _plugin = mp.HandLandmarkerPlugin.create(
        numHands: _numHands,
        minHandDetectionConfidence: _minDetectionConfidence,
        delegate: mp.HandLandmarkerDelegate.gpu,
      );

      _sub = _plugin!.landmarkStream.listen(_onHands);

      _stopwatch
        ..reset()
        ..start();
      await camera.startImageStream(_onCameraImage);
      _running = true;
    } on CameraException catch (e) {
      // 다른 앱이 카메라를 점유했거나 초기화에 실패한 경우.
      _controller.addError(
        LandmarkSourceException(
          '카메라를 열 수 없습니다. (${e.code}) '
          '카메라를 쓰는 다른 앱을 종료하고 다시 시도해주세요.',
        ),
      );
    } finally {
      _starting = false;
    }
  }

  @override
  Future<void> stop() async {
    if (!_running) return;
    _running = false;
    _stopwatch.stop();
    final camera = _camera;
    if (camera != null && camera.value.isStreamingImages) {
      await camera.stopImageStream();
    }
  }

  @override
  void resetClock() {
    _stopwatch
      ..reset()
      ..start();
  }

  @override
  void dispose() {
    if (_disposed) return;
    _disposed = true;
    _running = false;
    _stopwatch.stop();
    _sub?.cancel();
    _sub = null;
    // 네이티브 자원 해제 순서가 중요하다. 카메라가 아직 프레임을 밀어넣는
    // 상태에서 landmarker를 먼저 release하면 JNI 쪽에서 터진다.
    _camera?.dispose();
    _camera = null;
    _plugin?.dispose();
    _plugin = null;
    _controller.close();
  }

  @override
  Widget? buildPreview() {
    final camera = _camera;
    if (camera == null || !camera.value.isInitialized) return null;
    // 원 안을 꽉 채우도록 cover로 깐다. HandOverlayPainter의 sourceAspectRatio
    // 계산과 같은 규칙이어야 오버레이가 프리뷰 위에 정확히 겹친다.
    return FittedBox(
      fit: BoxFit.cover,
      child: SizedBox(
        width: camera.value.previewSize?.height ?? 1,
        height: camera.value.previewSize?.width ?? 1,
        child: CameraPreview(camera),
      ),
    );
  }

  @override
  LandmarkTransform get transform {
    final camera = _camera;
    final preview = camera?.value.previewSize;
    return LandmarkTransform(
      // 플러그인의 processFrame()에 sensorOrientation을 넘기면 네이티브 쪽에서
      // 비트맵을 미리 회전시킨 뒤 추론한다. 즉 돌아오는 좌표는 이미 세로 기준이라
      // 여기서 또 돌리면 이중 회전이 된다. 실기기에서 오버레이가 90도 틀어져
      // 보이면 이 값만 조정하면 되고, 화면/페인터 코드는 건드릴 필요가 없다.
      rotationDegrees: 0,
      // 전면 카메라 프리뷰는 거울처럼 보여야 자연스럽다. 표시 전용 반전이며
      // _toHandFrame()이 만드는 전송용 좌표에는 적용하지 않는다. (SPEC 8.2)
      mirror: true,
      // previewSize는 센서 방향 기준(가로)이라 세로 화면에서는 뒤집어 쓴다.
      sourceAspectRatio: preview == null
          ? null
          : preview.height / preview.width,
    );
  }

  void _onCameraImage(CameraImage image) {
    if (_disposed || !_running) return;
    final plugin = _plugin;
    final camera = _camera;
    if (plugin == null || camera == null) return;
    // fire-and-forget. 결과는 landmarkStream으로 따로 돌아온다.
    plugin.processFrame(image, camera.description.sensorOrientation);
  }

  void _onHands(List<mp.Hand> hands) {
    if (_disposed || _controller.isClosed) return;
    if (hands.isEmpty) return; // 손이 없는 프레임은 흘리지 않는다.

    final hand = hands.first;
    if (hand.landmarks.length != kLandmarkCount) return;

    _controller.add(_toHandFrame(hand));
  }

  /// 플러그인 결과 → 앱 모델. **좌표는 손대지 않고 그대로 옮긴다.**
  ///
  /// 정규화·미러링·특징추출을 여기서 하면 서버의 전처리와 어긋난다.
  /// (SPEC 원칙 A)
  HandFrame _toHandFrame(mp.Hand hand) {
    return HandFrame(
      // 실제 도착 시각. 프레임 수 × 33 같은 계산을 쓰지 않는다. (SPEC 6장)
      tMs: _stopwatch.elapsedMilliseconds,
      landmarks: [
        for (final lm in hand.landmarks) Landmark(lm.x, lm.y, lm.z),
      ],
      handedness: kAssumedHandedness,
      // hand_landmarker 3.0.1의 Hand는 신뢰도를 돌려주지 않는다. 다만 플러그인이
      // minHandDetectionConfidence 미만은 걸러내므로, 그 임계값을 "이 값 이상"
      // 이라는 하한으로 기록한다. 정확한 값이 필요하면 플러그인 확장이 필요하다.
      score: _minDetectionConfidence,
    );
  }
}

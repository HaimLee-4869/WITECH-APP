/// MediaPipe에 넣은 이미지의 해상도.
///
/// 백엔드 필수 항목이다. 학습 때 영상 종횡비를 보정했기 때문에 없으면
/// 422 `missing_camera_size`로 거절된다. (backend/README 4.1)
///
/// **프리뷰 크기가 아니라 실제로 검출에 넣은 프레임의 크기**를 담는다.
/// 둘이 다르면 서버의 종횡비 보정이 틀어진다.
class CameraInfo {
  final int width;
  final int height;

  const CameraInfo({required this.width, required this.height});

  Map<String, dynamic> toJson() => <String, dynamic>{
    'width': width,
    'height': height,
  };

  @override
  String toString() => 'CameraInfo(${width}x$height)';
}

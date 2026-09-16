/// 센서 좌표 → 화면 방향 좌표 회전.
///
/// 카메라 센서는 가로(예: 720×480)인데 폰은 세로로 든다. 그래서 MediaPipe가 주는
/// 정규화 좌표는 **화면에서 보이는 방향과 다르다.** 오버레이는 이 회전을 적용해
/// 그리므로 뼈대가 손에 잘 겹치지만, 회전을 빼먹은 쪽은 좌우·상하가 뒤바뀐다.
///
/// **각도는 회전에 불변이고 방향은 아니다.** 그래서 손 모양 판정(FIST/INDEX…)은
/// 회전 없이도 맞지만 이동 방향 판정은 틀린다. 2026-09-18 실기기에서 겪었다:
/// `req=MOVE_UP → axis=x- → label=MOVE_RIGHT` (축비 19배로 확실한데 축만 swap).
/// `challenge_response`도 영상 회전 메타데이터를 안 쓰던 시절 이동 일치율이 0~6%였다.
///
/// 이 규칙이 두 군데에 따로 있으면 또 갈라진다. 오버레이(`HandOverlayPainter`)와
/// 판정 입력(`ChallengeController`)이 **같은 함수**를 쓴다.
library;

/// 정규화 좌표 한 점을 시계방향으로 [degrees]만큼 돌린다.
///
/// 이미지 내용을 돌리는 것이므로, 90도에서 `(x, y) → (1-y, x)`다.
/// 실기기에서 270도가 정확히 겹치는 것을 확인했다
/// (`OnDeviceLandmarkSource.transform` 주석의 실측 기록).
({double x, double y}) rotateNormalizedPoint(double x, double y, int degrees) {
  return switch (degrees % 360) {
    90 => (x: 1.0 - y, y: x),
    180 => (x: 1.0 - x, y: 1.0 - y),
    270 => (x: y, y: 1.0 - x),
    _ => (x: x, y: y),
  };
}

/// 회전 뒤 프레임의 가로·세로.
///
/// 90·270도에서는 가로와 세로가 바뀐다. 종횡비 보정(`toIsotropic`)에 **회전 전**
/// 크기를 그대로 쓰면 각도와 변위가 왜곡된다.
({int width, int height}) rotatedFrameSize(int width, int height, int degrees) {
  final bool quarter = degrees % 180 != 0;
  return quarter ? (width: height, height: width) : (width: width, height: height);
}

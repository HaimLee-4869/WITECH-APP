/// Challenge 안내 문구.
///
/// 사유 코드를 그대로 보여주면 사용자가 무엇을 해야 할지 모른다. 사유마다
/// **다음에 할 행동**이 달라지므로 문구를 나눈다.
library;

import '../challenge/challenge_state_machine.dart';
import '../challenge/hand_action_detector.dart';

/// 실패 사유별 안내.
String challengeFailMessage(FailReason? reason) => switch (reason) {
      FailReason.handNotFound =>
        '손이 보이지 않았습니다. 원 안에 손을 들어 올리고 다시 시도해주세요.',
      FailReason.handLost =>
        '동작 중 손이 화면에서 벗어났습니다. 손을 원 안에 둔 채로 해주세요.',
      FailReason.wrongShape =>
        '요청한 손 모양과 다릅니다. 화면의 그림을 보고 같은 모양을 만들어주세요.',
      FailReason.wrongDirection =>
        '요청한 방향과 다릅니다. 화살표 방향으로 손을 움직여주세요.',
      FailReason.wrongOrder =>
        '동작 순서가 다릅니다. 화면에 표시된 순서대로 하나씩 해주세요.',
      FailReason.actionTimeout =>
        '제한 시간 안에 동작을 완료하지 못했습니다. 조금 더 크고 분명하게 해주세요.',
      FailReason.totalTimeout =>
        '전체 제한 시간이 지났습니다. 처음부터 다시 시도해주세요.',
      FailReason.trackingUnstable =>
        '손 인식이 불안정합니다. 밝은 곳에서 배경이 단순한 쪽을 보고 해주세요.',
      null => '동작을 확인하지 못했습니다. 다시 시도해주세요.',
    };

/// 요청 동작을 사람이 읽는 말로.
String challengeActionLabel(String action) => switch (action) {
      'OPEN_PALM' => '손바닥 펴기',
      'FIST' => '주먹 쥐기',
      'INDEX' => '검지만 펴기',
      'TWO_FINGERS' => '검지와 중지 펴기',
      'MOVE_LEFT' => '왼쪽으로 움직이기',
      'MOVE_RIGHT' => '오른쪽으로 움직이기',
      'MOVE_UP' => '위로 움직이기',
      'MOVE_DOWN' => '아래로 움직이기',
      _ => action,
    };

/// 지금 화면에 띄울 한 줄. 상태에 따라 사용자가 할 일이 다르다.
String challengePrompt(Status status) {
  if (status.awaitingEscape) {
    // 이전 모양 그대로면 판정을 시작하지 않는다. 그 이유를 알려줘야 사용자가
    // "왜 안 넘어가지"에서 멈추지 않는다.
    return '손을 한 번 바꿨다가 다시 해주세요';
  }
  final String? action = status.currentAction;
  if (action == null) return '';
  return challengeActionLabel(action);
}

/// 검출된 손 모양을 디버그 표시용 짧은 말로.
String challengeShapeLabel(String shape) =>
    shape == kUnknownShape ? '—' : challengeActionLabel(shape);

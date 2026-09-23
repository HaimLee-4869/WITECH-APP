/// Challenge 안내 문구.
///
/// 사유 코드를 그대로 보여주면 사용자가 무엇을 해야 할지 모른다. 사유마다
/// **다음에 할 행동**이 달라지므로 문구를 나눈다.
library;

import '../challenge/challenge_state_machine.dart';
import '../challenge/hand_action_detector.dart';

/// 세션이 끊겼을 때의 안내. 연속 촬영이라 손을 빼면 전체가 실패한다.
const String challengeSessionBrokenNotice =
    '인증 도중 손이 화면에서 벗어났습니다.\n'
    '처음부터 끝까지 손을 화면 안에 유지해주세요.';

/// 세션 내내 띄우는 안내. 사람은 통과 표시를 보면 손을 내리게 돼 있다.
const String challengeKeepHandNotice = '인증이 끝날 때까지 손을 화면 안에 유지해주세요';

/// 촬영 구간의 안내. 여기서 손을 내리면 처음부터 다시 해야 한다는 것까지 말한다.
///
/// "유지해주세요"만으로는 왜 유지해야 하는지가 안 보인다. 대가를 알아야
/// 사람이 손을 안 내린다.
const String challengeRecordingKeepHandNotice =
    '손을 내리지 마세요. 내리면 동작 확인부터 다시 합니다';

/// 마지막 단계를 통과하고 촬영으로 넘어가기 직전의 안내.
///
/// 사용자는 여기서 "끝났다"고 생각한다. 실제로는 이제 시작이다.
const String challengeHandOffToCaptureNotice = '손을 그대로 두세요 · 이어서 촬영합니다';

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
      FailReason.sessionBroken =>
        '인증 도중 손이 화면에서 벗어났습니다.\n'
            '처음부터 끝까지 손을 화면 안에 유지해주세요.',
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
  if (status.stepResult != null) {
    // 결과는 원 위 배지가 크게 보여준다. 아래 문구는 조용히 둔다.
    final int? done = status.justPassedStep;
    if (status.stepResult != StepOutcome.pass || done == null) return '';
    // 마지막 단계만 예외다. 여기서 손을 내리면 세션이 끊기는데, 사용자는
    // 동작 확인이 끝났으니 다 끝났다고 생각한다. 그 오해를 여기서 끊는다.
    return done == status.totalSteps - 1
        ? challengeHandOffToCaptureNotice
        : '${done + 1}단계 완료';
  }
  if (status.preparing) {
    // 방금 뭘 했는지 알려주고, 다음 동작을 준비할 시간을 준다.
    final int? done = status.justPassedStep;
    final String head = done == null ? '' : '${done + 1}단계 완료  ·  ';
    final String? next = status.currentAction;
    return next == null ? head : '$head다음: ${challengeActionLabel(next)}';
  }
  if (status.awaitingHand) {
    // 손을 들기 전까지는 제한 시간이 흐르지 않는다. 인증 화면과 같은 문구를 쓴다.
    return '손을 원 안에 위치시켜 주세요';
  }
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

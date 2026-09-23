/// SPEC 완료 기준 중 코드로 확인할 수 있는 항목들.
///
/// 전송 규약(원본 좌표·userId·업로드 실패 안내)은 Challenge와 촬영이 한
/// 세션으로 합쳐지면서 `auth_session_test.dart`로 옮겼다. 여기에는 **상태마다
/// 사용자가 다른 안내를 받는가**만 남긴다. 사유 코드를 그대로 보여주면
/// 사용자는 다음에 무엇을 할지 모른다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:signid/challenge/challenge_state_machine.dart';
import 'package:signid/challenge/movement_detector.dart';
import 'package:signid/models/challenge_messages.dart';
import 'package:signid/state/auth_session_controller.dart';

void main() {
  group('실패 사유마다 다음에 할 행동이 다르다', () {
    test('사유가 모두 서로 다른 문구를 갖는다', () {
      final Set<String> messages = <String>{
        for (final FailReason r in FailReason.values) challengeFailMessage(r),
      };
      expect(messages.length, FailReason.values.length,
          reason: '같은 문구를 쓰는 사유가 있다 = 사용자가 무엇을 고쳐야 할지 모른다');
    });

    test('사유를 모를 때도 빈 화면을 주지 않는다', () {
      expect(challengeFailMessage(null), isNotEmpty);
    });

    test('세션이 끊긴 사유는 손을 유지하라고 말한다', () {
      // 연속 촬영의 핵심 규칙이라 문구가 바뀌어도 이 뜻은 남아야 한다.
      expect(challengeFailMessage(FailReason.sessionBroken),
          contains('손을 화면 안에 유지'));
      expect(challengeSessionBrokenNotice, contains('손을 화면 안에 유지'));
    });
  });

  group('지금 무엇을 해야 하는지 한 줄로 말한다', () {
    Status status({
      ChallengeState state = ChallengeState.action,
      String? action,
      String? escapeFrom,
      StepOutcome? stepResult,
      bool preparing = false,
      int? justPassedStep,
    }) =>
        Status(
          state: state,
          stepIndex: 0,
          currentAction: action,
          detectedShape: '—',
          detectedMove: kNoMove,
          shapeConfidence: 0.0,
          holdProgress: 0.0,
          remainingMs: 3000,
          failReason: null,
          steps: const <StepResult>[],
          moveProbe: null,
          escapeFrom: escapeFrom,
          escapeProgress: escapeFrom == null ? 1.0 : 0.0,
          stepResult: stepResult,
          preparing: preparing,
          justPassedStep: justPassedStep,
        );

    test('손을 기다리는 동안에는 손을 들라고 한다', () {
      expect(challengePrompt(status(state: ChallengeState.waitHand)),
          '손을 원 안에 위치시켜 주세요');
    });

    test('이탈 관문에서는 왜 안 넘어가는지 알려준다', () {
      // 이 문구가 없으면 사용자는 "왜 안 넘어가지"에서 멈춘다.
      expect(challengePrompt(status(escapeFrom: 'FIST')),
          '손을 한 번 바꿨다가 다시 해주세요');
    });

    test('동작 중에는 요청 동작을 사람 말로 보여준다', () {
      expect(challengePrompt(status(action: 'MOVE_LEFT')), '왼쪽으로 움직이기');
      expect(challengeActionLabel('TWO_FINGERS'), '검지와 중지 펴기');
    });

    test('준비 시간에는 방금 결과와 다음 동작을 함께 보여준다', () {
      final String text = challengePrompt(
        status(preparing: true, justPassedStep: 0, action: 'FIST'),
      );
      expect(text, contains('1단계 완료'));
      expect(text, contains('주먹 쥐기'));
    });

    test('마지막 단계 통과는 "끝났다"가 아니라 "손을 그대로 두세요"다', () {
      // 동작 확인이 끝나면 사용자는 다 끝난 줄 알고 손을 내린다. 실제로는
      // 여기서 촬영이 시작되고, 손을 내리면 세션이 끊긴다.
      final Status last = Status(
        state: ChallengeState.action,
        stepIndex: 2,
        currentAction: null,
        detectedShape: '—',
        detectedMove: kNoMove,
        shapeConfidence: 0.0,
        holdProgress: 1.0,
        remainingMs: 0,
        failReason: null,
        steps: <StepResult>[
          StepResult('FIST'),
          StepResult('INDEX'),
          StepResult('MOVE_LEFT'),
        ],
        moveProbe: null,
        escapeFrom: null,
        escapeProgress: 1.0,
        stepResult: StepOutcome.pass,
        justPassedStep: 2,
      );
      expect(challengePrompt(last), challengeHandOffToCaptureNotice);
      expect(challengePrompt(last), contains('이어서 촬영'));
    });

    test('중간 단계 통과는 단계 수를 말한다', () {
      final Status mid = Status(
        state: ChallengeState.action,
        stepIndex: 0,
        currentAction: null,
        detectedShape: '—',
        detectedMove: kNoMove,
        shapeConfidence: 0.0,
        holdProgress: 1.0,
        remainingMs: 0,
        failReason: null,
        steps: <StepResult>[
          StepResult('FIST'),
          StepResult('INDEX'),
          StepResult('MOVE_LEFT'),
        ],
        moveProbe: null,
        escapeFrom: null,
        escapeProgress: 1.0,
        stepResult: StepOutcome.pass,
        justPassedStep: 0,
      );
      expect(challengePrompt(mid), '1단계 완료');
    });

    test('결과 표시 중에는 배지가 말하므로 아래 문구는 조용하다', () {
      expect(challengePrompt(status(stepResult: StepOutcome.fail)), '');
    });
  });

  group('손을 유지해야 하는 구간을 화면이 안다', () {
    test('수집 중에는 항상 유지해야 한다', () {
      const AuthSessionState st =
          AuthSessionState(phase: SessionPhase.recording);
      expect(st.mustKeepHand, isTrue);
      expect(st.finished, isFalse);
    });

    test('손을 기다리는 동안에는 아직 아니다', () {
      final AuthSessionState st = AuthSessionState(
        phase: SessionPhase.challenge,
        status: const Status(
          state: ChallengeState.waitHand,
          stepIndex: 0,
          currentAction: null,
          detectedShape: '—',
          detectedMove: kNoMove,
          shapeConfidence: 0.0,
          holdProgress: 0.0,
          remainingMs: 0,
          failReason: null,
          steps: <StepResult>[],
          moveProbe: null,
          escapeFrom: null,
          escapeProgress: 1.0,
        ),
      );
      expect(st.mustKeepHand, isFalse, reason: '손을 들기도 전에 경고를 띄운다');
    });

    test('끝난 뒤에는 유지할 필요가 없다', () {
      for (final SessionPhase p in <SessionPhase>[
        SessionPhase.done,
        SessionPhase.failed,
        SessionPhase.unavailable,
      ]) {
        expect(AuthSessionState(phase: p).finished, isTrue);
        expect(AuthSessionState(phase: p).mustKeepHand, isFalse);
      }
    });
  });
}

# Challenge–Response 안티스푸핑 프로토타입

수어 제스처 인증의 **replay attack 대응 모듈**. 인증할 때마다 시스템이 무작위 동작
3개(손 모양 2개 + 방향 이동 1개)를 요청하고, 사용자가 제한 시간 안에 수행했는지
규칙 기반으로 판정한다. 딥러닝 학습은 없다. MediaPipe 랜드마크 + 기하 계산 +
상태 머신으로 구현했다.

**모든 임계값은 파일럿 영상 52개의 실측 분포에서 나왔다.** 코드에는 임계값 숫자
리터럴이 없고, `configs/challenge_config.json`의 모든 값에 근거 분포가 `_source`로
적혀 있다. 분포가 겹쳐 도출하지 못한 값은 임의로 채우지 않고 `null` + `_unresolved`로
남겼다.

---

## 1. 설치

Python **3.10 또는 3.11**을 쓴다. (mediapipe 0.10.14는 3.12를 지원하지 않는다.)

```bash
cd challenge_response
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

`mediapipe==0.10.14`와 `numpy<2`는 고정이다. AI팀이 이 버전으로 기존 제스처
데이터를 처리했으므로 버전을 올리면 랜드마크 좌표가 미세하게 달라져 통합할 때
어긋난다.

`configs/paths.json`의 `video_root`를 촬영 영상 위치로 맞춘다.

## 2. 실행 순서

```bash
python scripts/01_extract_landmarks.py          # 영상 -> data/landmarks/*.npz  (--force로 재생성)
python scripts/02_check_mirror.py               # 좌우 반전 확정 -> paths.json에 기록
python scripts/03_analyze_distributions.py      # 분포 측정 -> reports/
python scripts/04_derive_thresholds.py          # 임계값 도출 -> configs/challenge_config.json
python scripts/05_validate_rules.py             # 혼동 행렬 + SPEC 4.11 목표 대비
python scripts/run_challenge.py --participant P01   # 웹캠 실시간 프로토타입
python scripts/06_analyze_sessions.py           # 실시간 세션 집계 + 파일럿 대비 갭
pytest                                          # 합성 랜드마크 기반 단위 테스트
```

**02는 03보다 먼저 반드시 실행해야 한다.** 반전 여부를 모르고 분석하면 좌우 이동
판정이 통째로 뒤집힌다.

`run_challenge.py` 키 조작: `q` 종료, `r` 재시작, `s` 참가자 ID 입력.
성공·실패 영상을 모두 `data/sessions/`에 저장한다. 실패 영상이 규칙 개선의 재료다.

화면 구성:
- 웹캠 영상을 **거울처럼 좌우 반전해** 보여준다. 화면에 보이는 방향으로 움직이면 된다.
- 오른쪽 위 **안내 패널**에 요청 동작을 그림으로 보여준다. 손 모양은 어느 손가락을
  펴야 하는지, 이동은 어느 쪽으로 가야 하는지 화살표로 나온다. 아래쪽 작은 아이콘
  3개는 전체 단계이며 현재 단계가 노란 테두리로 표시된다.
- 손 그림은 MediaPipe 21점 연결 구조로 그린다(`scripts/hand_sketch.py`).
  펴는 손가락은 초록, 접는 손가락은 회색이다.
- 안내 그림은 `SHAPE_PATTERNS`와 config의 `direction_map`에서 직접 만든다. 그림과
  판정 규칙이 어긋날 수 없고, `tests/test_guide_overlay.py`가 이를 검증한다.
- 엄지는 판정에서 빼므로 안내 그림에서도 회색으로만 그린다.
- **이동 단계에서는 왼쪽에 판정 계측 패널이 뜬다.** 두 관문의 현재 값을 그대로
  보여준다. 임계값을 짐작해서 바꾸기 전에 무엇이 막고 있는지부터 눈으로 본다.

```
window       15/15                    O
gate1 disp   0.42 / 0.169  x2.49      O     <- 변위 크기 / 임계값 / 배수
gate2 axis   2.10 / 4.19   x0.50      X     <- 주축비 / 임계값 / 배수
axis         y+   -> NONE                   <- 주축과 부호, 최종 라벨
```

시도가 끝날 때마다 **이번 실행의 사유별 통계**를 화면(결과 화면 왼쪽)과 콘솔에
같이 띄운다. 여러 번 돌린 뒤 무엇이 걸림돌인지 바로 보기 위한 것이다.

```
이번 실행 20회 중 통과 7회 (35%)
  중앙 소요시간 2999ms, 재시도 사용 3회
  실패 사유                  횟수   단계별
  WRONG_SHAPE             7   1단계 5회, 3단계 2회
  HAND_LOST               3   2단계 3회
  ACTION_TIMEOUT          2   3단계 2회
```

사유뿐 아니라 **몇 단계에서 막혔는지**도 센다. 같은 `WRONG_SHAPE`라도 1단계에
몰리면 사용자가 시작 자세를 잡을 시간이 부족한 것이고, 3단계에 몰리면 앞 단계에서
시간을 다 쓴 것이라 원인이 다르다.

통계는 **프로세스 단위**로 쌓인다. `q`로 끄면 초기화되므로, 한 세션에서 연속으로
돌린 뒤 종료 시 나오는 최종 요약을 보면 된다. 개별 시도 기록은 계속
`data/sessions/results.csv`에 누적되므로 나중에 다시 집계할 수 있다.

## 3. config 항목

### `configs/paths.json`
| 항목 | 설명 |
|---|---|
| `video_root` | 파일럿 영상 위치 (저장소 바깥) |
| `landmark_cache` | 랜드마크 `.npz` 캐시 |
| `session_out` | 실시간 세션 영상·랜드마크·결과 CSV |
| `report_out` | 분포 리포트 |
| `mirror_flip` | 참가자별 좌우 반전 여부. **02가 자동 기록한다** |
| `mirror_flip_flicker_ratio` | handedness가 프레임마다 흔들린 비율 |

### `configs/extraction.json`
MediaPipe Hands 설정. 판정 임계값이 아니라 추출 설정이다. SPEC 4.1에 고정.

### `configs/derivation_policy.json`
임계값 자체가 아니라 **"분포에서 임계값을 어떻게 뽑을지"** 를 적은 파일.
04가 이걸 읽어서 config를 만든다.

| 항목 | 설명 |
|---|---|
| `positive_percentile` / `negative_percentile` | 정상 p5를 통과시키고 경계 p95를 거르는 규칙 |
| `separation_margin_ratio` | 틈이 있을 때 임계값을 틈의 몇 지점에 놓을지 (0.5 = 가운데) |
| `motion_edge_trim_windows` | 영상 앞뒤 손 진입/이탈 구간을 몇 윈도우 잘라낼지 |
| `unresolvable_shape_negatives` | 규칙으로 분리 불가 확정된 반례. 다른 임계값 도출 근거에서 제외 |
| `targets` | SPEC 4.11 목표. **채점에만 쓰고 임계값을 정하는 데는 쓰지 않는다** |
| `max_retries`, `coordinate_frame` | 측정으로 정할 수 없는 정책 값. `_source`에 '측정값 아님' 명시 |

### `configs/challenge_config.json` (04가 생성)

| 항목 | 값 | 근거 |
|---|---|---|
| `angle_space` | `image_iso` | 펴짐/접힘 분리폭이 `world`(45.5°)보다 넓음(67.1°) |
| `finger_extended_angle.others` | 132.6° | 펴야 하는 손가락 p5=166.1° / 접어야 하는 손가락 p95=99.0° |
| `finger_extended_angle.thumb` | 145.2° | OPEN_PALM 엄지 p5=151.1° / FIST 엄지 p95=139.3° |
| `shape_hold_frames` | 9 | 손 모양 반례 오검출 연속길이 p95=7.8프레임 +1 |
| `shape_confidence_margin_deg` | 33.5 | 펴짐/접힘 분포 틈 67.1°의 절반 |
| `shape_confidence_min` | **null** | 도출 실패 (아래 5장) |
| `movement.window_ms` | 500 | 획 1회 소요시간 p5=524ms |
| `movement.min_displacement_ratio` | 0.169 | MOVE 영상 p75 변위의 p5=0.280 / NEG_shake p95=0.057 |
| `movement.axis_dominance_ratio` | 4.194 | MOVE 획 주축비 p5=5.34 / NEG_diagonal p95=3.05 |
| `movement.max_duration_ms` | 2000 | 획 1회 소요시간 p95=1915ms |
| `movement.direction_map` | 좌=x−, 우=x+, 상=y−, 하=y+ | 16개 영상의 첫 획 방향 만장일치 |
| `timing.per_action_timeout_ms` | 2500 | 정답 유지까지 걸린 시간·획 시간 p95=2120ms |
| `timing.total_timeout_ms` | 7500 | 단계 시간 × 3 |
| `timing.max_retries` | 1 | **측정값 아님.** 프로토콜 정책 |
| `tracking.max_lost_frames` | 38 | 정상 영상 중간 끊김 p95=9.1 / NEG_exit 중간 끊김 p5=66.9 |
| `tracking.min_detection_score` | 0.857 | 정상 영상 detection_score p5 |
| `coordinate_frame` | `mirrored` | **측정값 아님.** 화면을 보는 사용자 기준으로 판정 (SPEC 4.5) |

`_unresolved`에 값이 있으면 그 항목은 분포가 겹쳐 도출하지 못한 것이다.
`run_challenge.py`가 실행 시 경고를 띄운다.

## 4. 검증 결과 (`05_validate_rules.py`)

SPEC 4.11 목표 10개 중 **9개 달성**.

| 항목 | 측정 | 목표 | |
|---|---|---|---|
| OPEN_PALM 정확 판정 | 99.8% | ≥90% | 달성 |
| FIST 정확 판정 | 99.3% | ≥90% | 달성 |
| INDEX 정확 판정 | 99.8% | ≥90% | 달성 |
| TWO_FINGERS 정확 판정 | 98.1% | ≥90% | 달성 |
| NEG_halffist → OPEN_PALM/FIST | **91.2%** | <5% | **미달** |
| NEG_threefingers → TWO_FINGERS | 0.3% | <5% | 달성 |
| NEG_indexring → TWO_FINGERS | 1.9% | <5% | 달성 |
| MOVE_* 왕복 3회 검출 | 16/16영상 | 전부 | 달성 |
| NEG_shake 이동 검출 | 0회 | 0회 | 달성 |
| NEG_diagonal 단일 방향 확정 | 1.1% | <20% | 달성 |

### 4.1 실기기(웹캠) 확인

`run_challenge.py`를 실제 웹캠으로 돌려 확인했다. 초기 버전은 20회 중 2회만
통과했고, 실패 11건 중 7건이 "손을 든 순간의 모양이 요청과 달라 0.3~0.7초 만에
종료"된 경우였다. 아래 두 가지를 고친 뒤 4회 중 3회 통과했고, 남은 1회는 카메라
앞에 손이 없던 경우(`HAND_NOT_FOUND`)다.

**(1) 단계별 유예 시간.** 틀린 동작을 즉시 실패로 보지 않고
`per_action_timeout_ms`(2500ms)까지 기다린 뒤, 그동안 무엇을 했는지로 사유를
정한다. 사용자가 요청을 읽고 손 모양을 바꿀 시간이 생긴다. `FailReason` 종류는
그대로이고 새 임계값도 만들지 않는다.

| 그동안 한 것 | 사유 |
|---|---|
| 다른 선언된 손 모양을 유지 | `WRONG_SHAPE` |
| 그게 뒤 단계 동작이었음 | `WRONG_ORDER` |
| 요청과 다른 방향으로 이동 | `WRONG_DIRECTION` |
| 아무것도 확정 못 함 | `ACTION_TIMEOUT` |

이동 단계에도 같은 규칙이 필요하다. 왕복 동작 중에는 반대 방향 획이 반드시
지나가므로, 즉시 실패시키면 정상 수행도 통과할 수 없다.

**(2) 좌우 반전 이중 적용 수정.** 아래 5.7 참조.

### 4.2 실시간 세션 집계 (`06_analyze_sessions.py`)

`data/sessions/results.csv`를 읽어 무엇이 병목인지 집계한다.

- 실패 사유별 횟수와 **막힌 단계**
- 요청 동작별 통과율 (어느 동작이 유독 안 되는지)
- **이동 관문별 통과 비율**: 평가된 윈도우 중 1번 관문(변위 크기)을 통과한 비율,
  그중 2번 관문(주축 지배)을 통과한 비율
- 시도 단위 병목: 1번을 한 번도 못 넘은 횟수 / 1번은 넘었지만 2번에서 막힌 횟수
- **파일럿 촬영 vs 실시간 사용 비교**

마지막 항목이 핵심이다. 파일럿 영상은 폰을 거치하고 의식적으로 반듯하게 찍은
것이라 실시간 사용 조건과 다를 수 있다. 이 스크립트는 파일럿 영상에도 실시간과
**같은 윈도우 길이·같은 진입/이탈 제외 규칙·같은 관문 조건**을 적용해 다시 재고,
두 분포를 나란히 놓는다. 갭이 있다면 숫자로 드러난다.

주축비는 최대치와 중앙값을 같이 본다. 부축 변위가 0에 가까운 윈도우 하나가
최대치를 수천 배로 끌어올려 분포 비교에 쓸 수 없기 때문이다. 주축비는 변위
관문을 통과한 윈도우에서만 모은다. 거의 안 움직인 윈도우의 주축비는 잡음이다.

`results.csv`에는 그때의 임계값(`move_min_disp_threshold`,
`move_axis_threshold`, `move_window_ms`)도 같이 적힌다. 나중에 임계값이 바뀌어도
과거 기록을 해석할 수 있다.

## 5. 알려진 한계

### 5.1 `NEG_halffist`를 FIST와 구분하지 못한다 (미해결)

반쯤 쥔 손의 91.2%가 FIST로 판정된다. 목표는 5% 미만이다.

**원인은 임계값 조정으로 해결되지 않는다.** 두 분포가 실제로 겹친다.

| 집단 | p5 | p50 | p95 |
|---|---|---|---|
| FIST 4손가락 관절 각도 | 15.7° | 43.3° | 90.5° |
| NEG_halffist 4손가락 관절 각도 | 46.8° | 83.6° | 137.0° |
| 프레임별 **가장 펴진** 손가락 — FIST | 44.2° | 51.8° | **106.1°** |
| 프레임별 **가장 펴진** 손가락 — halffist | **69.8°** | 96.6° | 143.3° |

프레임 단위로 봐도 **36.3° 겹친다**. 임계값을 훑어본 결과:

| 임계값 | halffist→FIST | halffist→OPEN_PALM | 합계 오검출 |
|---|---|---|---|
| 110° | 64.8% | 12.5% | 77.3% |
| 132.6° (채택) | 86.5% | 4.6% | 91.1% |
| 150° | 98.3% | 0.0% | 98.3% |

임계값을 낮추면 FIST 오인은 줄지만 OPEN_PALM 오인이 늘어 총 오검출은 오히려
나빠진다. **어떤 값에서도 5% 미만이 되지 않는다.**

구조적 이유: FIST 패턴은 네 손가락이 "펴지지 않음"만 요구한다. 반쯤 접힌 손은
정의상 여기에 걸린다.

**엄지를 판정에 넣어도 해결되지 않는다.** 히스토그램에서는 엄지가 갈라 보이지만
참가자별로 보면 겹친다.

| 엄지 각도 | P01 | P05 |
|---|---|---|
| FIST p50 | 120.0° | 76.6° |
| FIST p95 | 157.4° | 99.2° |
| NEG_halffist p5 | 136.4° | 132.3° |

P01은 주먹을 쥘 때 엄지를 펴고 P05는 접는다. 참가자별 최악 기준으로
**틈이 −25.1°** 다. SPEC 4.6이 엄지를 판정에서 뺀 이유가 데이터로 확인됐다.

**현재 판단(수용):** FIST 판정이 관대해지는 것은 보안상 문제가 되지 않는다.
Challenge가 3단계이고 손 모양 2개는 서로 다르게 뽑히므로, 반쯤 쥔 손으로 FIST
단계 하나를 통과해도 나머지 두 단계(다른 손 모양 1개 + 방향 이동 1개)를 통과해야
한다. 특히 이동 단계는 `NEG_shake` 0회·`NEG_diagonal` 1.1%로 방어가 확인됐다.

**해결하려면:** 손끝-손바닥 거리 등 관절 각도 외의 특징을 추가하거나, 이 경계
케이스에 한해 소형 분류기를 쓰는 방향이 필요하다. 규칙 기반만으로는 안 된다.

### 5.2 `shape_confidence_min`을 도출하지 못했다

정답 프레임의 신뢰도 p5=0.811인데 NEG 오검출 프레임의 신뢰도 p95=0.897로 더 높다.
오검출 프레임(주로 `NEG_indexring` 1.9%)은 손가락 상태 자체는 뚜렷하고 조합만
정상 패턴과 겹치는 경우라, 신뢰도로는 걸러낼 수 없다.

`null`로 두었고 상태 머신은 이를 **게이트 없음(0.0)** 으로 해석한다. 임의의 값을
넣지 않았다.

### 5.3 P01 영상의 검출률이 낮다

P05는 26개 전부 100% 검출인데 P01은 26개 중 25개가 95% 미만이다. 특히
`P01_FIST_near` 2.8%, `P01_FIST_far` 2.2%. 프레임을 확인한 결과 손 모양과
프레이밍은 정상이고 **영상이 심하게 뿌옇게 날아간(저대비) 상태**다.

그 결과 FIST 표본 703프레임 중 P01 몫이 163개뿐이라, **FIST 관련 분포는 사실상
P05 한 명의 데이터**다. 참가자 2명은 임계값 일반화에 부족하며, 특히 엄지처럼
개인차가 큰 특징은 더 그렇다.

`dark` 조건의 검출 실패율(6.9%)이 `near`(12.0%)보다 오히려 낮았다. 조명보다
촬영 품질·개인차가 지배적이다.

### 5.4 영상 회전 메타데이터를 반드시 적용해야 한다

파일럿 영상은 컨테이너 회전값을 갖고 있는데(P01=90°, P05=270°) OpenCV는 기본적으로
적용하지 않는다. 끄고 읽으면 손이 옆으로 누운 프레임이 나와 **상하/좌우 이동 축이
통째로 뒤바뀌고** MediaPipe 검출률도 떨어진다. `landmark_io.extract_clip`이
`CAP_PROP_ORIENTATION_AUTO`를 켜고 회전값을 캐시에 기록한다. 다른 기기 영상을
추가할 때 이 값을 반드시 확인할 것.

### 5.5 이동 분석은 영상 앞뒤를 잘라내야 한다

영상 앞뒤에는 손이 화면으로 들어오고 나가는 큰 동작이 들어 있다. 이걸 포함하면
- `NEG_shake`의 변위가 0.04 → 1.64로 뛰어 흔들기와 이동을 구분할 수 없게 되고,
- P01의 `MOVE_LEFT/RIGHT`가 세로축 이동으로 잘못 보인다(축비 1.11~1.65).

첫/마지막 검출에서 1윈도우씩 잘라내면 16개 MOVE 영상 전부가 기대한 축으로
정렬된다(축비 3.09~9.94). 실시간에서는 `WAIT_HAND` 이전과 `HAND_LOST` 이후를
판정하지 않으므로 같은 조건이다.

### 5.7 좌우 반전은 한 번만 적용해야 한다

거울 화면과 `coordinate_frame: "mirrored"`가 겹치면 좌우 판정이 통째로 뒤집힌다.
초기 구현은 뒤집은 프레임을 MediaPipe에 넣고 config의 반전까지 적용해 반전이 두 번
걸렸다. `MOVE_UP/DOWN`은 영향을 받지 않아 상하 이동만 테스트했을 때는 드러나지
않았다.

현재 구현은 이렇게 나눈다.

| | 좌표계 | 이유 |
|---|---|---|
| MediaPipe 입력 | **원본** | handedness가 반대로 나오지 않게 |
| 저장 영상·랜드마크 | **원본** | 파일럿 영상과 같은 좌표계여야 함께 분석 가능 |
| 화면 표시·랜드마크 오버레이 | 거울(x → 1−x) | 사용자가 자연스럽게 인식 |
| 판정 | config의 `coordinate_frame` | 반전은 `movement_detector` 안에서 한 번만 |

안내 화살표 방향은 `guide_overlay.screen_direction()`이 이 계산을 한 곳에서
처리하므로, 화살표와 판정이 항상 같은 방향을 가리킨다.

### 5.8 그 밖에

- `NEG_exit` 영상에서는 손이 빠져나가는 동안 이동이 검출된다. 실시간에서는
  `max_lost_frames`(38프레임) 초과로 `HAND_LOST` 처리되지만, 손이 사라지기 직전의
  움직임이 이동 단계를 통과시킬 여지가 있다.
- 파일럿 영상은 참가자당 동작별 1개뿐이라 백분위 추정이 불안정하다.
- `timing`은 파일럿 영상의 수행 시간에서 뽑았다. 실제 사용자는 요청을 읽고
  반응하는 시간이 추가로 필요하므로 실사용 데이터로 다시 재야 한다.
- `coordinate_frame`은 실시간에서 `mirrored`, 파일럿 영상 검증에서는 `raw`다.
  파일럿 영상은 거울 반전 없이 저장됐기 때문이다.

## 6. 구조

```
core/
  naming.py                 파일명 파싱. NEG를 손모양/이동/추적 반례로 분류
  landmark_io.py            영상 -> 랜드마크, 캐시 입출력, 회전·반전 정렬
  geometry.py               각도·거리·손바닥 중심. 임계값 없음
  features.py               분석과 판정이 공유하는 특징 계산. 임계값 없음
  hand_action_detector.py   손 모양 패턴 매칭
  movement_detector.py      이동 방향 판정
  challenge_generator.py    secrets 기반 무작위 Challenge 생성
  challenge_state_machine.py 순서·시간 관리. UI 프레임워크 의존 없음
scripts/
  guide_overlay.py          요청 동작 안내 패널. 판정 규칙에서 직접 생성
  hand_sketch.py            MediaPipe 21점 구조로 손 뼈대 그리기 (그림 전용)
  challenge_logger.py       세션 결과 저장 + 실행 중 사유별 통계(RunStats)
```

`challenge_state_machine.py`는 순수 파이썬이다(numpy 외 의존 없음). Flutter로
이식할 때 이 클래스가 명세 역할을 한다. 실패 사유는 문자열이 아니라 `FailReason`
enum이며, 어떤 공격이 어느 단계에서 막혔는지 집계할 수 있다.

테스트는 실제 영상 없이 **합성 랜드마크**(`tests/synth.py`)로 돌아간다. 관절 각도를
지정해 손을 만들 수 있으므로 임계값 경계 동작까지 검증한다.

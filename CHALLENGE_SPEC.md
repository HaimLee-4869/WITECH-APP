# Challenge–Response 안티스푸핑 프로토타입 구현 명세

> 수어 제스처 인증 시스템의 **Replay attack 대응 모듈**.
> 인증할 때마다 시스템이 무작위 동작을 요청하고, 사용자가 제한 시간 안에 수행했는지 규칙 기반으로 판정한다.
> 딥러닝 학습은 없다. MediaPipe 랜드마크 + 기하 계산 + 상태 머신으로 구현한다.

---

## 0. 가장 중요한 원칙

**임계값을 추측해서 코드에 박지 말 것.**

이 프로젝트의 핵심은 촬영한 파일럿 영상에서 **실제 분포를 측정해 임계값을 도출**하는 것이다. "손가락 각도 160도 이상이면 펴진 것" 같은 값을 상식으로 정하면 안 된다. 반드시 다음 순서를 지킨다.

```
영상 → 랜드마크 추출 → 동작별 분포 측정 → 분포에서 임계값 도출 → config에 기록
```

특히 `NEG_*` 영상(경계 케이스)이 어디에 분포하는지가 임계값을 결정한다. `NEG_halffist`가 FIST와 OPEN_PALM 사이 어디에 떨어지는지 보고 경계를 긋는 것이지, 그 반대가 아니다.

**모든 임계값은 `configs/challenge_config.json` 한 곳에만 존재한다.** 코드 어디에도 숫자 리터럴이 있으면 안 된다.

---

## 1. 실행 환경

```bash
cd challenge_response
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt`:
```
mediapipe==0.10.14
numpy<2
opencv-python
pandas
matplotlib
pytest
```

**MediaPipe 0.10.14와 numpy<2로 고정한다.** AI팀이 이 버전으로 기존 제스처 데이터를 처리했고, 버전이 다르면 랜드마크 좌표가 미세하게 달라져 나중에 통합할 때 어긋난다. 최신 버전으로 올리지 말 것.

Python은 3.10 또는 3.11을 쓴다. (mediapipe 0.10.14가 3.12를 지원하지 않을 수 있으므로 먼저 확인할 것)

---

## 2. 데이터 위치

영상은 **저장소 바깥**에 있다. 경로는 `configs/paths.json`으로 받는다.

```json
{
  "video_root": "C:/Users/3425e/witech_data",
  "landmark_cache": "./data/landmarks",
  "report_out": "./reports"
}
```

`.gitignore`에 다음을 추가한다.
```
challenge_response/.venv/
challenge_response/data/
challenge_response/reports/
*.mp4
```

랜드마크 캐시(`data/landmarks/*.npz`)는 용량이 작지만 재생성 가능하므로 커밋하지 않는다. 분석 리포트도 마찬가지다.

### 촬영 참가자

파일럿 참가자는 **P01과 P05** 두 명이다. (P02가 아님에 주의)
각자 26개 영상, 총 52개.

### 파일명 규칙

```
{참가자}_{동작}_{조건}_{번호}.mp4

P01_OPEN_PALM_near_01.mp4
P01_MOVE_LEFT_far_01.mp4
P01_NEG_halffist_01.mp4
```

- 동작: `OPEN_PALM` `FIST` `INDEX` `TWO_FINGERS` `MOVE_LEFT` `MOVE_RIGHT` `MOVE_UP` `MOVE_DOWN`
- 조건: `near` `far` `dark`
- NEG: `halffist` `threefingers` `indexring`(또는 `indexpinky`) `shake` `diagonal` `exit`

`NEG_` 영상은 조건 접미사가 없다. 파서는 두 형태를 모두 처리해야 한다.

**파일명이 규칙과 다른 파일이 있으면 조용히 건너뛰지 말고 경고를 출력할 것.** 촬영 실수를 놓치면 안 된다.

---

## 3. 폴더 구조

```
challenge_response/
├── requirements.txt
├── README.md
├── configs/
│   ├── paths.json
│   └── challenge_config.json      # 모든 임계값. 자동 생성 후 수동 조정
├── data/
│   └── landmarks/                 # *.npz 캐시
├── reports/                       # 분포 히스토그램, 요약 CSV
├── core/
│   ├── landmark_io.py             # 영상 → 랜드마크
│   ├── geometry.py                # 각도·거리·정규화 계산
│   ├── hand_action_detector.py    # 손 모양 판정
│   ├── movement_detector.py       # 이동 방향 판정
│   ├── challenge_generator.py     # 무작위 요청 생성
│   ├── challenge_state_machine.py # 순서·시간 관리
│   └── challenge_logger.py        # 결과 저장
├── scripts/
│   ├── 01_extract_landmarks.py
│   ├── 02_check_mirror.py
│   ├── 03_analyze_distributions.py
│   ├── 04_derive_thresholds.py
│   ├── 05_validate_rules.py
│   └── run_challenge.py           # 실시간 프로토타입
└── tests/
    ├── test_geometry.py
    ├── test_hand_actions.py
    ├── test_movements.py
    └── test_state_machine.py
```

---

## 4. 단계별 구현

### 4.1 `01_extract_landmarks.py` — 영상에서 랜드마크 추출

모든 영상을 순회하며 MediaPipe Hands로 21점을 추출해 `data/landmarks/{파일명}.npz`에 저장한다.

저장할 것:
- `landmarks`: shape (프레임수, 21, 3), 정규화 좌표 [0,1]
- `valid_mask`: shape (프레임수,), 손 검출 성공 여부
- `handedness`: 프레임별 "Left"/"Right"
- `detection_score`: 프레임별 신뢰도
- `fps`, `width`, `height`, `duration_ms`
- 메타: `participant`, `action`, `condition`

**손이 검출되지 않은 프레임을 버리지 말 것.** `valid_mask=False`로 남긴다. `NEG_exit` 영상은 의도적으로 손이 사라지는 구간이 있고, 검출 실패율 자체가 분석 대상이다.

이미 캐시가 있으면 건너뛰되 `--force` 옵션으로 재생성할 수 있게 한다.

MediaPipe 설정:
```python
mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5,
)
```

### 4.2 `02_check_mirror.py` — 좌우 반전 확인 (반드시 먼저)

참가자별 `OPEN_PALM_near` 영상의 handedness를 집계한다.

촬영 가이드상 전원이 **오른손, 손바닥이 카메라를 향하게** 찍었다. 따라서:
- handedness가 "Right"로 나오면 → 원본 저장 폰
- "Left"로 나오면 → 좌우 반전 저장 폰

참가자별 판정 결과를 `configs/paths.json`에 기록한다.

```json
"mirror_flip": { "P01": false, "P05": true }
```

`landmark_io.py`가 랜드마크를 읽을 때 이 플래그를 보고 `x → 1-x`로 정렬한다. **이후 모든 분석은 정렬된 좌표를 쓴다.**

두 참가자의 판정이 다르게 나오면 콘솔에 크게 경고를 출력한다. 이걸 놓치면 좌우 이동 판정이 통째로 망가진다.

만약 handedness가 프레임마다 흔들리면 다수결로 정하되, 흔들린 비율을 리포트에 남긴다.

### 4.3 `geometry.py` — 계산 유틸

**손가락 폄/굽힘 판정**

각 손가락에 대해 관절 각도를 계산한다. 검지를 예로 들면 랜드마크 5(MCP)-6(PIP)-8(TIP)의 사잇각이다.

```
finger_joints = {
  "thumb":  (1, 2, 4),
  "index":  (5, 6, 8),
  "middle": (9, 10, 12),
  "ring":   (13, 14, 16),
  "pinky":  (17, 18, 20),
}
```

각도가 크면(펴짐) 180도에 가깝고, 접히면 작아진다. 엄지는 구조가 달라 별도 임계값을 쓴다.

결과는 `[thumb, index, middle, ring, pinky]` 형태의 bool 5개.

**손 크기 정규화**

이동 판정에 쓸 기준 길이. 손목(0)과 중지 MCP(9) 사이 거리를 쓴다. 카메라와의 거리가 달라도 이 값으로 나누면 비교 가능해진다.

```python
hand_scale = dist(landmarks[0], landmarks[9])
```

**손바닥 중심**

```python
palm_center = mean(landmarks[[0, 5, 9, 13, 17]])
```

손가락 끝은 움직임이 커서 중심으로 부적합하다. 손바닥 뼈대만 쓴다.

### 4.4 `03_analyze_distributions.py` — 분포 측정

**여기가 이 프로젝트에서 가장 중요한 스크립트다.**

모든 랜드마크 캐시를 읽어 다음을 측정하고 `reports/`에 히스토그램(PNG)과 요약(CSV)을 남긴다.

**손 모양 관련**
- 동작별 × 손가락별 관절 각도 분포 (near/far/dark 조건별로도 분리)
- `OPEN_PALM` / `FIST` / `NEG_halffist` 세 그룹의 각도 분포를 **한 그래프에 겹쳐서** 그릴 것. 경계가 여기서 눈에 보여야 한다.
- `TWO_FINGERS` / `NEG_threefingers` / `NEG_indexring` 겹쳐 그리기
- 조건별 검출 실패율 (dark가 얼마나 나쁜지)
- 조건별 detection_score 분포

**이동 관련**
- `MOVE_*` 영상의 프레임 간 palm_center 변위 / hand_scale 분포
- 왕복 3회가 실제로 검출되는지 (시간축 궤적 플롯)
- 주축 변위 대 부축 변위의 비율 — `MOVE_LEFT`와 `NEG_diagonal`을 겹쳐 그릴 것
- `NEG_shake`의 변위 크기 (이게 이동으로 오인되면 안 됨)
- near와 far에서 정규화 후 분포가 실제로 겹치는지 검증

**요약 CSV**에는 동작별 각 지표의 평균·표준편차·p5·p25·p50·p75·p95를 남긴다.

### 4.5 `04_derive_thresholds.py` — 임계값 도출

분포 요약에서 임계값을 계산해 `configs/challenge_config.json`을 생성한다.

**도출 원칙**
- 정상 동작(`OPEN_PALM` 등)의 p5를 통과시키고, 경계 케이스(`NEG_halffist` 등)의 p95를 걸러내는 지점을 찾는다.
- 두 분포가 겹쳐서 그런 지점이 없으면 **자동으로 중간값을 넣지 말고 경고를 출력**한다. 그건 규칙만으로 구분이 안 된다는 뜻이고, 사람이 판단해야 한다.
- 각 임계값 옆에 `_source` 필드로 어떤 분포에서 나왔는지 기록한다.

생성될 config 예시(값은 실제 데이터에서 나와야 함):
```json
{
  "finger_extended_angle": {
    "thumb": 150.0,
    "others": 160.0,
    "_source": "OPEN_PALM p5=168.2 / NEG_halffist p95=142.7"
  },
  "shape_hold_frames": 8,
  "shape_confidence_min": 0.6,
  "movement": {
    "min_displacement_ratio": 1.2,
    "axis_dominance_ratio": 2.0,
    "max_duration_ms": 2500,
    "_source": "MOVE_* p5=1.61 / NEG_shake p95=0.34 / NEG_diagonal 주축비 p95=1.42"
  },
  "timing": {
    "per_action_timeout_ms": 4000,
    "total_timeout_ms": 12000,
    "max_retries": 1
  },
  "tracking": {
    "max_lost_frames": 15,
    "min_detection_score": 0.5
  },
  "coordinate_frame": "raw"
}
```

**`axis_dominance_ratio`가 대각선을 거르는 장치다.** 주축 변위가 부축 변위보다 이 배수 이상이어야 방향으로 인정한다.

`coordinate_frame`은 판정을 화면 기준(mirrored)으로 할지 원본 좌표 기준(raw)으로 할지다. **사용자가 화면을 보고 "오른쪽"이라 인식하는 방향과 좌표상 방향이 반대이므로**, 실시간 프로토타입에서는 화면 기준으로 판정해야 자연스럽다. 이 변환을 `movement_detector` 안에 격리하고 config로 제어한다.

### 4.6 `hand_action_detector.py`

입력: 프레임 1개의 랜드마크 (21,3)
출력: `("OPEN_PALM" | "FIST" | "INDEX" | "TWO_FINGERS" | "UNKNOWN", confidence)`

손가락 폄 패턴으로 매칭한다. 엄지는 사람마다 편차가 커서 판정에서 제외한다.

```
[index, middle, ring, pinky]
OPEN_PALM     [T, T, T, T]
FIST          [F, F, F, F]
INDEX         [T, F, F, F]
TWO_FINGERS   [T, T, F, F]
그 외          UNKNOWN
```

`NEG_threefingers`는 [T,T,T,F]라 어디에도 안 걸리고, `NEG_indexring`은 [T,F,T,F]라 역시 안 걸린다. **이 패턴 매칭 방식이 경계 케이스를 자연스럽게 거르는 핵심이다.** 단일 임계값으로 뭉뚱그리면 안 된다.

`confidence`는 각 손가락 각도가 임계값에서 얼마나 떨어져 있는지로 계산한다. 경계에 걸친 애매한 프레임을 걸러내는 데 쓴다.

### 4.7 `movement_detector.py`

입력: 최근 N프레임의 랜드마크 시퀀스
출력: `("MOVE_LEFT" | ... | "NONE", confidence)`

```
1. 각 프레임의 palm_center와 hand_scale 계산
2. 시작점 대비 최대 변위 벡터를 구함
3. 변위를 hand_scale로 나눠 정규화
4. 정규화 변위 크기가 min_displacement_ratio 미만이면 NONE  ← shake 거름
5. |dx|와 |dy| 비율이 axis_dominance_ratio 미만이면 NONE     ← diagonal 거름
6. 주축 부호로 방향 결정
7. coordinate_frame이 "mirrored"면 좌우를 뒤집어 반환
```

### 4.8 `challenge_generator.py`

```python
def generate_challenge() -> list[str]:
    """손 모양 2개 + 방향 이동 1개를 무작위로 뽑아 순서를 섞는다."""
```

- `secrets` 모듈을 쓴다. `random`은 예측 가능해서 보안 용도로 부적합하다.
- 손 모양 2개는 **서로 달라야 한다.** 같은 모양이 연속되면 사용자가 아무것도 안 해도 통과한다.
- 각 Challenge에 `challenge_id`(uuid4)와 생성 시각을 부여한다.

### 4.9 `challenge_state_machine.py`

```
IDLE → WAIT_HAND → ACTION_1 → ACTION_2 → ACTION_3 → PASS
                        ↓          ↓          ↓
                     FAIL(사유)
```

각 ACTION 단계에서:
- 손 모양이면: 해당 모양이 `shape_hold_frames` 연속 유지되어야 통과
- 이동이면: 시작 위치를 기록하고 이동 판정이 성립하면 통과
- `per_action_timeout_ms` 초과 시 실패
- 손이 `max_lost_frames` 이상 연속으로 사라지면 실패

**실패 사유를 반드시 구조화된 값으로 반환한다.** 문자열 메시지가 아니라 enum이다.

```python
class FailReason(Enum):
    HAND_NOT_FOUND
    WRONG_SHAPE
    WRONG_DIRECTION
    WRONG_ORDER
    ACTION_TIMEOUT
    TOTAL_TIMEOUT
    HAND_LOST
    TRACKING_UNSTABLE
```

나중에 어떤 공격이 어느 단계에서 막혔는지 분석해야 하므로 사유 구분이 중요하다.

**Riverpod이나 UI 프레임워크에 의존하지 않는 순수 Python 클래스로 만들 것.** 나중에 Flutter로 이식할 때 이 로직이 명세 역할을 한다.

### 4.10 `run_challenge.py` — 실시간 프로토타입

OpenCV 창에서 웹캠을 띄우고 Challenge를 수행한다.

화면 표시:
- 웹캠 영상 (좌우 반전해서 거울처럼)
- 손 랜드마크 오버레이
- 현재 요청 동작 (텍스트 + 큰 글씨)
- 진행 단계 (1/3, 2/3, 3/3)
- 남은 시간 바
- 현재 검출된 손 모양 (디버깅용)
- 성공/실패 결과와 사유

저장:
- 원본 영상 (`data/sessions/{challenge_id}.mp4`)
- 랜드마크 (`.npz`)
- 결과 CSV 한 줄: challenge_id, 참가자, 요청 동작 3개, 각 단계 통과 여부, 실패 사유, 소요 시간

**성공/실패 영상을 모두 저장한다.** 실패 영상이 규칙 개선의 재료다.

키 조작: `q` 종료, `r` 재시작, `s` 참가자 ID 입력

### 4.11 `05_validate_rules.py` — 규칙 검증

실시간 촬영 없이, 이미 찍은 파일럿 영상으로 판정기가 제대로 동작하는지 확인한다.

```
각 영상에 대해:
  - 손 모양 영상 → 판정 결과가 파일명의 동작과 일치하는 프레임 비율
  - MOVE 영상    → 왕복 3회가 모두 올바른 방향으로 검출되는지
  - NEG 영상     → UNKNOWN 또는 NONE으로 나오는 프레임 비율
```

결과를 혼동 행렬(confusion matrix)로 출력한다. **이게 "되나 안 되나"의 판단 근거다.**

목표 기준(README에 명시):
- 손 모양 4종: 각각 정확 판정 프레임 90% 이상
- `NEG_halffist`: OPEN_PALM/FIST로 판정되는 프레임 5% 미만
- `NEG_threefingers`, `NEG_indexring`: TWO_FINGERS로 판정 5% 미만
- `MOVE_*`: 왕복 3회 중 3회 모두 검출
- `NEG_shake`: 이동 검출 0회
- `NEG_diagonal`: 단일 방향으로 확정 판정되는 비율 20% 미만

### 4.12 테스트

`tests/`에 pytest로 작성한다. 실제 영상 없이 **합성 랜드마크**로 검증한다.

- `test_geometry.py`: 알려진 좌표에서 각도 계산이 맞는지, 손 크기 정규화가 거리 변화에 불변인지
- `test_hand_actions.py`: 각 패턴이 올바른 라벨을 내는지, [T,T,T,F]가 UNKNOWN인지
- `test_movements.py`: 순수 수평 이동이 LEFT/RIGHT로, 45도 대각선이 NONE으로 나오는지, 크기를 2배로 키워도 같은 결과인지
- `test_state_machine.py`: 순서 위반, 타임아웃, 손 소실이 각각 올바른 FailReason을 내는지

---

## 5. 작업 순서

각 단계마다 결과를 확인하고 다음으로 넘어간다.

1. 프로젝트 구조, requirements, config 스켈레톤
2. `landmark_io.py` + `01_extract_landmarks.py` → 52개 영상 처리, 캐시 생성 확인
3. `02_check_mirror.py` → **두 참가자의 반전 여부를 반드시 먼저 확정**
4. `geometry.py` + 테스트
5. `03_analyze_distributions.py` → 리포트 생성. **여기서 멈추고 결과를 보고할 것**
6. `04_derive_thresholds.py` → config 생성
7. `hand_action_detector.py`, `movement_detector.py` + 테스트
8. `05_validate_rules.py` → 혼동 행렬 출력. **여기서 다시 보고**
9. `challenge_generator.py`, `challenge_state_machine.py` + 테스트
10. `challenge_logger.py`, `run_challenge.py`
11. README 작성

5번과 8번 이후에는 반드시 결과를 요약해서 보고한다. 분포가 겹쳐서 규칙으로 구분이 안 되는 경우 그대로 진행하지 말고 보고할 것.

---

## 6. 완료 기준

- [ ] 52개 영상 전부 랜드마크 추출 완료, 실패한 파일 목록 보고
- [ ] 참가자별 좌우 반전 여부 확정 및 config 기록
- [ ] `reports/`에 동작별 분포 히스토그램과 요약 CSV 생성
- [ ] `challenge_config.json`의 모든 임계값에 `_source` 근거 기재
- [ ] 코드에 임계값 숫자 리터럴이 없음
- [ ] `05_validate_rules.py` 혼동 행렬 출력, 4.11의 목표 기준 대비 달성 여부 표기
- [ ] `pytest` 전부 통과
- [ ] `run_challenge.py`가 웹캠으로 실제 동작 (실행 불가 환경이면 그 사실을 명시)
- [ ] README에 실행 순서, config 항목 설명, 알려진 한계 기재

---

## 7. 하지 말 것

- 임계값을 상식이나 추측으로 정하지 말 것. 반드시 분포에서 도출
- MediaPipe나 numpy 버전을 올리지 말 것
- 영상 파일을 git에 커밋하지 말 것
- 검출 실패 프레임을 조용히 버리지 말 것
- Flutter/Dart 코드를 건드리지 말 것 (이번 작업 범위 밖)
- 딥러닝 모델을 학습시키지 말 것 (규칙 기반으로 충분한지 먼저 확인하는 단계)
- 분포가 겹쳐 구분이 안 되는데도 임의의 중간값으로 채우고 넘어가지 말 것

# ⚠️ 현재 `ai/`는 스텁이다

`encoder.py`, `features.py`는 AI팀 `ai_release/`가 오기 전까지 쓰는 **가짜 구현**이다.

| | 스텁 | 실제 (명세 1장) |
|---|---|---|
| `MODEL_VERSION` | `stub-v0` | `handonly-supcon-v1.0.0` |
| `GESTURE_MODEL_VERSION` | `stub-gesture-v0` | `handonly-gesture-1dcnn-v1.0.0` |
| 임베딩 | 입력 해시로 만든 128차원 난수, L2 정규화 | 학습된 인코더 출력 |
| 제스처 분류 | 입력 해시로 G1~G5 중 하나, 신뢰도 0.90 고정 | 1D-CNN 분류기 |
| 거절 조건 | 명세 1장 6종 구현 | 동일 |

## 스텁으로 검증되는 것 / 안 되는 것

- 된다: 등록 → 템플릿 → 인증 흐름, threshold 전환, 재색인, 422 변환
- 안 된다: 실제 사람의 동작이 통과하는지. 스텁에서는 **바이트 단위로 같은 입력**만
  유사도 1.0이 나오고, 조금이라도 다르면 무관한 벡터가 된다.

## 교체 시 확인할 가정

백엔드는 AI 모듈에 아래 형태의 dict 하나를 `frames` 인자로 넘긴다.
실제 모듈의 입력 형태가 다르면 **`app/services/ai_gateway.py`의 `to_ai_input()`만** 고친다.

```python
{
  "camera": {"width": 720, "height": 1280},
  "frames": [{"tMs": 0, "lm": [[x, y, z], ...], "handedness": "Right", "score": 0.98}, ...]
}
```

`InvalidSequenceError`에 `reason` 속성이 없으면 백엔드는 메시지 문구로 사유 코드를
추정한다. 추정이 틀리면 `ai_gateway.py`의 `_REASON_PATTERNS`를 맞춘다.

교체 절차는 `backend/README.md`의 "ai_release 교체 절차"를 따른다.

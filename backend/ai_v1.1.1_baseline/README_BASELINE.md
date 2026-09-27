# ⚠️ baseline — 사용하지 않는 이전 릴리스

`shared-dual-head-v1.1.1` (코드 상수 `MODEL_VERSION`은 `shared-dual-head-v1.1.0`).
2026-09-17 ~ 2026-09-27에 운영했고, **2026-09-27에 `witeck-mobile-shared-dual-head-g1g24-v1.0.0`으로 교체**했다.

여기 있는 코드는 **어디에서도 import되지 않는다.** 백엔드는 `backend/ai/`만 쓴다.
비교·되돌리기 용도로만 남겨 둔다. 파일은 교체 직전 `backend/ai/`를 그대로 복사했다.

| | baseline (여기) | 현재 `backend/ai/` |
|---|---|---|
| 학습 제스처 | G1~G5 | G1~G24 |
| 공개 API | `embed_user` / `embed_gesture` / `embed_both`(dict) | `embed` / `embed_batch` → **(gesture, user) 튜플** |
| duration 입력 | 첫~끝 `tMs` 간격 + 중앙값 한 칸 | `totalFrames / fps` (백엔드가 `durationMs`·`nominalFps`로 채운다) |
| 거절 조건 | 8종 (750ms·프레임 수·tMs 순서·왼손 포함) | 유효 프레임·카메라 크기·21×3·NaN·tMs 중복만. 나머지는 `ai_gateway`가 막는다 |
| 왼손 | 거절 (`wrong_hand`) | handedness가 있으면 오른손으로 미러링해 받는다 |
| Tg / Tu (default) | 0.9020 / 0.3424 | 0.9374 / 0.8244 |
| 가중치 | `shared_dual_head_v1.pt` | `shared_dual_head.pt` |
| 신규 사용자 Same-Gesture FAR | 17.34% | 23.98% |
| 신규 사용자 Genuine FRR | 28.04% | 11.67% |

(두 릴리스의 성능 수치는 평가 조건이 달라 직접 비교할 수 없다. 각 README·calibration_report 참고.)

## 되돌려야 한다면

1. `backend/ai/`를 치우고 이 폴더를 `backend/ai/`로 복사 (`README_BASELINE.md`는 빼도 된다)
2. 백엔드 코드는 새 API 기준이라 그대로는 동작하지 않는다.
   `git log`에서 "witeck-mobile-shared-dual-head-g1g24-v1.0.0" 교체 커밋 이전으로 되돌려야 한다.
3. 등록 원본이 남아 있으므로 `POST /admin/reindex`(`modelVersion: shared-dual-head-v1.1.0`)로
   이 버전의 템플릿을 다시 만든다. 옛 버전 templates는 지우지 않았으므로 그대로 남아 있을 수도 있다.

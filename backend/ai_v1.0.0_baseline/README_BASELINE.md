# ⚠️ baseline — 사용하지 않는 이전 릴리스

`handonly-supcon-v1.0.0` (인증) + `handonly-gesture-1dcnn-v1.0.0` (제스처 분류).
2026-09-16 ~ 2026-09-17에 운영했고, **2026-09-17에 `shared-dual-head-v1.1.1`로 교체**했다.

여기 있는 코드는 **어디에서도 import되지 않는다.** 백엔드는 `backend/ai/`만 쓴다.
비교·되돌리기 용도로만 남겨 둔다.

| | baseline (여기) | 현재 `backend/ai/` |
|---|---|---|
| 구조 | 인증 인코더 + 제스처 분류기(2모델) | 공유 인코더 + user/gesture 임베딩 헤드(1모델) |
| 제스처 판정 | `classify_gesture()` G1~G5 닫힌 집합 | gesture 임베딩 × 템플릿 코사인 (Tg) |
| 판정 규칙 | user 유사도 ≥ threshold | `gesture ≥ Tg AND user ≥ Tu` |
| 가중치 | `auth_handonly_supcon_v1.pt`, `gesture_handonly_1dcnn_v1.pt` | `shared_dual_head_v1.pt` |
| 신규 사용자(P08~P10) | FRR 40.54% / FAR 7.16% | FRR 28.04% / 종합 FAR 3.22% |

## 되돌려야 한다면

1. `backend/ai/`를 새 릴리스 폴더로 치우고 이 폴더를 `backend/ai/`로 복사
2. 백엔드 코드는 dual-head 기준이라 그대로는 동작하지 않는다.
   `git log`에서 "v1.1.1 Shared Dual Encoder 적용" 커밋 이전으로 되돌려야 한다.
3. **벡터 공간이 다르므로 등록도 전부 다시 받아야 한다** (재색인으로는 해결되지 않는다).

## 왜 교체했나

이 baseline은 인증 판정에 **user 임베딩만** 썼다. 제스처 분류기는 닫힌 집합(G1~G5)이라
판정에서 빼고 기록만 했다. 그 결과 **본인이 등록과 다른 동작을 해도 통과했다.**
2026-09-17 실기기 테스트에서 본인의 다른 동작이 0.81~0.99로 전부 통과했고,
이는 AI팀이 보고한 "본인 + 다른 제스처 58.70% 통과"의 재현이다.

dual-head는 gesture 임베딩을 따로 내고 `Tg`로 거른다. 그것이 교체 이유다.

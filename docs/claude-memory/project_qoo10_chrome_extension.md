---
name: Qoo10 R-8 크롬 확장 (qoo10-helper-extension)
description: 2026-05-02 R-8 — naver_fetch_v2 깨진 상태 해결. 메인 Chrome 1개 + JSON-LD/__PRELOADED_STATE__ page-world dump
type: project
originSessionId: 9510c84c-1b7a-4a0a-a4b1-b2b30e3a2ebb
---
**2026-05-02 구축.** 5/2 Phase 0 검증에서 `naver_fetch_v2` 가 5/5 모두 "Naver 로그인 redirect" 로 실패하는 것 발견 — `naver_session_check` (디스크 검사) 와 `naver_fetch_v2` (메인 Chrome 9222 attach) 가 **다른 프로필** 봄. 그 모순을 해소하려 사장님이 설계서(`CHROME_EXTENSION_DESIGN.md`) 작성 → R-8.

## 위치
- 확장: `C:\Users\Admin\qoo10-keyword-extractor\qoo10-helper-extension\`
- backend 클라이언트: `backend/app/services/ext_client.py`
- backend API: `backend/app/api/extension.py` (`/api/ext/queue`, `/api/ext/queue/next`, `/api/ext/result`, `/api/ext/queue/complete`, `/api/ext/status`, `/api/ext/queue/{id}` DELETE, `/api/ext/queue/clear`)

## 흐름
```
backend ─POST /api/ext/queue──▶ in-memory 큐
확장 ─GET /api/ext/queue/next──▶ pending job 1건 (in_progress 전환, FIFO)
확장 ─chrome.tabs.create({active:true}) → page world dump (JSON-LD + __PRELOADED_STATE__ polling) →
       content.js 명시 inject (DOM detail 이미지 휴리스틱) → POST /api/ext/result
확장 ─POST /api/ext/queue/complete──▶ 작업 완료 보고
backend (ext_client) ─GET /api/ext/status?job_id──▶ polling 으로 결과 수신 → naver_fetch_v2 호환 dict 변환
```

## 핵심 결정 (설계서 v1.0 → v1.1 보정)

1. **alarms 1분** (V3 minPeriod 제한). 5초 폴링 불가. 즉시 트리거는 popup [즉시 폴링] 버튼.
2. **content_scripts 자동 주입 X** — `chrome.scripting.executeScript({files})` 으로 명시 주입 (사장님 평소 탭 오염 방지).
3. **`world: "MAIN"` page world dump** 으로 isolated world 우회. `window.__PRELOADED_STATE__` 추출.
4. **active tab 필수** — 백그라운드 탭은 SPA hydration 진행 안 됨. `chrome.tabs.create({active: true})` + 작업 후 원래 탭 복원. 사장님 화면 ~10초 깜빡임 (사장님 OK).
5. **Page world polling** — `isFilled()` (옵션/배송까지) → `isMinimallyFilled()` (name/price 만) 2단계. max 25 attempts × 800ms.
6. **Naver redux store keyed-by-ID 패턴**: `ps.product = {"A": {진짜}}`. `unwrap(sub) = Object.values(sub)[0]`.
7. **셀렉터 의존 0** — JSON-LD + `__PRELOADED_STATE__` 가 1·2순위. detail_images 만 DOM (모든 `<img>` 중 600x400+ + 페이지 위치 0.18~0.95 + exclude 패턴 휴리스틱).
8. **brand 폴백 3단계**: JSON-LD.brand → `__PRELOADED_STATE__.channel.channelName` → `page_title` 의 콜론 뒤 ("제품명 : 셀러명").
9. **SW keepalive** — 작업 중에만 `setInterval` 25초 + `chrome.storage.session.set({heartbeat})` (no-op getPlatformInfo 는 효과 없음).

## 운영

### 설치 (1회)
1. `chrome://extensions` → 개발자 모드 ON
2. "압축해제된 확장 프로그램 로드" → `qoo10-helper-extension/` 선택
3. 핀 고정. 사장님 메인 Chrome 에 네이버 로그인 유지

### 코드 변경 후
`chrome://extensions` → Qoo10 Helper **OFF → ON 토글** (새로고침 ↻ 만으론 SW 안 reload — 토글이 확실)

### 일상
- 시트 [URL 재생성] 클릭 → backend `_do_regenerate` 가 `ext_client.fetch_one` 경유
- popup [즉시 폴링] 누르면 즉시 처리. 안 누르면 1분 alarm 자동
- 사장님 메인 Chrome 켜둠 필수 (Phase 0 (b) 검증)

## 검증 결과 (5/2)

| 단계 | 추출 성공 | 비고 |
|---|---|---|
| Phase 0 backend `naver_fetch_v2` | 0/5 | Naver 세션 false negative |
| Phase 1 background tab | 0/5 | hydration 안 됨 |
| Phase 1 active+polling | **6/8 필드 100%** | name/brand/price/cover/category/detail_images |
| Phase 2 시트 [URL 재생성] e2e | ✓ | 사장님 검증 완료 |

**미해결**: options / shipping — Naver SPA 가 client-side fetch 후 채우는 sub-store. polling 20초로도 안 잡힘. **현재 시트 수동 입력 흐름과 정합되어 미시급**. 해결책: Naver smartstore API 직접 호출 (DevTools network 분석 1~3시간).

## 환경변수

```env
EXT_USE_EXTENSION=true       # 기본. false 시 레거시 naver_fetch_v2 흐름 (롤백)
```

`ext_client.fetch_one` 의 default config:
```python
DEFAULT_CONFIG = {
    "active_tab": True,
    "extract_detail_images": True,
    "max_detail_images": 15,
    "settle_ms": 10000,        # legacy — 현재는 page world polling 안 통합되어 무관
    "delay_min_ms": 1000,
    "delay_max_ms": 1500,
}
```

## 정리 안 한 (Phase 5 추후)
- `naver_fetch_v2.py` 삭제 (env 토글로 fallback 보존 중)
- `naver_session_check.py` 삭제
- `data/naver-browser-profile/` 폴더
- `automation/launch_chrome_debug.bat` (큐텐 STEP 3 / 쿠팡 captcha 용 유지)
- `Qoo10ChromeDebug` 스케줄러 task

R-8 며칠 운영 검증 후 정리.

## 다음 (Phase 3+)

- Phase 3: `daily_workflow.py` STEP 5 한국 상세 수집을 `ext_client` 경유로 변경 (full mode 복귀 시)
- Phase 4: 며칠 두고 셀렉터 깨짐 빈도 + 화면 깜빡임 수용도 측정
- options/shipping 자동화: Naver smartstore API 직접 호출 (필요 시)

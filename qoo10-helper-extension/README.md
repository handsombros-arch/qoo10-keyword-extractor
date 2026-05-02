# Qoo10 Helper — 크롬 확장

네이버 스마트스토어 / 브랜드스토어 상세를 사장님 메인 Chrome 세션으로 직접 수집하기 위한 확장.
백엔드(`localhost:8000`)에 5초 단위로 작업을 폴링하고, 백그라운드 탭에서 추출 후 결과를 전송한다.

## 설치 (1회)

1. Chrome → `chrome://extensions`
2. 우상단 **개발자 모드** ON
3. **압축해제된 확장 프로그램을 로드합니다** → 이 폴더(`qoo10-helper-extension/`) 선택
4. 확장 아이콘 핀 고정 권장

## 작동 흐름

```
백엔드 → /api/ext/queue            (URL 배열 등록)
크롬 확장 → /api/ext/queue/next    (1분 alarms + 사용자 트리거 폴링)
            ↓
            chrome.tabs.create({ active: false })
            chrome.scripting.executeScript (content-scripts/* 명시 주입)
            ↓
            content.js: JSON-LD → __NEXT_DATA__ → DOM 폴백
            ↓
            sendMessage → background → POST /api/ext/result
            ↓
            tab.remove + 3~5초 랜덤 딜레이 → 다음
```

## 필수 조건

- 사장님 메인 Chrome 에 **네이버 로그인 유지** (그것이 기존 9222 + naver-browser-profile 조합을 대체하는 이유)
- 백엔드(`start.pyw`) 실행 중

## 현재 지원 도메인

- `smartstore.naver.com/*/products/*`
- `brand.naver.com/*/products/*`

다른 도메인(쿠팡, 11st, 큐텐 등)은 별도 content-script 추가 시 확장 가능.

## 개발

코드 변경 후 `chrome://extensions` → Qoo10 Helper → 새로고침 아이콘(↻).

### 폴링 주기

- production: `chrome.alarms.create({ periodInMinutes: 1 })` — V3 minPeriod 1분 제한
- 작업 중에는 `setInterval` keepalive 25초 주기 → SW 30초 자동종료 회피
- 즉시 트리거가 필요할 때는 popup 의 [즉시 폴링] 버튼 또는 백엔드가 `/api/ext/queue` 등록 후 1분 대기 OK

### 셀렉터 의존도

핵심 추출은 **JSON-LD (`<script type="application/ld+json">`) + `__NEXT_DATA__` 페이로드** 기반이다. 네이버 빌드의 클래스명 난독화 영향이 거의 없다. DOM querySelector 는 상세 이미지 폴백에만 사용한다.

## 디버깅

- `chrome://extensions` → Qoo10 Helper → 서비스 워커 보기 → background console
- popup 우클릭 → 검사 → popup console
- 백그라운드 탭이 자동으로 닫히지 않으면 `chrome.tabs` 권한 점검

## 변경 이력

- v0.1.0 (2026-05-02): Phase 1 — 골격 + 네이버 스마트스토어 JSON-LD 추출.

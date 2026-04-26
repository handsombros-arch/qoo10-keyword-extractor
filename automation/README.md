# 야간 자동화 (`automation/`)

퇴근 전 한 번 실행하면 트렌드 키워드 수집부터 추천 후보 산출까지 3~4시간 동안 알아서 돌고, 완료/에러를 텔레그램으로 알리는 시스템.

## 동작 흐름

```
START (예: 19:00)
   │
   ├─ 1. /api/auth/status 헬스체크
   ├─ 2. /api/auth/status 로그인 확인 (실패 시 🔐 알림 후 종료)
   ├─ 3. /api/keywords/trend (전체 카테고리, translate+상품수+비딩)
   │      └─ /api/tasks/{id} 폴링으로 완료 대기 (~2시간)
   ├─ 4. /api/keywords/auto-filter (임계값 통과 키워드만)
   │      └─ 0개면 ⚠️ 알림 후 종료
   ├─ 5. /api/recommendations/collect (큐텐+쿠팡+네이버, 후보별)
   │      └─ /api/tasks/{id} 폴링으로 완료 대기 (~1시간)
   └─ 6. /api/recommend/auto-build → user_data 테이블 저장
          └─ ✅ 완료 알림
```

알림은 **시작/필터0건/CAPTCHA/에러/완료** 5건 이내. 단계별 알림은 보내지 않음 (피로 방지).

## 설치

백엔드와 같은 Python 환경에서 실행한다. `httpx`, `python-dotenv` 는 backend 의존성에 이미 있어 추가 설치 보통 불필요.

```cmd
cd C:\Users\Admin\qoo10-keyword-extractor

REM automation/.env 파일 생성
copy automation\.env.example automation\.env
REM → .env 열어서 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 채우기
```

만약 venv를 쓴다면 그 venv를 먼저 활성화 (`backend\.venv\Scripts\activate`).
venv 없이 시스템 Python으로 백엔드를 돌리고 있다면 바로 `python` 으로 실행하면 됨.

`ModuleNotFoundError` 가 뜨면:
```cmd
pip install httpx python-dotenv
```

## 텔레그램 봇 만드는 법

1. 텔레그램에서 **@BotFather** 검색 → `/newbot` → 봇 이름·아이디 입력 → **봇 토큰** 발급 (예: `1234:ABCDEFGH...`)
2. 만든 봇과 대화 시작 → 아무 메시지 한 번 보냄 (`/start`)
3. 다음 URL 브라우저로 접속 → `chat.id` 값을 복사
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
4. `automation/.env` 에 두 값 입력:
   ```
   TELEGRAM_BOT_TOKEN=1234:ABCDEFGH...
   TELEGRAM_CHAT_ID=123456789
   ```

## dry-run (반드시 먼저 한 번)

> **처음 운영 전 반드시 `--dry-run` 으로 한 번 테스트.**
> POST 호출은 모킹되고, GET (헬스체크/태스크 조회)만 실제 실행되어 흐름·로깅·텔레그램 알림이 정상 동작하는지 검증한다.

```cmd
cd C:\Users\Admin\qoo10-keyword-extractor
python automation\daily_workflow.py --dry-run
```

확인할 것:
- 텔레그램에 `[DRY RUN] ▶️ 야간 자동화 시작...` 메시지 도착
- 콘솔과 `logs/automation_YYYYMMDD.log` 에 `[DRY RUN] would call POST ...` 라인이 단계마다 출력
- 마지막에 `[DRY RUN] ✅ 야간 자동화 완료` 메시지 도착

dry-run 도 **백엔드는 켜져 있어야** 한다 (`/api/auth/status` GET을 실제로 한 번 친다).

## 실제 실행

```cmd
cd C:\Users\Admin\qoo10-keyword-extractor
python automation\daily_workflow.py
```

- 백엔드는 미리 `start.pyw` 로 켜져 있어야 함
- 큐텐에 로그인된 상태여야 함 (쿠키 만료 시 캡차 알림 후 종료)

## 환경변수 (`automation/.env`)

| 키 | 기본값 | 설명 |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | (없음) | BotFather 발급 토큰 |
| `TELEGRAM_CHAT_ID` | (없음) | 받을 사람 chat_id |
| `BACKEND_BASE_URL` | `http://localhost:8000` | 백엔드 주소 |
| `AUTO_FILTER_COMPETITION_MAX` | `0.5` | 경쟁강도 상한 |
| `AUTO_FILTER_KR_RATIO_MIN` | `0.3` | 한국비율 하한 (0~1) |
| `AUTO_FILTER_VOLUME_MIN` | `100` | 주평 검색량 하한 |
| `PRODUCTS_PER_KEYWORD` | `5` | 키워드당 수집 상품 수 |
| `MIN_MARGIN_RATE` | `0.10` | 마진율 하한 (0~1) |
| `TASK_POLL_INTERVAL_SEC` | `10` | 태스크 폴링 주기 |
| `TASK_TIMEOUT_SEC` | `14400` | 단계당 최대 대기 (4시간) |

## 결과 확인

자동화가 끝나면:
- 로그 파일: `logs/automation_YYYYMMDD.log` (단계별 상세)
- DB: `user_data` 테이블에 `key="last_auto_collected:YYYY-MM-DD"` 로 후보 JSON 저장
- 텔레그램에 완료 알림 + 후보 키워드 수 + `/recommend-products` 링크
- **다음 날 출근 후** `http://localhost:8000/recommend-products` 에서 시트 빌드

## 새 백엔드 엔드포인트 (자동화 전용)

자동화에서만 호출하는 두 라우터를 새로 추가했다. 프론트엔드에는 노출되지 않음.

### `POST /api/keywords/auto-filter`

```json
{
  "competition_max": 0.5,
  "kr_ratio_min": 0.3,
  "search_volume_min": 100,
  "date": "2026-04-25",
  "brand_filter": "general",
  "limit": 50
}
```

해당 날짜 수집 키워드 중 임계값 통과한 것만 점수 내림차순으로 반환.

### `POST /api/recommend/auto-build`

```json
{
  "keywords_jp": ["..."],
  "date": "2026-04-25",
  "min_margin_rate": 0.10,
  "limit": 30
}
```

각 키워드의 큐텐/국내 상품을 결합해 마진까지 계산. `user_data` 테이블에 `last_auto_collected:{date}` 로 저장.

## Windows 작업 스케줄러 등록 (선택)

처음 한 달은 **수동 실행 권장.** 안정화되면 그때 자동 등록:

1. `Win+R` → `taskschd.msc`
2. **작업 만들기** → 일반 탭에서 이름 `Qoo10 야간 자동화` / 사용자가 로그온되었을 때만 실행
3. 트리거 → 매일 오후 7:00 시작
4. 동작 → 프로그램/스크립트:
   ```
   C:\Users\Admin\qoo10-keyword-extractor\backend\.venv\Scripts\python.exe
   ```
   인수:
   ```
   C:\Users\Admin\qoo10-keyword-extractor\automation\daily_workflow.py
   ```
   시작 위치:
   ```
   C:\Users\Admin\qoo10-keyword-extractor
   ```
5. 조건 탭 → "AC 전원에서만" 체크 해제 (배터리에서도 실행)
6. 설정 탭 → "이미 실행 중인 경우 새 인스턴스 시작 안 함" 선택

## 트러블슈팅

**텔레그램 알림이 안 옴**
- `.env` 의 토큰/chat_id 확인
- 콘솔에는 항상 메시지가 출력되니, 콘솔에 보이는데 텔레그램에 없으면 토큰/chat_id 문제

**`CAPTCHA 발생` 알림이 떴다**
- 큐텐 측에서 캡차 챌린지를 띄운 상태. 데스크톱 큐텐 창에서 수동 로그인 → 다시 실행

**`자동 필터 통과 키워드 0개`**
- `.env` 의 `AUTO_FILTER_*` 임계값을 한 단계씩 완화

**중간에 한 단계만 다시 돌리고 싶다**
- 현재는 처음부터 재실행만 가능. 트렌드 수집은 같은 날 재실행 시 (lookup_date, category, classification) 조합으로 기존 행을 지우고 새로 적재하므로 중복은 없음.

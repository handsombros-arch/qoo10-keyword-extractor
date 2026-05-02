# Qoo10 자동화 액션 플로우

도식화용 흐름 정리 (2026-05-02 기준).

> **현재 모드**: `AUTOMATION_MODE=keyword_only` (R-6, 2026-05-01).
> 야간 자동화는 키워드 RD (STEP 1~4.5) 까지만. STEP 5+ (매칭/이미지/auto-build) 는 사장님 수동.

---

## 1. 전체 그림 — 24시간 사이클

```
┌──────────────────────────────────────────────────────────────┐
│                     24시간 사이클 (매일)                       │
└──────────────────────────────────────────────────────────────┘

  00:30      ~01:00         08:00            09:00 ~ 18:00
   │           │              │                    │
   ▼           ▼              ▼                    ▼
[야간자동화]  [완료]    [morning_report]      [사장님 검수+수동]
   │           │      텔레그램+슬랙                 │
   │           │      자동 알림                    │
   ▼           ▼                                   ▼
 run_nightly  키워드 RD 까지만               STEP 5+ 직접:
 → daily_     (R-6 keyword_only)             • 한국 검색
   workflow   ✓ 트렌드 670건                  • 매칭 (URL 재생성)
   + verify   ✓ LLM 분류 435건                • 시트로 보내기
   + recover  ✓ 자동 필터 통과 20건            • 등록상태 토글 (R-7)
              ✓ M05 확장 85건 (R-5)              │
              (DB만)                              ▼
                                          시트에서 swap/reject
                                          → user_corrections INSERT
                                          (자동 학습 입력 — 룰 반영
                                           은 GGG-2 분석 후 수동)
```

---

## 2. Windows 작업 스케줄러 (3개 task)

| Task 이름             | 트리거                  | 동작                                                 | 한도 |
|---------------------|-----------------------|----------------------------------------------------|----|
| `Qoo10ChromeDebug`  | AtLogOn + AtStartup    | 디버그 Chrome (port 9222) 자동 시작                | -  |
| `Qoo10DailyWorkflow`| 매일 00:30             | `run_nightly.py` (또는 `-UseLegacyWorkflow` 시 daily) | 6h |
| `Qoo10MorningReport`| 매일 08:00             | `morning_report.py` → 알림 전송                    | 5분 |

**`Qoo10DailyWorkflow` 안에서 (R-4)**:
1. `daily_workflow.py` 1차 시도 (rc≠0,2,3 → 60초 후 1회 재시도, watchdog 포함)
2. `verify_run.py {date} --recover` (C1~C6 검증 + 누락 STEP 자동 회복)
3. `morning_report.py` (텔레그램+슬랙)

---

## 3. 야간 자동화 STEP 흐름 (R-6 keyword_only, 00:30 ~ ~01:00)

```
[00:30] run_nightly.py {today} → daily_workflow.py
  │
  ▼
STEP 1   헬스체크 + Chrome 9222 자동 launch
  │      └─ 죽으면 watchdog: 8000 포트 kill + start.pyw 재실행 + 30초 대기
  │
STEP 2   로그인 상태
  │      └─ 큐텐 / 네이버 API / Chrome9222 / Naver smartstore 세션
  │      └─ Naver 디스크 검사 (NID_AUT/NID_SES) — 만료 시 즉시 알림+중단
  │
STEP 3   트렌드 키워드 수집 (01.종합 + 03.뷰티&화장품 + 07.식품, 비딩 포함)
  │      └─ categories=[1, 3, 7] — 사장님 디폴트 (5/2부터 변경, 이전 12개 전체)
  │      └─ 결과: keywords 테이블 INSERT
  │      └─ 같은 날짜 이미 있으면 SKIP
  │
STEP 3.5 LLM 카테고리 분류 (qwen2.5:14b)
  │      └─ category_inferred + is_brand 채움
  │      └─ category_inferred IS NULL 만 처리 (재개 가능)
  │
STEP 4   자동 필터
  │      └─ UserData 임계값: competition_max, kr_ratio_min, volume_min
  │      └─ category_blacklist: ["05.디지털","08.엔터테인먼트&e티켓","10.모바일"]
  │      └─ 결과: 후보 ~20-40개 (5/2 = 20)
  │      └─ 0개 시 _diagnose_filter_zero — loose 임계값 재호출 분기
  │
STEP 4.5 ★ M05 유사/연관 키워드 (R-5, NEW 5/1)
  │      └─ parent ≤ 33, RELATED_KEYWORDS_MAX_PER_PARENT=15
  │      └─ RelatedKeywordScraper → 번역 → expanded_keywords INSERT
  │      └─ jaccard 0.95 (4/29-30) → 신규 INSERT 200건/일 목표
  │      └─ 5/2 결과: 85건 신규 (parent 39)
  ▼
[~01:00] keyword_only 모드 종료
  │
  ▼
verify_run.py {date} --recover
  │      └─ C1 keywords/dates count > 0 (mode=keyword_only 면 여기까지)
  │      └─ C2 auto-filter idempotent → 1개 이상 통과
  │      └─ C3+ (auto-build/폴더/SEO) — keyword_only 면 SKIP
  │
  ▼
morning_report.py — 텔레그램+슬랙 알림

──────── full 모드일 때만 (AUTOMATION_MODE=full) ────────
STEP 5    한국 상품 수집 (네이버 m08 + 큐텐 m09)
STEP 5.5  set_count 추출 (정규식 + cover OCR + LLM)
STEP 5.7  브랜드 키워드 확장 (qwen3:14b)
STEP 5.8  expanded keyword → 한국 검색
STEP 5.9  한국 이미지 다운+비전 (skip default)
STEP 5.95 큐텐↔한국 1:N 매칭 (image_match + text_match)
STEP 6.0  큐텐 SEO 콘텐츠 (qoo10_title_jp/tags/marketing — 패턴 A/B/C/D)
STEP 6    추천 자동 빌드 (cheapest 한국 SKU + 마진)
STEP 6.5  set_count 비전 검증 (마진≥N% 만)
STEP 6.6  매칭 retry — alt 키워드 의역 (HHH-1)
STEP 6.7  candidate 폴더 (image/{date}/N. <kw>/)
STEP 7    Quality 임계값 auto-tune
```

---

## 4. 데이터 저장 위치

```
┌─ DB (Supabase Postgres) ─────────────────────┐
│  keywords            트렌드 키워드 + LLM 분류 │
│  qoo10_products      큐텐 상품 + cover_desc  │
│  domestic_products   한국 상품 + cover_desc  │
│  domestic_match_     매칭 결과 (image/text/   │
│    candidates         quality_score, decision)│
│  brands              브랜드 + aliases JSON    │
│  expanded_keywords   브랜드 확장 + 학습 kw   │
│  user_corrections    사장님 swap/reject 학습 │
│  user_data           UserData (시트/임계값)   │
└──────────────────────────────────────────────┘

┌─ 파일 시스템 ─────────────────────────────────┐
│  image/{date}/                                │
│    1. 메디큐브_AGE-R/                         │
│      cover_naver_988.jpg                      │
│      alt_naver_*_원.jpg (3개)                 │
│      qoo10_*_엔.jpg (5개, g_500 큰 이미지)    │
│      meta.json                                │
│      INFO.txt                                 │
│    2. 달바_화이트_트러플/                      │
│    ...                                        │
│  logs/automation_YYYYMMDD.log                 │
└──────────────────────────────────────────────┘
```

---

## 5. 사장님 검수 흐름 (출근 후)

```
[08:00] 텔레그램+슬랙 알림 수신
  │     "🌅 야간 자동화 결과 — 2026-05-02 (keyword_only)
  │      ✅ 완료 (0 ERR, 20분 24초)
  │      📊 트렌드 670 / 분류 435 / 필터 통과 20
  │      🌱 M05 확장 85건 (parent 39)"
  ▼
[09:00] /recommend-products 시트 열기 (또는 /api/recommend/auto-collected/{date})
  │
  ▼
시트 컬럼 (좌→우):
  ★ 등록상태 (R-7)  미정/등록중/등록완료 dropdown — 색깔 + 필터
  1. 폴더명          예: "1. 메디큐브_AGE-R"  (image/ 폴더와 1:1)
  2. 큐텐 URL        🛒 검색 (keyword_jp 기반)
  3. 키워드(일본어)  → 클릭하면 큐텐 검색 새 탭
  4. 키워드(한국어)  → 클릭하면 네이버 검색 새 탭
  5. 출처            auto:2026-05-02
  6. 한국 SKU 명     좌(큐텐 cover) | 우(한국 cover) 2-image
  7. 큐텐 → 한글     LLM 번역 (참고용)
  8. 매칭            accepted / ⚠ 검수 / rejected
  9. 무게/원가/판매가/마진
  ▼
사장님 행동 (R-6 mode — STEP 5+ 직접 수행):
  ┌─ 키워드 보고 한국 검색 → 상품 선정 (수동)
  ├─ 시트에 한국 SKU 입력 → 옵션/원가/무게 → 마진 계산
  ├─ 우측 슬라이드 패널 [URL 재생성] (4/30 신규)
  │     └─ POST /api/products/regenerate-content-from-url
  │     └─ naver_fetch_v2 (CDP attach) + OCR + SEO + JP detail + 진행률 폴링
  │     └─ qoo10_title_jp / tags / option_name / marketing 자동 생성
  ├─ 매칭 의심 → 상품명 클릭 → 우측 패널
  │     ├─ 큐텐 cover ↔ 한국 cover 비교
  │     ├─ AI 묘사 (qwen2.5vl, GGG-1)
  │     └─ swap → user_corrections INSERT (4/30) — GGG-2 분석 입력
  └─ 등록상태 토글 (R-7) — 등록완료 시 registered_at 자동기록
  ▼
검수 완료 → 큐텐 export
```

---

## 6. 자동 학습 루프 (현재 R-6 mode — 데이터만 누적)

R-6 자동화 범위 축소로 STEP 5+ 가 야간 자동화에서 빠지면서, 기존 자동 학습 루프 (KKK-1 A/B/C) 도 자동 반영이 멈춘 상태. 데이터는 `user_corrections` 에 계속 쌓이며, **GGG-2 분석 (5/6 이후) 으로 수동 반영 예정**.

```
[Day N]
  사장님 swap/reject (시트 우측 패널)
  │
  ▼
  user_corrections INSERT (4/30 FFF-2)
  (ai_choice_id, user_choice_id, scores, kw_jp, kw_kr,
   ai_cover_description, user_cover_description ...)
  │
  ▼
  데이터만 누적 (자동 반영 OFF — R-6)

[5/6 이후, 사장님 "GGG-2 분석해" 트리거 시]
  1. corrections 통계 + cover_description 자카드 비교
  2. qwen2.5vl 자주 틀리는 카테고리 패턴 추출
  3. 매칭 임계값 / 결합 룰 개선안 출력 (마크다운 200줄 이내)
  4. 사장님 승인 → 코드 변경
  5. (필요 시) AUTOMATION_MODE=full 재가동 검토

──────── full 모드 복귀 시 자동 루프 (참고) ────────
[Day N+1 00:30]  STEP 5.6 — preferred kw inject (user_choice → expanded_keywords)
[Day N+7~14]     STEP 7   — quality 임계값 auto-tune (swap_rate ≥30% → +0.05 등)
```

---

## 7. UI 구조 (frontend)

```
사이드바 메인
├─ 📊 대시보드        /
├─ ⭐ 역직구 추천      /recommend          ← 키워드 발견
├─ ✅ 검수            /review/{date}       ← 카드형
├─ 📋 상품 시트       /recommend-products  ← 메인 작업 hub (AG-Grid)
│    ├─ [+ 자동화]     date picker → 후보 머지
│    ├─ [+ 큐텐 샵]    샵 URL 분석
│    ├─ [+ 트렌드]     키워드 선택 머지
│    ├─ [필터]         source / decision / 마진율
│    ├─ [일괄 액션]    삭제 / SEO 재생성 / 거부
│    └─ 우측 슬라이드 패널 (행 클릭)
├─ 🎯 샵 벤치마크
├─ 💹 마진 계산기
├─ 🎨 워터마크 제거
└─ ⚙️ AI 설정         /settings
     ├─ 자동 필터 카테고리 화이트리스트
     ├─ 자동 필터 임계값 (3 슬라이더)
     ├─ AI 학습 진행 (4-카드 + top swap kw)
     ├─ 매칭 품질 임계값 (III-1) — 슬라이더 + 가중치 + 미리보기
     │  + ↻ 기존 매칭 일괄 재라벨
     └─ 브랜드 자동 추가 임계값
```

---

## 8. 환경변수 토글

| 변수                              | 기본            | 의미                                                  |
|---------------------------------|---------------|-----------------------------------------------------|
| `AUTOMATION_MODE`                | keyword_only  | R-6: STEP 4.5 까지만. `full` 시 STEP 5+ 포함            |
| `ENABLE_RELATED_KEYWORDS`         | 1             | R-5 M05 STEP 4.5 (다양성)                            |
| `RELATED_KEYWORDS_MAX_PER_PARENT` | 15            | M05 parent 당 최대 확장 수                            |
| `ENABLE_DOMESTIC_IMAGES`          | 0             | 한국 모든 SKU cover 다운 (낭비)                       |
| `ENABLE_CANDIDATE_IMAGES`         | 1             | auto-build 후보만 폴더 (DDD-1)                       |
| `ENABLE_BRAND_EXPAND`             | 1             | 브랜드 → specific 키워드                              |
| `ENABLE_EXPANDED_SEARCH`          | 1             | 확장 키워드 한국 검색                                 |
| `ENABLE_MATCH_IMAGES`             | 1             | 1:N 매칭                                            |
| `ENABLE_SET_COUNT_VERIFY`         | 1             | 마진 N%+ vision 검증                                 |
| `ENABLE_QOO10_CONTENT`            | 1             | SEO 콘텐츠 자동                                      |
| `ENABLE_MATCH_RETRY`              | 1             | HHH-1 alt 키워드 retry                              |
| `ENABLE_AUTO_LEARNING`            | 1             | KKK-1 자동 학습 (B+C — full mode 시)                 |

---

## 9. 도식화 권장 — 추천 다이어그램

```
[1] 시간축 → STEP 박스 → 데이터 저장소     (전체 흐름)
[2] 사장님 swap → 자동 학습 → 다음 날     (피드백 루프)
[3] 시트 row + 폴더 + DB 1:1 매핑          (데이터 무결성)
```

mermaid / draw.io / Excalidraw 권장.

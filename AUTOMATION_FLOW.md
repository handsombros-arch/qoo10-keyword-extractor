# Qoo10 자동화 액션 플로우

도식화용 흐름 정리 (2026-04-29 기준).

---

## 1. 전체 그림 — 24시간 사이클

```
┌──────────────────────────────────────────────────────────────┐
│                     24시간 사이클 (매일)                       │
└──────────────────────────────────────────────────────────────┘

  00:30      04:00~05:00     08:00         09:00 ~ 18:00
   │             │             │                  │
   ▼             ▼             ▼                  ▼
[야간자동화]  [완료]      [morning_report]   [사장님 검수]
   │             │       텔레그램+슬랙           │
   │             │       자동 알림              │
   │             │                              │
   ▼             ▼                              ▼
 daily_       모든 데이터               시트에서 swap/reject
 workflow     준비됨                    → user_corrections
              (DB+폴더+시트)              자동 INSERT
                                              │
                                              ▼
                                       다음 날 자동 학습 입력
                                       (blocklist + preferred kw)
```

---

## 2. Windows 작업 스케줄러 (3개 task)

| Task 이름             | 트리거                  | 동작                                 | 한도 |
|---------------------|-----------------------|------------------------------------|----|
| `Qoo10ChromeDebug`  | AtLogOn + AtStartup    | 디버그 Chrome (port 9222) 자동 시작 | -  |
| `Qoo10DailyWorkflow`| 매일 00:30             | `daily_workflow.py` 실행            | 6h |
| `Qoo10MorningReport`| 매일 08:00             | `morning_report.py` → 알림 전송     | 5분 |

---

## 3. 야간 자동화 STEP 흐름 (00:30 ~ 04:00~05:00)

```
[00:30] daily_workflow.py 시작
  │
  ▼
STEP 1   헬스체크 + Chrome 9222 자동 launch (30초 wait)
  │
STEP 2   로그인 상태 (큐텐/네이버 API/CDP)
  │
STEP 3   트렌드 키워드 수집 (12 카테고리, 비딩 포함)
  │      └─ 결과: keywords 테이블 INSERT (~425개/일)
  │      └─ 같은 날짜 이미 있으면 SKIP
STEP 3.5 LLM 카테고리 분류 (qwen2.5:14b)
  │      └─ category_inferred + is_brand 채움
  │      └─ category_inferred IS NULL 만 처리 (재개 가능)
STEP 4   자동 필터
  │      └─ UserData 임계값: competition_max, kr_ratio_min, volume_min
  │      └─ category_blacklist: ["05.디지털","08.엔터테인먼트&e티켓","10.모바일"]
  │      └─ 결과: 후보 ~20-30개
  │
STEP 5   한국 상품 수집 (네이버 + 큐텐 fresh scrape)
  │      └─ 각 keyword_kr 로 네이버 m08 + 큐텐 m09
  │      └─ DomesticProduct + Qoo10Product INSERT
STEP 5.4 ★ 큐텐 상품명 jp→ko 번역 (qwen3:14b, MMM-1 NEW)
  │      └─ 시트 "큐텐→한글" 컬럼 채움
STEP 5.5 set_count 추출 (정규식 + OCR + LLM 폴백)
STEP 5.6 ★ 자동 학습 — preferred kw 주입 (KKK-1 B, NEW)
  │      └─ 사장님 swap 사례 → ExpandedKeyword INSERT
STEP 5.7 브랜드 키워드 확장 (LLM)
STEP 5.8 expanded keyword → 한국 검색
STEP 5.9 한국 이미지 다운+비전 (skip default — DDD-1)
STEP 5.95 큐텐↔한국 1:N 매칭
  │      └─ image_match (minicpm-v) + text_match (자카드)
  │      └─ III-1 quality_score 자동 계산 → decision 라벨
  │      └─ KKK-1 A blocklist (사장님 reject 사례 자동 skip)
  │
STEP 6.0 큐텐 SEO 콘텐츠 생성 (qoo10_title_jp/tags/marketing)
STEP 6   추천 자동 빌드 (cheapest 한국 SKU + 마진 계산)
STEP 6.6 ★ 매칭 retry — alt 키워드 의역 (HHH-1, NEW)
  │      └─ image_score < 0.5 → LLM alt 한국어 키워드 2~3개
  │      └─ Naver 재검색 → 재매칭
  │      └─ 개선 시 auto_build 재실행
STEP 6.7 candidate 폴더 (image/{date}/N. <kw>/) — DDD-1
  │      └─ 폴더명 1~N 넘버링 (final_score DESC)
  │      └─ cover/alt/qoo10 이미지 (g_500) + meta.json + INFO.txt
  │      └─ UserData(last_candidate_folders:{date}) 저장 → 시트 매핑용
STEP 6.5 set_count 비전 검증 (마진≥N% 만)
  │
STEP 7   ★ Quality 임계값 auto-tune (KKK-1 C, NEW)
  │      └─ 최근 14일 swap_rate 측정
  │      └─ ≥30% → accept +0.05 (빡빡)  /  <5% → -0.05 (느슨)
  │      └─ UserData(quality_thresholds) 자동 업데이트
  ▼
[04:00~05:00] 완료 + 텔레그램+슬랙 자동 알림
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
  │     "🌅 야간 자동화 결과 — 2026-04-30
  │      ✅ 완료 (0 ERR)
  │      📊 후보 19개 | 평균 마진 45.3%
  │      🔄 retry 6건 시도, 5개 개선
  │      🧠 누적 수정 N건 | AI 정확도 ~83%"
  ▼
[09:00] /recommend-products 시트 열기
  │
  ▼
시트 컬럼 (순서):
  1. 폴더명          예: "1. 메디큐브_AGE-R"  (image/ 폴더와 1:1)
  2. 큐텐 URL        🛒 검색 (keyword_jp 기반)
  3. 키워드(일본어)  → 클릭하면 큐텐 검색 새 탭
  4. 키워드(한국어)  → 클릭하면 네이버 검색 새 탭
  5. 출처            auto:2026-04-30
  6. 한국 SKU 명     좌(큐텐 cover) | 우(한국 cover) 2-image
  7. 큐텐 → 한글     LLM 번역 (참고용)
  8. 매칭            accepted / ⚠ 검수 / rejected
  9. 무게/원가/판매가/마진
  ▼
사장님 행동:
  ┌─ 매칭 OK → 그대로 사용
  ├─ 매칭 의심 → 상품명 클릭 → 우측 슬라이드 패널
  │             ├─ 큐텐 cover ↔ 한국 cover 큰 비교 (h-64)
  │             ├─ AI 묘사 (qwen2.5vl) 양쪽 표시 (GGG-1)
  │             ├─ 한국 다른 SKU (적합도 순) 미리보기
  │             ├─ alt SKU 클릭 → 한국 슬롯 미리보기 (LLL-1)
  │             ├─ "✓ 이 SKU 로 교체" 확정 / "↶ 취소"
  │             ├─ swap 시 user_corrections INSERT (FFF-2)
  │             │  → KKK-1 자동 학습 입력
  │             └─ "거부" 시 reject INSERT
  └─ 매칭 불가 → 거부
  ▼
검수 완료 → 큐텐 export
```

---

## 6. 자동 학습 루프 (사장님 swap → 다음 날 자동 적용)

```
[Day N]
  사장님 swap (시트 우측 패널)
  │
  ▼
  user_corrections INSERT
  (ai_choice_id, user_choice_id, scores, kw_jp, kw_kr...)
  │
  ▼
  [즉시] A. blocklist 추가
        다음 매칭부터 (qid, ai_choice_id) 자동 skip

[Day N+1 00:30]
  STEP 5.6 → B. preferred kw inject
    user_choice_id → DomesticProduct.search_keyword
    → ExpandedKeyword INSERT (source_count=-1)
  ▼
  STEP 5.8 expanded_search 가 자동으로 새 keyword_kr 검색
  → 한국 SKU 풀 보강 → 매칭 정합도 ↑

[Day N+7 ~ N+14, 매주]
  STEP 7 → C. quality 임계값 auto-tune
    swap_rate 측정 → 임계값 자동 ±0.05
    UserData(quality_thresholds) 저장 + 캐시 무효화
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

## 8. 환경변수 토글 (전부 ON 기본)

| 변수                        | 기본 | 의미                          |
|---------------------------|----|------------------------------|
| `ENABLE_DOMESTIC_IMAGES`   | 0  | 한국 모든 SKU cover 다운 (낭비)  |
| `ENABLE_CANDIDATE_IMAGES`  | 1  | auto-build 후보만 폴더 (DDD-1) |
| `ENABLE_BRAND_EXPAND`      | 1  | 브랜드 → specific 키워드        |
| `ENABLE_EXPANDED_SEARCH`   | 1  | 확장 키워드 한국 검색           |
| `ENABLE_MATCH_IMAGES`      | 1  | 1:N 매칭                     |
| `ENABLE_SET_COUNT_VERIFY`  | 1  | 마진 N%+ vision 검증          |
| `ENABLE_QOO10_CONTENT`     | 1  | SEO 콘텐츠 자동                |
| `ENABLE_MATCH_RETRY`       | 1  | HHH-1 alt 키워드 retry        |
| `ENABLE_AUTO_LEARNING`     | 1  | KKK-1 자동 학습 (B+C)         |

---

## 9. 도식화 권장 — 추천 다이어그램

```
[1] 시간축 → STEP 박스 → 데이터 저장소     (전체 흐름)
[2] 사장님 swap → 자동 학습 → 다음 날     (피드백 루프)
[3] 시트 row + 폴더 + DB 1:1 매핑          (데이터 무결성)
```

mermaid / draw.io / Excalidraw 권장.

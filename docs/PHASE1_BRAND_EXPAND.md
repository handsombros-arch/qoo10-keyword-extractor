# Phase 1-D — 브랜드 키워드 확장 (명세 3.3#1~3)

**일시**: 2026-04-28
**관련 문서**: MASTER_SPEC § 3.3 / Phase 1 잔여

## 1. 목표 (사장님 명세)

is_brand=1 키워드 → 큐텐 상위 노출 + 리뷰 많은 상품 5~10개 식별
→ 「브랜드 + 상품명」 specific 키워드 추출 (예: anua pdrn)
→ 한글 번역 후 네이버/쿠팡 검색

## 2. 구현

### 2-1. DB
- `expanded_keywords` 테이블 신규
- 컬럼: id, parent_jp, parent_kr, keyword_jp, keyword_kr, source_count, created_at, domestic_match_count

### 2-2. LLM 모듈
- `services/llm/brand_expand.py` 신규
- `prompts/brand_expansion.txt` 신규
- 입력: 브랜드명(jp/kr) + 큐텐 상위 N개 상품명
- 출력 JSON: `{"expansions": [{"keyword_jp": "...", "keyword_kr": "..."}, ...]}` (3~5개)
- 정규화: 길이 1~80자, lowercase 중복 제거, max 5개
- env: `BRAND_EXPAND_MODEL=ollama:qwen3:14b`

### 2-3. 엔드포인트 + 트리거
- `POST /api/keywords/expand-brand`
- `automation/trigger_brand_expand.py`
- 옵션: `--date`, `--qoo10-date`, `--top-n`, `--limit`, `--brands`

## 3. 시운전 결과 (4/27 keywords + 4/25 큐텐, limit 5)

| 항목 | 값 |
|---|---|
| 처리 대상 | 5 (is_brand=1, 검색량 순) |
| 큐텐 매칭 | 1 (메디큐브 美顔器) |
| LLM 추출 성공 | 5개 keyword |
| SKIP (큐텐 0) | 4 (4/25 큐텐 미수집 키워드) |

### 메디큐브 추출 결과 ✅ (사장님 명세 정확)

| keyword_jp | keyword_kr |
|---|---|
| メディキューブ AGE-R ウルトラチューン | 메디큐브 AGE-R 울트라 터ン |
| メディキューブ ブースタープロX2 | 메디큐브 부스터 프로 X2 |
| メディキューブ ブースタープロミニプラス | 메디큐브 부스터 프로 미니 플러스 |
| メディキューブ ハイフォーカスショットプラス | 메디큐브 하이포커스 샷 플러스 |
| メディキューブ PDRNブースター | 메디큐브 PDRN 부스터 |

## 4. 평가

- ✅ **사장님 명세 「anua pdrn」 패턴 정확**: 「メディキューブ PDRN ブースター」 같은 specific 모델명 식별
- ✅ **한국 검색 가능 형태**: 「메디큐브 부스터 프로 X2」 등 한국 셀러 검색에 그대로 사용 가능
- ⚠️ 4/27 keywords 의 4건이 4/25 큐텐 미매칭 (모라크 등) — 데이터 수집 누락 영향
- ⚠️ 카타카나 잔존 1건 (「ターン」 → 「터ン」, qwen3:14b 한계)

## 5. 통합 흐름

```
4/27 keywords (is_brand=1)
  ↓ trigger_brand_expand
4/25 qoo10_products (search_keyword 매칭, top 10)
  ↓ LLM brand_expand
expanded_keywords (parent_jp + specific keyword_jp + kr)
  ↓ [후속 작업]
m08_naver / m07_coupang 검색 (keyword_kr)
  ↓
domestic_products (search_keyword=keyword_kr)
  ↓ 매칭 결합 룰
domestic_match_candidates (높은 정확도)
```

## 6. 후속 작업 (Phase 1-D 마무리)

| # | 작업 |
|---|---|
| R-1 | expanded_keywords 의 keyword_kr 로 m08_naver 자동 검색 (백그라운드 워커) |
| R-2 | 검색 결과 → 매칭 결합 룰 자동 진입 (image_match + text_match) |
| R-3 | daily_workflow STEP 4.5 추가 (자동 필터 후 brand 확장) |

## 7. MASTER_SPEC § 8 갱신

- ★★★ 갭 #3 (1-D 브랜드 키워드 확장) → ✅ **핵심 LLM 추출 완료**, 한국 검색 통합은 후속 (R-1~R-3)

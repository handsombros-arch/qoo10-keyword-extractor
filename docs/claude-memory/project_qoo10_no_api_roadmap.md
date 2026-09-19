---
name: qoo10-no-api-2026-05-21
description: API 비용 0 + ollama 품질 부족 + 사양 한계 조합의 해결책 — LLM 호출 자체 감축 + 메인 PC sleep+wake + MBP conductor + Claude Code Max
metadata: 
  node_type: memory
  type: project
  originSessionId: 18b0aa8f-49a8-4f16-af32-80afe55eab2e
---

**2026-05-21.** 사장님 "맥북 24h 자동실행" 요청에서 시작 → ollama 품질 부족 + API 거부 + 사양 한계 종합 분석 → 새 패러다임 합의. "내일 진행".

## 사장님 제약 (확정, 5/21)

| | 가능 |
|---|---|
| Claude API / OpenAI API | ❌ |
| ollama 단독 | ❌ (번역=brand 매핑, OCR 한국 화장품 약점) |
| VPS / 클라우드 백엔드 | ❌ |
| Claude Max 구독 (Claude Code CLI) | ✅ |
| ChatGPT Plus (Codex CLI) | ✅ 옵션 |
| 메인 PC RTX 5080 (격리 조건 충족 시) | ✅ |
| Intel 2015 MBP (conductor 만) | ✅ |
| Tailscale | ✅ |

## 핵심 발상 — LLM 호출 횟수 자체를 줄임

현 가정 (2000~3000회/일) 폐기 → DB 영속화로 일 10~50회 축소.

| 도메인 | 현 ~/일 | 영속화 후 ~/일 | 방법 |
|---|---|---|---|
| translate | 700 | 0 | translation_cache + brand_aliases 시드 |
| category | 700 | 0 | keyword→category 영속 캐시 |
| brand_expand | 700 | 0 | brand 단위 1회 → DB |
| set_count | 700 | 5~10 | 정규식+OCR 우선 |
| image_match | 1086 | 200 | (qoo10_id, domestic_id) 매칭 캐시 |
| qoo10_content/jp_detail | 30 | 30 | URL 별 1회 영속 (이미 적음) |

## 새 아키텍처

```
[사장님 폰 Telegram]
  ↓ 명령 한 줄
[Intel 2015 MBP — 24h ON, conductor]
  hermes-agent + 텔레그램 봇
  Claude Code (Max 구독, 무료)
  cron / launchd
  Tailscale 매직 패킷 송신
  ↓ wake-on-LAN
[메인 PC RTX 5080 — 야간 02:30~04:00 만 ON]
  ollama (qwen2.5:14b + minicpm-v:8b)
  Playwright + 메인 Chrome 확장 (R-8)
  daily_workflow.py (STEP 4.5 까지만, R-6 범위)
  ↓ 04:00 자동 sleep
[Supabase 클라우드] DB 그대로
```

## 자동화 범위 (변경 없음)

- 자동 (야간 1.5h): 키워드 발굴 + 분류 + 한국 매칭 + 이미지 매칭 시도 → 시트에 **PR 형태로** 쌓기만
- 수동 (사장님): 시트에서 PR 검토 → 수락/거부 → 등록
- AI 보조 (텔레그램): "오늘 PR 정리해줘" → Claude Code 가 행 정리/요약

## 7단계 로드맵 (5/22 시작)

1. **brand_aliases 일괄 채우기** — Claude Code Max 가 K-뷰티 brand 100개 jp/en/ko alias DB INSERT (1회 호출 → 영속)
2. **category 캐시 테이블** — `category_cache(keyword_jp PK, category, classified_at)` 추가, classify_category_async 이전에 lookup
3. **brand_expand 캐시** — brand 단위 1회만 LLM → DB 영속, 이후 lookup
4. **image_match 결과 캐시** — `image_match_cache(qoo10_id, domestic_id PK, name_score, image_score)` 추가
5. **MBP 셋업** — hermes-agent + 텔레그램 봇 + Claude Code (Max 인증) + Tailscale
6. **메인 PC wake-on-LAN 패턴** — MBP cron 02:30 → 매직 패킷 → 메인 PC wake → 자동화 → 04:00 sleep
7. **MBP ↔ 메인 PC RPC** — 텔레그램 명령 시 MBP 가 메인 PC 깨워서 작업, 결과 받음

## 비용

- API: $0
- 클라우드: Supabase 무료 티어 + Tailscale 무료 + Claude Max 기존 구독 (Qoo10 외 용도와 공유)
- 전기/하드웨어: 메인 PC 야간 1.5h × 30일 ≈ 미미

## How to apply

- "내일 진행" / "1단계 시작" / "brand alias 채워" 트리거 시 위 1~7 단계 순서대로
- 진행 중 사장님이 추가 제약 발견 시 (예: Tailscale 매직 패킷 안 됨, MBP 셋업 막힘) 본 메모리 수정 + 대안 제시
- 본 메모리는 [[feedback_qoo10_local_ai]] (5/21 갱신본) 과 [[project_qoo10_mac_migration]] (5/18 결정) 의 후속. 충돌 시 본 메모리 우선

## 충돌/대체

- [[project_qoo10_mac_migration]] (5/18) — MBP 단독 + on-demand Chrome + OpenAI API → ❌ 폐기 (API 거부, MBP 사양 부족)
- [[project_qoo10_automation_off]] — 야간 자동화 OFF 사유는 fix 완료. 본 로드맵으로 재개 예정
- [[feedback_qoo10_local_ai]] (5/3 원본) — ollama 우선 → 5/21 갱신본으로 대체 (호출 최소화 + Claude Max 보조)

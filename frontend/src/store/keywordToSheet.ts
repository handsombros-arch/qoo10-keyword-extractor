/**
 * 키워드/관심키워드 → 시트 row 머지 utility (VV-1).
 *
 * KeywordPage / RecommendPage / SheetSourceToolbar 의 트렌드 modal 등에서
 * 공유. localStorage + cloudSync 모두 동기.
 *
 * dedup 기준: keyword_jp (없으면 product_name).
 */
import { loadSheet, saveSheet, newSheetRow, type SheetRow } from './productSheet';
import { pushCloud } from './cloudSync';
import api from '../api/client';

export type KeywordLike = {
  keyword_jp: string;
  keyword_kr?: string | null;
  category?: string | null;
  search_volume_weekly?: number | null;
  added_at?: string;
};

/** keyword → SheetRow 변환. source 자동 (예: 'keyword:2026-04-29' 또는 'interest').
 *
 * R-7: product_name 은 빈칸 — 사장님이 한국 셀러 검색 후 직접 입력 (이전 placeholder = keyword_jp 이라
 * 시트 컬럼에서 keyword_jp 와 한국 SKU 가 동일하게 보이는 문제 해결).
 * category 도 함께 자동 입력 (LLM category_inferred 또는 raw category).
 */
export function keywordToSheetRow(kw: KeywordLike, source: string): SheetRow {
  return newSheetRow({
    keyword_jp: kw.keyword_jp,
    keyword_kr: kw.keyword_kr || undefined,
    product_name: '',
    category: kw.category || undefined,
    source,
    match_decision: 'manual',
  });
}

/** 키워드 list → 시트에 머지. dedup 후 신규만 prepend. localStorage + DB 동기.
 *  O (5/3): 블랙리스트 사전 차단 — keyword_jp 매칭 시 시트 추가 안 함.
 *  return: { added, blacklisted, deduped }.
 */
export async function mergeKeywordsToSheet(
  keywords: KeywordLike[], source: string
): Promise<{ added: number; blacklisted: number; deduped: number }> {
  if (!keywords || !keywords.length) return { added: 0, blacklisted: 0, deduped: 0 };
  const sheet = loadSheet();
  const existing = new Set(
    sheet.map(r => r.keyword_jp || r.product_name).filter(Boolean)
  );

  // O (5/3) 블랙리스트 batch 체크
  let blockedSet = new Set<string>();
  try {
    const items = keywords.map(kw => ({ keyword_jp: kw.keyword_jp }));
    const r = await api.post<any>('/blacklist/check-batch', { items });
    for (const res of r.data.results || []) {
      if (res.blacklisted && res.keyword_jp) blockedSet.add(res.keyword_jp);
    }
  } catch (e) {
    // 백엔드 오류 시 차단 X (안전 장치 fallback)
    console.warn('[mergeKeywordsToSheet] blacklist check 실패, skip:', e);
  }

  const fresh: SheetRow[] = [];
  let blacklisted = 0;
  let deduped = 0;
  for (const kw of keywords) {
    const key = kw.keyword_jp;
    if (!key) continue;
    if (blockedSet.has(key)) { blacklisted++; continue; }
    if (existing.has(key)) { deduped++; continue; }
    existing.add(key);
    fresh.push(keywordToSheetRow(kw, source));
  }
  if (!fresh.length) return { added: 0, blacklisted, deduped };

  const next = [...fresh, ...sheet];  // 새 row 가 위로
  saveSheet(next);
  try {
    await pushCloud('product_sheet', next);
  } catch {
    /* localStorage 는 저장됨 */
  }
  return { added: fresh.length, blacklisted, deduped };
}

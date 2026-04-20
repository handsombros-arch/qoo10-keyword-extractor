/**
 * 관심 키워드 localStorage + 클라우드 저장소.
 */
import { pushCloud } from './cloudSync';

const KEY = 'interestKeywords.v1';

export type InterestKeyword = { keyword_jp: string; keyword_kr?: string | null };

export function getInterestKeywords(): InterestKeyword[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveInterestKeywords(list: InterestKeyword[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(list));
    // 비동기로 cloud push (실패해도 로컬은 유지)
    pushCloud('interest_keywords', list).catch(() => {});
  } catch {
    /* ignore */
  }
}

export function addInterestKeywords(items: InterestKeyword[]): InterestKeyword[] {
  const cur = getInterestKeywords();
  const byJp = new Map(cur.map(i => [i.keyword_jp, i]));
  for (const it of items) {
    if (!byJp.has(it.keyword_jp)) byJp.set(it.keyword_jp, it);
  }
  const merged = Array.from(byJp.values());
  saveInterestKeywords(merged);
  return merged;
}

export function removeInterestKeyword(keyword_jp: string): InterestKeyword[] {
  const cur = getInterestKeywords().filter(i => i.keyword_jp !== keyword_jp);
  saveInterestKeywords(cur);
  return cur;
}

export function clearInterestKeywords(): void {
  saveInterestKeywords([]);
}

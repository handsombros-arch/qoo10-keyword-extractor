/**
 * 관심 키워드 localStorage + 클라우드 저장소.
 */
import { pushCloud } from './cloudSync';

const KEY = 'interestKeywords.v1';

export interface InterestKeyword {
  keyword_jp: string;
  keyword_kr?: string | null;
  added_at?: string;                    // YYYY-MM-DD (관심 체크한 날짜)
  category?: string;
  search_volume_weekly?: number;
  search_volume_daily?: number;
  competition_intensity?: number;
  total_products?: number;
  products_jp?: number;
  products_kr?: number;
  products_cn?: number;
  products_other?: number;
}

export function getInterestKeywords(): InterestKeyword[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    // 하위 호환: added_at 없던 이전 데이터는 오늘 날짜로 채움
    const today = new Date().toISOString().slice(0, 10);
    return parsed.map((k: any) => ({
      ...k,
      added_at: k.added_at || today,
    }));
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
  const today = new Date().toISOString().slice(0, 10);
  for (const it of items) {
    if (!byJp.has(it.keyword_jp)) {
      byJp.set(it.keyword_jp, { ...it, added_at: it.added_at || today });
    }
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

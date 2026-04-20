/**
 * 샵 벤치마크 결과 localStorage 캐시.
 * 페이지 새로고침해도 마지막 결과 복원.
 */
const KEY = 'shopBenchmarkCache.v1';

export interface CachedShopProduct {
  product_name: string;
  price_jpy?: number;
  product_url?: string;
  cover_image_url?: string;
  shop_rank?: number;
  review_count?: number;
}

export interface CachedShopResult {
  shop_id: string;
  shop_url: string;
  products: CachedShopProduct[];
  sort_type?: string;
  fetched_at: string;  // ISO datetime
}

export function loadShopCache(): CachedShopResult[] {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

import { pushCloud } from './cloudSync';

export function saveShopCache(results: CachedShopResult[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(results));
    pushCloud('shop_cache', results).catch(() => {});
  } catch {
    /* ignore */
  }
}

export function clearShopCache(): void {
  localStorage.removeItem(KEY);
  pushCloud('shop_cache', []).catch(() => {});
}

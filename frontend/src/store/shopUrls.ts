/**
 * 샵 벤치마크 URL 리스트 영속 store.
 * 사장님이 매번 텍스트 영역에 다시 붙여넣지 않아도 되도록 localStorage + cloudSync.
 */
import { pushCloud } from './cloudSync';

const KEY = 'shopBenchmarkUrls.v1';

export interface ShopUrlEntry {
  url: string;        // 큐텐 샵 URL (https://www.qoo10.jp/shop/{id})
  shop_id?: string;   // 자동 추출 가능 — URL 의 마지막 segment
  added_at?: string;  // ISO date 추가 시점
}

const _DEFAULT_URLS: ShopUrlEntry[] = [
  { url: 'https://www.qoo10.jp/shop/tsurutsuru', shop_id: 'tsurutsuru' },
  { url: 'https://www.qoo10.jp/shop/jjunabeauty', shop_id: 'jjunabeauty' },
];

function _extractShopId(url: string): string {
  try {
    const u = new URL(url);
    const parts = u.pathname.split('/').filter(Boolean);
    return parts[parts.length - 1] || url;
  } catch {
    return url.replace(/^https?:\/\//, '').slice(0, 30);
  }
}

export function loadShopUrls(): ShopUrlEntry[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return _DEFAULT_URLS;
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.length > 0) return parsed;
    return _DEFAULT_URLS;
  } catch {
    return _DEFAULT_URLS;
  }
}

export function saveShopUrls(urls: ShopUrlEntry[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(urls));
    pushCloud('shop_urls', urls).catch(() => {});
  } catch {
    /* ignore */
  }
}

export function addShopUrl(url: string): ShopUrlEntry[] {
  const trimmed = url.trim();
  if (!trimmed) return loadShopUrls();
  const list = loadShopUrls();
  if (list.some(e => e.url === trimmed)) return list;  // dedup
  const entry: ShopUrlEntry = {
    url: trimmed,
    shop_id: _extractShopId(trimmed),
    added_at: new Date().toISOString(),
  };
  const next = [...list, entry];
  saveShopUrls(next);
  return next;
}

export function removeShopUrl(url: string): ShopUrlEntry[] {
  const next = loadShopUrls().filter(e => e.url !== url);
  saveShopUrls(next);
  return next;
}

/**
 * 클라우드 동기화 유틸.
 * localStorage는 즉시 캐시, 백엔드 DB는 debounce로 저장.
 * 페이지 로드 시 DB 먼저 fetch → 로컬보다 최신이면 덮어씀.
 */
import api from '../api/client';

type SyncKey = 'product_sheet' | 'interest_keywords' | 'shop_cache';

interface CloudEnvelope<T> {
  key: string;
  data: T | null;
  updated_at: string | null;
}

/** DB에서 최신 데이터 fetch */
export async function fetchCloud<T>(key: SyncKey): Promise<{ data: T | null; updated_at: string | null }> {
  try {
    const { data } = await api.get<CloudEnvelope<T>>(`/user-data/${key}`);
    return { data: data.data, updated_at: data.updated_at };
  } catch {
    return { data: null, updated_at: null };
  }
}

/** DB에 저장 */
export async function pushCloud<T>(key: SyncKey, data: T): Promise<boolean> {
  try {
    await api.put(`/user-data/${key}`, { data });
    return true;
  } catch {
    return false;
  }
}

/** debounce 도구 */
export function makeDebouncedPusher<T>(key: SyncKey, delay = 1200) {
  let timer: number | null = null;
  let pending: T | null = null;

  return {
    push(data: T) {
      pending = data;
      if (timer !== null) window.clearTimeout(timer);
      timer = window.setTimeout(async () => {
        if (pending !== null) {
          await pushCloud(key, pending);
          pending = null;
        }
        timer = null;
      }, delay);
    },
    /** 즉시 push (페이지 unload 등) */
    flush: async () => {
      if (timer !== null) {
        window.clearTimeout(timer);
        timer = null;
      }
      if (pending !== null) {
        const p = pending;
        pending = null;
        await pushCloud(key, p);
      }
    },
  };
}

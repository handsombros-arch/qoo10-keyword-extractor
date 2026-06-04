/**
 * 오늘의 실시간 환율(1엔=원) 공용 모듈.
 *
 * 백엔드 /utils/exchange-rate (Dunamu→er-api, 하루1회 캐시) 를 한 번 받아
 * 메모리 + localStorage(날짜키)에 캐시. 마진 계산기 기본값·새 시트행 환율 주입에 사용.
 * 네트워크 실패 시 9.5 폴백(기존 하드코딩 기본값과 동일).
 */
import api from '../api/client';

const FALLBACK = 9.5;
const LS_KEY = 'today_exchange_rate.v1';

let _rate = FALLBACK;
let _meta: { rate: number; source: string; as_of: string } = {
  rate: FALLBACK, source: 'fallback', as_of: '',
};

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

// 부팅 시 localStorage 의 "오늘" 캐시 복원
try {
  const raw = localStorage.getItem(LS_KEY);
  if (raw) {
    const j = JSON.parse(raw);
    if (j && j.date === today() && Number(j.rate) > 0) {
      _rate = Number(j.rate);
      _meta = { rate: _rate, source: j.source || 'cache', as_of: j.as_of || j.date };
    }
  }
} catch { /* ignore */ }

/** 동기 — 캐시된 오늘 환율(없으면 9.5 폴백). 새 시트행/계산 기본값용. */
export function getCachedRate(): number {
  return _rate > 0 ? _rate : FALLBACK;
}

/** 표시용 메타 (rate/source/as_of). */
export function getRateMeta() {
  return _meta;
}

/** 비동기 — 백엔드에서 오늘 환율을 받아 캐시. 앱/페이지 진입 시 호출. */
export async function fetchTodayRate(): Promise<number> {
  try {
    const { data } = await api.get('/utils/exchange-rate', { params: { currency: 'JPY' } });
    const rate = Number(data?.rate);
    if (rate && rate > 0) {
      _rate = rate;
      _meta = { rate, source: data.source || 'live', as_of: data.as_of || today() };
      try {
        localStorage.setItem(LS_KEY, JSON.stringify({ date: today(), rate, source: _meta.source, as_of: _meta.as_of }));
      } catch { /* ignore */ }
    }
  } catch { /* 네트워크 실패 → 기존 캐시/폴백 유지 */ }
  return _rate;
}

// 모듈 로드 시 1회 워밍 (productSheet 등에서 import 되면 앱 시작 직후 실행)
void fetchTodayRate();

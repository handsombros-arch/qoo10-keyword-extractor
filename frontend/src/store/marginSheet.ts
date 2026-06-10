/**
 * 큐텐 마진 시트 — 행/설정 localStorage + 클라우드(user_data) 동기화.
 * 계산은 src/lib/qoo10MarginSheet.ts 에서 실시간으로 (저장은 입력값만).
 */
import { pushCloud } from './cloudSync';
import type { MarginMode } from '../lib/qoo10MarginSheet';

const ROWS_KEY = 'marginSheet.rows.v1';
const SETTINGS_KEY = 'marginSheet.settings.v1';

/** 시트 한 행 = 등록 후보 1건 (상품 × 구성). 입력값만 저장. */
export interface MarginRow {
  id: string;
  group_id: string;            // 같은 상품의 구성들을 묶는 키
  source_keyword?: string;     // 출처 키워드(RD)
  buy_site?: string;           // 구매사이트
  url?: string;
  product_name?: string;
  option_label?: string;       // 구성 라벨 (예: 1개입 / 2개 세트)
  qty: number;                 // 개수
  weight_g: number;            // 실제 무게(1개)
  purchase_krw: number;        // 구매가(1개)
  domestic_ship_krw: number;   // 국내 배송비+포장비(1개)
  mode: MarginMode;            // 'markup' | 'target'
  markup: number;              // 배수 (markup 모드)
  target_margin: number;       // 목표 마진율 (target 모드)
  kse_override_krw: number | null; // KSE 배송비 직접입력(null=자동)
  mega_discount: number;       // 메가와리 할인율
  registered: boolean;         // 등록 완료 체크
  memo?: string;
}

export interface MarginSheetSettings {
  exchange_rate: number;       // 작성 당일 환율(1엔당 원화). 0이면 미설정
  rate_source?: string;        // 출처/날짜 표시용
  rate_date?: string;
  default_markup: number;      // 신규 행 기본 배수
  default_target_margin: number;
  default_mega_discount: number;
  mega_min_margin: number;     // 메가와리 최소 마진율(미달 시 경고)
}

export const DEFAULT_SETTINGS: MarginSheetSettings = {
  exchange_rate: 0,
  default_markup: 1.4,
  default_target_margin: 0.3,
  default_mega_discount: 0.1,
  mega_min_margin: 0.05,
};

let _seq = 0;
export function newId(prefix = 'r'): string {
  // Date/Math.random 의존 줄이되 충돌만 피하면 됨
  _seq += 1;
  return `${prefix}_${_seq}_${performance.now().toString(36).replace('.', '')}`;
}

export function newMarginRow(partial: Partial<MarginRow> = {}, s = DEFAULT_SETTINGS): MarginRow {
  const id = newId();
  return {
    id,
    group_id: partial.group_id || id,
    qty: 1,
    weight_g: 0,
    purchase_krw: 0,
    domestic_ship_krw: 3000,
    mode: 'markup',
    markup: s.default_markup,
    target_margin: s.default_target_margin,
    kse_override_krw: null,
    mega_discount: s.default_mega_discount,
    registered: false,
    ...partial,
  };
}

export function loadRows(): MarginRow[] {
  try {
    const raw = localStorage.getItem(ROWS_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch { return []; }
}

export function saveRows(rows: MarginRow[]): void {
  try {
    localStorage.setItem(ROWS_KEY, JSON.stringify(rows));
    pushCloud('margin_sheet', rows).catch(() => {});
  } catch { /* ignore */ }
}

export function loadSettings(): MarginSheetSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    return raw ? { ...DEFAULT_SETTINGS, ...JSON.parse(raw) } : { ...DEFAULT_SETTINGS };
  } catch { return { ...DEFAULT_SETTINGS }; }
}

export function saveSettings(s: MarginSheetSettings): void {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
    pushCloud('margin_sheet_settings', s).catch(() => {});
  } catch { /* ignore */ }
}

/** 키워드(RD) 선택 → 마진 시트에 빈 후보행으로 시드. 출처 키워드만 채움. 추가된 행 수 반환. */
export function seedRowsFromKeywords(
  keywords: { keyword_jp?: string; keyword_kr?: string | null }[],
): number {
  const s = loadSettings();
  const cur = loadRows();
  const seeded = keywords
    .map(k => (k.keyword_kr || k.keyword_jp || '').trim())
    .filter(Boolean)
    .map(kw => newMarginRow({ source_keyword: kw }, s));
  if (!seeded.length) return 0;
  saveRows([...cur, ...seeded]);
  return seeded.length;
}

/** 한 행을 세트 구성으로 복제 (개수만 바꿔 같은 group_id). */
export function duplicateAsComposition(row: MarginRow, qty: number, label?: string): MarginRow {
  return newMarginRow({
    ...row,
    id: newId(),
    group_id: row.group_id,
    qty,
    option_label: label || `${qty}개 세트`,
    registered: false,
  });
}

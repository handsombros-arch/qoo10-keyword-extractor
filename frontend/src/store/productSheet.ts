/**
 * 상품 시트 localStorage 저장소.
 * 사용자가 수동 입력한 무게/구매가/배송비를 재방문 시 복원.
 */

/** 구성 옵션: 한 상품을 단품/세트/번들 등 여러 판매 형태로 등록하기 위한 하위 레코드. */
export interface CompositionOption {
  id: string;
  label: string;                    // 표시명 ("단품", "3개 세트", "5+1 세트" 등 자유)
  quantity: number;
  weight_g: number;                 // 총 무게 (세트 기준)
  item_price_krw: number;           // 총 상품가 (세트 기준, 할인가 포함 가능)
  domestic_shipping_krw: number;    // 국내배송비 (세트 기준 무게에 맞춰 사용자 기입)
  shipping_packaging_krw: number;   // KSE 포장+배대지
  sell_price_jpy: number;           // 엔화 판매가 (세트별)
  is_mega?: boolean;                // 메가와리 적용 여부 (개별 구성)
  notes?: string;
}

export interface SheetRow {
  id: string;                    // uuid
  product_name: string;          // 원문 (일본어)
  product_name_ko?: string;      // 한글 번역 (수동 편집 가능)
  product_url?: string;
  cover_image_url?: string;
  source?: string;               // 'shop:tsurutsuru', '수동', '관심키워드' 등
  shop_rank?: number | null;
  review_count?: number | null;
  created_at?: string;           // ISO date (yyyy-mm-dd)

  // 사용자 입력값
  weight_g: number;
  item_price_krw: number;         // 상품 단가
  domestic_shipping_krw: number;  // 국내 배송비 (구매처→내 사무실)
  shipping_packaging_krw: number; // KSE 배대지까지 배송+포장비

  // 판매가 (엔)
  competitor_price_jpy?: number;  // 스크래핑된 경쟁 상품가 (참고용)
  sell_price_jpy: number;         // 내가 실제 등록할 판매가 (마진 계산 기준)
  // 메가와리 판매가는 sell_price_jpy * 0.9 로 자동 계산

  // 예상 판매량 (월간)
  normal_sales_count?: number;    // 일반 판매 예상 개수
  mega_sales_count?: number;      // 메가와리 판매 예상 개수

  // 옵션
  exchange_rate?: number;
  shipping_mode?: 'auto' | 'free' | 'paid';
  notes?: string;

  // 구성 옵션 (단품/세트 등 — 없으면 메인 행 값으로 단품 취급)
  compositions?: CompositionOption[];

  // 하위 호환
  purchase_price_krw?: number;
}

/** 하위 호환 헬퍼: 구 필드 → 신 필드 이관 + 기본값 갱신 */
function migrateRow(raw: any): SheetRow {
  const row = { ...raw } as SheetRow;
  if ((row.item_price_krw == null || row.item_price_krw === 0) && raw.purchase_price_krw != null) {
    row.item_price_krw = raw.purchase_price_krw;
    row.domestic_shipping_krw = 0;
  }
  if (row.item_price_krw == null) row.item_price_krw = 0;
  if (row.domestic_shipping_krw == null) row.domestic_shipping_krw = 0;
  if (row.shipping_packaging_krw == null || row.shipping_packaging_krw === 2500) {
    row.shipping_packaging_krw = 3000;
  }
  // 경쟁가·판매 개수 기본값
  if (row.competitor_price_jpy == null) {
    // 스크래핑 시 sell_price_jpy에 들어간 값을 경쟁가로 간주, 내 판매가는 동일하게 시작
    row.competitor_price_jpy = row.sell_price_jpy || 0;
  }
  if (row.normal_sales_count == null) row.normal_sales_count = 0;
  if (row.mega_sales_count == null) row.mega_sales_count = 0;
  if (!row.created_at) row.created_at = new Date().toISOString().slice(0, 10);
  // 레거시 shipping_mode
  const m: any = row.shipping_mode;
  if (m === 'free_kse') row.shipping_mode = 'free';
  else if (m === 'paid_tracx') row.shipping_mode = 'paid';
  // 구성 옵션 배열 정규화
  if (!Array.isArray(row.compositions)) row.compositions = [];
  return row;
}

/** 새 구성 옵션 생성. 메인 행 값을 기본으로 채움 (1단위). */
export function newCompositionOption(row: SheetRow, partial: Partial<CompositionOption> = {}): CompositionOption {
  const qty = partial.quantity ?? 1;
  return {
    id: (crypto as any).randomUUID?.() || String(Date.now() + Math.random()),
    label: partial.label ?? (qty === 1 ? '단품' : `${qty}개 세트`),
    quantity: qty,
    weight_g: partial.weight_g ?? (row.weight_g || 0) * qty,
    item_price_krw: partial.item_price_krw ?? (row.item_price_krw || 0) * qty,
    domestic_shipping_krw: partial.domestic_shipping_krw ?? (row.domestic_shipping_krw || 0),
    shipping_packaging_krw: partial.shipping_packaging_krw ?? (row.shipping_packaging_krw || 3000),
    sell_price_jpy: partial.sell_price_jpy ?? (row.sell_price_jpy || 0) * qty,
    is_mega: partial.is_mega ?? false,
    notes: partial.notes ?? '',
  };
}

const KEY = 'productSheet.v1';

export function loadSheet(): SheetRow[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as any[];
    return parsed.map(migrateRow);
  } catch {
    return [];
  }
}

export function saveSheet(rows: SheetRow[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(rows));
  } catch {
    /* ignore */
  }
}

export function newSheetRow(partial: Partial<SheetRow>): SheetRow {
  const base: SheetRow = {
    id: (crypto as any).randomUUID?.() || String(Date.now() + Math.random()),
    product_name: '',
    created_at: new Date().toISOString().slice(0, 10),
    weight_g: 500,
    item_price_krw: 0,
    domestic_shipping_krw: 0,
    shipping_packaging_krw: 3000,
    competitor_price_jpy: 0,
    sell_price_jpy: 0,
    normal_sales_count: 0,
    mega_sales_count: 0,
    exchange_rate: 9.5,
    shipping_mode: 'auto',
    ...partial,
  };
  // 경쟁가와 판매가 동기화 (상품 추가 시점에는 동일하게 시작)
  if (base.competitor_price_jpy && !partial.sell_price_jpy) base.sell_price_jpy = base.competitor_price_jpy;
  if (base.sell_price_jpy && !base.competitor_price_jpy) base.competitor_price_jpy = base.sell_price_jpy;
  return base;
}

/** 마진 계산 입력용: 상품가 + 국내배송 합산 */
export function totalPurchaseKrw(row: SheetRow): number {
  return (row.item_price_krw || 0) + (row.domestic_shipping_krw || 0);
}

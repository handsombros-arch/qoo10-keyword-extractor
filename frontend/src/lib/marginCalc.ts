/**
 * 클라이언트 마진 계산기.
 * backend/app/services/margin_calculator.py와 동일 로직을 TS로 포팅.
 * 시트 셀 편집 시 즉시 재계산하기 위함.
 */
import shippingRates from '../assets/qoo10_shipping_rates.json';

export const QOO10_COMMISSION_RATE = 0.135;
export const MEGAWARI_DISCOUNT = 0.9;
export const APPROX_RATE = 10;
export const FREE_SHIPPING_THRESHOLD_KRW = 20000;

type ShippingRow = { weight_g: number; shipping_krw: number };
type RatesTable = { free_kse: ShippingRow[] };

const TABLES = shippingRates as unknown as RatesTable;

export type ShippingMode = 'auto' | 'free' | 'paid';
export type ResolvedShippingMode = 'free' | 'paid';

export function lookupKseShipping(weight_g: number): number {
  const table = TABLES.free_kse;
  if (weight_g <= 0) return 0;
  for (const row of table) {
    if (weight_g <= row.weight_g) return row.shipping_krw;
  }
  return table[table.length - 1].shipping_krw;
}

export function resolveShippingMode(sellPriceKrw: number, mode: ShippingMode): ResolvedShippingMode {
  if (mode === 'auto') {
    return sellPriceKrw >= FREE_SHIPPING_THRESHOLD_KRW ? 'free' : 'paid';
  }
  return mode;
}

export interface MarginInput {
  weight_g: number;
  purchase_price_krw: number;
  shipping_packaging_krw: number;
  sell_price_jpy: number;
  is_mega?: boolean;
  exchange_rate?: number;
  use_exact_rate?: boolean;
  shipping_mode?: ShippingMode;
  quantity?: number;
  price_multiplier?: number;
}

export interface MarginResult {
  effective_sell_jpy: number;
  commission_jpy: number;
  shipping_cost_krw: number;
  revenue_krw: number;
  total_cost_krw: number;
  profit_krw: number;
  margin_rate: number;
  shipping_mode_resolved: ResolvedShippingMode;
  recommended_price_krw_30pct: number;
}

export function calculateMargin(input: MarginInput): MarginResult {
  const {
    weight_g,
    purchase_price_krw,
    shipping_packaging_krw,
    sell_price_jpy,
    is_mega = false,
    exchange_rate = 9.5,
    use_exact_rate = false,
    shipping_mode = 'auto',
    quantity = 1,
    price_multiplier = 1.0,
  } = input;

  const rate = use_exact_rate ? exchange_rate : APPROX_RATE;

  const effectiveWeight = weight_g * quantity;
  const effectivePurchase = purchase_price_krw * quantity;
  const effectivePackaging = shipping_packaging_krw * quantity;
  const baseSellJpy = sell_price_jpy * price_multiplier;

  const effectiveJpy = baseSellJpy * (is_mega ? MEGAWARI_DISCOUNT : 1.0);

  // 배송모드는 항상 정확환율 기준 원화 판매가로 판정
  const sellKrwForMode = effectiveJpy * exchange_rate;
  const resolvedMode = resolveShippingMode(sellKrwForMode, shipping_mode);

  // 유료: 바이어 부담 → 셀러 비용 0 / 무료: 셀러가 KSE 부담
  const shippingCostKrw = resolvedMode === 'paid' ? 0 : lookupKseShipping(effectiveWeight);

  const commissionJpy = effectiveJpy * QOO10_COMMISSION_RATE;
  const revenueKrw = effectiveJpy * rate;
  const commissionKrw = commissionJpy * rate;
  const totalCostKrw = effectivePurchase + effectivePackaging + commissionKrw + shippingCostKrw;
  const profitKrw = revenueKrw - totalCostKrw;

  const marginRate = baseSellJpy > 0 ? profitKrw / (baseSellJpy * exchange_rate) : 0;

  const recommended = (effectivePurchase + effectivePackaging) * 1.3;

  return {
    effective_sell_jpy: effectiveJpy,
    commission_jpy: commissionJpy,
    shipping_cost_krw: shippingCostKrw,
    revenue_krw: revenueKrw,
    total_cost_krw: totalCostKrw,
    profit_krw: profitKrw,
    margin_rate: marginRate,
    shipping_mode_resolved: resolvedMode,
    recommended_price_krw_30pct: recommended,
  };
}

export function marginVerdict(margin_rate: number): '우수' | '양호' | '애매' | '부족' | '손실' {
  if (margin_rate >= 0.3) return '우수';
  if (margin_rate >= 0.2) return '양호';
  if (margin_rate >= 0.1) return '애매';
  if (margin_rate >= 0) return '부족';
  return '손실';
}

export const DEFAULT_COMPOSITIONS = [
  { label: '단품', quantity: 1, price_multiplier: 1.0 },
  { label: '2개 세트', quantity: 2, price_multiplier: 1.8 },
  { label: '3개 세트', quantity: 3, price_multiplier: 2.55 },
];

export function analyzeCompositionsLocal(input: MarginInput): (MarginResult & { label: string; quantity: number })[] {
  return DEFAULT_COMPOSITIONS.map(c => ({
    ...calculateMargin({ ...input, quantity: c.quantity, price_multiplier: c.price_multiplier, is_mega: false }),
    label: c.label,
    quantity: c.quantity,
  }));
}

/**
 * 추천 점수 (0~100).
 *
 * 공식: 가격대 × 40% + 마진율 × 40% + 리뷰 × 20%
 *
 * - 가격대: 원화 판매가 20,000원 이상이면 만점. 그 이하는 0~20,000 선형
 *   (20,000원은 큐텐 무료배송 임계점이자 스윗스팟 하한)
 * - 마진율: 0%=0점, 50%+=만점 선형
 * - 리뷰: log10(review+1) 정규화, 리뷰 1만개 = 만점
 */
export const PRICE_SWEETSPOT_MIN_KRW = 20000;

export function priceRangeFit(sell_price_krw: number): number {
  if (sell_price_krw <= 0) return 0;
  if (sell_price_krw >= PRICE_SWEETSPOT_MIN_KRW) return 1;
  return sell_price_krw / PRICE_SWEETSPOT_MIN_KRW;
}

// 하위 호환 (히스토그램 등): 엔화 기준 스윗스팟 상수
export const PRICE_SWEETSPOT_MIN_JPY = 2100;  // ≈ 20,000원 / 9.5
export const PRICE_SWEETSPOT_MAX_JPY = 10000; // 임의 상한 (표시용)

export function reviewScore(review_count: number): number {
  if (!review_count || review_count <= 0) return 0;
  // log10(count+1) / log10(10001) = 0~1 (리뷰 1만개에서 1.0)
  return Math.min(1, Math.log10(review_count + 1) / 4);
}

export interface RecommendScoreInput {
  sell_price_jpy: number;
  exchange_rate: number;
  review_count: number;
  margin_rate: number;
}

export interface RecommendScoreBreakdown {
  total: number;            // 0~100
  price_component: number;  // 0~40
  margin_component: number; // 0~40
  review_component: number; // 0~20
}

export function calculateRecommendScore(input: RecommendScoreInput): RecommendScoreBreakdown {
  const sellKrw = input.sell_price_jpy * input.exchange_rate;
  const priceFit = priceRangeFit(sellKrw);
  const marginClamped = Math.max(0, Math.min(0.5, input.margin_rate)) / 0.5;
  const reviewFit = reviewScore(input.review_count);

  const price_component = priceFit * 40;
  const margin_component = marginClamped * 40;
  const review_component = reviewFit * 20;

  return {
    total: price_component + margin_component + review_component,
    price_component,
    margin_component,
    review_component,
  };
}

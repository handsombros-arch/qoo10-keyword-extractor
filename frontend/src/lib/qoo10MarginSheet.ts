/**
 * 큐텐 마진 선계산 (KSE 해상요금 전용, 클라이언트 실시간 재계산).
 *
 * 원본 "큐텐 상품 등록.xlsx" KSE 블록(W~AD)을 분석/디벨롭한 버전.
 *  - 환율(R, 1엔당 원화)은 "작성 당일 환율". 마진엔 영향 없고 "엔 등록가"만 결정.
 *  - 상시 / 메가와리(빅프로모션 필수 할인) 마진을 동시 산출 (메가 역마진 감지).
 *  - 계산 방향: markup(원가×배수) | target(목표 마진율 → 등록가 역산, 상시 기준).
 *  - KSE 배송비는 무게로 자동 조회하되 행별 직접 입력(override) 가능.
 */

export const QOO10_COMMISSION = 0.135;   // 큐텐 수수료 13.5%
export const PACKAGING_WEIGHT_G = 100;   // 포장 가산 무게 (실무게 + 100g)

// KSE 해상요금표 (무게 상한 g → 배송비 원). VLOOKUP 근사: 무게 이하의 가장 큰 구간.
// 원본 '큐텐 배송비' 시트 K:N = backend qoo10_shipping_rates.json free_kse 와 동일.
export const KSE_TABLE: { w: number; krw: number }[] = [
  { w: 0, krw: 0 }, { w: 100, krw: 4950 }, { w: 250, krw: 5250 }, { w: 500, krw: 5900 },
  { w: 750, krw: 6800 }, { w: 1000, krw: 7200 }, { w: 1250, krw: 7600 }, { w: 1500, krw: 8100 },
  { w: 1750, krw: 8600 }, { w: 2000, krw: 9100 }, { w: 2500, krw: 9500 }, { w: 3000, krw: 10200 },
  { w: 3500, krw: 11100 }, { w: 4000, krw: 11700 }, { w: 4500, krw: 12300 }, { w: 5000, krw: 13400 },
  { w: 5500, krw: 14500 }, { w: 6000, krw: 15300 }, { w: 6500, krw: 16100 }, { w: 7000, krw: 16800 },
  { w: 7500, krw: 17600 }, { w: 8000, krw: 18300 }, { w: 8500, krw: 19000 }, { w: 9000, krw: 19800 },
  { w: 9500, krw: 20400 }, { w: 10000, krw: 21200 }, { w: 10500, krw: 21900 }, { w: 11000, krw: 22700 },
  { w: 11500, krw: 23400 }, { w: 12000, krw: 24200 }, { w: 12500, krw: 24900 }, { w: 13000, krw: 25600 },
  { w: 13500, krw: 26400 }, { w: 14000, krw: 27200 }, { w: 14500, krw: 27800 }, { w: 15000, krw: 28600 },
  { w: 15500, krw: 29400 }, { w: 16000, krw: 30200 }, { w: 16500, krw: 31100 }, { w: 17000, krw: 31800 },
  { w: 17500, krw: 32600 }, { w: 18000, krw: 33500 }, { w: 18500, krw: 34300 }, { w: 19000, krw: 35100 },
  { w: 19500, krw: 36000 }, { w: 20000, krw: 36800 }, { w: 20500, krw: 37600 }, { w: 21000, krw: 38300 },
  { w: 21500, krw: 39300 }, { w: 22000, krw: 39800 }, { w: 22500, krw: 40500 }, { w: 23000, krw: 41200 },
  { w: 23500, krw: 42700 }, { w: 24000, krw: 43000 }, { w: 24500, krw: 43300 }, { w: 25000, krw: 44000 },
  { w: 25500, krw: 44600 }, { w: 26000, krw: 45500 }, { w: 26500, krw: 46300 }, { w: 27000, krw: 47000 },
  { w: 27500, krw: 47700 }, { w: 28000, krw: 48400 }, { w: 28500, krw: 49100 }, { w: 29000, krw: 49600 },
  { w: 29500, krw: 49800 }, { w: 30000, krw: 50900 },
];

/** KSE 배송비 조회 (무게 이하 가장 큰 구간; <100g 은 0). */
export function lookupKseShipping(weightG: number): number {
  if (!(weightG > 0)) return 0;
  let krw = 0;
  for (const row of KSE_TABLE) {
    if (weightG >= row.w) krw = row.krw;
    else break;
  }
  return krw;
}

export type MarginMode = 'markup' | 'target';

export interface MarginRowInput {
  qty: number;                 // 개수 (세트 구성)
  weightG: number;             // 실제 무게(g, 1개 기준)
  purchaseKrw: number;         // 구매가(원, 1개 기준) = 상품원가 + 국내배송비
  domesticShipKrw: number;     // KSE 배대지까지 배송비+포장비(원, 1개 기준)
  mode: MarginMode;
  markup: number;              // 원가 배수 (markup 모드, 예 1.4)
  targetMargin: number;        // 목표 마진율 (target 모드, 예 0.30) — 상시 기준
  kseOverrideKrw: number | null; // KSE 해상운임 직접 입력(원). null 이면 자동
  megaDiscount: number;        // 메가와리 할인율 (예 0.10)
  shipPaidByBuyer: boolean;    // 유료배송(바이어가 운임 부담) → 셀러 운임 부담 0
}

export interface MarginRowResult {
  effWeightG: number;          // 발송 무게 = weightG*qty + 포장
  costKrw: number;             // 원가 합 = (구매가+국내배송포장)*qty
  kseShipKrw: number;          // 적용된 KSE 배송비(자동 or override)
  kseAutoKrw: number;          // 자동 조회값(참고)
  targetPriceKrw: number;      // P: 원화 목표 판매가
  // 상시
  listJpy: number;             // 엔 등록가
  commissionKrw: number;
  profitKrw: number;
  marginRate: number;
  // 메가와리
  megaListJpy: number;
  megaProfitKrw: number;
  megaMarginRate: number;
}

// 0.865 * 1.135 — target 역산용 상수 (이익계수)
const PROFIT_COEF = (1 - QOO10_COMMISSION) * (1 + QOO10_COMMISSION); // 0.982275

/** 한 행 계산. rate = 1엔당 원화(작성 당일 환율). */
export function computeMarginRow(inp: MarginRowInput, rate: number): MarginRowResult {
  const qty = Math.max(1, inp.qty || 1);
  const R = rate > 0 ? rate : 10;             // 환율 없으면 안전 폴백(원본 근사치 10)
  const effWeightG = (inp.weightG || 0) * qty + PACKAGING_WEIGHT_G;
  const costKrw = ((inp.purchaseKrw || 0) + (inp.domesticShipKrw || 0)) * qty;
  const kseAutoKrw = lookupKseShipping(effWeightG);
  const kseShipKrw = inp.kseOverrideKrw != null ? inp.kseOverrideKrw : kseAutoKrw;
  // 유료배송이면 운임은 바이어 부담 → 셀러 마진 계산에서 KSE 제외 (운임 자체는 표시용으로 유지)
  const kseForMargin = inp.shipPaidByBuyer ? 0 : kseShipKrw;

  // 목표 원화 판매가 P
  let P: number;
  if (inp.mode === 'target') {
    const denom = PROFIT_COEF - (inp.targetMargin || 0);
    // 목표마진이 비현실적으로 높으면(>이익계수) 음수/발산 → 0 방어
    P = denom > 0 ? (costKrw + QOO10_COMMISSION * kseForMargin) / denom : 0;
  } else {
    P = costKrw * (inp.markup || 1.4);
  }

  // 상시: S = W*R = P*1.135 + KSE(셀러부담분)
  const S = P * (1 + QOO10_COMMISSION) + kseForMargin;
  const listJpy = R > 0 ? S / R : 0;
  const commissionKrw = S * QOO10_COMMISSION;
  const profitKrw = S - costKrw - commissionKrw - kseForMargin;
  const marginRate = P > 0 ? profitKrw / P : 0;

  // 메가와리: 등록가 ×(1-할인). 판매가↓ → 이익↓
  const megaListJpy = listJpy * (1 - (inp.megaDiscount || 0));
  const megaS = megaListJpy * R;
  const megaProfitKrw = megaS - costKrw - megaS * QOO10_COMMISSION - kseForMargin;
  const megaMarginRate = P > 0 ? megaProfitKrw / P : 0;

  return {
    effWeightG, costKrw, kseShipKrw, kseAutoKrw, targetPriceKrw: P,
    listJpy, commissionKrw, profitKrw, marginRate,
    megaListJpy, megaProfitKrw, megaMarginRate,
  };
}

export function marginVerdict(rate: number): string {
  if (rate < 0) return '손실';
  if (rate >= 0.30) return '우수';
  if (rate >= 0.20) return '양호';
  if (rate >= 0.10) return '애매';
  return '부족';
}

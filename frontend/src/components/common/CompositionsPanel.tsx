/**
 * 옵션 sub-row 패널 — 메인 시트와 동일한 양식·입력 처리.
 * - 옵션명 / 옵션값 별도 입력 (큐텐 등록 형식)
 * - parseNum 콤마 자동 strip
 * - 무게 변경 시 lookupKseShipping 자동 계산 → 포장+KSE
 * - 그룹 색 (내 원가 = 파랑 톤, 판매가 = 초록 톤) 메인 시트와 통일
 */
import { useMemo } from 'react';
import { Trash2 } from 'lucide-react';
import { calculateMargin, lookupKseShipping, marginVerdict } from '../../lib/marginCalc';
import {
  newCompositionOption,
  type CompositionOption,
  type SheetRow,
} from '../../store/productSheet';

interface Props {
  row: SheetRow;
  onChange: (compositions: CompositionOption[]) => void;
  onClose?: () => void;
}

const fmtKrw = (n: number) => (n == null ? '-' : Math.round(n).toLocaleString() + '원');
const fmtJpy = (n: number) => (n == null ? '-' : '¥' + Math.round(n).toLocaleString());
const fmtPct = (n: number) => (n == null ? '-' : (n * 100).toFixed(1) + '%');

const PRESETS = [1, 2, 3, 5];

// 메인 시트 parseNum 과 동등 — 콤마/공백 strip + Number, NaN → 0
const parseNum = (raw: string | number | null | undefined): number => {
  const s = String(raw ?? '').replace(/[,\s]/g, '');
  const n = Number(s);
  return isFinite(n) ? n : 0;
};

// 메인 시트 그룹 색 (RecommendProductsPage 와 동일)
const COST_BG = 'rgba(99, 102, 241, 0.06)';
const SELL_BG = 'rgba(34, 197, 94, 0.07)';

const inputBaseClass = 'w-full px-1.5 py-1 text-[12px] tracking-tight outline-none focus:bg-white';
const numInputClass = `${inputBaseClass} text-right font-mono`;
const textInputClass = `${inputBaseClass} text-left`;

export default function CompositionsPanel({ row, onChange, onClose }: Props) {
  const compositions = row.compositions || [];

  const update = (id: string, patch: Partial<CompositionOption>) => {
    onChange(compositions.map(c => (c.id === id ? { ...c, ...patch } : c)));
  };

  // 무게/수량 변경 시 shipping_packaging_krw 자동 계산
  const updateWeight = (id: string, w: number) => {
    const opt = compositions.find(c => c.id === id);
    if (!opt) return;
    const auto_pkg = lookupKseShipping(w * (opt.quantity || 1));
    update(id, { weight_g: w, shipping_packaging_krw: auto_pkg });
  };
  const updateQuantity = (id: string, q: number) => {
    const opt = compositions.find(c => c.id === id);
    if (!opt) return;
    const auto_pkg = lookupKseShipping((opt.weight_g || 0) * Math.max(1, q));
    update(id, { quantity: Math.max(1, q), shipping_packaging_krw: auto_pkg });
  };

  const remove = (id: string) => onChange(compositions.filter(c => c.id !== id));
  const add = (qty?: number) => {
    const opt = newCompositionOption(row, qty != null ? { quantity: qty } : {});
    onChange([...compositions, opt]);
  };

  const results = useMemo(() => {
    return compositions.map(c => {
      const res = calculateMargin({
        weight_g: c.weight_g || 0,
        purchase_price_krw: (c.item_price_krw || 0) + (c.domestic_shipping_krw || 0),
        shipping_packaging_krw: c.shipping_packaging_krw || 0,
        sell_price_jpy: c.sell_price_jpy || 0,
        exchange_rate: row.exchange_rate ?? 9.5,
        shipping_mode: row.shipping_mode ?? 'auto',
        is_mega: c.is_mega ?? false,
        quantity: 1,
      });
      return { opt: c, res };
    });
  }, [compositions, row.exchange_rate, row.shipping_mode]);

  const bestIdx = useMemo(() => {
    let idx = -1;
    let best = -Infinity;
    results.forEach((r, i) => {
      if (r.res.margin_rate > best) {
        best = r.res.margin_rate;
        idx = i;
      }
    });
    return idx;
  }, [results]);

  return (
    <div className="bg-apple-bg-2 rounded-xl border" style={{ borderColor: 'var(--color-apple-border)', padding: 12 }}>
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="apple-title-3 text-[14px]">
            옵션 편집 <span className="text-apple-text-3 font-normal text-[12px] ml-1">— {row.product_name_ko || row.product_name || '(상품명 없음)'}</span>
          </h3>
          <div className="text-[11px] text-apple-text-3 mt-0.5 tracking-tight">
            메인 행 단품값 (무게 {row.weight_g}g · 단가 {fmtKrw(row.item_price_krw)} · 판매가 {fmtJpy(row.sell_price_jpy)}) 기준 자동 채움. 무게 변경 시 포장+KSE 자동 재계산.
          </div>
        </div>
        {onClose && (
          <button onClick={onClose} className="apple-btn apple-btn-ghost apple-btn-sm" style={{ padding: '4px 8px' }}>닫기</button>
        )}
      </div>

      <div className="flex gap-1.5 mb-3 items-center flex-wrap">
        <span className="text-[11px] text-apple-text-3 mr-1">빠른 추가:</span>
        {PRESETS.map(n => (
          <button
            key={n}
            onClick={() => add(n)}
            className="apple-btn apple-btn-ghost apple-btn-sm"
            style={{ padding: '3px 8px', fontSize: 11 }}
          >
            +{n === 1 ? '단품' : `${n}세트`}
          </button>
        ))}
        <button
          onClick={() => add()}
          className="apple-btn apple-btn-ghost apple-btn-sm"
          style={{ padding: '3px 8px', fontSize: 11 }}
          title="빈 옵션 추가 (옵션명/옵션값 직접 입력)"
        >
          + 빈 옵션
        </button>
        {compositions.length > 0 && (
          <button
            onClick={() => onChange([])}
            className="ml-auto text-[11px] text-red-600 hover:text-red-800"
          >
            모든 옵션 삭제
          </button>
        )}
      </div>

      {compositions.length === 0 ? (
        <div className="text-center py-6 text-apple-text-3 text-[12px] border border-dashed rounded-lg" style={{ borderColor: 'var(--color-apple-border)' }}>
          옵션 없음. 위 버튼으로 단품/세트/빈 옵션을 추가해 옵션명·값·가격 입력하세요.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border" style={{ borderColor: 'var(--color-apple-border)' }}>
          <table className="w-full text-[12px]" style={{ borderCollapse: 'collapse' }}>
            <thead style={{ background: 'var(--color-apple-bg-3)' }}>
              <tr className="text-apple-text-3 text-[11px] uppercase tracking-wider font-medium">
                <th className="px-2 py-1.5 text-left border-b" style={{ borderColor: 'var(--color-apple-border)' }}>옵션명</th>
                <th className="px-2 py-1.5 text-left border-b" style={{ borderColor: 'var(--color-apple-border)' }}>옵션값</th>
                <th className="px-2 py-1.5 text-right border-b" style={{ borderColor: 'var(--color-apple-border)' }}>수량</th>
                <th className="px-2 py-1.5 text-right border-b" style={{ borderColor: 'var(--color-apple-border)', background: COST_BG }}>무게(g)</th>
                <th className="px-2 py-1.5 text-right border-b" style={{ borderColor: 'var(--color-apple-border)', background: COST_BG }}>구매가</th>
                <th className="px-2 py-1.5 text-right border-b" style={{ borderColor: 'var(--color-apple-border)', background: COST_BG }}>구매배송</th>
                <th className="px-2 py-1.5 text-right border-b" style={{ borderColor: 'var(--color-apple-border)', background: COST_BG }} title="무게 기반 자동 계산. 수동 override 가능">포장+KSE</th>
                <th className="px-2 py-1.5 text-right border-b" style={{ borderColor: 'var(--color-apple-border)', background: SELL_BG }}>판매가(¥)</th>
                <th className="px-2 py-1.5 text-center border-b" style={{ borderColor: 'var(--color-apple-border)' }}>메가</th>
                <th className="px-2 py-1.5 text-right border-b" style={{ borderColor: 'var(--color-apple-border)' }}>배송</th>
                <th className="px-2 py-1.5 text-right border-b" style={{ borderColor: 'var(--color-apple-border)' }}>총원가</th>
                <th className="px-2 py-1.5 text-right border-b" style={{ borderColor: 'var(--color-apple-border)' }}>이익</th>
                <th className="px-2 py-1.5 text-right border-b" style={{ borderColor: 'var(--color-apple-border)' }}>마진</th>
                <th className="px-2 py-1.5 text-center border-b" style={{ borderColor: 'var(--color-apple-border)' }}>평가</th>
                <th className="px-2 py-1.5 border-b" style={{ borderColor: 'var(--color-apple-border)' }}></th>
              </tr>
            </thead>
            <tbody>
              {results.map(({ opt, res }, i) => {
                const verdict = marginVerdict(res.margin_rate);
                const verdictColor = {
                  '우수': 'bg-emerald-100 text-emerald-800',
                  '양호': 'bg-blue-100 text-blue-800',
                  '애매': 'bg-amber-100 text-amber-800',
                  '부족': 'bg-orange-100 text-orange-800',
                  '손실': 'bg-red-100 text-red-800',
                }[verdict];
                const isBest = i === bestIdx && compositions.length > 1;
                const cellStyle = { borderColor: 'var(--color-apple-border)' };
                return (
                  <tr key={opt.id} className={isBest ? 'bg-amber-50' : 'hover:bg-apple-bg-3'} style={{ borderTop: '1px solid var(--color-apple-border)' }}>
                    <td className="px-1 py-0.5 border-r" style={cellStyle}>
                      <div className="flex items-center gap-1">
                        {isBest && <span className="text-amber-600 text-[10px]" title="최고 마진">★</span>}
                        <input
                          type="text"
                          value={opt.option_name || ''}
                          onChange={e => update(opt.id, { option_name: e.target.value })}
                          onFocus={e => e.currentTarget.select()}
                          placeholder="용량"
                          className={textInputClass}
                          style={{ background: 'transparent', border: 'none' }}
                        />
                      </div>
                    </td>
                    <td className="px-1 py-0.5 border-r" style={cellStyle}>
                      <input
                        type="text"
                        value={opt.option_value || ''}
                        onChange={e => update(opt.id, { option_value: e.target.value })}
                        onFocus={e => e.currentTarget.select()}
                        placeholder="30ml"
                        className={textInputClass}
                        style={{ background: 'transparent', border: 'none' }}
                      />
                    </td>
                    <td className="px-1 py-0.5 border-r" style={cellStyle}>
                      <input
                        type="text"
                        value={opt.quantity}
                        onChange={e => updateQuantity(opt.id, parseNum(e.target.value))}
                        onFocus={e => e.currentTarget.select()}
                        className={numInputClass}
                        style={{ background: 'transparent', border: 'none' }}
                      />
                    </td>
                    <td className="px-1 py-0.5 border-r" style={{ ...cellStyle, background: COST_BG }}>
                      <input
                        type="text"
                        value={opt.weight_g}
                        onChange={e => updateWeight(opt.id, parseNum(e.target.value))}
                        onFocus={e => e.currentTarget.select()}
                        className={numInputClass}
                        style={{ background: 'transparent', border: 'none' }}
                      />
                    </td>
                    <td className="px-1 py-0.5 border-r" style={{ ...cellStyle, background: COST_BG }}>
                      <input
                        type="text"
                        value={opt.item_price_krw}
                        onChange={e => update(opt.id, { item_price_krw: parseNum(e.target.value) })}
                        onFocus={e => e.currentTarget.select()}
                        className={numInputClass}
                        style={{ background: 'transparent', border: 'none' }}
                      />
                    </td>
                    <td className="px-1 py-0.5 border-r" style={{ ...cellStyle, background: COST_BG }}>
                      <input
                        type="text"
                        value={opt.domestic_shipping_krw}
                        onChange={e => update(opt.id, { domestic_shipping_krw: parseNum(e.target.value) })}
                        onFocus={e => e.currentTarget.select()}
                        className={numInputClass}
                        style={{ background: 'transparent', border: 'none' }}
                      />
                    </td>
                    <td className="px-1 py-0.5 border-r" style={{ ...cellStyle, background: COST_BG }}>
                      <input
                        type="text"
                        value={opt.shipping_packaging_krw}
                        onChange={e => update(opt.id, { shipping_packaging_krw: parseNum(e.target.value) })}
                        onFocus={e => e.currentTarget.select()}
                        className={numInputClass}
                        style={{ background: 'transparent', border: 'none' }}
                        title="무게 변경 시 자동 갱신. 수동 override 가능."
                      />
                    </td>
                    <td className="px-1 py-0.5 border-r" style={{ ...cellStyle, background: SELL_BG }}>
                      <input
                        type="text"
                        value={opt.sell_price_jpy}
                        onChange={e => update(opt.id, { sell_price_jpy: parseNum(e.target.value) })}
                        onFocus={e => e.currentTarget.select()}
                        className={`${numInputClass} font-semibold`}
                        style={{ background: 'transparent', border: 'none' }}
                      />
                    </td>
                    <td className="px-1 py-0.5 text-center border-r" style={cellStyle}>
                      <input
                        type="checkbox"
                        checked={opt.is_mega ?? false}
                        onChange={e => update(opt.id, { is_mega: e.target.checked })}
                        title="메가와리 10% 할인 적용"
                      />
                    </td>
                    <td className="px-1.5 py-0.5 text-right text-[10px] text-apple-text-3 border-r" style={cellStyle}>
                      {res.shipping_mode_resolved === 'free' ? '무료' : '유료'}
                      <div className="text-[9px] text-apple-text-3">{fmtKrw(res.shipping_cost_krw)}</div>
                    </td>
                    <td className="px-1.5 py-0.5 text-right text-apple-text-2 border-r" style={cellStyle}>{fmtKrw(res.total_cost_krw)}</td>
                    <td className={`px-1.5 py-0.5 text-right font-semibold border-r ${res.profit_krw >= 0 ? 'text-emerald-700' : 'text-red-700'}`} style={cellStyle}>
                      {fmtKrw(res.profit_krw)}
                    </td>
                    <td className={`px-1.5 py-0.5 text-right font-semibold border-r ${res.margin_rate >= 0 ? 'text-emerald-700' : 'text-red-700'}`} style={cellStyle}>
                      {fmtPct(res.margin_rate)}
                    </td>
                    <td className="px-1 py-0.5 text-center border-r" style={cellStyle}>
                      <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold ${verdictColor}`}>
                        {verdict}
                      </span>
                    </td>
                    <td className="px-1 py-0.5 text-center" style={cellStyle}>
                      <button
                        onClick={() => remove(opt.id)}
                        className="text-red-500 hover:text-red-700"
                        title="옵션 삭제"
                      >
                        <Trash2 size={12} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {compositions.length > 1 && bestIdx >= 0 && (
        <div className="mt-2 text-[11px] text-apple-text-3">
          ★ 최고 마진: <b className="text-apple-text-1">{compositions[bestIdx].option_value || compositions[bestIdx].label || `옵션 ${bestIdx + 1}`}</b> — {fmtPct(results[bestIdx].res.margin_rate)} ({fmtKrw(results[bestIdx].res.profit_krw)})
        </div>
      )}
    </div>
  );
}

/** 외부(메인 시트)에서 최고 마진 구성 요약을 뱃지로 표시할 때 사용. */
export function summarizeBestComposition(row: SheetRow): { label: string; margin_rate: number } | null {
  const list = row.compositions || [];
  if (list.length === 0) return null;
  let best: { label: string; margin_rate: number } | null = null;
  for (const c of list) {
    const res = calculateMargin({
      weight_g: c.weight_g || 0,
      purchase_price_krw: (c.item_price_krw || 0) + (c.domestic_shipping_krw || 0),
      shipping_packaging_krw: c.shipping_packaging_krw || 0,
      sell_price_jpy: c.sell_price_jpy || 0,
      exchange_rate: row.exchange_rate ?? 9.5,
      shipping_mode: row.shipping_mode ?? 'auto',
      is_mega: c.is_mega ?? false,
      quantity: 1,
    });
    const lab = c.option_value || c.label || '(옵션)';
    if (!best || res.margin_rate > best.margin_rate) {
      best = { label: lab, margin_rate: res.margin_rate };
    }
  }
  return best;
}

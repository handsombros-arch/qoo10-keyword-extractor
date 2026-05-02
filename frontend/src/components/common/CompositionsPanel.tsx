import { useMemo } from 'react';
import { calculateMargin, marginVerdict } from '../../lib/marginCalc';
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

export default function CompositionsPanel({ row, onChange, onClose }: Props) {
  const compositions = row.compositions || [];

  const update = (id: string, patch: Partial<CompositionOption>) => {
    onChange(compositions.map(c => (c.id === id ? { ...c, ...patch } : c)));
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
        quantity: 1, // 각 구성 자체가 이미 세트 기준이므로 1로 고정
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
    <div className="bg-white rounded-lg shadow-lg border border-blue-200 p-4 mt-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="font-semibold text-sm">
            📦 구성 옵션 편집 <span className="text-gray-500 font-normal">— {row.product_name_ko || row.product_name}</span>
          </h3>
          <div className="text-[11px] text-gray-500 mt-0.5">
            메인 행 단품값 (무게 {row.weight_g}g · 단가 {fmtKrw(row.item_price_krw)} · 판매가 {fmtJpy(row.sell_price_jpy)}) 기준으로 자동 채워집니다. 세트별로 자유 수정 가능.
          </div>
        </div>
        {onClose && (
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-sm px-2">✕ 닫기</button>
        )}
      </div>

      <div className="flex gap-1 mb-3 items-center flex-wrap">
        <span className="text-xs text-gray-600 mr-1">빠른 추가:</span>
        {PRESETS.map(n => (
          <button
            key={n}
            onClick={() => add(n)}
            className="text-xs px-2 py-0.5 bg-blue-50 text-blue-700 hover:bg-blue-100 border border-blue-200 rounded"
          >
            +{n === 1 ? '단품' : `${n}세트`}
          </button>
        ))}
        <button
          onClick={() => add()}
          className="text-xs px-2 py-0.5 bg-gray-100 hover:bg-gray-200 border border-gray-300 rounded"
          title="1개 기본값으로 빈 구성 추가"
        >
          + 빈 구성
        </button>
        {compositions.length > 0 && (
          <button
            onClick={() => onChange([])}
            className="ml-auto text-xs px-2 py-0.5 text-red-600 hover:text-red-800"
          >
            모든 구성 삭제
          </button>
        )}
      </div>

      {compositions.length === 0 ? (
        <div className="text-center py-6 text-gray-400 text-sm border border-dashed rounded">
          구성 없음. 위 버튼으로 단품/세트 옵션을 추가해 마진을 비교하세요.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead className="bg-gray-50 text-gray-700">
              <tr>
                <th className="border px-2 py-1 text-left">구성</th>
                <th className="border px-2 py-1 text-right">수량</th>
                <th className="border px-2 py-1 text-right">무게(g)</th>
                <th className="border px-2 py-1 text-right">구매가(원)</th>
                <th className="border px-2 py-1 text-right">구매배송(원)</th>
                <th className="border px-2 py-1 text-right">포장·KSE(원)</th>
                <th className="border px-2 py-1 text-right">판매가(¥)</th>
                <th className="border px-2 py-1 text-center">메가</th>
                <th className="border px-2 py-1 text-right">배송</th>
                <th className="border px-2 py-1 text-right">총원가</th>
                <th className="border px-2 py-1 text-right">이익</th>
                <th className="border px-2 py-1 text-right">마진</th>
                <th className="border px-2 py-1 text-center">평가</th>
                <th className="border px-2 py-1"></th>
              </tr>
            </thead>
            <tbody>
              {results.map(({ opt, res }, i) => {
                const verdict = marginVerdict(res.margin_rate);
                const verdictColor = {
                  '우수': 'bg-green-100 text-green-800',
                  '양호': 'bg-blue-100 text-blue-800',
                  '애매': 'bg-amber-100 text-amber-800',
                  '부족': 'bg-orange-100 text-orange-800',
                  '손실': 'bg-red-100 text-red-800',
                }[verdict];
                const isBest = i === bestIdx && compositions.length > 1;
                return (
                  <tr key={opt.id} className={isBest ? 'bg-yellow-50' : ''}>
                    <td className="border px-1 py-0.5">
                      <div className="flex items-center gap-1">
                        {isBest && <span className="text-yellow-600" title="최고 마진">⭐</span>}
                        <input
                          type="text"
                          value={opt.label}
                          onChange={e => update(opt.id, { label: e.target.value })}
                          className="w-24 border rounded px-1 py-0.5 text-[12px]"
                        />
                      </div>
                    </td>
                    <td className="border px-1 py-0.5 text-right">
                      <input
                        type="number" min={1}
                        value={opt.quantity}
                        onChange={e => update(opt.id, { quantity: Math.max(1, Number(e.target.value) || 1) })}
                        className="w-12 border rounded px-1 py-0.5 text-right text-[12px]"
                      />
                    </td>
                    <td className="border px-1 py-0.5 text-right">
                      <input
                        type="number" min={0}
                        value={opt.weight_g}
                        onChange={e => update(opt.id, { weight_g: Math.max(0, Number(e.target.value) || 0) })}
                        className="w-16 border rounded px-1 py-0.5 text-right text-[12px]"
                      />
                    </td>
                    <td className="border px-1 py-0.5 text-right">
                      <input
                        type="number" min={0}
                        value={opt.item_price_krw}
                        onChange={e => update(opt.id, { item_price_krw: Math.max(0, Number(e.target.value) || 0) })}
                        className="w-20 border rounded px-1 py-0.5 text-right text-[12px]"
                      />
                    </td>
                    <td className="border px-1 py-0.5 text-right">
                      <input
                        type="number" min={0}
                        value={opt.domestic_shipping_krw}
                        onChange={e => update(opt.id, { domestic_shipping_krw: Math.max(0, Number(e.target.value) || 0) })}
                        className="w-16 border rounded px-1 py-0.5 text-right text-[12px]"
                      />
                    </td>
                    <td className="border px-1 py-0.5 text-right">
                      <input
                        type="number" min={0}
                        value={opt.shipping_packaging_krw}
                        onChange={e => update(opt.id, { shipping_packaging_krw: Math.max(0, Number(e.target.value) || 0) })}
                        className="w-16 border rounded px-1 py-0.5 text-right text-[12px]"
                      />
                    </td>
                    <td className="border px-1 py-0.5 text-right">
                      <input
                        type="number" min={0}
                        value={opt.sell_price_jpy}
                        onChange={e => update(opt.id, { sell_price_jpy: Math.max(0, Number(e.target.value) || 0) })}
                        className="w-20 border rounded px-1 py-0.5 text-right text-[12px] bg-yellow-50 font-semibold"
                      />
                    </td>
                    <td className="border px-1 py-0.5 text-center">
                      <input
                        type="checkbox"
                        checked={opt.is_mega ?? false}
                        onChange={e => update(opt.id, { is_mega: e.target.checked })}
                        title="메가와리 10% 할인 적용"
                      />
                    </td>
                    <td className="border px-1 py-0.5 text-right text-[11px] text-gray-600">
                      {res.shipping_mode_resolved === 'free' ? '무료' : '유료'}
                      <br />
                      <span className="text-gray-400">{fmtKrw(res.shipping_cost_krw)}</span>
                    </td>
                    <td className="border px-1 py-0.5 text-right text-gray-600">{fmtKrw(res.total_cost_krw)}</td>
                    <td className={`border px-1 py-0.5 text-right font-semibold ${res.profit_krw >= 0 ? 'text-green-700' : 'text-red-700'}`}>
                      {fmtKrw(res.profit_krw)}
                    </td>
                    <td className={`border px-1 py-0.5 text-right font-semibold ${res.margin_rate >= 0 ? 'text-green-700' : 'text-red-700'}`}>
                      {fmtPct(res.margin_rate)}
                    </td>
                    <td className="border px-1 py-0.5 text-center">
                      <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold ${verdictColor}`}>
                        {verdict}
                      </span>
                    </td>
                    <td className="border px-1 py-0.5 text-center">
                      <button
                        onClick={() => remove(opt.id)}
                        className="text-red-500 hover:text-red-700 text-xs"
                        title="이 구성 삭제"
                      >
                        ✕
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
        <div className="mt-2 text-xs text-gray-600">
          ⭐ 최고 마진 구성: <b>{compositions[bestIdx].label}</b> — {fmtPct(results[bestIdx].res.margin_rate)} ({fmtKrw(results[bestIdx].res.profit_krw)})
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
    if (!best || res.margin_rate > best.margin_rate) {
      best = { label: c.label, margin_rate: res.margin_rate };
    }
  }
  return best;
}

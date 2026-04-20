import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import api from '../api/client';
import { calculateMargin } from '../api/endpoints';

interface Scenario {
  weight_g: number;
  purchase_price_krw: number;
  shipping_packaging_krw: number;
  sell_price_jpy: number;
  exchange_rate: number;
  is_mega: boolean;
  quantity: number;
  composition_label: string;
  shipping_mode_resolved: string;
  effective_sell_jpy: number;
  commission_jpy: number;
  shipping_cost_krw: number;
  revenue_krw: number;
  total_cost_krw: number;
  profit_krw: number;
  margin_rate: number;
  recommended_price_krw_30pct: number;
  verdict: string;
}

const fmt = {
  krw: (n: number) => `${Math.round(n).toLocaleString()}원`,
  jpy: (n: number) => `¥${Math.round(n).toLocaleString()}`,
  pct: (n: number) => `${(n * 100).toFixed(2)}%`,
};

const verdictColor: Record<string, string> = {
  우수: 'bg-green-100 text-green-700',
  양호: 'bg-blue-100 text-blue-700',
  애매: 'bg-amber-100 text-amber-700',
  부족: 'bg-orange-100 text-orange-700',
  손실: 'bg-red-100 text-red-700',
};

const shipLabel: Record<string, string> = {
  free_kse: '무료(KSE)',
  paid_tracx: '유료(Tracx)',
};

function ResultCard({ title, s, accent }: { title: string; s: Scenario; accent: string }) {
  const profit = s.profit_krw;
  const profitColor = profit >= 0 ? 'text-green-600' : 'text-red-600';
  return (
    <div className={`border-l-4 ${accent} bg-white rounded-lg shadow p-5`}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-semibold">{title}</h3>
        {s.verdict && (
          <span className={`text-xs font-semibold px-2 py-0.5 rounded ${verdictColor[s.verdict]}`}>
            {s.verdict}
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <div className="text-gray-500">실제 판매가(엔)</div>
        <div className="text-right font-mono">{fmt.jpy(s.effective_sell_jpy)}</div>
        <div className="text-gray-500">매출(원)</div>
        <div className="text-right font-mono">{fmt.krw(s.revenue_krw)}</div>
        <div className="text-gray-500">큐텐 수수료(엔)</div>
        <div className="text-right font-mono">{fmt.jpy(s.commission_jpy)}</div>
        <div className="text-gray-500">배송 ({shipLabel[s.shipping_mode_resolved] || s.shipping_mode_resolved})</div>
        <div className="text-right font-mono">{fmt.krw(s.shipping_cost_krw)}</div>
        <div className="text-gray-500">총 원가(원)</div>
        <div className="text-right font-mono">{fmt.krw(s.total_cost_krw)}</div>
        <div className="border-t col-span-2 my-1" />
        <div className="font-semibold">순이익(원)</div>
        <div className={`text-right font-mono font-bold text-lg ${profitColor}`}>{fmt.krw(profit)}</div>
        <div className="font-semibold">마진율</div>
        <div className={`text-right font-mono font-bold ${profitColor}`}>{fmt.pct(s.margin_rate)}</div>
      </div>
    </div>
  );
}

function CompositionRow({ c, isBest }: { c: Scenario; isBest: boolean }) {
  return (
    <tr className={`border-b ${isBest ? 'bg-green-50' : ''}`}>
      <td className="px-3 py-2 font-semibold">
        {c.composition_label}
        {isBest && <span className="ml-2 text-[10px] bg-green-600 text-white px-1.5 py-0.5 rounded">추천</span>}
      </td>
      <td className="px-3 py-2 text-right font-mono">{fmt.jpy(c.effective_sell_jpy)}</td>
      <td className="px-3 py-2 text-right font-mono text-gray-500">{fmt.krw(c.revenue_krw)}</td>
      <td className="px-3 py-2 text-center text-xs">{shipLabel[c.shipping_mode_resolved]}</td>
      <td className="px-3 py-2 text-right font-mono">{fmt.krw(c.shipping_cost_krw)}</td>
      <td className={`px-3 py-2 text-right font-mono font-bold ${c.profit_krw >= 0 ? 'text-green-600' : 'text-red-600'}`}>
        {fmt.krw(c.profit_krw)}
      </td>
      <td className="px-3 py-2 text-right font-mono font-bold">{fmt.pct(c.margin_rate)}</td>
      <td className="px-3 py-2 text-center">
        <span className={`text-xs font-semibold px-2 py-0.5 rounded ${verdictColor[c.verdict]}`}>{c.verdict}</span>
      </td>
    </tr>
  );
}

export default function MarginPage() {
  const [params] = useSearchParams();
  const [form, setForm] = useState({
    weight_g: Number(params.get('weight_g') ?? 500),
    purchase_price_krw: Number(params.get('purchase_krw') ?? 22200),
    shipping_packaging_krw: Number(params.get('shipping_krw') ?? 3000),
    sell_price_jpy: Number(params.get('sell_jpy') ?? 4300),
    exchange_rate: Number(params.get('rate') ?? 9.5),
    use_exact_rate: params.get('exact') === '1',
    shipping_mode: (params.get('shipping') ?? 'auto') as 'auto' | 'free_kse' | 'paid_tracx',
  });
  const productName = params.get('name') ?? '';
  const [result, setResult] = useState<{ normal: Scenario; mega: Scenario } | null>(null);
  const [compositions, setCompositions] = useState<{ compositions: Scenario[]; best_composition_label: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const runAll = async () => {
    setLoading(true);
    setErr(null);
    try {
      const [mainRes, compRes] = await Promise.all([
        calculateMargin(form),
        api.post('/margin/analyze-compositions', form),
      ]);
      setResult(mainRes.data);
      setCompositions(compRes.data);
    } catch (e: any) {
      setErr(e?.message || '계산 실패');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (params.get('sell_jpy') || params.get('purchase_krw')) {
      runAll();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    runAll();
  };

  const update = (k: keyof typeof form, v: any) =>
    setForm(prev => ({ ...prev, [k]: v }));

  const normalVerdict = result?.normal.verdict;
  const showComposition = compositions && (normalVerdict === '애매' || normalVerdict === '부족' || normalVerdict === '손실');

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">💹 큐텐 마진 계산기</h2>

      {productName && (
        <div className="bg-amber-50 border-l-4 border-amber-400 text-sm p-3 mb-4 rounded">
          📦 대상 상품: <b>{productName}</b>
        </div>
      )}
      <div className="bg-blue-50 border-l-4 border-blue-400 text-xs p-3 mb-4 rounded">
        💡 <b>자동 배송</b>: 원화 판매가 20,000원 미만 → 유료(Tracx) / 이상 → 무료(KSE). 무게는 <b>실무게 + 100g</b> 입력.
      </div>

      <form onSubmit={onSubmit} className="bg-white rounded-lg shadow p-5 mb-6">
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          <label className="text-sm">
            <div className="text-gray-600 mb-1">무료배송 무게(g)</div>
            <input type="number" step="any" value={form.weight_g}
              onChange={e => update('weight_g', +e.target.value)}
              className="w-full border rounded px-2 py-1.5" required />
          </label>
          <label className="text-sm">
            <div className="text-gray-600 mb-1">구매가(원) <span className="text-gray-400">구매원가+국내배송</span></div>
            <input type="number" step="any" value={form.purchase_price_krw}
              onChange={e => update('purchase_price_krw', +e.target.value)}
              className="w-full border rounded px-2 py-1.5" required />
          </label>
          <label className="text-sm">
            <div className="text-gray-600 mb-1">배송비+포장비(원) <span className="text-gray-400">KSE까지</span></div>
            <input type="number" step="any" value={form.shipping_packaging_krw}
              onChange={e => update('shipping_packaging_krw', +e.target.value)}
              className="w-full border rounded px-2 py-1.5" required />
          </label>
          <label className="text-sm">
            <div className="text-gray-600 mb-1">큐텐 판매가(엔)</div>
            <input type="number" step="any" value={form.sell_price_jpy}
              onChange={e => update('sell_price_jpy', +e.target.value)}
              className="w-full border rounded px-2 py-1.5" required />
          </label>
          <label className="text-sm">
            <div className="text-gray-600 mb-1">환율(1엔=원)</div>
            <input type="number" step="0.01" value={form.exchange_rate}
              onChange={e => update('exchange_rate', +e.target.value)}
              className="w-full border rounded px-2 py-1.5" required />
          </label>
          <label className="text-sm">
            <div className="text-gray-600 mb-1">배송 모드</div>
            <select value={form.shipping_mode}
              onChange={e => update('shipping_mode', e.target.value)}
              className="w-full border rounded px-2 py-1.5">
              <option value="auto">자동 (20,000원 기준)</option>
              <option value="free_kse">무료 (KSE 해상)</option>
              <option value="paid_tracx">유료 (Tracx 항공)</option>
            </select>
          </label>
          <label className="text-sm flex items-end pb-1 gap-2 col-span-2 md:col-span-3">
            <input type="checkbox" checked={form.use_exact_rate}
              onChange={e => update('use_exact_rate', e.target.checked)} />
            <span className="text-gray-700 text-xs">
              정확 환율로 이익 계산 (체크 안 하면 원본 시트처럼 ×10 대략 환율)
            </span>
          </label>
        </div>
        <div className="mt-4 flex gap-3">
          <button type="submit" disabled={loading}
            className="bg-blue-600 text-white px-4 py-2 rounded text-sm disabled:opacity-50">
            {loading ? '계산 중...' : '계산'}
          </button>
          {err && <span className="text-red-600 text-sm self-center">{err}</span>}
        </div>
      </form>

      {result && (
        <div className="mb-6">
          <div className="mb-3 text-sm text-gray-600">
            30% 마진 권장가: <b className="text-gray-800">{fmt.krw(result.normal.recommended_price_krw_30pct)}</b>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <ResultCard title="일반가 (단품)" s={result.normal} accent="border-blue-500" />
            <ResultCard title="메가와리 (10% 할인)" s={result.mega} accent="border-amber-500" />
          </div>
        </div>
      )}

      {showComposition && compositions && (
        <div className="bg-white rounded-lg shadow p-5">
          <h3 className="text-lg font-semibold mb-1">📦 구성 제안</h3>
          <p className="text-xs text-gray-500 mb-3">
            단품 마진이 <b className="text-amber-600">{normalVerdict}</b>입니다. 2개/3개 세트 구성으로 단가 올려 마진 개선 가능한지 확인하세요.
          </p>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-3 py-2 text-left">구성</th>
                <th className="px-3 py-2 text-right">판매가(엔)</th>
                <th className="px-3 py-2 text-right">매출(원)</th>
                <th className="px-3 py-2 text-center">배송</th>
                <th className="px-3 py-2 text-right">배송비</th>
                <th className="px-3 py-2 text-right">순이익</th>
                <th className="px-3 py-2 text-right">마진율</th>
                <th className="px-3 py-2 text-center">평가</th>
              </tr>
            </thead>
            <tbody>
              {compositions.compositions.map(c => (
                <CompositionRow key={c.composition_label} c={c}
                  isBest={c.composition_label === compositions.best_composition_label} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

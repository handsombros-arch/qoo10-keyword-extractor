import { useEffect, useMemo, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import api from '../api/client';

type ReviewMatch = {
  image_score: number | null;
  name_score: number | null;
  note: string;
  decision: string;
};

type ReviewQoo10 = {
  cover_image_url: string;
  product_name_jp: string;
  product_name_ko: string;
  title_jp: string;
  tags: string[];
  marketing_points: string[];
  option_name: string;
};

type ReviewOption = {
  name: string;
  price_krw: number | null;
  in_stock: boolean;
};

type ReviewCandidate = {
  keyword_jp: string;
  keyword_kr: string;
  search_volume: number;
  kr_ratio: number;
  competition_intensity: number;
  qoo10_count: number;
  qoo10_avg_jpy: number;
  qoo10_min_jpy: number;
  qoo10_max_jpy: number;
  cheapest_domestic: {
    id: number;
    source: string;
    product_name: string;
    price_krw: number;
    product_url: string;
    cover_image_url: string;
    match_source: string;
    options: ReviewOption[];
  } | null;
  margin: {
    profit_krw: number;
    margin_rate: number;
    verdict: string;
    sell_price_jpy: number;
    purchase_price_krw: number;
  };
  final_score: number;
  qoo10?: ReviewQoo10;
  match?: ReviewMatch;
  options_full?: ReviewOption[];
};

type ReviewPayload = {
  date: string;
  generated_at?: string;
  count: number;
  candidates: ReviewCandidate[];
  error?: string;
};

type LocalEdit = {
  weight_g: number;
  sell_price_jpy: number;
  status: 'pending' | 'sent' | 'rejected';
  selected: boolean;
};

const EXCHANGE_RATE = 9.5;
const COMMISSION = 0.135;
const FREE_THRESHOLD = 20000;

function fmtKrw(n: number) { return Math.round(n).toLocaleString() + '원'; }

function verdictColor(rate: number): string {
  if (rate >= 0.30) return 'text-emerald-700 font-semibold';
  if (rate >= 0.20) return 'text-emerald-600 font-semibold';
  if (rate >= 0.10) return 'text-amber-600';
  if (rate >= 0) return 'text-orange-600';
  return 'text-red-700 font-semibold';
}

function lookupKseShipping(weight_g: number): number {
  // 간단한 KSE 가정 — 100g당 200원 (실제는 KSE 표 lookup)
  if (weight_g <= 0) return 0;
  if (weight_g <= 500) return 5000;
  if (weight_g <= 1000) return 7000;
  if (weight_g <= 2000) return 10000;
  return 12000 + Math.ceil((weight_g - 2000) / 1000) * 2000;
}

function calcMargin(c: ReviewCandidate, edit: LocalEdit) {
  const ip = c.cheapest_domestic?.price_krw || 0;
  const sj = edit.sell_price_jpy || c.margin?.sell_price_jpy || c.qoo10_avg_jpy || 0;
  const w = edit.weight_g || 0;
  const sellKrwForMode = sj * EXCHANGE_RATE;
  const free = sellKrwForMode >= FREE_THRESHOLD;
  const ship = free ? lookupKseShipping(w) : 0;
  const commission = sj * COMMISSION * 10;
  const totalCost = ip + 3000 + commission + ship; // 3000 = packaging+배대지
  const revenue = sj * 10;
  const profit = revenue - totalCost;
  const rate = sj > 0 ? profit / (sj * EXCHANGE_RATE) : 0;
  return { totalCost, revenue, profit, rate };
}

export default function ReviewPage() {
  const { date: paramDate } = useParams<{ date: string }>();
  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate] = useState(paramDate || today);
  const [data, setData] = useState<ReviewPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showOnlyAccepted, setShowOnlyAccepted] = useState(false);
  const [edits, setEdits] = useState<Record<string, LocalEdit>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState('');

  async function load(d: string) {
    setLoading(true); setError('');
    try {
      const res = await api.get<ReviewPayload>(`/review/${d}`);
      setData(res.data);
      // 초기 edit — qoo10_avg 를 sell_price 로
      const init: Record<string, LocalEdit> = {};
      for (const c of res.data.candidates || []) {
        init[c.keyword_jp] = {
          weight_g: 0,
          sell_price_jpy: Math.round(c.qoo10_avg_jpy || 0),
          status: 'pending',
          selected: false,
        };
      }
      setEdits(init);
    } catch (e: any) {
      setError(e?.response?.data?.error || e.message || 'fetch 실패');
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(date); }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  function patchEdit(kw: string, p: Partial<LocalEdit>) {
    setEdits(prev => ({ ...prev, [kw]: { ...prev[kw], ...p } }));
  }

  const filtered = useMemo(() => {
    if (!data?.candidates) return [];
    if (!showOnlyAccepted) return data.candidates;
    return data.candidates.filter(c => c.match?.decision === 'accepted');
  }, [data, showOnlyAccepted]);

  const acceptedCount = data?.candidates.filter(c => c.match?.decision === 'accepted').length || 0;

  async function sendToSheet(c: ReviewCandidate) {
    const edit = edits[c.keyword_jp];
    if (!edit) return;
    if (!edit.weight_g) {
      if (!confirm('무게가 비어있습니다. 그래도 시트로 보내시겠습니까?')) return;
    }
    setBusy(c.keyword_jp);
    try {
      const item = {
        keyword_jp: c.keyword_jp,
        product_name: c.cheapest_domestic?.product_name || '',
        product_name_ko: c.qoo10?.product_name_ko || '',
        product_url: c.cheapest_domestic?.product_url || '',
        cover_image_url: c.cheapest_domestic?.cover_image_url || '',
        weight_g: edit.weight_g,
        item_price_krw: c.cheapest_domestic?.price_krw || 0,
        domestic_shipping_krw: 0,
        shipping_packaging_krw: 3000,
        sell_price_jpy: edit.sell_price_jpy,
        exchange_rate: EXCHANGE_RATE,
        shipping_mode: 'auto',
      };
      const res = await api.post(`/recommend/send-to-sheet/${data?.date}`, { items: [item] });
      patchEdit(c.keyword_jp, { status: 'sent' });
      setToast(`✓ ${c.keyword_jp} 시트 추가 (${res.data.added || 1}건)`);
    } catch (e: any) {
      setToast(`✗ ${e?.response?.data?.error || e.message}`);
    } finally {
      setBusy(null);
      setTimeout(() => setToast(''), 4000);
    }
  }

  function reject(c: ReviewCandidate) {
    patchEdit(c.keyword_jp, { status: 'rejected' });
    setToast(`◯ ${c.keyword_jp} 거부 표시`);
    setTimeout(() => setToast(''), 3000);
  }

  function toggleSelectAll(on: boolean) {
    setEdits(prev => {
      const next = { ...prev };
      for (const c of filtered) {
        if (next[c.keyword_jp] && next[c.keyword_jp].status === 'pending') {
          next[c.keyword_jp] = { ...next[c.keyword_jp], selected: on };
        }
      }
      return next;
    });
  }

  async function sendSelectedToSheet() {
    const targets = filtered.filter(c => edits[c.keyword_jp]?.selected && edits[c.keyword_jp]?.status === 'pending');
    if (targets.length === 0) {
      setToast('선택된 항목 없음');
      setTimeout(() => setToast(''), 3000);
      return;
    }
    const missingWeight = targets.filter(c => !edits[c.keyword_jp].weight_g).length;
    if (missingWeight > 0) {
      if (!confirm(`${targets.length}건 중 ${missingWeight}건 무게 비어있음. 그래도 진행?`)) return;
    } else {
      if (!confirm(`${targets.length}건을 시트로 보냅니다.`)) return;
    }
    setBusy('__bulk__');
    let added = 0; let failed = 0;
    for (const c of targets) {
      const edit = edits[c.keyword_jp];
      try {
        const item = {
          keyword_jp: c.keyword_jp,
          product_name: c.cheapest_domestic?.product_name || '',
          product_name_ko: c.qoo10?.product_name_ko || '',
          product_url: c.cheapest_domestic?.product_url || '',
          cover_image_url: c.cheapest_domestic?.cover_image_url || '',
          weight_g: edit.weight_g,
          item_price_krw: c.cheapest_domestic?.price_krw || 0,
          domestic_shipping_krw: 0,
          shipping_packaging_krw: 3000,
          sell_price_jpy: edit.sell_price_jpy,
          exchange_rate: EXCHANGE_RATE,
          shipping_mode: 'auto',
        };
        const res = await api.post(`/recommend/send-to-sheet/${data?.date}`, { items: [item] });
        if (res.data.error) failed++;
        else { added += res.data.added || 1; patchEdit(c.keyword_jp, { status: 'sent', selected: false }); }
      } catch {
        failed++;
      }
    }
    setBusy(null);
    setToast(`✓ 일괄 ${added}건 추가 / 실패 ${failed}`);
    setTimeout(() => setToast(''), 5000);
  }

  async function exportQoo10Excel() {
    if (!data?.date) return;
    setBusy('__export__');
    try {
      // 시트에 있는 항목 일괄 export
      const res = await api.post(`/products/qoo10/export-excel`, {}, { responseType: 'blob' });
      const url = URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement('a');
      a.href = url;
      a.download = `qoo10_export_${data.date}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
      setToast('✓ 큐텐 엑셀 다운로드 완료');
    } catch (e: any) {
      setToast(`✗ export 실패: ${e?.response?.data?.error || e.message}`);
    } finally {
      setBusy(null);
      setTimeout(() => setToast(''), 4000);
    }
  }

  const selectedCount = filtered.filter(c => edits[c.keyword_jp]?.selected).length;

  return (
    <div className="p-4 max-w-7xl mx-auto">
      <div className="flex items-center gap-3 mb-3">
        <Link to="/recommend-products" className="text-blue-600 text-sm">← 시트 빌드 페이지</Link>
        <h1 className="text-xl font-bold">검수 페이지</h1>
        <input
          type="date"
          value={date}
          onChange={e => setDate(e.target.value)}
          className="border rounded px-2 py-1 text-sm"
        />
        <button
          onClick={() => load(date)}
          className="bg-blue-600 text-white px-3 py-1 rounded text-sm hover:bg-blue-700"
        >불러오기</button>
        <label className="flex items-center gap-1 text-sm">
          <input
            type="checkbox"
            checked={showOnlyAccepted}
            onChange={e => setShowOnlyAccepted(e.target.checked)}
          />
          accepted 만 ({acceptedCount}/{data?.count || 0})
        </label>
        {toast && <span className="ml-auto text-sm bg-amber-100 text-amber-900 px-3 py-1 rounded">{toast}</span>}
      </div>

      <div className="sticky top-0 bg-white border-b z-10 py-2 mb-3 flex items-center gap-2 text-sm">
        <button
          onClick={() => toggleSelectAll(true)}
          className="px-3 py-1 bg-gray-100 hover:bg-gray-200 rounded text-xs"
        >전체 선택</button>
        <button
          onClick={() => toggleSelectAll(false)}
          className="px-3 py-1 bg-gray-100 hover:bg-gray-200 rounded text-xs"
        >해제</button>
        <span className="text-xs text-gray-600">{selectedCount}개 선택</span>
        <button
          onClick={sendSelectedToSheet}
          disabled={busy === '__bulk__' || selectedCount === 0}
          className="ml-auto px-4 py-1 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white rounded text-xs font-semibold"
        >{busy === '__bulk__' ? '전송 중...' : `선택 ${selectedCount}건 시트로 보내기`}</button>
        <button
          onClick={exportQoo10Excel}
          disabled={busy === '__export__'}
          className="px-4 py-1 bg-emerald-600 hover:bg-emerald-700 disabled:bg-gray-400 text-white rounded text-xs font-semibold"
        >{busy === '__export__' ? '생성 중...' : '큐텐 엑셀 다운'}</button>
      </div>

      {loading && <div className="text-gray-500">로딩...</div>}
      {error && <div className="text-red-600">에러: {error}</div>}
      {data && data.count === 0 && <div className="text-gray-500">데이터 없음 (야간 자동화 실행 필요)</div>}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {filtered.map(c => {
          const edit = edits[c.keyword_jp] || { weight_g: 0, sell_price_jpy: 0, status: 'pending' };
          const calc = calcMargin(c, edit);
          const ch = c.cheapest_domestic;
          const q = c.qoo10;
          const opts = c.options_full || [];
          const dec = c.match?.decision || 'pending';
          const decColor = dec === 'accepted' ? 'bg-emerald-100 text-emerald-800'
            : dec === 'rejected' ? 'bg-red-100 text-red-800'
            : 'bg-gray-100 text-gray-700';
          const cardOpacity = edit.status === 'sent' ? 'opacity-50'
            : edit.status === 'rejected' ? 'opacity-30' : '';

          return (
            <div key={c.keyword_jp} className={`border rounded-lg p-3 bg-white shadow-sm ${cardOpacity}`}>
              <div className="flex items-start justify-between mb-2">
                <div className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    checked={!!edit.selected}
                    disabled={edit.status !== 'pending'}
                    onChange={e => patchEdit(c.keyword_jp, { selected: e.target.checked })}
                    className="mt-1"
                  />
                  <div>
                    <div className="font-bold text-base">{c.keyword_jp}</div>
                    <div className="text-xs text-gray-500">
                      {c.keyword_kr} · 검색 {c.search_volume.toLocaleString()} ·
                      KR {(c.kr_ratio * 100).toFixed(0)}%
                    </div>
                  </div>
                </div>
                <span className={`text-xs px-2 py-0.5 rounded ${decColor}`}>{dec}</span>
              </div>

              <div className="grid grid-cols-2 gap-2 mb-2">
                <div>
                  <div className="text-xs font-semibold text-gray-600 mb-1">큐텐</div>
                  {q?.cover_image_url ? (
                    <img src={q.cover_image_url} className="w-full h-32 object-contain bg-gray-50 border rounded" />
                  ) : <div className="w-full h-32 bg-gray-100 border rounded flex items-center justify-center text-gray-400 text-xs">no image</div>}
                  <div className="text-[10px] text-gray-500 mt-1 truncate">{q?.product_name_jp || '-'}</div>
                </div>
                <div>
                  <div className="text-xs font-semibold text-gray-600 mb-1">한국 ({ch?.source})</div>
                  {ch?.cover_image_url ? (
                    <img src={ch.cover_image_url} className="w-full h-32 object-contain bg-gray-50 border rounded" />
                  ) : <div className="w-full h-32 bg-gray-100 border rounded flex items-center justify-center text-gray-400 text-xs">no image</div>}
                  <div className="text-[10px] text-gray-500 mt-1 truncate">
                    <a href={ch?.product_url} target="_blank" rel="noreferrer" className="text-blue-600">
                      {ch?.product_name || '-'}
                    </a>
                  </div>
                </div>
              </div>

              {c.match && (
                <div className="text-xs bg-gray-50 border rounded p-2 mb-2">
                  <span className="mr-3">img <b>{c.match.image_score?.toFixed(2) ?? '-'}</b></span>
                  <span className="mr-3">txt <b>{c.match.name_score?.toFixed(2) ?? '-'}</b></span>
                  <span className="text-gray-600">{c.match.note}</span>
                </div>
              )}

              {q?.title_jp && (
                <div className="text-xs mb-2">
                  <div className="font-semibold text-gray-600 mb-0.5">큐텐 SEO 콘텐츠</div>
                  <div className="text-gray-800">title: {q.title_jp}</div>
                  {q.tags && q.tags.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1">
                      {q.tags.slice(0, 8).map((t, i) => (
                        <span key={i} className="bg-blue-50 text-blue-700 px-1.5 py-0.5 rounded text-[10px]">{t}</span>
                      ))}
                    </div>
                  )}
                  {q.marketing_points && q.marketing_points.length > 0 && (
                    <ul className="mt-1 list-disc list-inside text-gray-700">
                      {q.marketing_points.slice(0, 4).map((m, i) => <li key={i} className="text-[11px]">{m}</li>)}
                    </ul>
                  )}
                </div>
              )}

              {opts.length > 0 && (
                <div className="text-xs mb-2">
                  <div className="font-semibold text-gray-600">옵션 ({opts.length})</div>
                  <ul className="text-[11px] text-gray-700">
                    {opts.slice(0, 5).map((o, i) => (
                      <li key={i}>· {o.name} {o.price_krw ? `— ${fmtKrw(o.price_krw)}` : ''}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="flex items-center gap-2 text-xs mb-2">
                <label className="flex items-center gap-1">무게(g)
                  <input
                    type="number" value={edit.weight_g || ''}
                    onChange={e => patchEdit(c.keyword_jp, { weight_g: Number(e.target.value) || 0 })}
                    className="w-20 border rounded px-1 py-0.5"
                    placeholder="필수"
                  />
                </label>
                <label className="flex items-center gap-1">판매(엔)
                  <input
                    type="number" value={edit.sell_price_jpy || ''}
                    onChange={e => patchEdit(c.keyword_jp, { sell_price_jpy: Number(e.target.value) || 0 })}
                    className="w-24 border rounded px-1 py-0.5"
                  />
                </label>
              </div>

              <div className="flex items-center justify-between mb-2 text-xs bg-gray-50 border rounded p-2">
                <div>구매 <b>{fmtKrw(ch?.price_krw || 0)}</b></div>
                <div>매출 <b>{fmtKrw(calc.revenue)}</b></div>
                <div>이익 <b className={verdictColor(calc.rate)}>{fmtKrw(calc.profit)}</b></div>
                <div className={verdictColor(calc.rate)}>마진 <b>{(calc.rate * 100).toFixed(1)}%</b></div>
              </div>

              <div className="flex gap-2">
                <button
                  disabled={busy === c.keyword_jp || edit.status !== 'pending'}
                  onClick={() => sendToSheet(c)}
                  className="flex-1 bg-blue-600 text-white py-1.5 rounded text-xs font-semibold hover:bg-blue-700 disabled:bg-gray-400"
                >
                  {edit.status === 'sent' ? '✓ 시트 추가됨' : busy === c.keyword_jp ? '전송 중...' : '시트로 보내기'}
                </button>
                <button
                  disabled={edit.status !== 'pending'}
                  onClick={() => reject(c)}
                  className="px-3 bg-gray-200 hover:bg-gray-300 py-1.5 rounded text-xs disabled:opacity-40"
                >거부</button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

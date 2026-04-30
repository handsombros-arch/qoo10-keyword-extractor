/**
 * 시트 상단 통합 toolbar (TT-2).
 *
 * 4가지 source 한 곳에서 시트로 머지:
 *   [+ 자동화 결과 (date picker)] — /api/review/{date} fetch → 모든 candidate row
 *   [+ 키워드 추가]                 — modal: 빈 row 1건
 *   [+ 큐텐 샵 분석]                — modal: 샵 URL → recommendations/from-shop
 *   [+ 트렌드 키워드]               — modal: keywords API → 선택 row
 *
 * 모든 결과는 SheetRow 양식으로 통일되어 메인 시트에 머지 (newSheetRow()).
 */
import { useState } from 'react';
import api from '../api/client';
import { newSheetRow, type SheetRow } from '../store/productSheet';

type Props = {
  onMergeRows: (newRows: SheetRow[], dedupKey?: 'keyword_jp' | 'product_name') => number;
};

export default function SheetSourceToolbar({ onMergeRows }: Props) {
  const [openModal, setOpenModal] = useState<null | 'auto' | 'shop' | 'trend'>(null);

  return (
    <div className="flex items-center gap-1.5 mr-2">
      <span className="text-[11px] text-gray-500 mr-1">+ 시트 추가:</span>
      <button
        onClick={() => setOpenModal('auto')}
        className="px-2 py-1 bg-emerald-100 hover:bg-emerald-200 text-emerald-800 text-[11px] rounded font-medium"
      >🌙 자동화</button>
      <button
        onClick={() => setOpenModal('shop')}
        className="px-2 py-1 bg-purple-100 hover:bg-purple-200 text-purple-800 text-[11px] rounded font-medium"
      >🏪 큐텐 샵</button>
      <button
        onClick={() => setOpenModal('trend')}
        className="px-2 py-1 bg-amber-100 hover:bg-amber-200 text-amber-800 text-[11px] rounded font-medium"
      >📈 트렌드</button>

      {openModal === 'auto' && (
        <AutoResultModal onClose={() => setOpenModal(null)} onMerge={onMergeRows} />
      )}
      {openModal === 'shop' && (
        <ShopAnalysisModal onClose={() => setOpenModal(null)} onMerge={onMergeRows} />
      )}
      {openModal === 'trend' && (
        <TrendKeywordModal onClose={() => setOpenModal(null)} onMerge={onMergeRows} />
      )}
    </div>
  );
}

// ─── 1) 자동화 결과 머지 ─────────────────────────

function AutoResultModal({ onClose, onMerge }: { onClose: () => void; onMerge: Props['onMergeRows'] }) {
  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate] = useState(today);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');

  async function load() {
    setBusy(true); setMsg('');
    try {
      const r = await api.get<{ candidates: any[] }>(`/review/${date}`);
      const cands = r.data.candidates || [];
      if (!cands.length) { setMsg('후보 0건 — 다른 날짜 확인'); return; }

      // 폴더 매핑 (folder_index/name + qoo10_url) — STEP 6.7 출력
      const folderMap: Record<string, any> = {};
      try {
        const fr = await api.get<{ data: { items: any[] } | null }>(`/user-data/last_candidate_folders:${date}`);
        const items = fr.data?.data?.items || [];
        for (const it of items) {
          if (it.keyword_jp) folderMap[it.keyword_jp] = it;
        }
      } catch { /* 매핑 없으면 빈 값으로 진행 */ }

      const rows: SheetRow[] = cands.map(c => {
        const fm = folderMap[c.keyword_jp] || {};
        const cd = c.cheapest_domestic;
        // PPP-1: 한국 검색 결과 0건 — 사장님이 직접 한국 SKU 찾아야 함
        const needsSearch = !cd || !cd.product_name;
        return newSheetRow({
          keyword_jp: c.keyword_jp,
          keyword_kr: c.keyword_kr,
          product_name: needsSearch ? '' : (cd.product_name || c.keyword_jp),
          product_name_ko: c.qoo10?.product_name_ko || '',
          product_url: cd?.product_url || '',
          qoo10_url: fm.qoo10_url || '',
          cover_image_url: cd?.cover_image_url || '',
          qoo10_cover_image_url: fm.qoo10_cover_image_url || '',
          folder_index: fm.folder_index ?? undefined,
          folder_name: fm.folder_name || '',
          item_price_krw: cd?.price_krw || 0,
          sell_price_jpy: Math.round(c.qoo10_avg_jpy || 0),
          competitor_price_jpy: Math.round(c.qoo10_avg_jpy || 0),
          source: `auto:${date}`,
          created_at: date,
          match_decision: needsSearch
            ? 'needs_search'
            : (c.match?.decision || cd.match_source || 'pending'),
          match_image_score: c.match?.image_score ?? undefined,
          match_name_score: c.match?.name_score ?? undefined,
          match_note: c.match?.note || '',
          qoo10_title_jp: c.qoo10?.title_jp || '',
          qoo10_tags: c.qoo10?.tags || [],
          qoo10_marketing: c.qoo10?.marketing_points || [],
          qoo10_option_name: c.qoo10?.option_name || '',
          qoo10_jp_detail: c.qoo10?.jp_detail || undefined,  // FFFF-1
        });
      });
      // folder_index 순으로 정렬 (1, 2, 3, ...)
      rows.sort((a, b) => (a.folder_index ?? 999) - (b.folder_index ?? 999));
      const added = onMerge(rows, 'keyword_jp');
      setMsg(`✓ ${added}건 추가 (${cands.length}건 중 중복 제외)`);
      setTimeout(onClose, 1500);
    } catch (e: any) {
      setMsg(`✗ ${e?.response?.data?.error || e.message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="🌙 야간 자동화 결과 → 시트로" onClose={onClose}>
      <div className="space-y-3 text-sm">
        <div>
          <label className="block mb-1 text-gray-600">날짜</label>
          <input type="date" value={date} onChange={e => setDate(e.target.value)}
            className="border rounded px-2 py-1" />
        </div>
        <button onClick={load} disabled={busy}
          className="w-full bg-emerald-600 text-white py-2 rounded font-semibold hover:bg-emerald-700 disabled:bg-gray-400">
          {busy ? '로딩...' : '자동화 후보 불러와서 시트에 추가'}
        </button>
        {msg && <div className="text-xs">{msg}</div>}
      </div>
    </Modal>
  );
}

// ─── 2) 키워드 직접 추가 — 사용자 피드백으로 폐기 (KeywordPage 통합 예정) ───
// @ts-expect-error 미사용 (UU-2 통합 작업 후 부활 가능)
function ManualKeywordModal({ onClose, onMerge }: { onClose: () => void; onMerge: Props['onMergeRows'] }) {
  const [kwJp, setKwJp] = useState('');
  const [kwKr, setKwKr] = useState('');
  const [productName, setProductName] = useState('');

  function add() {
    const jp = kwJp.trim();
    const kr = kwKr.trim();
    const name = productName.trim() || jp || kr;
    if (!name) return;
    const row = newSheetRow({
      keyword_jp: jp,
      keyword_kr: kr,
      product_name: name,
      source: 'manual',
      match_decision: 'manual',
    });
    const added = onMerge([row], 'keyword_jp');
    if (added > 0) onClose();
  }

  return (
    <Modal title="✏ 키워드 직접 추가" onClose={onClose}>
      <div className="space-y-3 text-sm">
        <div>
          <label className="block mb-1 text-gray-600">키워드 (일본어)</label>
          <input value={kwJp} onChange={e => setKwJp(e.target.value)}
            placeholder="예: メディキューブ AGE-R"
            className="w-full border rounded px-2 py-1" />
        </div>
        <div>
          <label className="block mb-1 text-gray-600">키워드 (한국어, 선택)</label>
          <input value={kwKr} onChange={e => setKwKr(e.target.value)}
            placeholder="예: 메디큐브 AGE-R"
            className="w-full border rounded px-2 py-1" />
        </div>
        <div>
          <label className="block mb-1 text-gray-600">상품명 (선택, 비우면 키워드 사용)</label>
          <input value={productName} onChange={e => setProductName(e.target.value)}
            className="w-full border rounded px-2 py-1" />
        </div>
        <button onClick={add}
          className="w-full bg-gray-700 text-white py-2 rounded font-semibold hover:bg-gray-800">
          시트에 추가 (URL/원가는 직접 입력)
        </button>
      </div>
    </Modal>
  );
}

// ─── 3) 큐텐 샵 분석 ─────────────────────────

function ShopAnalysisModal({ onClose, onMerge }: { onClose: () => void; onMerge: Props['onMergeRows'] }) {
  const [shopUrl, setShopUrl] = useState('');
  const [limit, setLimit] = useState(20);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');

  async function analyze() {
    if (!shopUrl.trim()) return;
    setBusy(true); setMsg('');
    try {
      const r = await api.post<{ products: any[] }>('/recommendations/from-shop', {
        shop_url: shopUrl.trim(),
        limit_per_shop: limit,
      });
      const products = r.data.products || [];
      if (!products.length) { setMsg('상품 0건'); return; }

      const rows: SheetRow[] = products.map(p => newSheetRow({
        product_name: p.product_name || '',
        product_name_ko: p.product_name_ko || '',
        product_url: p.product_url || '',
        cover_image_url: p.cover_image_url || '',
        sell_price_jpy: p.price_jpy || 0,
        competitor_price_jpy: p.price_jpy || 0,
        source: `shop:${p.shop_id || 'unknown'}`,
        shop_rank: p.rank || null,
        review_count: p.review_count || 0,
        match_decision: 'manual',
      }));
      const added = onMerge(rows, 'product_name');
      setMsg(`✓ ${added}건 추가 (${products.length}건 중 중복 제외)`);
      setTimeout(onClose, 1500);
    } catch (e: any) {
      setMsg(`✗ ${e?.response?.data?.error || e.message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="🏪 큐텐 샵 분석 → 시트로" onClose={onClose}>
      <div className="space-y-3 text-sm">
        <div>
          <label className="block mb-1 text-gray-600">샵 URL</label>
          <input value={shopUrl} onChange={e => setShopUrl(e.target.value)}
            placeholder="https://www.qoo10.jp/shop/..."
            className="w-full border rounded px-2 py-1" />
        </div>
        <div>
          <label className="block mb-1 text-gray-600">상위 N개</label>
          <input type="number" value={limit} onChange={e => setLimit(Number(e.target.value) || 20)}
            min={1} max={50} className="w-24 border rounded px-2 py-1" />
        </div>
        <button onClick={analyze} disabled={busy}
          className="w-full bg-purple-600 text-white py-2 rounded font-semibold hover:bg-purple-700 disabled:bg-gray-400">
          {busy ? '수집 중...' : '샵 상품 수집 + 시트 추가'}
        </button>
        {msg && <div className="text-xs">{msg}</div>}
      </div>
    </Modal>
  );
}

// ─── 4) 트렌드 키워드 (VV-4 활성화) ───

function TrendKeywordModal({ onClose, onMerge }: { onClose: () => void; onMerge: Props['onMergeRows'] }) {
  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate] = useState(today);
  const [limit, setLimit] = useState(20);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [keywords, setKeywords] = useState<any[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  async function fetchKeywords() {
    setBusy(true); setMsg('');
    try {
      const r = await api.post<{ keywords: any[] }>('/keywords/auto-filter', {
        date, limit,
      });
      setKeywords(r.data.keywords || []);
      setSelected(new Set());
      if ((r.data.keywords || []).length === 0) setMsg('키워드 0건');
    } catch (e: any) {
      setMsg(`✗ ${e?.response?.data?.error || e.message}`);
    } finally {
      setBusy(false);
    }
  }

  function toggle(jp: string) {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(jp)) next.delete(jp); else next.add(jp);
      return next;
    });
  }

  function addSelected() {
    const sel = keywords.filter(k => selected.has(k.keyword_jp));
    if (!sel.length) return;
    const rows: SheetRow[] = sel.map(k => newSheetRow({
      keyword_jp: k.keyword_jp,
      keyword_kr: k.keyword_kr,
      product_name: k.keyword_jp,
      source: `trend:${date}`,
      match_decision: 'manual',
    }));
    const added = onMerge(rows, 'keyword_jp');
    setMsg(`✓ ${added}건 추가`);
    setTimeout(onClose, 1500);
  }

  return (
    <Modal title="📈 트렌드 키워드 → 시트로" onClose={onClose} wide>
      <div className="space-y-3 text-sm">
        <div className="flex gap-2 items-end">
          <div>
            <label className="block mb-1 text-gray-600">날짜</label>
            <input type="date" value={date} onChange={e => setDate(e.target.value)}
              className="border rounded px-2 py-1" />
          </div>
          <div>
            <label className="block mb-1 text-gray-600">상한</label>
            <input type="number" value={limit} onChange={e => setLimit(Number(e.target.value) || 20)}
              min={1} max={200} className="w-20 border rounded px-2 py-1" />
          </div>
          <button onClick={fetchKeywords} disabled={busy}
            className="bg-amber-600 text-white px-3 py-1 rounded text-xs hover:bg-amber-700">
            {busy ? '로딩...' : '키워드 조회'}
          </button>
        </div>

        {keywords.length > 0 && (
          <>
            <div className="text-xs text-gray-500">{keywords.length}건 조회됨 — 선택 후 추가</div>
            <div className="border rounded max-h-64 overflow-y-auto">
              {keywords.map((k, i) => (
                <label key={i} className="flex items-center gap-2 px-2 py-1 hover:bg-gray-50 cursor-pointer text-xs border-b last:border-0">
                  <input type="checkbox" checked={selected.has(k.keyword_jp)} onChange={() => toggle(k.keyword_jp)} />
                  <span className="flex-1">{k.keyword_jp}</span>
                  <span className="text-gray-500">{k.keyword_kr}</span>
                  <span className="text-gray-400 text-[10px]">검색 {k.search_volume?.toLocaleString() || '-'}</span>
                </label>
              ))}
            </div>
            <button onClick={addSelected} disabled={selected.size === 0}
              className="w-full bg-amber-600 text-white py-2 rounded font-semibold hover:bg-amber-700 disabled:bg-gray-400">
              선택 {selected.size}건 시트에 추가
            </button>
          </>
        )}
        {msg && <div className="text-xs">{msg}</div>}
      </div>
    </Modal>
  );
}

// ─── 공통 modal ─────────────────────────

function Modal({ title, children, onClose, wide }: {
  title: string; children: React.ReactNode; onClose: () => void; wide?: boolean;
}) {
  return (
    <div className="fixed inset-0 bg-black/40 z-40 flex items-center justify-center p-4" onClick={onClose}>
      <div className={`bg-white rounded-lg shadow-xl ${wide ? 'w-[600px]' : 'w-[400px]'} max-w-full max-h-[90vh] overflow-hidden flex flex-col`}
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between p-3 border-b bg-gray-50">
          <h3 className="font-bold text-sm">{title}</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-800 text-xl">×</button>
        </div>
        <div className="p-4 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}

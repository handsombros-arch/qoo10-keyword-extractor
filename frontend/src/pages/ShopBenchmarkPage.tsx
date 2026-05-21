/**
 * 샵 벤치마크 — 큐텐 샵 URL 입력해서 상위 상품 수집.
 * 결과는 product_sheet (cloudSync) 에 직접 추가됨.
 *
 * T (5/3): URL 리스트 영속 + 카드형 UI + 검색 필터 + 안내.
 */
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Check, Plus, RefreshCw, Trash2, Search, Info } from 'lucide-react';
import api from '../api/client';
import { loadSheet, saveSheet, newSheetRow, type SheetRow } from '../store/productSheet';
import { loadShopCache, saveShopCache, clearShopCache } from '../store/shopCache';
import { loadShopUrls, addShopUrl, removeShopUrl, type ShopUrlEntry } from '../store/shopUrls';
import { pushCloud } from '../store/cloudSync';

interface ShopProduct {
  product_name: string;
  price_jpy: number | null;
  product_url: string;
  cover_image_url: string;
  shop_rank?: number | null;
  review_count?: number | null;
  shipping_fee?: string;        // 5/3: raw 배송비 텍스트 (送料無料 / 300円 ~)
  shipping_jpy?: number | null; // 5/3: 파싱된 숫자 (¥)
  is_new?: boolean;             // U (5/3): 지난 fetch 이후 새로 등장한 상품
}

interface ShopMeta {
  followers?: number | null;
  total_reviews?: number | null;
  product_count?: number | null;
  rating?: number | null;
}

interface ShopResult {
  shop_id: string;
  shop_url: string;
  products: ShopProduct[];
  error?: string;
  fetched_at?: string;
  shop_meta?: ShopMeta;
}

export default function ShopBenchmarkPage() {
  const [urlEntries, setUrlEntries] = useState<ShopUrlEntry[]>(() => loadShopUrls());
  const [newUrl, setNewUrl] = useState('');
  const [limit, setLimit] = useState(30);
  const [sortType, setSortType] = useState<'ranking' | 'review' | 'new' | 'price_high' | 'price_low'>('review');
  const [results, setResults] = useState<ShopResult[] | null>(() => {
    const cached = loadShopCache();
    return cached.length > 0 ? (cached as any) : null;
  });
  const [loadingShops, setLoadingShops] = useState<Set<string>>(new Set());
  const [err, setErr] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [searchQ, setSearchQ] = useState('');
  const [showNewOnly, setShowNewOnly] = useState(false);   // U (5/3): 신규만 토글

  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 3000);
    return () => window.clearTimeout(t);
  }, [toast]);

  // U (5/3): 페이지 로드 시 cloudSync 로 shop_cache 가져오기 — 야간 자동화 결과 자동 로드
  useEffect(() => {
    (async () => {
      try {
        const { fetchCloud } = await import('../store/cloudSync');
        const r = await fetchCloud<ShopResult[]>('shop_cache');
        if (r.data && Array.isArray(r.data) && r.data.length > 0) {
          setResults(r.data);
          saveShopCache(r.data as any);
        }
      } catch { /* ignore */ }
    })();
  }, []);

  // 시트에 이미 있는 product_url + product_name set
  const [addedKeys, setAddedKeys] = useState<Set<string>>(new Set());
  const refreshAddedKeys = () => {
    const sheet = loadSheet();
    const s = new Set<string>();
    for (const r of sheet) {
      if (r.product_url) s.add(r.product_url);
      if (r.product_name) s.add(r.product_name);
    }
    setAddedKeys(s);
  };
  useEffect(() => { refreshAddedKeys(); }, [results]);
  const isInSheet = (p: ShopProduct) =>
    (!!p.product_url && addedKeys.has(p.product_url)) ||
    (!!p.product_name && addedKeys.has(p.product_name));

  // 멀티 선택
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const keyOf = (shopId: string, p: ShopProduct) => `${shopId}::${p.product_url}`;
  const toggleRow = (shopId: string, p: ShopProduct) => {
    if (isInSheet(p)) return;
    const k = keyOf(shopId, p);
    setSelectedKeys(prev => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k); else next.add(k);
      return next;
    });
  };
  const toggleAllInShop = (shop: ShopResult) => {
    const eligibleKeys = shop.products.filter(p => !isInSheet(p)).map(p => keyOf(shop.shop_id, p));
    if (eligibleKeys.length === 0) return;
    const allSelected = eligibleKeys.every(k => selectedKeys.has(k));
    setSelectedKeys(prev => {
      const next = new Set(prev);
      if (allSelected) eligibleKeys.forEach(k => next.delete(k));
      else eligibleKeys.forEach(k => next.add(k));
      return next;
    });
  };
  const selectedCount = selectedKeys.size;

  // ── 샵 URL 관리 ─────────────────────────────────────
  const addUrl = () => {
    const u = newUrl.trim();
    if (!u) return;
    if (!u.includes('qoo10.jp/shop/')) {
      setErr('큐텐 샵 URL 형식: https://www.qoo10.jp/shop/{shop_id}');
      return;
    }
    const next = addShopUrl(u);
    setUrlEntries(next);
    setNewUrl('');
    setErr(null);
  };
  const removeUrl = (u: string) => {
    const next = removeShopUrl(u);
    setUrlEntries(next);
    // 결과에서도 제거
    if (results) setResults(results.filter(r => r.shop_url !== u));
  };

  // ── 수집 ────────────────────────────────────────────
  const fetchShops = async (urls: string[]) => {
    if (urls.length === 0) return;
    setLoadingShops(prev => {
      const next = new Set(prev);
      urls.forEach(u => next.add(u));
      return next;
    });
    setErr(null);
    try {
      const { data } = await api.post('/recommendations/from-shop', {
        shop_urls: urls, limit_per_shop: limit, sort_type: sortType,
      });
      if (data.error) { setErr(data.error); return; }
      const newResults = (data.results || []).map((r: any) => ({
        ...r, sort_type: sortType, fetched_at: new Date().toISOString(),
      }));
      // 기존 결과 + 새 fetch 결과 머지 (덮어쓰기)
      const merged: ShopResult[] = [];
      const newByUrl = new Map<string, ShopResult>(newResults.map((r: ShopResult) => [r.shop_url, r]));
      const existing = results || [];
      for (const r of existing) {
        if (newByUrl.has(r.shop_url)) {
          merged.push(newByUrl.get(r.shop_url)!);
          newByUrl.delete(r.shop_url);
        } else {
          merged.push(r);
        }
      }
      for (const r of newByUrl.values()) merged.push(r);
      setResults(merged);
      saveShopCache(merged as any);
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || '실패');
    } finally {
      setLoadingShops(prev => {
        const next = new Set(prev);
        urls.forEach(u => next.delete(u));
        return next;
      });
    }
  };
  const fetchAll = () => fetchShops(urlEntries.map(e => e.url));
  const fetchOne = (url: string) => fetchShops([url]);

  const clearCache = () => {
    if (!confirm('수집 결과를 모두 지우시겠습니까? (URL 리스트는 보존)')) return;
    clearShopCache();
    setResults(null);
    setSelectedKeys(new Set());
  };

  // ── 시트 추가 ────────────────────────────────────────
  const addSelectedToSheet = async () => {
    if (!results || selectedKeys.size === 0) return;
    const byShop = new Map<string, ShopProduct[]>();
    for (const shop of results) {
      const picks = shop.products.filter(p => selectedKeys.has(keyOf(shop.shop_id, p)) && !isInSheet(p));
      if (picks.length > 0) byShop.set(shop.shop_id, picks);
    }
    let totalAdded = 0;
    let totalBlocked = 0;
    for (const [shopId, products] of byShop) {
      const shop = results.find(s => s.shop_id === shopId)!;
      const before = loadSheet().length;
      await addProductsToSheet(shop, products);
      const after = loadSheet().length;
      totalAdded += after - before;
      totalBlocked += products.length - (after - before);
    }
    setSelectedKeys(new Set());
    refreshAddedKeys();
    setToast(
      `${totalAdded}개 시트에 추가됨` +
      (totalBlocked > 0 ? ` (블랙리스트 ${totalBlocked} 차단)` : '')
    );
  };

  const addProductsToSheet = async (shop: ShopResult, products: ShopProduct[]) => {
    let translations: string[] = [];
    try {
      const { data } = await api.post('/utils/translate-batch', {
        texts: products.map(p => p.product_name),
        source: 'ja', target: 'ko',
      });
      translations = data.translations || [];
    } catch {
      translations = products.map(() => '');
    }

    // 블랙리스트 batch 체크
    let blockedSet = new Set<string>();
    try {
      const r = await api.post<any>('/blacklist/check-batch', {
        items: products.map(p => ({ product_name: p.product_name })),
      });
      for (const res of r.data.results || []) {
        if (res.blacklisted && res.product_name) blockedSet.add(res.product_name);
      }
    } catch (e) {
      console.warn('[shop-benchmark] blacklist check 실패, skip:', e);
    }

    const filtered = products
      .map((p, i) => ({ p, i }))
      .filter(({ p }) => !blockedSet.has(p.product_name));

    if (filtered.length === 0) return;

    const newRows: SheetRow[] = filtered.map(({ p, i }) => newSheetRow({
      product_name: p.product_name,
      product_name_ko: translations[i] || '',
      product_url: p.product_url,
      cover_image_url: p.cover_image_url,
      competitor_price_jpy: p.price_jpy || 0,
      // 5/3: 샵에서 추출한 배송비 → 시트의 경쟁배송 컬럼
      competitor_shipping_jpy: p.shipping_jpy ?? 0,
      sell_price_jpy: p.price_jpy || 0,
      shop_rank: p.shop_rank,
      review_count: p.review_count,
      source: `shop:${shop.shop_id}`,
    }));

    const existing = loadSheet();
    const merged = [...existing, ...newRows];
    saveSheet(merged);
    try { await pushCloud('product_sheet', merged); } catch { /* */ }
  };

  // ── 결과 검색 + 신규만 필터 ─────────────────────────
  const filteredResults = useMemo(() => {
    if (!results) return null;
    const q = searchQ.trim().toLowerCase();
    if (!q && !showNewOnly) return results;
    return results.map(shop => ({
      ...shop,
      products: shop.products.filter(p => {
        if (showNewOnly && !p.is_new) return false;
        if (q && !(p.product_name || '').toLowerCase().includes(q)) return false;
        return true;
      }),
    }));
  }, [results, searchQ, showNewOnly]);

  const totalNewCount = useMemo(() => {
    if (!results) return 0;
    return results.reduce((sum, s) => sum + s.products.filter(p => p.is_new).length, 0);
  }, [results]);

  return (
    <div className="apple-container-wide py-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="apple-title-1">샵 벤치마크</h1>
          <p className="text-[14px] text-apple-text-3 mt-1 tracking-tight">
            큐텐 경쟁 셀러의 상위 상품을 수집하여 상품 시트에 추가
          </p>
        </div>
        <Link
          to="/recommend-products"
          className="apple-btn apple-btn-secondary apple-btn-sm"
        >
          상품 시트 →
        </Link>
      </div>

      {/* 안내 — 중복/동기화 동작 */}
      <div className="apple-card mb-4 flex gap-3" style={{ padding: '14px 16px' }}>
        <Info size={16} className="text-apple-accent shrink-0 mt-0.5" />
        <div className="text-[13px] text-apple-text-2 tracking-tight space-y-0.5">
          <div><strong>중복</strong>: 시트에 이미 있는 상품은 회색 처리 + 추가 불가 (product_url / product_name 매칭)</div>
          <div><strong>동기화</strong>: 매번 새로 fetch — 큐텐 페이지의 그 시점 상위 N개. 새 상품 등장 / 빠진 상품 / 순위 변경 모두 반영</div>
          <div><strong>시트는 별개</strong>: 한 번 추가된 행은 새 fetch 결과에 영향 없음 (사장님 검수 데이터 보존)</div>
        </div>
      </div>

      {/* 수집 옵션 + URL 관리 */}
      <div className="apple-card mb-4" style={{ padding: '20px 22px' }}>
        <div className="flex items-end gap-3 mb-3">
          <div className="flex-1">
            <label className="block text-[12px] text-apple-text-2 mb-1.5 tracking-tight">새 샵 URL 추가</label>
            <input
              type="text"
              value={newUrl}
              onChange={e => setNewUrl(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') addUrl(); }}
              placeholder="https://www.qoo10.jp/shop/{shop_id}"
              className="apple-input"
            />
          </div>
          <button
            onClick={addUrl}
            className="apple-btn apple-btn-secondary apple-btn-sm flex items-center gap-1.5"
          >
            <Plus size={14} strokeWidth={2} />
            <span>추가</span>
          </button>
        </div>

        <div className="flex items-end gap-3 mb-4">
          <div>
            <label className="block text-[12px] text-apple-text-2 mb-1.5 tracking-tight">정렬</label>
            <select
              value={sortType}
              onChange={e => setSortType(e.target.value as any)}
              className="apple-input"
              style={{ width: 160 }}
            >
              <option value="ranking">랭킹순</option>
              <option value="review">리뷰순</option>
              <option value="new">신착순</option>
              <option value="price_high">가격 높은순</option>
              <option value="price_low">가격 낮은순</option>
            </select>
          </div>
          <div>
            <label className="block text-[12px] text-apple-text-2 mb-1.5 tracking-tight">샵당 상품 수</label>
            <input
              type="number"
              value={limit}
              onChange={e => setLimit(+e.target.value)}
              className="apple-input"
              style={{ width: 100 }}
            />
          </div>
          <div className="ml-auto flex gap-2">
            <button
              onClick={fetchAll}
              disabled={loadingShops.size > 0 || urlEntries.length === 0}
              className="apple-btn apple-btn-primary apple-btn-sm flex items-center gap-1.5"
            >
              <RefreshCw size={14} strokeWidth={2} className={loadingShops.size > 0 ? 'animate-spin' : ''} />
              <span>{loadingShops.size > 0 ? '수집 중…' : '전체 수집'}</span>
            </button>
            {results && results.length > 0 && (
              <button onClick={clearCache} className="apple-btn apple-btn-ghost apple-btn-sm">
                결과 지우기
              </button>
            )}
          </div>
        </div>

        {/* URL 리스트 */}
        <div>
          <div className="text-[12px] text-apple-text-2 mb-1.5 tracking-tight">
            등록된 샵 ({urlEntries.length})
          </div>
          {urlEntries.length === 0 ? (
            <div className="text-[12px] text-apple-text-3 italic py-2">위 칸에서 URL 추가하세요</div>
          ) : (
            <div className="grid grid-cols-2 gap-2">
              {urlEntries.map(e => {
                const lastFetch = (results || []).find(r => r.shop_url === e.url)?.fetched_at;
                const isLoading = loadingShops.has(e.url);
                return (
                  <div
                    key={e.url}
                    className="flex items-center gap-2 py-1.5 px-2.5 rounded-lg"
                    style={{ background: 'var(--color-apple-bg-2)' }}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="text-[13px] font-medium tracking-tight truncate">{e.shop_id || e.url}</div>
                      {lastFetch && (
                        <div className="text-[10px] text-apple-text-3">
                          마지막 수집 {new Date(lastFetch).toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                        </div>
                      )}
                    </div>
                    <button
                      onClick={() => fetchOne(e.url)}
                      disabled={isLoading}
                      className="apple-btn apple-btn-ghost apple-btn-sm"
                      style={{ padding: '4px 10px', fontSize: 12 }}
                      title="이 샵만 재수집"
                    >
                      <RefreshCw size={12} strokeWidth={2} className={isLoading ? 'animate-spin' : ''} />
                    </button>
                    <button
                      onClick={() => removeUrl(e.url)}
                      className="apple-btn apple-btn-ghost apple-btn-sm"
                      style={{ padding: '4px 10px', fontSize: 12 }}
                      title="샵 제거"
                    >
                      <Trash2 size={12} strokeWidth={1.75} />
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {err && (
        <div className="mb-3 px-3 py-2 rounded-lg text-[13px]"
             style={{ background: 'color-mix(in srgb, var(--color-apple-error) 8%, transparent)', color: 'var(--color-apple-error)' }}>
          {err}
        </div>
      )}
      {toast && (
        <div className="mb-3 px-3 py-2 rounded-lg text-[13px]"
             style={{ background: 'color-mix(in srgb, var(--color-apple-success) 8%, transparent)', color: 'var(--color-apple-success)' }}>
          {toast}
        </div>
      )}

      {/* 결과 */}
      {results && results.length > 0 && (
        <>
          {/* 검색 + 선택 일괄 추가 */}
          <div className="sticky top-14 z-30 mb-3 flex items-center gap-3 backdrop-blur"
               style={{
                 background: 'color-mix(in srgb, var(--color-apple-bg) 90%, transparent)',
                 border: '1px solid var(--color-apple-border)',
                 padding: '10px 14px',
                 borderRadius: 12,
                 boxShadow: selectedCount > 0 ? '0 4px 16px rgba(0,0,0,0.08)' : 'none',
               }}>
            <Search size={16} className="text-apple-text-3 shrink-0" />
            <input
              type="text"
              value={searchQ}
              onChange={e => setSearchQ(e.target.value)}
              placeholder="상품명 검색"
              className="flex-1 outline-none bg-transparent text-[14px] tracking-tight"
              style={{ minWidth: 180 }}
            />
            <button
              onClick={() => setShowNewOnly(v => !v)}
              className={`apple-btn apple-btn-sm ${showNewOnly ? 'apple-btn-primary' : 'apple-btn-ghost'}`}
              title="지난 자동 수집 이후 새로 등장한 상품만 표시"
            >
              신규{totalNewCount > 0 ? ` ${totalNewCount}` : ''}
            </button>
            {selectedCount > 0 && (
              <>
                <span className="text-[13px] text-apple-text-2 tracking-tight">
                  <strong>{selectedCount}</strong>개 선택
                </span>
                <button
                  onClick={addSelectedToSheet}
                  className="apple-btn apple-btn-primary apple-btn-sm flex items-center gap-1.5"
                >
                  <Plus size={14} strokeWidth={2.25} />
                  <span>시트로 추가</span>
                </button>
                <button
                  onClick={() => setSelectedKeys(new Set())}
                  className="apple-btn apple-btn-ghost apple-btn-sm"
                >
                  해제
                </button>
              </>
            )}
          </div>

          <div className="space-y-3">
            {(filteredResults || []).map(shop => {
              const eligible = shop.products.filter(p => !isInSheet(p));
              const eligibleKeys = eligible.map(p => keyOf(shop.shop_id, p));
              const allSelected = eligibleKeys.length > 0 && eligibleKeys.every(k => selectedKeys.has(k));
              const someSelected = eligibleKeys.some(k => selectedKeys.has(k));
              const inSheetCount = shop.products.length - eligible.length;
              return (
                <div key={shop.shop_id} className="bg-apple-bg rounded-2xl border" style={{ borderColor: 'var(--color-apple-border)' }}>
                  <div className="px-4 py-3 border-b flex items-center justify-between flex-wrap gap-2" style={{ borderBottomColor: 'var(--color-apple-border)' }}>
                    <div className="flex items-center gap-3">
                      <a
                        href={shop.shop_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-[15px] font-semibold tracking-tight text-apple-accent hover:underline"
                      >
                        {shop.shop_id}
                      </a>
                      <span className="text-[12px] text-apple-text-3">
                        수집 {shop.products.length}
                        {inSheetCount > 0 && <span className="ml-1.5">· 시트에 {inSheetCount}</span>}
                      </span>
                      {shop.error && <span className="text-[12px] text-apple-error">{shop.error}</span>}
                    </div>
                    {/* 5/3: 샵 메타 (팔로우/리뷰/상품수/평점) */}
                    {shop.shop_meta && (
                      <div className="flex items-center gap-3 text-[12px] text-apple-text-2 tracking-tight">
                        {shop.shop_meta.followers != null && (
                          <span title="팔로워 수">
                            <span className="text-apple-text-3">팔로워 </span>
                            <strong className="font-mono tabular-nums">{shop.shop_meta.followers.toLocaleString()}</strong>
                          </span>
                        )}
                        {shop.shop_meta.total_reviews != null && (
                          <span title="총 리뷰 수">
                            <span className="text-apple-text-3">리뷰 </span>
                            <strong className="font-mono tabular-nums">{shop.shop_meta.total_reviews.toLocaleString()}</strong>
                          </span>
                        )}
                        {shop.shop_meta.product_count != null && (
                          <span title="상품 수">
                            <span className="text-apple-text-3">상품 </span>
                            <strong className="font-mono tabular-nums">{shop.shop_meta.product_count.toLocaleString()}</strong>
                          </span>
                        )}
                        {shop.shop_meta.rating != null && (
                          <span title="평점">
                            <span className="text-apple-text-3">★ </span>
                            <strong className="font-mono tabular-nums">{shop.shop_meta.rating.toFixed(1)}</strong>
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="max-h-96 overflow-y-auto">
                    <table className="w-full text-[13px]">
                      <thead className="sticky top-0 bg-apple-bg-2 text-[11px] text-apple-text-3 uppercase tracking-wider">
                        <tr>
                          <th className="px-3 py-2 w-10">
                            <input
                              type="checkbox"
                              checked={allSelected}
                              ref={el => { if (el) el.indeterminate = !allSelected && someSelected; }}
                              onChange={() => toggleAllInShop(shop)}
                              disabled={eligible.length === 0}
                              title={eligible.length === 0 ? '추가 가능한 행 없음' : '샵 전체 선택'}
                            />
                          </th>
                          <th className="px-2 py-2 w-10 text-right">#</th>
                          <th className="px-2 py-2 text-left font-medium">상품명</th>
                          <th className="px-2 py-2 text-right font-medium">가격 ¥</th>
                          <th className="px-2 py-2 text-right font-medium">배송 ¥</th>
                          <th className="px-2 py-2 text-right font-medium">리뷰</th>
                        </tr>
                      </thead>
                      <tbody>
                        {shop.products.map((p, i) => {
                          const inSheet = isInSheet(p);
                          const k = keyOf(shop.shop_id, p);
                          const checked = selectedKeys.has(k);
                          return (
                            <tr
                              key={i}
                              className={`border-b transition-colors ${
                                inSheet
                                  ? 'opacity-50 bg-apple-bg-2 cursor-not-allowed'
                                  : checked
                                    ? 'bg-apple-bg-2'
                                    : 'hover:bg-apple-bg-2 cursor-pointer'
                              }`}
                              style={{ borderBottomColor: 'var(--color-apple-border)' }}
                              onClick={(e) => {
                                if ((e.target as HTMLElement).tagName === 'A') return;
                                toggleRow(shop.shop_id, p);
                              }}
                            >
                              <td className="px-3 py-1.5">
                                {inSheet ? (
                                  <span title="이미 상품 시트에 추가됨">
                                    <Check size={14} className="text-apple-text-3" strokeWidth={2} />
                                  </span>
                                ) : (
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={() => toggleRow(shop.shop_id, p)}
                                    onClick={e => e.stopPropagation()}
                                  />
                                )}
                              </td>
                              <td className="px-2 py-1.5 text-apple-text-3 text-right">{p.shop_rank || i + 1}</td>
                              <td className="px-2 py-1.5">
                                {p.product_url
                                  ? <a href={p.product_url} target="_blank" rel="noreferrer" className="text-apple-accent hover:underline">{p.product_name}</a>
                                  : p.product_name}
                                {p.is_new && (
                                  <span
                                    className="ml-2 text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded"
                                    style={{ background: 'var(--color-apple-accent)', color: 'white' }}
                                    title="지난 자동 수집 이후 새로 등장"
                                  >NEW</span>
                                )}
                                {inSheet && <span className="ml-2 text-[10px] text-apple-text-3">(시트에 있음)</span>}
                              </td>
                              <td className="px-2 py-1.5 text-right font-mono tabular-nums">{p.price_jpy?.toLocaleString() || '-'}</td>
                              <td className="px-2 py-1.5 text-right font-mono tabular-nums text-apple-text-3" title={p.shipping_fee || ''}>
                                {p.shipping_jpy === 0 ? '무료' : (p.shipping_jpy != null ? p.shipping_jpy.toLocaleString() : '-')}
                              </td>
                              <td className="px-2 py-1.5 text-right font-mono tabular-nums text-apple-text-3">{p.review_count || '-'}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      {(!results || results.length === 0) && urlEntries.length > 0 && !err && (
        <div className="apple-card text-center text-apple-text-3 text-[13px]" style={{ padding: '40px 20px' }}>
          [전체 수집] 또는 샵별 [↻] 클릭으로 상품 가져오기
        </div>
      )}
    </div>
  );
}

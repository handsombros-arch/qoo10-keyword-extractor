/**
 * 샵 벤치마크 — 큐텐 샵 URL 입력해서 상위 상품 수집.
 * 결과는 product_sheet (cloudSync 통해 user_data) 에 직접 추가됨.
 * 시트 페이지(/recommend-products) 새로고침하면 반영.
 */
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../api/client';
import { loadSheet, saveSheet, newSheetRow, type SheetRow } from '../store/productSheet';
import { loadShopCache, saveShopCache, clearShopCache } from '../store/shopCache';
import { pushCloud } from '../store/cloudSync';

interface ShopProduct {
  product_name: string;
  price_jpy: number | null;
  product_url: string;
  cover_image_url: string;
  shop_rank?: number | null;
  review_count?: number | null;
}

interface ShopResult {
  shop_id: string;
  shop_url: string;
  products: ShopProduct[];
  error?: string;
}

export default function ShopBenchmarkPage() {
  const [urls, setUrls] = useState('https://www.qoo10.jp/shop/tsurutsuru\nhttps://www.qoo10.jp/shop/jjunabeauty');
  const [limit, setLimit] = useState(30);
  const [sortType, setSortType] = useState<'ranking' | 'review' | 'new' | 'price_high' | 'price_low'>('review');
  const [results, setResults] = useState<ShopResult[] | null>(() => {
    const cached = loadShopCache();
    return cached.length > 0 ? cached : null;
  });
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const cachedAt = useMemo(() => {
    const c = loadShopCache();
    return c[0]?.fetched_at || null;
  }, [results]);

  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 3000);
    return () => window.clearTimeout(t);
  }, [toast]);

  const fetchProducts = async () => {
    const list = urls.split(/\s+/).map(u => u.trim()).filter(u => u);
    if (list.length === 0) return;
    setLoading(true); setErr(null);
    try {
      const { data } = await api.post('/recommendations/from-shop', {
        shop_urls: list, limit_per_shop: limit, sort_type: sortType,
      });
      if (data.error) { setErr(data.error); return; }
      const newResults = data.results || [];
      setResults(newResults);
      const now = new Date().toISOString();
      saveShopCache(newResults.map((r: any) => ({ ...r, sort_type: sortType, fetched_at: now })));
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || '실패');
    } finally {
      setLoading(false);
    }
  };

  const clearCache = () => {
    if (!confirm('샵 벤치마크 결과를 지우시겠습니까?')) return;
    clearShopCache();
    setResults(null);
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

    const newRows: SheetRow[] = products.map((p, i) => newSheetRow({
      product_name: p.product_name,
      product_name_ko: translations[i] || '',
      product_url: p.product_url,
      cover_image_url: p.cover_image_url,
      competitor_price_jpy: p.price_jpy || 0,
      sell_price_jpy: p.price_jpy || 0,
      shop_rank: p.shop_rank,
      review_count: p.review_count,
      source: `shop:${shop.shop_id}`,
    }));

    // 기존 시트 + 새 행 머지 후 localStorage + cloud 둘 다 저장
    const existing = loadSheet();
    const merged = [...existing, ...newRows];
    saveSheet(merged);
    try {
      await pushCloud('product_sheet', merged);
    } catch { /* 무시 */ }

    setToast(`${newRows.length}개 시트에 추가 — /recommend-products 새로고침하면 반영`);
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-2xl font-bold">🎯 샵 벤치마크</h2>
        <Link
          to="/recommend-products"
          className="px-3 py-1.5 bg-blue-600 text-white rounded text-xs font-semibold hover:bg-blue-700"
        >
          📋 상품 시트로 이동
        </Link>
      </div>
      <div className="bg-blue-50 border-l-4 border-blue-400 text-xs p-3 mb-4 rounded">
        💡 큐텐 샵 URL 입력 → 상위 상품 수집 → 시트에 자동 추가. 한글명 자동 번역.
      </div>

      <div className="bg-white rounded-lg shadow p-5 mb-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold">샵 URL 입력</h3>
          {cachedAt && (
            <div className="flex items-center gap-2 text-xs text-gray-500">
              마지막 조회: {new Date(cachedAt).toLocaleString('ko-KR')}
              <button onClick={clearCache} className="text-red-500 hover:text-red-700">✕ 캐시 삭제</button>
            </div>
          )}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-[1fr,auto,auto,auto] gap-3 items-end mb-3">
          <label className="text-sm">
            <div className="text-xs text-gray-600 mb-1">샵 URL (줄바꿈으로 여러 개)</div>
            <textarea rows={3} value={urls} onChange={e => setUrls(e.target.value)}
              className="w-full border rounded px-2 py-1 text-xs font-mono" />
          </label>
          <label className="text-sm">
            <div className="text-xs text-gray-600 mb-1">정렬</div>
            <select value={sortType} onChange={e => setSortType(e.target.value as any)}
              className="border rounded px-2 py-1.5 text-sm">
              <option value="ranking">랭킹순 (기본)</option>
              <option value="review">리뷰 많은순 ⭐</option>
              <option value="new">신착순</option>
              <option value="price_high">가격 높은순</option>
              <option value="price_low">가격 낮은순</option>
            </select>
          </label>
          <label className="text-sm">
            <div className="text-xs text-gray-600 mb-1">샵당 상품 수</div>
            <input type="number" value={limit} onChange={e => setLimit(+e.target.value)}
              className="w-24 border rounded px-2 py-1.5" />
          </label>
          <button onClick={fetchProducts} disabled={loading}
            className="px-4 py-2 bg-purple-600 text-white text-sm rounded hover:bg-purple-700 disabled:opacity-50">
            {loading ? '수집 중...' : '🎯 상품 가져오기'}
          </button>
        </div>
        {err && <div className="bg-red-50 text-red-700 text-xs p-2 rounded mb-2">{err}</div>}
        {toast && <div className="bg-emerald-50 text-emerald-700 text-xs p-2 rounded mb-2">{toast}</div>}
      </div>

      {results && (
        <div className="space-y-3">
          {results.map(shop => (
            <div key={shop.shop_id} className="bg-white rounded shadow border">
              <div className="px-3 py-2 bg-gray-50 border-b flex items-center justify-between">
                <div>
                  <span className="font-semibold">{shop.shop_id}</span>
                  <span className="ml-2 text-xs text-gray-500">{shop.products.length}개</span>
                  {shop.error && <span className="ml-2 text-xs text-red-600">{shop.error}</span>}
                </div>
                {shop.products.length > 0 && (
                  <button
                    onClick={() => addProductsToSheet(shop, shop.products)}
                    className="px-3 py-1 bg-emerald-600 text-white text-xs rounded hover:bg-emerald-700"
                  >
                    ➕ 전체 시트에 추가 (자동 번역)
                  </button>
                )}
              </div>
              <div className="max-h-96 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="bg-gray-50 sticky top-0">
                    <tr>
                      <th className="px-2 py-1 w-10 text-right">#</th>
                      <th className="px-2 py-1 text-left">상품명</th>
                      <th className="px-2 py-1 text-right">가격(¥)</th>
                      <th className="px-2 py-1 text-right">리뷰</th>
                      <th className="px-2 py-1 w-16 text-center">추가</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shop.products.map((p, i) => (
                      <tr key={i} className="border-b hover:bg-gray-50">
                        <td className="px-2 py-1 text-gray-400 text-right">{p.shop_rank || i + 1}</td>
                        <td className="px-2 py-1">
                          {p.product_url
                            ? <a href={p.product_url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">{p.product_name}</a>
                            : p.product_name}
                        </td>
                        <td className="px-2 py-1 text-right font-mono">{p.price_jpy?.toLocaleString() || '-'}</td>
                        <td className="px-2 py-1 text-right font-mono">{p.review_count || '-'}</td>
                        <td className="px-2 py-1 text-center">
                          <button
                            onClick={() => addProductsToSheet(shop, [p])}
                            className="text-xs px-2 py-0.5 bg-blue-100 text-blue-700 rounded hover:bg-blue-200"
                          >➕</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

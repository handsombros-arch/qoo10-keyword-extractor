import { useState } from 'react';
import api from '../api/client';

interface Qoo10Product {
  product_name: string;
  price_jpy: number;
  price_krw: number;
  shipping_fee?: string;
  origin?: string;
  cover_image_url?: string;
  product_url?: string;
}

interface NaverProduct {
  product_name: string;
  price_krw: number;
  shipping_fee?: string;
  cover_image_url?: string;
  product_url?: string;
}

interface CompareResult {
  keyword_ko: string;
  keyword_ja: string;
  rate_per_yen: number;
  rate_jpy_krw_per_100: number;
  qoo10: Qoo10Product[];
  naver: NaverProduct[];
  error?: string;
}

export default function PriceComparePage() {
  const [keyword, setKeyword] = useState('');
  const [limit, setLimit] = useState(30);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CompareResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const search = async () => {
    if (!keyword.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.post('/price-compare/search', { keyword_ko: keyword.trim(), limit });
      if (res.data.error) {
        setError(res.data.error);
      } else {
        setResult(res.data);
      }
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || '오류');
    } finally {
      setLoading(false);
    }
  };

  const fmt = (n?: number) => (n == null ? '-' : n.toLocaleString());

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">💱 가격비교 (큐텐 ↔ 네이버)</h2>

      <div className="bg-white rounded-lg shadow p-5 mb-4">
        <div className="flex gap-3 items-end">
          <div className="flex-1">
            <label className="block text-xs text-gray-600 mb-1">한글 키워드</label>
            <input
              type="text"
              value={keyword}
              onChange={e => setKeyword(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && search()}
              placeholder="예: 아누아, 메디큐브, 연어크림"
              className="w-full border rounded px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-600 mb-1">상품 개수</label>
            <select value={limit} onChange={e => setLimit(Number(e.target.value))} className="border rounded px-3 py-2 text-sm">
              <option value={10}>10개</option>
              <option value={20}>20개</option>
              <option value={30}>30개</option>
              <option value={50}>50개</option>
            </select>
          </div>
          <button
            onClick={search}
            disabled={loading}
            className="px-5 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? '검색 중...' : '🔍 검색'}
          </button>
        </div>

        {result && (
          <div className="mt-3 text-xs text-gray-600 flex flex-wrap gap-3">
            <span>한글: <b>{result.keyword_ko}</b></span>
            <span>→ 일본어: <b>{result.keyword_ja}</b></span>
            <span>환율: <b>100엔 = {result.rate_jpy_krw_per_100.toLocaleString()}원</b> (1엔 = {result.rate_per_yen.toFixed(2)}원)</span>
          </div>
        )}

        {error && <div className="mt-3 bg-red-50 text-red-700 text-sm p-3 rounded">{error}</div>}
      </div>

      {loading && (
        <div className="bg-white rounded-lg shadow p-10 text-center">
          <div className="text-4xl mb-3 animate-pulse">🔄</div>
          <div className="text-sm text-gray-600">큐텐 + 네이버 검색 중... (10~30초)</div>
        </div>
      )}

      {result && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {/* 큐텐 */}
          <div className="bg-white rounded-lg shadow">
            <div className="px-4 py-3 border-b flex items-center justify-between">
              <h3 className="font-bold">🇯🇵 큐텐 (일본) — {result.qoo10.length}개</h3>
              <a
                href={`https://www.qoo10.jp/s/?keyword=${encodeURIComponent(result.keyword_ja)}`}
                target="_blank" rel="noreferrer"
                className="text-xs text-blue-600 hover:underline"
              >
                큐텐에서 직접 보기 →
              </a>
            </div>
            <div className="max-h-[700px] overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="bg-gray-50 sticky top-0">
                  <tr>
                    <th className="px-2 py-2 text-left w-12">#</th>
                    <th className="px-2 py-2 text-left">상품명</th>
                    <th className="px-2 py-2 text-right">엔화</th>
                    <th className="px-2 py-2 text-right">원화</th>
                    <th className="px-2 py-2 text-left">배송비</th>
                    <th className="px-2 py-2 text-left">출하지</th>
                  </tr>
                </thead>
                <tbody>
                  {result.qoo10.map((p, i) => (
                    <tr key={i} className="border-b hover:bg-gray-50">
                      <td className="px-2 py-1 text-gray-400">{i + 1}</td>
                      <td className="px-2 py-1">
                        {p.product_url ? (
                          <a href={p.product_url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">
                            {p.product_name}
                          </a>
                        ) : p.product_name}
                      </td>
                      <td className="px-2 py-1 text-right font-mono">¥{fmt(p.price_jpy)}</td>
                      <td className="px-2 py-1 text-right font-mono text-gray-600">₩{fmt(p.price_krw)}</td>
                      <td className="px-2 py-1 text-gray-500">{p.shipping_fee || '-'}</td>
                      <td className="px-2 py-1">{p.origin || '-'}</td>
                    </tr>
                  ))}
                  {result.qoo10.length === 0 && (
                    <tr><td colSpan={6} className="text-center text-gray-400 py-6">결과 없음</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* 네이버 */}
          <div className="bg-white rounded-lg shadow">
            <div className="px-4 py-3 border-b flex items-center justify-between">
              <h3 className="font-bold">🇰🇷 네이버 쇼핑 — {result.naver.length}개</h3>
              <a
                href={`https://search.shopping.naver.com/search/all?query=${encodeURIComponent(result.keyword_ko)}`}
                target="_blank" rel="noreferrer"
                className="text-xs text-blue-600 hover:underline"
              >
                네이버에서 직접 보기 →
              </a>
            </div>
            <div className="max-h-[700px] overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="bg-gray-50 sticky top-0">
                  <tr>
                    <th className="px-2 py-2 text-left w-12">#</th>
                    <th className="px-2 py-2 text-left">상품명</th>
                    <th className="px-2 py-2 text-right">가격(원)</th>
                    <th className="px-2 py-2 text-left">배송비</th>
                  </tr>
                </thead>
                <tbody>
                  {result.naver.map((p, i) => (
                    <tr key={i} className="border-b hover:bg-gray-50">
                      <td className="px-2 py-1 text-gray-400">{i + 1}</td>
                      <td className="px-2 py-1">
                        {p.product_url ? (
                          <a href={p.product_url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">
                            {p.product_name}
                          </a>
                        ) : p.product_name}
                      </td>
                      <td className="px-2 py-1 text-right font-mono">₩{fmt(p.price_krw)}</td>
                      <td className="px-2 py-1 text-gray-500">{p.shipping_fee || '-'}</td>
                    </tr>
                  ))}
                  {result.naver.length === 0 && (
                    <tr><td colSpan={4} className="text-center text-gray-400 py-6">결과 없음</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

import { useEffect, useState } from 'react';
import { getQoo10Products, searchQoo10Products } from '../api/endpoints';
import type { Qoo10Product } from '../types';

export default function ProductSearchPage() {
  const [products, setProducts] = useState<Qoo10Product[]>([]);
  const [keyword, setKeyword] = useState('');
  const [loading, setLoading] = useState(false);

  const fetchProducts = async () => {
    try {
      const res = await getQoo10Products();
      setProducts(res.data);
    } catch { /* ignore */ }
  };

  useEffect(() => { fetchProducts(); }, []);

  const handleSearch = async () => {
    if (!keyword.trim()) return;
    setLoading(true);
    try {
      await searchQoo10Products(keyword);
      setTimeout(fetchProducts, 5000);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">상품 검색</h2>

      <div className="bg-white rounded-lg shadow p-5 mb-4">
        <h3 className="font-semibold mb-3">Qoo10 상품 검색</h3>
        <div className="flex gap-3 items-end">
          <div className="flex-1">
            <input
              value={keyword}
              onChange={e => setKeyword(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSearch()}
              className="border rounded px-3 py-2 text-sm w-full"
              placeholder="상품명 또는 키워드 입력"
            />
          </div>
          <button
            onClick={handleSearch}
            disabled={loading}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
          >
            검색
          </button>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="px-3 py-2 text-left w-16">이미지</th>
              <th className="px-3 py-2 text-left">상품명</th>
              <th className="px-3 py-2 text-right">가격(엔)</th>
              <th className="px-3 py-2 text-left">배송비</th>
              <th className="px-3 py-2 text-left">출하지</th>
              <th className="px-3 py-2 text-center">조회날짜</th>
            </tr>
          </thead>
          <tbody>
            {products.map(p => (
              <tr key={p.id} className="border-b hover:bg-gray-50">
                <td className="px-3 py-2">
                  {p.cover_image_url && (
                    <img src={p.cover_image_url} alt="" className="w-12 h-12 object-cover rounded" />
                  )}
                </td>
                <td className="px-3 py-2">
                  {p.product_url ? (
                    <a href={p.product_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
                      {p.product_name}
                    </a>
                  ) : p.product_name}
                </td>
                <td className="px-3 py-2 text-right">{p.price_jpy?.toLocaleString()}</td>
                <td className="px-3 py-2">{p.shipping_fee || '-'}</td>
                <td className="px-3 py-2">{p.origin || '-'}</td>
                <td className="px-3 py-2 text-center">{p.lookup_date}</td>
              </tr>
            ))}
            {products.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-8 text-center text-gray-400">검색 결과 없음</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

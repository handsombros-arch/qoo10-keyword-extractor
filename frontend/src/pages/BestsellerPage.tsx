import { useEffect, useState } from 'react';
import { getBestsellers, collectBestsellers } from '../api/endpoints';
import type { BestsellerItem } from '../types';

const CATEGORIES = [
  { value: 0, label: '종합' },
  { value: 1, label: '여성패션' },
  { value: 2, label: '뷰티&화장품' },
  { value: 3, label: '남성&스포츠' },
  { value: 4, label: '디지털' },
  { value: 5, label: '홈&생활' },
  { value: 6, label: '식품' },
  { value: 7, label: '엔터테인먼트' },
  { value: 8, label: '베이비&키즈' },
];

export default function BestsellerPage() {
  const [items, setItems] = useState<BestsellerItem[]>([]);
  const [category, setCategory] = useState(0);
  const [loading, setLoading] = useState(false);

  const fetchItems = async () => {
    try {
      const res = await getBestsellers();
      setItems(res.data);
    } catch { /* ignore */ }
  };

  useEffect(() => { fetchItems(); }, []);

  const handleCollect = async () => {
    setLoading(true);
    try {
      await collectBestsellers(category);
      setTimeout(fetchItems, 10000);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">인기상품</h2>

      <div className="bg-white rounded-lg shadow p-5 mb-4">
        <div className="flex gap-3 items-end">
          <div>
            <label className="block text-sm text-gray-600 mb-1">카테고리</label>
            <select
              value={category}
              onChange={e => setCategory(Number(e.target.value))}
              className="border rounded px-3 py-2 text-sm"
            >
              {CATEGORIES.map(c => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
          </div>
          <button
            onClick={handleCollect}
            disabled={loading}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
          >
            인기상품 수집
          </button>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="px-3 py-2 text-left">순위</th>
              <th className="px-3 py-2 text-left w-12">이미지</th>
              <th className="px-3 py-2 text-left">상품명</th>
              <th className="px-3 py-2 text-left">브랜드</th>
              <th className="px-3 py-2 text-right">가격(엔)</th>
              <th className="px-3 py-2 text-right">판매량</th>
              <th className="px-3 py-2 text-left">카테고리</th>
              <th className="px-3 py-2 text-center">조회날짜</th>
            </tr>
          </thead>
          <tbody>
            {items.map(item => (
              <tr key={item.id} className="border-b hover:bg-gray-50">
                <td className="px-3 py-2">{item.rank}</td>
                <td className="px-3 py-2">
                  {item.cover_image_url && <img src={item.cover_image_url} alt="" className="w-10 h-10 object-cover rounded" />}
                </td>
                <td className="px-3 py-2">
                  {item.product_url ? (
                    <a href={item.product_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
                      {item.product_name}
                    </a>
                  ) : item.product_name}
                </td>
                <td className="px-3 py-2">{item.brand || '-'}</td>
                <td className="px-3 py-2 text-right">{item.price_jpy?.toLocaleString()}</td>
                <td className="px-3 py-2 text-right">{item.sales_volume?.toLocaleString() || '-'}</td>
                <td className="px-3 py-2">{item.category}</td>
                <td className="px-3 py-2 text-center">{item.lookup_date}</td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr><td colSpan={8} className="px-3 py-8 text-center text-gray-400">데이터 없음</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

import { useEffect, useState } from 'react';
import { getTrackingItems, addTrackingItem, runTracking } from '../api/endpoints';
import type { TrackingItem } from '../types';

export default function TrackingPage() {
  const [items, setItems] = useState<TrackingItem[]>([]);
  const [productId, setProductId] = useState('');
  const [keyword, setKeyword] = useState('');
  const [loading, setLoading] = useState(false);

  const fetchItems = async () => {
    try {
      const res = await getTrackingItems();
      setItems(res.data);
    } catch { /* ignore */ }
  };

  useEffect(() => { fetchItems(); }, []);

  const handleAdd = async () => {
    if (!productId.trim() || !keyword.trim()) return;
    await addTrackingItem({ product_id: productId, keyword });
    setProductId('');
    setKeyword('');
    fetchItems();
  };

  const handleRun = async () => {
    setLoading(true);
    try {
      await runTracking();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">순위 추적</h2>

      <div className="bg-white rounded-lg shadow p-5 mb-4">
        <h3 className="font-semibold mb-3">추적 항목 추가</h3>
        <div className="flex gap-3 items-end">
          <div>
            <label className="block text-sm text-gray-600 mb-1">상품번호</label>
            <input
              value={productId}
              onChange={e => setProductId(e.target.value)}
              className="border rounded px-3 py-2 text-sm"
              placeholder="예: 123456789"
            />
          </div>
          <div>
            <label className="block text-sm text-gray-600 mb-1">검색 키워드</label>
            <input
              value={keyword}
              onChange={e => setKeyword(e.target.value)}
              className="border rounded px-3 py-2 text-sm"
              placeholder="일본어 키워드"
            />
          </div>
          <button onClick={handleAdd} className="px-4 py-2 bg-green-600 text-white text-sm rounded hover:bg-green-700">추가</button>
          <button onClick={handleRun} disabled={loading} className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50">
            순위 추적 실행
          </button>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="px-3 py-2 text-left">상품번호</th>
              <th className="px-3 py-2 text-left">키워드</th>
              <th className="px-3 py-2 text-left">상품명</th>
            </tr>
          </thead>
          <tbody>
            {items.map(item => (
              <tr key={item.id} className="border-b hover:bg-gray-50">
                <td className="px-3 py-2">{item.product_id}</td>
                <td className="px-3 py-2">{item.keyword}</td>
                <td className="px-3 py-2">{item.product_name || '-'}</td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr><td colSpan={3} className="px-3 py-8 text-center text-gray-400">추적 항목 없음</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

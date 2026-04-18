import { useEffect, useState } from 'react';
import { getBidHistory, collectBidResults } from '../api/endpoints';
import type { BidHistory } from '../types';

export default function BidPage() {
  const [bids, setBids] = useState<BidHistory[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);

  const fetchBids = async () => {
    try {
      const res = await getBidHistory();
      setBids(res.data);
    } catch { /* ignore */ }
  };

  useEffect(() => { fetchBids(); }, []);

  const handleCollect = async () => {
    if (!input.trim()) return;
    setLoading(true);
    try {
      const kws = input.split('\n').map(s => s.trim()).filter(Boolean);
      await collectBidResults(kws);
      setTimeout(fetchBids, 5000);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">경매 결과</h2>

      <div className="bg-white rounded-lg shadow p-5 mb-4">
        <h3 className="font-semibold mb-3">경매 결과 수집</h3>
        <div className="flex gap-3 items-end">
          <div className="flex-1">
            <label className="block text-sm text-gray-600 mb-1">키워드 (줄바꿈 구분)</label>
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              rows={3}
              className="border rounded px-3 py-2 text-sm w-full"
              placeholder="키워드를 입력하세요"
            />
          </div>
          <button
            onClick={handleCollect}
            disabled={loading}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
          >
            수집
          </button>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="px-3 py-2 text-left">키워드</th>
              <th className="px-3 py-2 text-right">낙찰수</th>
              <th className="px-3 py-2 text-right">1위</th>
              <th className="px-3 py-2 text-right">2위</th>
              <th className="px-3 py-2 text-right">3위</th>
              <th className="px-3 py-2 text-right">4위</th>
              <th className="px-3 py-2 text-right">5위</th>
              <th className="px-3 py-2 text-center">조회날짜</th>
            </tr>
          </thead>
          <tbody>
            {bids.map(b => (
              <tr key={b.id} className="border-b hover:bg-gray-50">
                <td className="px-3 py-2">{b.keyword_jp}</td>
                <td className="px-3 py-2 text-right">{b.bid_count}</td>
                <td className="px-3 py-2 text-right">{b.bid_price_1?.toLocaleString()}</td>
                <td className="px-3 py-2 text-right">{b.bid_price_2?.toLocaleString()}</td>
                <td className="px-3 py-2 text-right">{b.bid_price_3?.toLocaleString()}</td>
                <td className="px-3 py-2 text-right">{b.bid_price_4?.toLocaleString()}</td>
                <td className="px-3 py-2 text-right">{b.bid_price_5?.toLocaleString()}</td>
                <td className="px-3 py-2 text-center">{b.lookup_date}</td>
              </tr>
            ))}
            {bids.length === 0 && (
              <tr><td colSpan={8} className="px-3 py-8 text-center text-gray-400">데이터 없음</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

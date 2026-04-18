import { useEffect, useState } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import { getNewKeywords, getKeywordChanges, getKeywordTimeseries } from '../api/endpoints';

interface ChangeItem {
  keyword_jp: string;
  keyword_kr?: string;
  category?: string;
  classification?: string;
  rank_old: number;
  rank_new: number;
  rank_delta: number;
  search_volume_old: number;
  search_volume_new: number;
  search_volume_pct: number | null;
}

interface NewItem {
  keyword_jp: string;
  keyword_kr?: string;
  category?: string;
  classification?: string;
  rank: number;
  search_volume_weekly?: number;
  lookup_date: string;
}

interface SeriesPoint {
  date: string;
  rank: number | null;
  search_volume: number | null;
}

const WINDOWS = [1, 7];

function KeywordLink({ kw }: { kw: string }) {
  return (
    <a href={`https://www.qoo10.jp/s/?keyword=${kw}`} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">
      {kw}
    </a>
  );
}

function Badge({ children, color = 'gray' }: any) {
  const colors: any = {
    green: 'bg-green-100 text-green-700',
    red: 'bg-red-100 text-red-700',
    gray: 'bg-gray-100 text-gray-700',
    blue: 'bg-blue-100 text-blue-700',
    amber: 'bg-amber-100 text-amber-700',
  };
  return <span className={`inline-block px-1.5 py-0.5 text-[10px] rounded ${colors[color]}`}>{children}</span>;
}

function ChangesTable({ items, mode }: { items: ChangeItem[]; mode: 'rising' | 'falling'; }) {
  if (items.length === 0) return <div className="text-gray-400 text-sm py-4">데이터 없음</div>;
  return (
    <table className="w-full text-xs">
      <thead className="bg-gray-50 border-b">
        <tr>
          <th className="px-2 py-1 text-left">키워드</th>
          <th className="px-2 py-1 text-left">한국어</th>
          <th className="px-2 py-1 text-left">카테고리</th>
          <th className="px-2 py-1 text-right">이전→현재</th>
          <th className="px-2 py-1 text-right">변화</th>
          <th className="px-2 py-1 text-right">검색량</th>
        </tr>
      </thead>
      <tbody>
        {items.map((it, i) => (
          <tr key={i} className="border-b hover:bg-gray-50">
            <td className="px-2 py-1"><KeywordLink kw={it.keyword_jp} /></td>
            <td className="px-2 py-1">{it.keyword_kr || '-'}</td>
            <td className="px-2 py-1">{it.category} / {it.classification}</td>
            <td className="px-2 py-1 text-right font-mono">{it.rank_old} → {it.rank_new}</td>
            <td className="px-2 py-1 text-right font-semibold">
              {mode === 'rising' ? (
                <Badge color="green">▲ {it.rank_delta}</Badge>
              ) : (
                <Badge color="red">▼ {Math.abs(it.rank_delta)}</Badge>
              )}
            </td>
            <td className="px-2 py-1 text-right">
              {it.search_volume_new.toLocaleString()}
              {it.search_volume_pct !== null && (
                <span className={`ml-1 text-[10px] ${it.search_volume_pct >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                  {it.search_volume_pct >= 0 ? '+' : ''}{it.search_volume_pct}%
                </span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function KeywordModal({ keyword, onClose }: { keyword: string; onClose: () => void }) {
  const [series, setSeries] = useState<SeriesPoint[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    getKeywordTimeseries(keyword, 90)
      .then(r => setSeries(r.data.series || []))
      .catch(() => setSeries([]))
      .finally(() => setLoading(false));
  }, [keyword]);

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-3xl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold"><KeywordLink kw={keyword} /> 추이</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">닫기 ✕</button>
        </div>
        {loading ? (
          <div className="text-center py-10 text-gray-400">불러오는 중...</div>
        ) : series.length < 2 ? (
          <div className="text-center py-10 text-gray-400">
            추이를 보려면 2일 이상 데이터가 필요합니다 (현재 {series.length}일)
          </div>
        ) : (
          <>
            <div className="mb-4">
              <h4 className="text-sm font-semibold mb-2">순위 추이 (낮을수록 좋음)</h4>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={series}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                  <YAxis reversed tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="rank" stroke="#2563eb" name="순위" />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div>
              <h4 className="text-sm font-semibold mb-2">검색량 추이 (주평)</h4>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={series}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="search_volume" stroke="#10b981" name="검색량" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function WindowSection({ daysBack }: { daysBack: number }) {
  const [news, setNews] = useState<NewItem[]>([]);
  const [rising, setRising] = useState<ChangeItem[]>([]);
  const [falling, setFalling] = useState<ChangeItem[]>([]);
  const [latest, setLatest] = useState<string | null>(null);
  const [compareTo, setCompareTo] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [selectedKeyword, setSelectedKeyword] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      getNewKeywords(daysBack).then(r => { setNews(r.data.new_keywords || []); setLatest(r.data.latest); }),
      getKeywordChanges(daysBack).then(r => {
        setRising(r.data.rising || []);
        setFalling(r.data.falling || []);
        setCompareTo(r.data.compare_to);
        if (r.data.message) setErr(r.data.message);
      }),
    ]).catch(e => setErr(String(e)));
  }, [daysBack]);

  return (
    <div className="bg-white rounded-lg shadow p-4 mb-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-base font-bold">{daysBack}일 전 대비 변화</h3>
        <div className="text-xs text-gray-500">
          최신: {latest || '-'} / 비교 기준일: {compareTo || '-'}
        </div>
      </div>
      {err && <div className="bg-amber-50 text-amber-700 text-xs p-2 rounded mb-2">{err}</div>}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div>
          <h4 className="text-sm font-semibold mb-2">🆕 신규 키워드 ({news.length})</h4>
          <div className="max-h-[360px] overflow-y-auto border rounded">
            {news.length === 0 ? (
              <div className="text-gray-400 text-xs p-3">신규 키워드 없음</div>
            ) : (
              <table className="w-full text-xs">
                <tbody>
                  {news.slice(0, 50).map((it, i) => (
                    <tr
                      key={i}
                      className="border-b hover:bg-gray-50 cursor-pointer"
                      onClick={() => setSelectedKeyword(it.keyword_jp)}
                    >
                      <td className="px-2 py-1 w-8 text-right text-gray-400">{it.rank}</td>
                      <td className="px-2 py-1"><KeywordLink kw={it.keyword_jp} /></td>
                      <td className="px-2 py-1 text-gray-500">{it.keyword_kr}</td>
                      <td className="px-2 py-1 text-right text-gray-500">{it.search_volume_weekly?.toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
        <div>
          <h4 className="text-sm font-semibold mb-2 text-green-700">📈 급상승 TOP</h4>
          <div className="max-h-[360px] overflow-y-auto border rounded">
            <ChangesTable items={rising} mode="rising" />
          </div>
        </div>
        <div>
          <h4 className="text-sm font-semibold mb-2 text-red-700">📉 급하락 TOP</h4>
          <div className="max-h-[360px] overflow-y-auto border rounded">
            <ChangesTable items={falling} mode="falling" />
          </div>
        </div>
      </div>

      {selectedKeyword && (
        <KeywordModal keyword={selectedKeyword} onClose={() => setSelectedKeyword(null)} />
      )}
    </div>
  );
}

export default function InsightsPage() {
  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">📈 시계열 인사이트</h2>
      <div className="bg-blue-50 border-l-4 border-blue-400 text-xs p-3 mb-4 rounded">
        💡 신규/급상승/급하락은 2일 이상 누적된 데이터가 있을 때 유효합니다.
        키워드를 클릭하면 최대 90일 추이 차트가 표시됩니다.
      </div>
      {WINDOWS.map(d => <WindowSection key={d} daysBack={d} />)}
    </div>
  );
}

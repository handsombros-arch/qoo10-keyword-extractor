import { useEffect, useState } from 'react';
import api from '../api/client';

type BlacklistItem = {
  id: string;
  keyword_jp?: string;
  product_name?: string;
  reason?: string;
  added_at?: string;
  source?: string;
};

export default function BlacklistPage() {
  const [items, setItems] = useState<BlacklistItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState('');

  async function load() {
    setLoading(true);
    try {
      const r = await api.get<{ items: BlacklistItem[]; total: number }>('/blacklist');
      setItems(r.data.items || []);
    } catch (e: any) {
      setMsg(`✗ 로드 실패: ${e?.message || e}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function removeItem(id: string) {
    if (!confirm('삭제하시겠습니까?')) return;
    try {
      await api.delete(`/blacklist/${id}`);
      setMsg('✓ 삭제됨');
      load();
    } catch (e: any) {
      setMsg(`✗ ${e?.response?.data?.detail || e.message}`);
    }
  }

  return (
    <div className="p-6 max-w-5xl">
      <h1 className="text-xl font-bold mb-4">⛔ 블랙리스트</h1>
      <p className="text-sm text-gray-600 mb-2">
        소싱 계획 없는 상품/키워드. 자동화 [시트로 보내기] 시 매칭되면 시트 추가 안 함 (사전 차단).
      </p>
      <div className="bg-blue-50 border-l-4 border-blue-400 text-xs p-3 mb-4 rounded">
        💡 <strong>추가 방법</strong>: <code>상품 시트</code> 페이지 → 행 클릭 → 우측 패널 하단 <code>⛔ 블랙리스트</code> 버튼.
        직접 입력 비활성화됨 (실수 방지).
      </div>

      {msg && (
        <div className={`text-xs mb-3 ${
          msg.startsWith('✓') ? 'text-emerald-700' :
          msg.startsWith('⚠') ? 'text-amber-700' :
          'text-red-700'
        }`}>{msg}</div>
      )}

      {/* 목록 */}
      <div className="border rounded overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-100 text-left">
            <tr>
              <th className="px-3 py-2">keyword_jp</th>
              <th className="px-3 py-2">product_name</th>
              <th className="px-3 py-2">사유</th>
              <th className="px-3 py-2 w-32">추가일</th>
              <th className="px-3 py-2 w-20">출처</th>
              <th className="px-3 py-2 w-16"></th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={6} className="px-3 py-4 text-center text-gray-500">로딩...</td></tr>
            )}
            {!loading && items.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-4 text-center text-gray-400">블랙리스트 항목 없음</td></tr>
            )}
            {items.map(it => (
              <tr key={it.id} className="border-t hover:bg-gray-50">
                <td className="px-3 py-2 font-mono text-xs">{it.keyword_jp || '-'}</td>
                <td className="px-3 py-2 text-xs">{it.product_name || '-'}</td>
                <td className="px-3 py-2 text-xs text-gray-600">{it.reason || '-'}</td>
                <td className="px-3 py-2 text-[10px] text-gray-500">
                  {(it.added_at || '').slice(0, 10)}
                </td>
                <td className="px-3 py-2 text-[10px] text-gray-500">{it.source || '-'}</td>
                <td className="px-3 py-2">
                  <button
                    onClick={() => removeItem(it.id)}
                    className="text-red-600 hover:underline text-xs"
                  >
                    삭제
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4 text-xs text-gray-500">
        총 {items.length}개 · 매칭 우선순위: keyword_jp 정확 매칭 → product_name 정확 매칭 (대소문자/공백 정규화)
      </div>
    </div>
  );
}

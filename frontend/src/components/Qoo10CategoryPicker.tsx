/**
 * 큐텐 등록 카테고리 선택 모달 (V, 5/3).
 * Qoo10_CategoryInfo.csv 의 3-level (대/중/소) 카테고리 검색 + 선택.
 */
import { useEffect, useMemo, useState } from 'react';
import { Search, X, Check } from 'lucide-react';
import api from '../api/client';

interface Qoo10Category {
  l_code: string;
  l_name: string;
  m_code: string;
  m_name: string;
  s_code: string;
  s_name: string;
  path: string;
}

interface Props {
  initialCode?: string;
  onSelect: (cat: Qoo10Category) => void;
  onClose: () => void;
}

export default function Qoo10CategoryPicker({ initialCode, onSelect, onClose }: Props) {
  const [allCats, setAllCats] = useState<Qoo10Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');
  const [selectedL, setSelectedL] = useState<string | null>(null);
  const [selectedM, setSelectedM] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const r = await api.get<{ items: Qoo10Category[] }>('/qoo10-categories');
        setAllCats(r.data.items || []);
        // initialCode 매칭 시 cascade 미리 설정
        if (initialCode) {
          const found = (r.data.items || []).find(c => c.s_code === initialCode);
          if (found) {
            setSelectedL(found.l_code);
            setSelectedM(found.m_code);
          }
        }
      } catch (e) {
        console.error('[Qoo10Cat] load fail', e);
      } finally {
        setLoading(false);
      }
    })();
  }, [initialCode]);

  // 대카테고리 list (unique)
  const lCats = useMemo(() => {
    const map = new Map<string, { code: string; name: string }>();
    for (const c of allCats) {
      if (!map.has(c.l_code)) map.set(c.l_code, { code: c.l_code, name: c.l_name });
    }
    return Array.from(map.values());
  }, [allCats]);

  // 검색 모드 vs cascade 모드 — 검색어 있으면 flat 검색
  const isSearch = q.trim().length > 0;
  const filtered = useMemo(() => {
    if (isSearch) {
      const ql = q.trim().toLowerCase();
      return allCats
        .filter(c =>
          c.l_name.toLowerCase().includes(ql) ||
          c.m_name.toLowerCase().includes(ql) ||
          c.s_name.toLowerCase().includes(ql)
        )
        .slice(0, 200);  // 상한
    }
    // cascade
    if (!selectedL) return [];
    return allCats.filter(c =>
      c.l_code === selectedL && (selectedM ? c.m_code === selectedM : true)
    );
  }, [isSearch, q, allCats, selectedL, selectedM]);

  // 중카테고리 list — selectedL 기준
  const mCats = useMemo(() => {
    if (!selectedL) return [];
    const map = new Map<string, { code: string; name: string }>();
    for (const c of allCats) {
      if (c.l_code !== selectedL) continue;
      if (!map.has(c.m_code)) map.set(c.m_code, { code: c.m_code, name: c.m_name });
    }
    return Array.from(map.values());
  }, [allCats, selectedL]);

  // 소카테고리 list — selectedM 기준
  const sCats = useMemo(() => {
    if (!selectedL || !selectedM) return [];
    return allCats.filter(c => c.l_code === selectedL && c.m_code === selectedM);
  }, [allCats, selectedL, selectedM]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.4)', backdropFilter: 'blur(4px)' }}
      onClick={onClose}
    >
      <div
        className="bg-apple-bg rounded-2xl shadow-xl w-[760px] max-h-[80vh] flex flex-col"
        style={{ border: '1px solid var(--color-apple-border)' }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-5 py-4 border-b flex items-center justify-between" style={{ borderBottomColor: 'var(--color-apple-border)' }}>
          <div>
            <h3 className="apple-title-3">큐텐 등록 카테고리</h3>
            <p className="text-[12px] text-apple-text-3 mt-0.5">
              {loading ? '로딩…' : `총 ${allCats.length}개 (Qoo10_CategoryInfo.csv)`}
            </p>
          </div>
          <button onClick={onClose} className="apple-btn apple-btn-ghost apple-btn-sm" style={{ padding: '6px 10px' }}>
            <X size={14} />
          </button>
        </div>

        {/* Search */}
        <div className="px-5 py-3 border-b flex items-center gap-2" style={{ borderBottomColor: 'var(--color-apple-border)' }}>
          <Search size={16} className="text-apple-text-3 shrink-0" />
          <input
            type="text"
            value={q}
            onChange={e => setQ(e.target.value)}
            placeholder="대/중/소 카테고리 이름 검색 (비우면 cascade 선택)"
            className="flex-1 outline-none bg-transparent text-[14px] tracking-tight"
            autoFocus
          />
          {isSearch && (
            <span className="text-[11px] text-apple-text-3">
              {filtered.length}개 매칭 (최대 200)
            </span>
          )}
        </div>

        {/* Body */}
        {isSearch ? (
          /* 검색 결과 — flat list */
          <div className="flex-1 overflow-y-auto px-5 py-2">
            {filtered.length === 0 && !loading && (
              <div className="text-[13px] text-apple-text-3 py-8 text-center">
                "{q}" 매칭 카테고리 없음
              </div>
            )}
            <ul className="space-y-0.5">
              {filtered.map(c => (
                <li
                  key={c.s_code}
                  onClick={() => onSelect(c)}
                  className={`px-3 py-2 rounded-lg cursor-pointer hover:bg-apple-bg-2 transition-colors ${
                    initialCode === c.s_code ? 'bg-apple-bg-2' : ''
                  }`}
                >
                  <div className="text-[13px] tracking-tight">
                    <span className="text-apple-text-3">{c.l_name} › {c.m_name} ›</span>
                    <span className="ml-1 font-medium">{c.s_name}</span>
                    {initialCode === c.s_code && <Check size={12} className="inline-block ml-2 text-apple-accent" />}
                  </div>
                  <div className="text-[10px] text-apple-text-3 mt-0.5 font-mono">{c.s_code}</div>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          /* Cascade — 3 컬럼 */
          <div className="flex-1 grid grid-cols-3 divide-x" style={{ minHeight: 320, borderColor: 'var(--color-apple-border)' }}>
            <div className="overflow-y-auto" style={{ borderColor: 'var(--color-apple-border)' }}>
              <div className="sticky top-0 px-3 py-1.5 bg-apple-bg-2 text-[11px] uppercase tracking-wider text-apple-text-3 font-medium">대 ({lCats.length})</div>
              {lCats.map(c => (
                <div
                  key={c.code}
                  onClick={() => { setSelectedL(c.code); setSelectedM(null); }}
                  className={`px-3 py-1.5 cursor-pointer text-[13px] tracking-tight ${
                    selectedL === c.code
                      ? 'bg-apple-accent text-white'
                      : 'hover:bg-apple-bg-2'
                  }`}
                >
                  {c.name}
                </div>
              ))}
            </div>
            <div className="overflow-y-auto">
              <div className="sticky top-0 px-3 py-1.5 bg-apple-bg-2 text-[11px] uppercase tracking-wider text-apple-text-3 font-medium">중 ({mCats.length})</div>
              {!selectedL ? (
                <div className="text-[12px] text-apple-text-3 italic px-3 py-3">대 선택</div>
              ) : (
                mCats.map(c => (
                  <div
                    key={c.code}
                    onClick={() => setSelectedM(c.code)}
                    className={`px-3 py-1.5 cursor-pointer text-[13px] tracking-tight ${
                      selectedM === c.code
                        ? 'bg-apple-accent text-white'
                        : 'hover:bg-apple-bg-2'
                    }`}
                  >
                    {c.name}
                  </div>
                ))
              )}
            </div>
            <div className="overflow-y-auto">
              <div className="sticky top-0 px-3 py-1.5 bg-apple-bg-2 text-[11px] uppercase tracking-wider text-apple-text-3 font-medium">소 ({sCats.length})</div>
              {!selectedM ? (
                <div className="text-[12px] text-apple-text-3 italic px-3 py-3">중 선택</div>
              ) : (
                sCats.map(c => (
                  <div
                    key={c.s_code}
                    onClick={() => onSelect(c)}
                    className={`px-3 py-1.5 cursor-pointer text-[13px] tracking-tight ${
                      initialCode === c.s_code
                        ? 'bg-apple-bg-2 font-medium'
                        : 'hover:bg-apple-bg-2'
                    }`}
                  >
                    <div>{c.s_name}</div>
                    <div className="text-[10px] text-apple-text-3 font-mono">{c.s_code}</div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

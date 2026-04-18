import { useEffect, useMemo, useRef, useState } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { themeQuartz } from 'ag-grid-community';

const myTheme = themeQuartz.withParams({
  fontSize: 12,
  headerFontSize: 12,
  rowHeight: 30,
  headerHeight: 34,
  iconSize: 12,
  headerTextColor: '#111827',
  headerBackgroundColor: '#f3f4f6',
  foregroundColor: '#1f2937',
  headerFontWeight: 700,
});
import type { ColDef } from 'ag-grid-community';
import { getKeywords, listKeywordDates } from '../api/endpoints';
import type { Keyword } from '../types';
import CheckboxSetFilter from '../components/Grid/CheckboxSetFilter';

interface KeywordWithScore extends Keyword {
  kr_ratio: number;
  recommend_score: number;
}

function CriteriaModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[85vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="px-6 py-4 border-b flex justify-between items-center sticky top-0 bg-white">
          <h3 className="text-lg font-bold">⭐ 역직구 추천 기준 안내</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl leading-none">✕</button>
        </div>
        <div className="px-6 py-4 text-sm space-y-5">
          <section>
            <h4 className="font-bold text-base mb-2">🎯 목적</h4>
            <p className="text-gray-700">
              한국에서 일본으로 판매할 <b>역직구 상품</b>에 적합한 큐텐 키워드를 찾기 위한 점수 시스템입니다.
            </p>
          </section>

          <section>
            <h4 className="font-bold text-base mb-2">📐 추천점수 계산식</h4>
            <div className="bg-gray-50 border rounded p-3 font-mono text-xs">
              score = log₁₀(검색량 + 1) × (한국비율 ÷ 100) ÷ max(경쟁강도, 0.1)
            </div>
            <ul className="mt-2 space-y-1 text-gray-700 list-disc list-inside">
              <li><b>검색량(주평) ↑</b> → 점수 ↑ &nbsp;<span className="text-gray-500">(시장이 크다)</span></li>
              <li><b>한국비율 ↑</b> → 점수 ↑ &nbsp;<span className="text-gray-500">(한국 셀러 선점 → 수요 검증됨)</span></li>
              <li><b>경쟁강도 ↑</b> → 점수 ↓ &nbsp;<span className="text-gray-500">(상품이 너무 많으면 진입 어려움)</span></li>
              <li>log를 쓰는 이유: 검색량이 10배 차이 나도 점수는 1만 증가 → 극단값 왜곡 방지</li>
            </ul>
          </section>

          <section>
            <h4 className="font-bold text-base mb-2">📊 각 지표 정의</h4>
            <table className="w-full text-xs border">
              <thead className="bg-gray-50">
                <tr>
                  <th className="border px-2 py-1 text-left">지표</th>
                  <th className="border px-2 py-1 text-left">계산</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="border px-2 py-1">검색량(주평)</td>
                  <td className="border px-2 py-1">큐텐 내 주간 평균 검색 수</td>
                </tr>
                <tr>
                  <td className="border px-2 py-1">전체 상품수</td>
                  <td className="border px-2 py-1">큐텐 검색 결과 페이지 상단 숫자</td>
                </tr>
                <tr>
                  <td className="border px-2 py-1">한국 상품수</td>
                  <td className="border px-2 py-1">전체 상품 중 출하지 = 한국인 상품</td>
                </tr>
                <tr>
                  <td className="border px-2 py-1">한국비율</td>
                  <td className="border px-2 py-1">한국 상품수 ÷ 전체 상품수 × 100</td>
                </tr>
                <tr>
                  <td className="border px-2 py-1">경쟁강도</td>
                  <td className="border px-2 py-1">전체 상품수 ÷ 검색량(주평)</td>
                </tr>
              </tbody>
            </table>
          </section>

          <section>
            <h4 className="font-bold text-base mb-2">🎚 추천 임계값 (필터)</h4>
            <p className="text-gray-700 mb-2">아래 조건을 <b>모두 만족하는 키워드만</b> 추천 목록에 표시됩니다.</p>
            <table className="w-full text-xs border">
              <thead className="bg-gray-50">
                <tr>
                  <th className="border px-2 py-1 text-left">슬라이더</th>
                  <th className="border px-2 py-1 text-left">의미</th>
                  <th className="border px-2 py-1 text-left">기본값</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="border px-2 py-1">최소 검색수(주평)</td>
                  <td className="border px-2 py-1">주당 N회 미만 검색 키워드 제외 (너무 작은 시장)</td>
                  <td className="border px-2 py-1">100</td>
                </tr>
                <tr>
                  <td className="border px-2 py-1">최소 한국비율(%)</td>
                  <td className="border px-2 py-1">한국 상품 비율 N% 미만 제외 (역직구 수요 약함)</td>
                  <td className="border px-2 py-1">10</td>
                </tr>
                <tr>
                  <td className="border px-2 py-1">경쟁강도 최소</td>
                  <td className="border px-2 py-1">너무 낮은 값 제외 (데이터 불충분한 키워드)</td>
                  <td className="border px-2 py-1">0.1</td>
                </tr>
                <tr>
                  <td className="border px-2 py-1">경쟁강도 최대</td>
                  <td className="border px-2 py-1">과포화 시장 제외 (레드오션)</td>
                  <td className="border px-2 py-1">10</td>
                </tr>
              </tbody>
            </table>
          </section>

          <section className="bg-amber-50 border-l-4 border-amber-400 p-3 rounded text-xs">
            <b>💡 활용 팁</b>
            <ul className="list-disc list-inside mt-1 space-y-0.5 text-gray-700">
              <li>첫 탐색: 기본값 유지 → 점수 상위 20~30개 훑기</li>
              <li>신규 진입 선호: <b>경쟁강도 최대</b> 5로 낮춰서 블루오션 탐색</li>
              <li>큰 시장 선호: <b>최소 검색수</b> 1000 이상으로 올리기</li>
              <li>브랜드키워드(B 배지)는 상표권 이슈 있을 수 있으니 별도 검토</li>
            </ul>
          </section>
        </div>
      </div>
    </div>
  );
}

export default function RecommendPage() {
  const [showCriteria, setShowCriteria] = useState(false);
  const gridRef = useRef<AgGridReact>(null);
  const resizedColsRef = useRef<Set<string>>(new Set());
  const COL_STATE_KEY = 'recommendPage.colState';

  const saveColState = () => {
    const api = gridRef.current?.api as any;
    if (!api) return;
    try {
      const state = api.getColumnState?.();
      if (state) localStorage.setItem(COL_STATE_KEY, JSON.stringify(state));
    } catch { /* ignore */ }
  };
  const restoreColState = () => {
    const api = gridRef.current?.api as any;
    if (!api) return;
    try {
      const raw = localStorage.getItem(COL_STATE_KEY);
      if (!raw) return;
      const state = JSON.parse(raw);
      api.applyColumnState?.({ state, applyOrder: true });
      state.forEach((c: any) => { if (c.colId && c.width) resizedColsRef.current.add(c.colId); });
    } catch { /* ignore */ }
  };

  const handleColumnResized = (e: any) => {
    if (e.source === 'uiColumnResized' && e.column) {
      resizedColsRef.current.add(e.column.getColId());
      saveColState();
    }
  };
  const handleColumnMoved = (e: any) => { if (e.source === 'uiColumnDragged' || e.finished) saveColState(); };
  const handleSortChanged = () => saveColState();
  const handleGridReady = () => { restoreColState(); };
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [dates, setDates] = useState<{ lookup_date: string; count: number }[]>([]);

  // 기간 필터: mode = single(특정일) | range(기간) | all(전체)
  const [mode, setMode] = useState<'single' | 'range' | 'all'>('all');
  const [singleDate, setSingleDate] = useState('');
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');

  // 임계값
  const [minSearch, setMinSearch] = useState(50);
  const [minKrRatio, setMinKrRatio] = useState(5);
  const [compMin, setCompMin] = useState(0.1);
  const [compMax, setCompMax] = useState(15);
  // 중복 제거 / 브랜드 필터
  const [dedupe, setDedupe] = useState(true);
  const [brandFilter, setBrandFilter] = useState<'all' | 'general' | 'brand'>('all');

  useEffect(() => {
    Promise.all([getKeywords().then(r => setKeywords(r.data)).catch(() => {}),
                 listKeywordDates().then(r => setDates(r.data)).catch(() => {})]);
  }, []);

  // 데이터 변경 시 사용자가 조정 안 한 컬럼 자동 크기
  useEffect(() => {
    const api = gridRef.current?.api as any;
    if (!api) return;
    const cols = (api.getColumns?.() || [])
      .filter((c: any) => !resizedColsRef.current.has(c.getColId()))
      .map((c: any) => c.getColId());
    if (cols.length) {
      try { api.autoSizeColumns(cols, false); } catch { /* ignore */ }
    }
  }, [keywords]);

  const reload = () => {
    getKeywords().then(r => setKeywords(r.data)).catch(() => {});
  };

  const isBrand = (jp?: string) => !!jp && /^[a-zA-Z0-9\s\-_.&'+]+$/.test(jp);

  // 가공: kr_ratio, recommend_score 계산 + 기간/임계값 필터
  const enriched: (KeywordWithScore & { categories?: string[] })[] = useMemo(() => {
    const cmpDate = (d: string | undefined): boolean => {
      if (!d) return false;
      if (mode === 'single') return singleDate ? d === singleDate : true;
      if (mode === 'range') {
        if (fromDate && d < fromDate) return false;
        if (toDate && d > toDate) return false;
        return true;
      }
      return true;
    };
    let rows = keywords
      .filter(kw => cmpDate(kw.lookup_date))
      .map(kw => {
        const total = kw.total_products || 0;
        const kr = kw.products_kr || 0;
        const sw = kw.search_volume_weekly || 0;
        const comp = kw.competition_intensity || 0;
        const kr_ratio = total > 0 ? (kr / total) * 100 : 0;
        const compFactor = Math.max(comp, 0.1);
        const recommend_score = (sw > 0 && total > 0)
          ? (Math.log10(sw + 1) * (kr / total)) / compFactor
          : 0;
        return { ...kw, kr_ratio, recommend_score };
      })
      .filter(kw => {
        if ((kw.search_volume_weekly || 0) < minSearch) return false;
        if (kw.kr_ratio < minKrRatio) return false;
        const c = kw.competition_intensity || 0;
        if (c < compMin || c > compMax) return false;
        if (brandFilter === 'general' && isBrand(kw.keyword_jp)) return false;
        if (brandFilter === 'brand' && !isBrand(kw.keyword_jp)) return false;
        return true;
      });

    // 키워드 중복 제거: 같은 keyword_jp는 최고 점수만, 카테고리 목록 합침
    if (dedupe) {
      const byKw = new Map<string, KeywordWithScore & { categories: string[] }>();
      for (const r of rows) {
        const k = r.keyword_jp;
        const existing = byKw.get(k);
        const cat = r.category || '';
        if (!existing) {
          byKw.set(k, { ...r, categories: [cat].filter(Boolean) });
        } else {
          if (cat && !existing.categories.includes(cat)) existing.categories.push(cat);
          if (r.recommend_score > existing.recommend_score) {
            const cats = existing.categories;
            byKw.set(k, { ...r, categories: cats });
          }
        }
      }
      rows = Array.from(byKw.values());
    }

    return rows.sort((a, b) => b.recommend_score - a.recommend_score);
  }, [keywords, mode, singleDate, fromDate, toDate, minSearch, minKrRatio, compMin, compMax, dedupe, brandFilter]);

  const numFmt = (p: any) => p.value == null ? '' : Number(p.value).toLocaleString();
  const pctFmt = (p: any) => p.value == null ? '' : `${Number(p.value).toFixed(1)}%`;
  const scoreFmt = (p: any) => p.value == null ? '' : Number(p.value).toFixed(2);

  const columnDefs: ColDef[] = useMemo(() => [
    { field: 'lookup_date', headerName: '조회날짜', width: 110 },
    { headerName: '#', valueGetter: (p: any) => (p.node?.rowIndex ?? 0) + 1, width: 60, sortable: false, filter: false },
    { field: 'recommend_score', headerName: '추천점수', width: 100, type: 'numericColumn', valueFormatter: scoreFmt,
      cellStyle: { fontWeight: 700, backgroundColor: '#ecfeff' } },
    { field: 'keyword_jp', headerName: '키워드(일본어)', width: 180,
      cellRenderer: (p: any) => p.value
        ? <a href={`https://www.qoo10.jp/s/?keyword=${p.value}`} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">{p.value}</a>
        : '' },
    {
      field: 'keyword_kr', headerName: '키워드(한국어)', width: 200,
      cellRenderer: (p: any) => {
        const jp = p.data?.keyword_jp || '';
        const isBrand = /^[a-zA-Z0-9\s\-_.&'+]+$/.test(jp);
        return (
          <span className="inline-flex items-center gap-1">
            <span>{p.value || '-'}</span>
            {isBrand && (
              <span
                title="브랜드키워드"
                className="inline-flex items-center justify-center w-4 h-4 text-[9px] font-bold text-white bg-purple-500 rounded"
              >
                B
              </span>
            )}
          </span>
        );
      },
    },
    { field: 'kr_ratio', headerName: '한국비율(%)', width: 110, type: 'numericColumn', valueFormatter: pctFmt,
      cellStyle: (p: any) => p.value >= 30 ? { backgroundColor: '#fef3c7' } : null },
    {
      field: 'category', headerName: '카테고리', width: 140,
      valueGetter: (p: any) => {
        const cats = p.data?.categories;
        if (Array.isArray(cats) && cats.length > 0) return cats.join(', ');
        return p.data?.category || '';
      },
      cellRenderer: (p: any) => {
        const cats = p.data?.categories;
        if (Array.isArray(cats) && cats.length > 0) {
          const first = cats[0];
          const extra = cats.length - 1;
          return (
            <span className="inline-flex items-center gap-1" title={cats.join(', ')}>
              <span className="truncate">{first}</span>
              {extra > 0 && (
                <span className="px-1 text-[10px] font-semibold text-blue-700 bg-blue-100 rounded">+{extra}</span>
              )}
            </span>
          );
        }
        return p.data?.category || '';
      },
    },
    { field: 'search_volume_weekly', headerName: '검색수(주평)', width: 120, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'competition_intensity', headerName: '경쟁강도', width: 100, type: 'numericColumn' },
    { field: 'total_products', headerName: '전체상품수', width: 120, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'products_kr', headerName: '한국상품수', width: 110, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'products_jp', headerName: '일본', width: 100, type: 'numericColumn', valueFormatter: numFmt },
  ], []);

  const defaultColDef: ColDef = useMemo(() => ({
    sortable: true, resizable: true, filter: CheckboxSetFilter, suppressMovable: false, minWidth: 60,
  }), []);

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">⭐ 역직구 추천 키워드</h2>

      <div className="bg-white rounded-lg shadow p-5 mb-4">
        <h3 className="font-semibold mb-3">조회 기간</h3>
        <div className="flex flex-wrap gap-3 items-center text-sm mb-3">
          <label className="flex items-center gap-1">
            <input type="radio" checked={mode === 'all'} onChange={() => setMode('all')} /> 전체
          </label>
          <label className="flex items-center gap-1">
            <input type="radio" checked={mode === 'single'} onChange={() => setMode('single')} /> 특정일
          </label>
          {mode === 'single' && (
            <select value={singleDate} onChange={e => setSingleDate(e.target.value)} className="border rounded px-2 py-1">
              <option value="">날짜 선택</option>
              {dates.map(d => (
                <option key={d.lookup_date} value={d.lookup_date}>{d.lookup_date} ({d.count}개)</option>
              ))}
            </select>
          )}
          <label className="flex items-center gap-1">
            <input type="radio" checked={mode === 'range'} onChange={() => setMode('range')} /> 기간
          </label>
          {mode === 'range' && (
            <>
              <input type="date" value={fromDate} onChange={e => setFromDate(e.target.value)} className="border rounded px-2 py-1" />
              <span>~</span>
              <input type="date" value={toDate} onChange={e => setToDate(e.target.value)} className="border rounded px-2 py-1" />
            </>
          )}
          <button onClick={reload} className="ml-auto px-3 py-1 bg-gray-200 rounded hover:bg-gray-300 text-xs">새로고침</button>
        </div>

        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold">추천 임계값</h3>
            <button
              onClick={() => setShowCriteria(true)}
              title="추천 기준 안내"
              className="w-5 h-5 flex items-center justify-center text-[11px] font-bold text-white bg-blue-500 hover:bg-blue-600 rounded-full"
            >
              i
            </button>
          </div>
          <div className="flex gap-1">
            <button
              onClick={() => { setMinSearch(50); setMinKrRatio(5); setCompMin(0.1); setCompMax(15); setBrandFilter('all'); setDedupe(true); }}
              className="text-xs px-2 py-1 bg-gray-100 hover:bg-gray-200 rounded"
              title="검색 50 이상, 한국비율 5%, 경쟁강도 0.1~15, 전체 브랜드 포함"
            >
              기본
            </button>
            <button
              onClick={() => { setMinSearch(20); setMinKrRatio(10); setCompMin(0.1); setCompMax(3); setBrandFilter('general'); setDedupe(true); }}
              className="text-xs px-2 py-1 bg-emerald-500 text-white hover:bg-emerald-600 rounded"
              title="블루오션 니치 키워드 탐색: 브랜드 제외 + 검색 20 이상 + 경쟁강도 3 이하"
            >
              🌱 니치 모드
            </button>
            <button
              onClick={() => { setMinSearch(1000); setMinKrRatio(5); setCompMin(0.1); setCompMax(20); setBrandFilter('all'); setDedupe(true); }}
              className="text-xs px-2 py-1 bg-orange-500 text-white hover:bg-orange-600 rounded"
              title="대형 시장: 검색 1000 이상"
            >
              🔥 대형
            </button>
            <button
              onClick={() => { setMinSearch(200); setMinKrRatio(5); setCompMin(0.1); setCompMax(20); setBrandFilter('brand'); setDedupe(true); }}
              className="text-xs px-2 py-1 bg-purple-500 text-white hover:bg-purple-600 rounded"
              title="브랜드 키워드만 보기"
            >
              💎 브랜드만
            </button>
          </div>
        </div>

        <div className="flex gap-4 items-center mb-3 text-xs">
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={dedupe} onChange={e => setDedupe(e.target.checked)} />
            동일 키워드 중복 제거 (카테고리 합치기)
          </label>
          <div className="flex items-center gap-1">
            <span className="text-gray-600">브랜드 필터:</span>
            {[
              { v: 'all', label: '전체' },
              { v: 'general', label: '일반만' },
              { v: 'brand', label: '브랜드만' },
            ].map(b => (
              <button
                key={b.v}
                onClick={() => setBrandFilter(b.v as any)}
                className={`px-2 py-0.5 rounded border ${brandFilter === b.v ? 'bg-blue-600 text-white border-blue-600' : 'bg-white border-gray-300 hover:bg-gray-50'}`}
              >{b.label}</button>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-4 text-sm">
          <div>
            <div className="flex justify-between mb-1">
              <span className="text-xs text-gray-600">최소 검색수(주평)</span>
              <span className="text-xs font-semibold text-blue-700">{minSearch.toLocaleString()} 이상</span>
            </div>
            <input
              type="range" min={0} max={20000} step={100}
              value={minSearch}
              onChange={e => setMinSearch(Number(e.target.value))}
              className="w-full accent-blue-600"
            />
            <div className="flex justify-between text-[10px] text-gray-400">
              <span>0</span><span>5,000</span><span>10,000</span><span>15,000</span><span>20,000</span>
            </div>
          </div>

          <div>
            <div className="flex justify-between mb-1">
              <span className="text-xs text-gray-600">최소 한국비율(%)</span>
              <span className="text-xs font-semibold text-blue-700">{minKrRatio}% 이상</span>
            </div>
            <input
              type="range" min={0} max={100} step={1}
              value={minKrRatio}
              onChange={e => setMinKrRatio(Number(e.target.value))}
              className="w-full accent-blue-600"
            />
            <div className="flex justify-between text-[10px] text-gray-400">
              <span>0%</span><span>25%</span><span>50%</span><span>75%</span><span>100%</span>
            </div>
          </div>

          <div>
            <div className="flex justify-between mb-1">
              <span className="text-xs text-gray-600">경쟁강도 최소</span>
              <span className="text-xs font-semibold text-blue-700">{compMin.toFixed(1)} 이상</span>
            </div>
            <input
              type="range" min={0} max={20} step={0.1}
              value={compMin}
              onChange={e => {
                const v = Number(e.target.value);
                setCompMin(v);
                if (v > compMax) setCompMax(v);
              }}
              className="w-full accent-blue-600"
            />
            <div className="flex justify-between text-[10px] text-gray-400">
              <span>0</span><span>5</span><span>10</span><span>15</span><span>20</span>
            </div>
          </div>

          <div>
            <div className="flex justify-between mb-1">
              <span className="text-xs text-gray-600">경쟁강도 최대</span>
              <span className="text-xs font-semibold text-blue-700">{compMax.toFixed(1)} 이하</span>
            </div>
            <input
              type="range" min={0} max={20} step={0.1}
              value={compMax}
              onChange={e => {
                const v = Number(e.target.value);
                setCompMax(v);
                if (v < compMin) setCompMin(v);
              }}
              className="w-full accent-blue-600"
            />
            <div className="flex justify-between text-[10px] text-gray-400">
              <span>0</span><span>5</span><span>10</span><span>15</span><span>20</span>
            </div>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow p-2">
        <div className="px-2 py-2 text-sm text-gray-500">
          추천 키워드 {enriched.length}개 (추천점수 내림차순 정렬됨)
        </div>
        <div style={{ height: 600, width: '100%' }}>
          <AgGridReact
            ref={gridRef}
            theme={myTheme}
            rowData={enriched}
            columnDefs={columnDefs}
            defaultColDef={defaultColDef}
            animateRows={true}
            pagination={true}
            paginationPageSize={2000}
            paginationPageSizeSelector={[100, 500, 1000, 2000, 5000]}
            autoSizeStrategy={{ type: 'fitCellContents' }}
            onColumnResized={handleColumnResized}
            onColumnMoved={handleColumnMoved}
            onSortChanged={handleSortChanged}
            onGridReady={handleGridReady}
          />
        </div>
      </div>

      {showCriteria && <CriteriaModal onClose={() => setShowCriteria(false)} />}
    </div>
  );
}

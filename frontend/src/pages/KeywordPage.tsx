import { useEffect, useState, useRef, useMemo, useCallback } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { AllCommunityModule, ModuleRegistry, themeQuartz } from 'ag-grid-community';

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
import { getKeywords, collectTrendKeywords, collectRelatedKeywords, deleteKeyword, listKeywordDates, deleteKeywordsByDate } from '../api/endpoints';
import type { Keyword } from '../types';
import CheckboxSetFilter from '../components/Grid/CheckboxSetFilter';
import TaskProgressPanel from '../components/common/TaskProgressPanel';

ModuleRegistry.registerModules([AllCommunityModule]);

const CATEGORIES = [
  { value: 1, label: '종합' },
  { value: 2, label: '여성패션' },
  { value: 3, label: '뷰티&화장품' },
  { value: 4, label: '남성&스포츠' },
  { value: 5, label: '디지털' },
  { value: 6, label: '홈&생활' },
  { value: 7, label: '식품' },
  { value: 8, label: '엔터테인먼트&e티켓' },
  { value: 9, label: '베이비&키즈' },
  { value: 10, label: '모바일' },
  { value: 11, label: '펫 푸드&용품' },
  { value: 12, label: '서플리먼트&다이어트' },
];

export default function KeywordPage() {
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [selectedCats, setSelectedCats] = useState<number[]>([1]);
  const [translate, setTranslate] = useState(true);
  const [fillTotal, setFillTotal] = useState(true);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [relatedInput, setRelatedInput] = useState('');
  const [dates, setDates] = useState<{ lookup_date: string; count: number }[]>([]);
  const [deleteDate, setDeleteDate] = useState('');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchDates = async () => {
    try {
      const res = await listKeywordDates();
      setDates(res.data);
    } catch { /* ignore */ }
  };

  const handleDeleteByDate = async () => {
    if (!deleteDate) { setMessage('삭제할 날짜를 선택하세요.'); return; }
    const target = dates.find(d => d.lookup_date === deleteDate);
    const cnt = target?.count ?? 0;
    if (!confirm(`${deleteDate} 날짜 키워드 ${cnt}개를 삭제할까요?`)) return;
    const res = await deleteKeywordsByDate(deleteDate);
    setMessage(`${res.data.lookup_date} 키워드 ${res.data.count}개 삭제됨`);
    setDeleteDate('');
    await fetchDates();
    await fetchKeywords();
  };

  const toggleCat = (v: number) => {
    setSelectedCats(prev => prev.includes(v) ? prev.filter(c => c !== v) : [...prev, v]);
  };
  const selectAll = () => setSelectedCats(CATEGORIES.map(c => c.value));
  const clearAll = () => setSelectedCats([]);

  const fetchKeywords = async () => {
    try {
      const res = await getKeywords();
      setKeywords(res.data);
    } catch { /* ignore */ }
  };

  useEffect(() => {
    fetchKeywords();
    fetchDates();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  // 수집 시작 후 5초마다 키워드 목록 자동 새로고침 (30초간)
  const startPolling = () => {
    if (pollRef.current) clearInterval(pollRef.current);
    let count = 0;
    pollRef.current = setInterval(() => {
      fetchKeywords();
      count++;
      if (count >= 12) { // 60초 후 중지
        if (pollRef.current) clearInterval(pollRef.current);
        setLoading(false);
        setMessage('수집이 완료되었을 수 있습니다. 목록을 확인하세요.');
      }
    }, 5000);
  };

  const handleCollectTrend = async () => {
    if (selectedCats.length === 0) { setMessage('카테고리를 1개 이상 선택하세요.'); return; }
    setLoading(true);
    setMessage(`크롬 창에서 ${selectedCats.length}개 카테고리 트렌드 키워드를 수집하는 중... (번역+상품수 포함, 시간 걸림)`);
    try {
      const res = await collectTrendKeywords(selectedCats, { translate, fill_total_products: fillTotal });
      if (res.data.error) {
        setMessage(`오류: ${res.data.error}`);
        setLoading(false);
        return;
      }
      setMessage(res.data.message || '수집 중...');
      startPolling();
    } catch (err: any) {
      setMessage(`오류: ${err.message}`);
      setLoading(false);
    }
  };

  const handleCollectRelated = async () => {
    if (!relatedInput.trim()) return;
    setLoading(true);
    setMessage('연관 키워드 수집 중...');
    try {
      const kws = relatedInput.split('\n').map(s => s.trim()).filter(Boolean);
      const res = await collectRelatedKeywords(kws);
      if (res.data.error) {
        setMessage(`오류: ${res.data.error}`);
        setLoading(false);
        return;
      }
      setMessage(res.data.message || '수집 중...');
      startPolling();
    } catch (err: any) {
      setMessage(`오류: ${err.message}`);
      setLoading(false);
    }
  };

  const gridRef = useRef<AgGridReact>(null);
  const resizedColsRef = useRef<Set<string>>(new Set());
  const COL_STATE_KEY = 'keywordPage.colState';

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
    if (!api) return false;
    try {
      const raw = localStorage.getItem(COL_STATE_KEY);
      if (!raw) return false;
      const state = JSON.parse(raw);
      api.applyColumnState?.({ state, applyOrder: true });
      // 사용자 커스텀 너비가 있는 컬럼은 autoSize 대상에서 제외
      state.forEach((c: any) => { if (c.colId && c.width) resizedColsRef.current.add(c.colId); });
      return true;
    } catch { return false; }
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

  // 빠른 필터: 카테고리/분류 버튼
  const [activeCat, setActiveCat] = useState<string | null>(null);
  const [activeClass, setActiveClass] = useState<string | null>(null);

  const uniqueCats = useMemo(() => {
    const s = new Set<string>();
    keywords.forEach(k => k.category && s.add(k.category));
    return Array.from(s).sort();
  }, [keywords]);
  const uniqueClasses = useMemo(() => {
    const s = new Set<string>();
    keywords.forEach(k => k.classification && s.add(k.classification));
    return Array.from(s).sort();
  }, [keywords]);

  const applyQuickFilter = async (field: string, value: string | null) => {
    const api = gridRef.current?.api as any;
    if (!api) return;
    if (value === null) {
      await api.setColumnFilterModel?.(field, null);
    } else {
      await api.setColumnFilterModel?.(field, { values: [value] });
    }
    api.onFilterChanged?.();
  };

  const toggleQuickCat = (v: string) => {
    const next = activeCat === v ? null : v;
    setActiveCat(next);
    applyQuickFilter('category', next);
  };
  const toggleQuickClass = (v: string) => {
    const next = activeClass === v ? null : v;
    setActiveClass(next);
    applyQuickFilter('classification', next);
  };

  // 데이터가 바뀌면 사용자가 조정 안 한 컬럼만 자동 크기 조정
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
  const numFmt = (p: any) => p.value == null ? '' : Number(p.value).toLocaleString();
  const pctFmt = (p: any) => p.value == null ? '' : `${Number(p.value).toFixed(1)}%`;
  const scoreFmt = (p: any) => p.value == null ? '' : Number(p.value).toFixed(2);

  const krRatioGetter = (p: any) => {
    const total = p.data?.total_products || 0;
    const kr = p.data?.products_kr || 0;
    return total > 0 ? (kr / total) * 100 : 0;
  };

  const recommendScoreGetter = (p: any) => {
    const sw = p.data?.search_volume_weekly || 0;
    const total = p.data?.total_products || 0;
    const kr = p.data?.products_kr || 0;
    const comp = p.data?.competition_intensity || 0;
    if (sw <= 0 || total <= 0) return 0;
    const ratio = kr / total;
    const compFactor = Math.max(comp, 0.1);
    return (Math.log10(sw + 1) * ratio) / compFactor;
  };

  const sortByRecommendation = useCallback(() => {
    gridRef.current?.api?.applyColumnState({
      state: [{ colId: 'recommend_score', sort: 'desc' }],
      defaultState: { sort: null },
    });
  }, []);

  const columnDefs: ColDef[] = useMemo(() => [
    { field: 'lookup_date', headerName: '조회날짜', width: 110 },
    { field: 'rank', headerName: '순위', width: 70, type: 'numericColumn' },
    {
      field: 'keyword_jp', headerName: '키워드(일본어)', width: 180,
      cellRenderer: (p: any) => p.value
        ? <a href={`https://www.qoo10.jp/s/?keyword=${p.value}`} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">{p.value}</a>
        : '',
    },
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
    {
      colId: 'kr_ratio', headerName: '한국비율(%)', width: 110, type: 'numericColumn',
      valueGetter: krRatioGetter, valueFormatter: pctFmt,
      cellStyle: (p: any) => p.value >= 30 ? { backgroundColor: '#fef3c7' } : null,
    },
    { field: 'category', headerName: '카테고리', width: 130 },
    { field: 'classification', headerName: '분류', width: 90 },
    { field: 'search_volume_weekly', headerName: '검색수(주평)', width: 120, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'search_volume_daily', headerName: '검색수(전날)', width: 120, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'competition_intensity', headerName: '경쟁강도', width: 100, type: 'numericColumn' },
    { field: 'total_products', headerName: '전체상품수', width: 120, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'products_jp', headerName: '일본', width: 100, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'products_kr', headerName: '한국', width: 100, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'products_cn', headerName: '중국', width: 100, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'products_other', headerName: '그외', width: 100, type: 'numericColumn', valueFormatter: numFmt },
    {
      colId: 'recommend_score', headerName: '역직구 추천점수', width: 130, type: 'numericColumn',
      valueGetter: recommendScoreGetter, valueFormatter: scoreFmt,
      cellStyle: { fontWeight: 600, backgroundColor: '#ecfeff' },
      headerTooltip: '검색량 × 한국비율 ÷ 경쟁강도. 클수록 역직구 유망',
    },
    {
      headerName: '', width: 70, sortable: false, filter: false, resizable: false, suppressMovable: true,
      cellRenderer: (p: any) => (
        <button onClick={() => handleDelete(p.data.id)} className="text-red-500 hover:text-red-700 text-xs">삭제</button>
      ),
    },
  ], []);

  const defaultColDef: ColDef = useMemo(() => ({
    sortable: true,
    resizable: true,
    filter: CheckboxSetFilter,
    suppressMovable: false,
    floatingFilter: false,
    minWidth: 60,
  }), []);

  const handleDelete = async (id: number) => {
    await deleteKeyword(id);
    setKeywords(prev => prev.filter(k => k.id !== id));
  };

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">키워드 추출</h2>

      <TaskProgressPanel />

      {/* 상태 메시지 */}
      {message && (
        <div className={`rounded-lg p-4 mb-4 text-sm ${loading ? 'bg-blue-50 text-blue-700' : 'bg-gray-50 text-gray-600'}`}>
          {loading && <span className="inline-block animate-spin mr-2">&#9696;</span>}
          {message}
          {!loading && (
            <button onClick={() => setMessage('')} className="ml-3 text-gray-400 hover:text-gray-600">닫기</button>
          )}
        </div>
      )}

      {/* 트렌드 키워드 수집 */}
      <div className="bg-white rounded-lg shadow p-5 mb-4">
        <h3 className="font-semibold mb-3">트렌드 키워드 가져오기</h3>

        <div className="mb-3">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-sm text-gray-600">카테고리 ({selectedCats.length}개 선택)</span>
            <button onClick={selectAll} className="text-xs px-2 py-1 bg-gray-100 hover:bg-gray-200 rounded">전체</button>
            <button onClick={clearAll} className="text-xs px-2 py-1 bg-gray-100 hover:bg-gray-200 rounded">해제</button>
          </div>
          <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
            {CATEGORIES.map(c => (
              <label key={c.value} className={`flex items-center gap-1 text-sm px-2 py-1 border rounded cursor-pointer ${selectedCats.includes(c.value) ? 'bg-blue-50 border-blue-400' : 'bg-white'}`}>
                <input type="checkbox" checked={selectedCats.includes(c.value)} onChange={() => toggleCat(c.value)} />
                <span>{c.label}</span>
              </label>
            ))}
          </div>
        </div>

        <div className="flex gap-4 items-center mb-3 text-sm">
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={translate} onChange={e => setTranslate(e.target.checked)} />
            한국어 번역 (Google)
          </label>
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={fillTotal} onChange={e => setFillTotal(e.target.checked)} />
            전체 상품수 함께 수집 (느림)
          </label>
        </div>

        <div className="flex gap-3">
          <button
            onClick={handleCollectTrend}
            disabled={loading}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? '수집 중...' : '트렌드 키워드 수집'}
          </button>
          <button
            onClick={fetchKeywords}
            className="px-4 py-2 bg-gray-200 text-gray-700 text-sm rounded hover:bg-gray-300"
          >
            새로고침
          </button>
        </div>
      </div>

      {/* 연관 키워드 수집 */}
      <div className="bg-white rounded-lg shadow p-5 mb-4">
        <h3 className="font-semibold mb-3">연관 키워드 가져오기</h3>
        <div className="flex gap-3 items-end">
          <div className="flex-1">
            <label className="block text-sm text-gray-600 mb-1">키워드 (줄바꿈으로 구분)</label>
            <textarea
              value={relatedInput}
              onChange={e => setRelatedInput(e.target.value)}
              rows={3}
              className="border rounded px-3 py-2 text-sm w-full"
              placeholder="키워드를 입력하세요"
            />
          </div>
          <button
            onClick={handleCollectRelated}
            disabled={loading}
            className="px-4 py-2 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:opacity-50"
          >
            연관 키워드 수집
          </button>
        </div>
      </div>

      {/* 일자별 삭제 */}
      <div className="bg-white rounded-lg shadow p-5 mb-4">
        <h3 className="font-semibold mb-3">일자별 삭제</h3>
        <div className="flex gap-3 items-center">
          <select
            value={deleteDate}
            onChange={e => setDeleteDate(e.target.value)}
            className="border rounded px-3 py-2 text-sm min-w-[240px]"
          >
            <option value="">날짜 선택</option>
            {dates.map(d => (
              <option key={d.lookup_date} value={d.lookup_date}>
                {d.lookup_date} ({d.count.toLocaleString()}개)
              </option>
            ))}
          </select>
          <button
            onClick={handleDeleteByDate}
            disabled={!deleteDate}
            className="px-4 py-2 bg-red-600 text-white text-sm rounded hover:bg-red-700 disabled:opacity-50"
          >
            선택한 날짜 키워드 삭제
          </button>
          <button
            onClick={fetchDates}
            className="px-4 py-2 bg-gray-200 text-gray-700 text-sm rounded hover:bg-gray-300"
          >
            날짜 목록 새로고침
          </button>
        </div>
      </div>

      {/* 키워드 테이블 (AG Grid) */}
      <div className="bg-white rounded-lg shadow p-2">
        <div className="px-2 pt-2 pb-2 border-b border-gray-100 space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-semibold text-gray-600 w-16">카테고리</span>
            <button
              onClick={() => { setActiveCat(null); applyQuickFilter('category', null); }}
              className={`px-2 py-0.5 text-xs rounded border ${activeCat === null ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'}`}
            >전체</button>
            {uniqueCats.map(c => (
              <button
                key={c}
                onClick={() => toggleQuickCat(c)}
                className={`px-2 py-0.5 text-xs rounded border ${activeCat === c ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'}`}
              >{c}</button>
            ))}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-semibold text-gray-600 w-16">분류</span>
            <button
              onClick={() => { setActiveClass(null); applyQuickFilter('classification', null); }}
              className={`px-2 py-0.5 text-xs rounded border ${activeClass === null ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'}`}
            >전체</button>
            {uniqueClasses.map(c => (
              <button
                key={c}
                onClick={() => toggleQuickClass(c)}
                className={`px-2 py-0.5 text-xs rounded border ${activeClass === c ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'}`}
              >{c}</button>
            ))}
          </div>
        </div>
        <div className="px-2 py-2 text-sm text-gray-500 flex items-center gap-3 flex-wrap">
          <span>총 {keywords.length}개 키워드</span>
          <button
            onClick={sortByRecommendation}
            className="px-3 py-1 bg-amber-500 text-white text-xs rounded hover:bg-amber-600"
          >
            ⭐ 역직구 추천 정렬
          </button>
          <span className="text-xs text-gray-400">
            컬럼 헤더 우측 ≡ 메뉴로 필터, 헤더 클릭으로 정렬, 드래그로 순서/크기 변경
          </span>
        </div>
        <div style={{ height: 600, width: '100%' }}>
          <AgGridReact
            ref={gridRef}
            theme={myTheme}
            rowData={keywords}
            columnDefs={columnDefs}
            defaultColDef={defaultColDef}
            rowSelection={{ mode: 'multiRow' }}
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
    </div>
  );
}

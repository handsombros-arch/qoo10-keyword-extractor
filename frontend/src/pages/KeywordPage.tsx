import { useEffect, useState, useRef, useMemo } from 'react';
import { Link } from 'react-router-dom';
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
import { addInterestKeywords, getInterestKeywords, type InterestKeyword } from '../store/interestKeywords';
import { mergeKeywordsToSheet } from '../store/keywordToSheet';

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

// ── "좋은 키워드" 신호 ──
// 존: 검색수 50 / 상품수 200 기준 (황금존 = 수요 있고 공급 적음)
function zoneOf(k: any): string {
  const sv = Number(k?.search_volume_weekly) || 0;
  const tp = Number(k?.total_products) || 0;
  if (sv >= 50 && tp <= 200) return '황금존';
  if (sv >= 50) return '레드오션';
  if (tp <= 200) return '데드존';
  return '포화';
}
// 구좌 열림: 낙찰수 ≤ 3 (들어가면 바로 상위 노출). null(미수집)은 제외.
function slotOpen(k: any): boolean {
  return k?.bid_count != null && Number(k.bid_count) <= 3;
}
const ZONE_COLOR: Record<string, string> = {
  '황금존': '#fde68a', '레드오션': '#fecaca', '데드존': '#e5e7eb', '포화': '#ddd6fe',
};

// 빈값(null/undefined/'')은 정렬 방향과 무관하게 항상 맨 아래로.
// ag-grid 기본은 오름차순에서 null을 맨 위로 올려, 경쟁강도/낙찰가처럼 빈값 많은 컬럼은
// "오름차순이 안 먹는 것처럼"(빈 행이 화면을 덮음) 보임. → 빈값을 항상 바닥으로.
function sortNullsLast(a: any, b: any, _na: any, _nb: any, isDescending: boolean): number {
  const ea = a === null || a === undefined || a === '';
  const eb = b === null || b === undefined || b === '';
  if (ea && eb) return 0;
  if (ea) return isDescending ? -1 : 1;
  if (eb) return isDescending ? 1 : -1;
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  return String(a).localeCompare(String(b), 'ja');
}

export default function KeywordPage() {
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [selectedCats, setSelectedCats] = useState<number[]>([1]);
  const [translate, setTranslate] = useState(true);
  const [fillTotal, setFillTotal] = useState(true);
  const [collectBids, setCollectBids] = useState(true);  // 낙찰가도 같이 수집 (기본 ON, 6/4)
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [relatedInput, setRelatedInput] = useState('');
  const [dates, setDates] = useState<{ lookup_date: string; count: number }[]>([]);
  const [deleteDate, setDeleteDate] = useState('');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const didInitDate = useRef(false);

  const fetchDates = async () => {
    try {
      const res = await listKeywordDates();
      setDates(res.data);
      // 기본 뷰 = 최신 날짜 1개 (전 날짜 8900행 무차별 로드 방지 → 정렬 정상, 원본=시트 한 장 기준)
      if (!didInitDate.current && res.data.length) {
        const latest = res.data.map(d => d.lookup_date).filter(Boolean).sort().slice(-1)[0];
        if (latest) { setSingleDate(latest); setDateMode('single'); }
        didInitDate.current = true;
      }
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
      const res = await collectTrendKeywords(selectedCats, { translate, fill_total_products: fillTotal, collect_bids: collectBids });
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
  const COL_STATE_KEY = 'keywordPage.colState.v2'; // v2: 원본 listKeyword 컬럼 순서 적용 (옛 저장상태 무시)

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

  // 빠른 필터: 카테고리/분류/날짜 (state 기반 — rowData를 직접 필터링해 1-click 즉시 반영)
  const [activeCat, setActiveCat] = useState<string | null>(null);
  const [activeClass, setActiveClass] = useState<string | null>(null);
  const [activeZone, setActiveZone] = useState<string | null>(null);
  const [slotOnly, setSlotOnly] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);  // 수집/삭제 도구 접기 (시트 풀화면용)
  const [fullscreen, setFullscreen] = useState(false); // 시트 전체화면 (사이드바까지 덮음, ESC 닫기)
  type DateMode = 'all' | 'single' | 'range';
  const [dateMode, setDateMode] = useState<DateMode>('all');
  const [singleDate, setSingleDate] = useState('');
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');

  // 날짜 이동 헬퍼 — 데이터가 실제 있는 수집일만 오름차순으로 (◀▶ 로 하루씩 이동)
  const sortedDates = useMemo(
    () => dates.map(d => d.lookup_date).filter(Boolean).sort(),
    [dates],
  );
  const dateCount = (d: string) => dates.find(x => x.lookup_date === d)?.count ?? 0;
  const dateIdx = sortedDates.indexOf(singleDate);
  const goPrevDay = () => { if (dateIdx > 0) { setDateMode('single'); setSingleDate(sortedDates[dateIdx - 1]); } };
  const goNextDay = () => { if (dateIdx >= 0 && dateIdx < sortedDates.length - 1) { setDateMode('single'); setSingleDate(sortedDates[dateIdx + 1]); } };
  const goLatestDay = () => { if (sortedDates.length) { setDateMode('single'); setSingleDate(sortedDates[sortedDates.length - 1]); } };

  // 전체화면 중 ESC 로 닫기
  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setFullscreen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [fullscreen]);

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

  const toggleQuickCat = (v: string) => setActiveCat(prev => prev === v ? null : v);
  const toggleQuickClass = (v: string) => setActiveClass(prev => prev === v ? null : v);

  // 표시용 필터링된 rowData (state 기반)
  const filteredKeywords = useMemo(() => {
    return keywords.filter(k => {
      if (activeCat && k.category !== activeCat) return false;
      if (activeClass && k.classification !== activeClass) return false;
      if (activeZone && zoneOf(k) !== activeZone) return false;
      if (slotOnly && !slotOpen(k)) return false;
      const d = k.lookup_date;
      if (dateMode === 'single' && singleDate) {
        if (d !== singleDate) return false;
      } else if (dateMode === 'range') {
        if (fromDate && (!d || d < fromDate)) return false;
        if (toDate && (!d || d > toDate)) return false;
      }
      return true;
    });
  }, [keywords, activeCat, activeClass, activeZone, slotOnly, dateMode, singleDate, fromDate, toDate]);

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
  }, [filteredKeywords]);
  const numFmt = (p: any) => p.value == null ? '' : Number(p.value).toLocaleString();
  const pctFmt = (p: any) => p.value == null ? '' : `${Number(p.value).toFixed(1)}%`;

  const krRatioGetter = (p: any) => {
    const total = p.data?.total_products || 0;
    const kr = p.data?.products_kr || 0;
    return total > 0 ? (kr / total) * 100 : 0;
  };

  // 관심 키워드 북마크
  const [interestCount, setInterestCount] = useState<number>(() => getInterestKeywords().length);
  const addSelectedToInterest = () => {
    const api = gridRef.current?.api as any;
    if (!api) return;
    const selected: any[] = api.getSelectedRows?.() || [];
    if (selected.length === 0) {
      alert('키워드 행을 체크해주세요.');
      return;
    }
    const items: InterestKeyword[] = selected.map((r: any) => ({
      keyword_jp: r.keyword_jp,
      keyword_kr: r.keyword_kr,
      category: r.category,
      search_volume_weekly: r.search_volume_weekly,
      search_volume_daily: r.search_volume_daily,
      competition_intensity: r.competition_intensity,
      total_products: r.total_products,
      products_jp: r.products_jp,
      products_kr: r.products_kr,
      products_cn: r.products_cn,
      products_other: r.products_other,
    }));
    const merged = addInterestKeywords(items);
    setInterestCount(merged.length);
    alert(`${items.length}개 담았습니다. 관심 키워드 풀 총 ${merged.length}개.`);
  };

  // VV-2 — 선택 키워드를 시트로 직접 보내기 (관심 풀 거치지 않음)
  const sendSelectedToSheet = async () => {
    const api = gridRef.current?.api as any;
    if (!api) return;
    const selected: any[] = api.getSelectedRows?.() || [];
    if (selected.length === 0) {
      alert('키워드 행을 체크해주세요.');
      return;
    }
    const today = new Date().toISOString().slice(0, 10);
    const result = await mergeKeywordsToSheet(
      selected.map(r => ({
        keyword_jp: r.keyword_jp,
        keyword_kr: r.keyword_kr,
        // R-7: LLM 분류 결과(category_inferred) 우선 — 시트 카테고리 컬럼이 6분류
        category: r.category_inferred || r.category,
        search_volume_weekly: r.search_volume_weekly,
      })),
      `keyword:${today}`,
    );
    alert(
      `✓ ${result.added}건 시트에 추가 (${selected.length} 중)\n` +
      (result.deduped > 0 ? `- 중복 ${result.deduped}건\n` : '') +
      `\n/recommend-products 에서 확인 — URL/원가 직접 입력하세요.`
    );
  };

  const columnDefs: ColDef[] = useMemo(() => [
    // (선택 체크박스 컬럼은 rowSelection 신 API가 자동 생성 — selectionColumnDef로 제어)
    // ── 원본 listKeyword 컬럼 순서 (좌→우, 큐텐 키워드 추출기 v1.4.3 기준) ──
    { field: 'lookup_date', headerName: '조회날짜', width: 110 },
    { field: 'category', headerName: '카테고리', width: 130 },
    { field: 'classification', headerName: '분류', width: 90 },
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
    { field: 'competition_intensity', headerName: '경쟁강도', width: 100, type: 'numericColumn' },
    { field: 'search_volume_weekly', headerName: '검색수(주평)', width: 120, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'search_volume_daily', headerName: '검색수(전날)', width: 120, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'total_products', headerName: '전체상품수', width: 120, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'products_jp', headerName: '일본', width: 100, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'products_kr', headerName: '한국', width: 100, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'products_cn', headerName: '중국', width: 100, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'products_other', headerName: '그외', width: 100, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'bid_count', headerName: '낙찰수', width: 80, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'bid_price_10', headerName: '낙찰시가', width: 100, type: 'numericColumn', valueFormatter: numFmt, headerTooltip: '전체 낙찰 중 최저가 (가장 낮은 순위의 낙찰가)' },
    { field: 'bid_price_9', headerName: '9위', width: 80, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'bid_price_8', headerName: '8위', width: 80, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'bid_price_7', headerName: '7위', width: 80, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'bid_price_6', headerName: '6위', width: 80, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'bid_price_5', headerName: '5위', width: 80, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'bid_price_4', headerName: '4위', width: 80, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'bid_price_3', headerName: '3위', width: 80, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'bid_price_2', headerName: '2위', width: 80, type: 'numericColumn', valueFormatter: numFmt },
    { field: 'bid_price_1', headerName: '낙찰종가', width: 100, type: 'numericColumn', valueFormatter: numFmt, headerTooltip: '1위 낙찰가 (최고가)' },
    { field: 'volume_change_flag', headerName: '전날대비증감', width: 110 },
    // ── 엘비텐 분석 보조 (원본에 없음 · 헤더 드래그로 원하는 위치로 이동 가능) ──
    {
      colId: 'zone', headerName: '존', width: 90,
      valueGetter: (p: any) => zoneOf(p.data),
      cellStyle: (p: any) => ({ backgroundColor: ZONE_COLOR[p.value] || '', fontWeight: p.value === '황금존' ? 700 : 400 }),
      headerTooltip: '검색수 50 / 상품수 200 기준 (황금존=수요O·공급적음)',
    },
    {
      colId: 'slot', headerName: '구좌', width: 72,
      valueGetter: (p: any) => slotOpen(p.data) ? '열림' : '',
      cellStyle: (p: any) => p.value ? { backgroundColor: '#bbf7d0', fontWeight: 700 } : undefined,
      headerTooltip: '낙찰수 ≤ 3 — 들어가면 바로 상위 노출 가능',
    },
    {
      colId: 'kr_ratio', headerName: '한국비율(%)', width: 110, type: 'numericColumn',
      valueGetter: krRatioGetter, valueFormatter: pctFmt,
      cellStyle: (p: any) => p.value >= 30 ? { backgroundColor: '#fef3c7' } : null,
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
    comparator: sortNullsLast,  // 빈값 항상 바닥 → 오름차순도 정상 동작
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

      {/* 수집·삭제 도구 토글 (접으면 시트가 화면을 꽉 채움) */}
      <button
        onClick={() => setToolsOpen(o => !o)}
        className="mb-3 text-sm px-3 py-1.5 rounded border bg-white text-gray-600 hover:bg-gray-50"
      >
        {toolsOpen ? '▾ 키워드 수집·삭제 도구 접기' : '▸ 키워드 수집·삭제 도구 (트렌드 가져오기 · 일자별 삭제)'}
      </button>

      {toolsOpen && (<>
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
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={collectBids} onChange={e => setCollectBids(e.target.checked)} />
            광고 경매 낙찰가 함께 수집 (선택, 매우 느림)
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
      </>)}

      {/* 키워드 테이블 (AG Grid) — fullscreen 시 사이드바까지 덮는 고정 오버레이 + flex(헤더 고정, 그리드만 스크롤) */}
      <div className={fullscreen ? 'fixed inset-0 z-50 bg-white flex flex-col p-2 overflow-hidden' : 'bg-white rounded-lg shadow p-2'}>
        <div className={`px-2 pt-2 pb-2 border-b border-gray-100 space-y-2 ${fullscreen ? 'shrink-0' : ''}`}>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-semibold text-gray-600 w-16">날짜</span>

            {/* 하루씩 선택 (기본 · 가장 최신일) */}
            <div className="flex items-center gap-1">
              <button
                onClick={goPrevDay}
                disabled={dateMode !== 'single' || dateIdx <= 0}
                title="이전 수집일"
                className="px-2 py-1 text-sm rounded border bg-white text-gray-700 disabled:opacity-30 hover:bg-gray-50"
              >◀</button>
              <input
                type="date"
                value={dateMode === 'single' ? singleDate : ''}
                min={sortedDates[0]}
                max={sortedDates[sortedDates.length - 1]}
                onChange={e => { setDateMode('single'); setSingleDate(e.target.value); }}
                className={`border rounded px-2 py-1 text-sm ${dateMode === 'single' ? 'border-blue-500 ring-1 ring-blue-200 text-gray-900' : 'border-gray-300 text-gray-400'}`}
              />
              <button
                onClick={goNextDay}
                disabled={dateMode !== 'single' || dateIdx < 0 || dateIdx >= sortedDates.length - 1}
                title="다음 수집일"
                className="px-2 py-1 text-sm rounded border bg-white text-gray-700 disabled:opacity-30 hover:bg-gray-50"
              >▶</button>
              <button
                onClick={goLatestDay}
                title="가장 최신 수집일로"
                className="px-2 py-1 text-xs rounded border bg-white text-gray-600 hover:bg-gray-50"
              >최신</button>
              {dateMode === 'single' && singleDate && (
                <span className="text-xs text-gray-400 ml-1">{dateCount(singleDate).toLocaleString()}개</span>
              )}
            </div>

            <span className="mx-1 text-gray-300">|</span>

            <button
              onClick={() => { setDateMode('all'); setFromDate(''); setToDate(''); }}
              className={`px-2 py-0.5 text-xs rounded border ${dateMode === 'all' ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'}`}
            >전체</button>
            <button
              onClick={() => setDateMode('range')}
              className={`px-2 py-0.5 text-xs rounded border ${dateMode === 'range' ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'}`}
            >기간</button>
            {dateMode === 'range' && (
              <>
                <input
                  type="date"
                  value={fromDate}
                  min={sortedDates[0]}
                  max={sortedDates[sortedDates.length - 1]}
                  onChange={e => setFromDate(e.target.value)}
                  className="border rounded px-2 py-0.5 text-xs"
                />
                <span className="text-xs text-gray-400">~</span>
                <input
                  type="date"
                  value={toDate}
                  min={sortedDates[0]}
                  max={sortedDates[sortedDates.length - 1]}
                  onChange={e => setToDate(e.target.value)}
                  className="border rounded px-2 py-0.5 text-xs"
                />
              </>
            )}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-semibold text-gray-600 w-16">카테고리</span>
            <button
              onClick={() => setActiveCat(null)}
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
              onClick={() => setActiveClass(null)}
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
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-semibold text-gray-600 w-16">좋은키워드</span>
            <button
              onClick={() => { setActiveZone(null); setSlotOnly(false); }}
              className={`px-2 py-0.5 text-xs rounded border ${activeZone === null && !slotOnly ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'}`}
            >전체</button>
            {['황금존', '레드오션', '데드존', '포화'].map(z => (
              <button
                key={z}
                onClick={() => setActiveZone(prev => prev === z ? null : z)}
                className={`px-2 py-0.5 text-xs rounded border ${activeZone === z ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'}`}
              >{z}</button>
            ))}
            <button
              onClick={() => setSlotOnly(v => !v)}
              className={`px-2 py-0.5 text-xs rounded border ${slotOnly ? 'bg-green-600 text-white border-green-600' : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'}`}
            >구좌(낙찰≤3)</button>
            <button
              onClick={() => { setActiveZone('황금존'); setSlotOnly(true); }}
              className="px-2 py-0.5 text-xs rounded bg-amber-500 text-white hover:bg-amber-600"
              title="황금존 + 구좌 열림(낙찰≤3)"
            >⭐ 좋은 키워드</button>
          </div>
        </div>
        <div className={`px-2 py-2 text-sm text-gray-500 flex items-center gap-3 flex-wrap ${fullscreen ? 'shrink-0' : ''}`}>
          <span>표시 {filteredKeywords.length.toLocaleString()} / 총 {keywords.length.toLocaleString()}개</span>
          <button
            onClick={sendSelectedToSheet}
            className="px-3 py-1 bg-blue-600 text-white text-xs rounded hover:bg-blue-700"
            title="선택 키워드를 상품 시트에 직접 추가 (사장님이 한국 셀러 검색 → URL/원가 직접 입력)"
          >
            📋 선택 키워드를 시트로
          </button>
          <button
            onClick={addSelectedToInterest}
            className="px-3 py-1 bg-emerald-600 text-white text-xs rounded hover:bg-emerald-700"
            title="선택한(체크된) 행을 관심 키워드로 북마크 (상품 시트에서 활용)"
          >
            🔖 관심 키워드 (북마크) ({interestCount})
          </button>
          <Link
            to="/recommend-products"
            className="px-3 py-1 bg-indigo-600 text-white text-xs rounded hover:bg-indigo-700"
          >
            📋 상품 시트
          </Link>
          <button
            onClick={() => setFullscreen(f => !f)}
            className="px-3 py-1 bg-gray-800 text-white text-xs rounded hover:bg-black ml-auto"
            title="시트만 전체화면 — 사이드바 숨김, 세로 스크롤 1개. ESC 로 닫기"
          >
            {fullscreen ? '✕ 전체화면 닫기 (ESC)' : '⛶ 전체화면'}
          </button>
          <span className="text-xs text-gray-400">
            행 왼쪽 체크박스로 선택 · 컬럼 헤더 우측 ≡ 메뉴로 필터
          </span>
        </div>
        <div
          className={fullscreen ? 'flex-1 min-h-0' : ''}
          style={fullscreen
            ? { width: '100%' }
            : { height: toolsOpen ? 'calc(100vh - 200px)' : 'calc(100vh - 150px)', minHeight: 520, width: '100%' }}
        >
          <AgGridReact
            ref={gridRef}
            theme={myTheme}
            rowData={filteredKeywords}
            columnDefs={columnDefs}
            defaultColDef={defaultColDef}
            rowSelection={{ mode: 'multiRow', selectAll: 'filtered' }}
            selectionColumnDef={{ pinned: 'left', width: 50, suppressMovable: true, lockPosition: true }}
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

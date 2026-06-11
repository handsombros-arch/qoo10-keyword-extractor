import { useEffect, useState, useRef, useMemo } from 'react';
import { AgGridReact } from 'ag-grid-react';
import DataDatePicker from '../components/DataDatePicker';
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
import { addInterestKeywords, getInterestKeywords, removeInterestEntry, clearInterestKeywords, type InterestKeyword } from '../store/interestKeywords';
import { fetchCloud } from '../store/cloudSync';
import { seedRowsFromKeywords } from '../store/marginSheet';
import { useNavigate } from 'react-router-dom';

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

// ── "좋은 키워드" 5대 기준 (각 독립 토글, 선택한 것들의 AND 조합) ──
// 경쟁강도 = 전체상품수 ÷ 검색수(주평). 저장값이 비었거나 0(검색수 누락/반올림)이면 재계산.
function compVal(k: any): number | null {
  const ci = k?.competition_intensity;
  if (ci != null && Number(ci) > 0) return Number(ci);
  const sv = Number(k?.search_volume_weekly) || 0;
  const tp = k?.total_products;
  if (sv > 0 && tp != null) return Number(tp) / sv;
  return null;
}
function krRatioOf(k: any): number | null {
  const tp = Number(k?.total_products) || 0;
  const kr = Number(k?.products_kr) || 0;
  return tp > 0 ? kr / tp : null;
}
// 구좌 열림: 낙찰수 ≤ 3 (들어가면 바로 상위 노출). null(미수집)은 컬럼 표시상 제외.
function slotOpen(k: any): boolean {
  return k?.bid_count != null && Number(k.bid_count) <= 3;
}

type GoodKey = 'comp' | 'sv' | 'tp' | 'krr' | 'slot';
const GOOD_CRITERIA: { key: GoodKey; label: string; desc: string; test: (k: any) => boolean }[] = [
  { key: 'comp', label: '경쟁강도', desc: '경쟁강도 ≤ 2.0  (전체상품수 ÷ 검색수)', test: (k) => { const c = compVal(k); return c != null && c <= 2.0; } },
  { key: 'sv',   label: '검색수',   desc: '검색수(주평) ≥ 50', test: (k) => (Number(k?.search_volume_weekly) || 0) >= 50 },
  { key: 'tp',   label: '상품수',   desc: '전체상품수 ≤ 500', test: (k) => { const t = Number(k?.total_products) || 0; return t > 0 && t <= 500; } },
  { key: 'krr',  label: '한국비율', desc: '한국상품수 ÷ 전체상품수 ≥ 10%', test: (k) => { const r = krRatioOf(k); return r != null && r >= 0.10; } },
  { key: 'slot', label: '구좌',     desc: '낙찰 빈 구좌 (낙찰수 ≤ 3, 데이터 없으면 통과)', test: (k) => k?.bid_count == null || Number(k.bid_count) <= 3 },
];

// 간편 보기에서 숨기는 컬럼 — 국가별 상품수 / 모든 낙찰 컬럼 / 전날대비 / 일본어 키워드
const SIMPLE_VIEW_HIDE = [
  'keyword_jp',
  'products_jp', 'products_kr', 'products_cn', 'products_other',
  'bid_count', 'bid_price_10', 'bid_price_9', 'bid_price_8', 'bid_price_7',
  'bid_price_6', 'bid_price_5', 'bid_price_4', 'bid_price_3', 'bid_price_2', 'bid_price_1',
  'volume_change_flag',
];
// 관심만 보기 ON 시 기본 숨김 — 분류/순위 (스냅샷 무의미)
const INTEREST_HIDE = ['classification', 'rank'];

// 색상 강약(컬러 스케일) 적용 가능한 숫자 컬럼
const COLOR_COL_LIST = [
  'competition_intensity', 'search_volume_weekly', 'search_volume_daily', 'total_products',
  'products_jp', 'products_kr', 'products_cn', 'products_other',
  'bid_count', 'bid_price_10', 'bid_price_9', 'bid_price_8', 'bid_price_7', 'bid_price_6',
  'bid_price_5', 'bid_price_4', 'bid_price_3', 'bid_price_2', 'bid_price_1', 'kr_ratio',
];
const COLOR_COLS = new Set(COLOR_COL_LIST);
// 컬럼마다 고유 색상(hue) — 황금각(137.5°)으로 분산해 인접 컬럼도 서로 다른 색
const COLOR_HUE: Record<string, number> = {};
COLOR_COL_LIST.forEach((c, i) => { COLOR_HUE[c] = Math.round((i * 137.508) % 360); });


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
  const navigate = useNavigate();
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [selectedCats, setSelectedCats] = useState<number[]>([1]);
  const [translate, setTranslate] = useState(true);
  const [fillTotal, setFillTotal] = useState(true);
  const [collectBids, setCollectBids] = useState(true);  // 낙찰가도 같이 수집 (기본 ON, 6/4)
  const [loading, setLoading] = useState(false);
  const [gridLoading, setGridLoading] = useState(true);  // 그리드 데이터 로딩 오버레이 (첫 로드/새로고침)
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

  // showLoading: 첫 로드·새로고침처럼 사용자가 의도한 로드만 오버레이 표시 (폴링은 조용히)
  const fetchKeywords = async (showLoading = false) => {
    if (showLoading) setGridLoading(true);
    try {
      const res = await getKeywords();
      setKeywords(res.data);
    } catch { /* ignore */ }
    finally { if (showLoading) setGridLoading(false); }
  };

  useEffect(() => {
    fetchKeywords(true);
    fetchDates();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  // 관심 키워드 클라우드 pull (다른 PC 북마크 동기화 — 옛 상품시트 페이지가 하던 역할)
  useEffect(() => {
    (async () => {
      const { data } = await fetchCloud<any[]>('interest_keywords');
      if (data && Array.isArray(data)) {
        localStorage.setItem('interestKeywords.v1', JSON.stringify(data));
        setInterestTick(t => t + 1);
      }
    })();
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
      // 너비·순서·표시여부만 복원하고 정렬(sort)은 제외 — 옛 정렬이 재적용돼
      // "오름차순이 안 먹는 것처럼" 보이던 혼란 방지. 정렬은 항상 깨끗하게 시작.
      const state = JSON.parse(raw).map((c: any) => ({ ...c, sort: null, sortIndex: null }));
      api.applyColumnState?.({ state, applyOrder: true });
      // 사용자 커스텀 너비가 있는 컬럼은 autoSize 대상에서 제외
      state.forEach((c: any) => { if (c.colId && c.width) resizedColsRef.current.add(c.colId); });
      return true;
    } catch { return false; }
  };

  const handleColumnResized = (e: any) => {
    // 사용자가 드래그로 조정한 컬럼만 "고정 너비"로 표시 (autoSize 제외 대상).
    // 드래그 중 다수 이벤트가 오므로 최종(finished) 시점에 저장.
    if (e.source === 'uiColumnResized' && e.column) {
      resizedColsRef.current.add(e.column.getColId());
      if (e.finished) saveColState();
    }
  };
  const handleColumnMoved = (e: any) => { if (e.source === 'uiColumnDragged' || e.finished) saveColState(); };
  const handleSortChanged = () => saveColState();
  // 모든 컬럼 정렬 해제 (저장상태에 남은 다중정렬 등 즉시 클리어)
  const resetSort = () => {
    const api = gridRef.current?.api as any;
    api?.applyColumnState?.({ defaultState: { sort: null, sortIndex: null } });
    saveColState();
  };
  const handleGridReady = () => { restoreColState(); applyColumnVisibility(); };

  // 빠른 필터: 카테고리/분류/날짜 (state 기반 — rowData를 직접 필터링해 1-click 즉시 반영)
  const [activeCat, setActiveCat] = useState<string | null>(null);
  const [activeClass, setActiveClass] = useState<string | null>(null);
  const [goodFilters, setGoodFilters] = useState<Set<GoodKey>>(new Set());
  const toggleGood = (key: GoodKey) => setGoodFilters(prev => {
    const n = new Set(prev);
    if (n.has(key)) n.delete(key); else n.add(key);
    return n;
  });
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

  // ── 관심 키워드 (북마크) ──
  // interestTick 을 올리면 interestRows / interestCount 가 localStorage 에서 재조회됨.
  const [interestOnly, setInterestOnly] = useState(false);    // 관심만 보기 모드
  const [interestHistory, setInterestHistory] = useState(false); // 날짜별 흐름(전체 날짜) 보기
  const [interestTick, setInterestTick] = useState(0);
  const [simpleView, setSimpleView] = useState(false);        // 간편 보기 (일부 컬럼 숨김)

  // 저장된 북마크 스냅샷 → 그리드 행. (added_at = 데이터 수집일 → 조회날짜 칸)
  //  - 기본(최신만): keyword_jp 별 가장 최신 날짜 1건, 최신 날짜 먼저
  //  - 흐름 보기: 모든 날짜 행 유지, 키워드별로 묶어 날짜 오름차순 (시계열 추적)
  const interestRaw = useMemo(() => getInterestKeywords(), [interestTick]);
  const interestRows = useMemo<any[]>(() => {
    let list: InterestKeyword[];
    if (interestHistory) {
      list = [...interestRaw].sort((a, b) =>
        a.keyword_jp === b.keyword_jp
          ? String(a.added_at || '').localeCompare(String(b.added_at || ''))
          : String(a.keyword_jp).localeCompare(String(b.keyword_jp), 'ja'),
      );
    } else {
      const latest = new Map<string, InterestKeyword>();
      for (const k of interestRaw) {
        const prev = latest.get(k.keyword_jp);
        if (!prev || String(k.added_at || '') > String(prev.added_at || '')) latest.set(k.keyword_jp, k);
      }
      list = [...latest.values()].sort((a, b) => String(b.added_at || '').localeCompare(String(a.added_at || '')));
    }
    return list.map((k, i) => ({
      id: -(i + 1),                       // DB id 와 충돌 안 나게 음수
      __interest: true,                   // 행 구분 플래그 (삭제 버튼 분기)
      lookup_date: k.added_at,            // 수집/북마크 날짜를 조회날짜 칸에 표시
      keyword_jp: k.keyword_jp,
      keyword_kr: k.keyword_kr ?? null,
      category: k.category,
      search_volume_weekly: k.search_volume_weekly,
      search_volume_daily: k.search_volume_daily,
      competition_intensity: k.competition_intensity,
      total_products: k.total_products,
      products_jp: k.products_jp,
      products_kr: k.products_kr,
      products_cn: k.products_cn,
      products_other: k.products_other,
      bid_count: k.bid_count,
      bid_price_1: k.bid_price_1,
      bid_price_2: k.bid_price_2,
      bid_price_3: k.bid_price_3,
      bid_price_4: k.bid_price_4,
      bid_price_5: k.bid_price_5,
      bid_price_6: k.bid_price_6,
      bid_price_7: k.bid_price_7,
      bid_price_8: k.bid_price_8,
      bid_price_9: k.bid_price_9,
      bid_price_10: k.bid_price_10,
    }));
  }, [interestRaw, interestHistory]);
  const interestCount = interestRaw.length;   // 저장된 전체 행 수

  // 표시용 필터링된 rowData (state 기반)
  // 관심만 보기 모드: 소스를 북마크 스냅샷으로 교체.
  //  - 카테고리·좋은키워드 필터는 그대로 적용 (스냅샷에 해당 값이 있음)
  //  - 날짜·분류 필터는 스킵 (스냅샷엔 의미 있는 분류/수집일 필터 대상이 없음)
  const filteredKeywords = useMemo(() => {
    const source = interestOnly ? interestRows : keywords;
    return source.filter(k => {
      if (activeCat && k.category !== activeCat) return false;
      if (!interestOnly && activeClass && k.classification !== activeClass) return false;
      for (const c of GOOD_CRITERIA) {
        if (goodFilters.has(c.key) && !c.test(k)) return false;
      }
      if (!interestOnly) {
        const d = k.lookup_date;
        if (dateMode === 'single' && singleDate) {
          if (d !== singleDate) return false;
        } else if (dateMode === 'range') {
          if (fromDate && (!d || d < fromDate)) return false;
          if (toDate && (!d || d > toDate)) return false;
        }
      }
      return true;
    });
  }, [keywords, interestOnly, interestRows, activeCat, activeClass, goodFilters, dateMode, singleDate, fromDate, toDate]);

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
  const pctFmt = (p: any) => p.value == null ? '' : `${Math.round(Number(p.value))}%`;

  const krRatioGetter = (p: any) => {
    const total = p.data?.total_products || 0;
    const kr = p.data?.products_kr || 0;
    return total > 0 ? (kr / total) * 100 : 0;
  };

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
      // added_at = 데이터 수집일(lookup_date). 날짜가 다르면 별도 행으로 보관됨.
      added_at: r.lookup_date || undefined,
      category: r.category,
      search_volume_weekly: r.search_volume_weekly,
      search_volume_daily: r.search_volume_daily,
      competition_intensity: r.competition_intensity,
      total_products: r.total_products,
      products_jp: r.products_jp,
      products_kr: r.products_kr,
      products_cn: r.products_cn,
      products_other: r.products_other,
      // 낙찰 스냅샷 (관심만 보기에서 낙찰수/구좌 표시 — 북마크 시점 값)
      bid_count: r.bid_count,
      bid_price_1: r.bid_price_1,
      bid_price_2: r.bid_price_2,
      bid_price_3: r.bid_price_3,
      bid_price_4: r.bid_price_4,
      bid_price_5: r.bid_price_5,
      bid_price_6: r.bid_price_6,
      bid_price_7: r.bid_price_7,
      bid_price_8: r.bid_price_8,
      bid_price_9: r.bid_price_9,
      bid_price_10: r.bid_price_10,
    }));
    const before = getInterestKeywords().length;
    const merged = addInterestKeywords(items);
    const added = merged.length - before;
    setInterestTick(t => t + 1);
    alert(
      `${added}개 새로 담음 (선택 ${items.length}${added < items.length ? `, 같은 날짜 중복 ${items.length - added}` : ''}). ` +
      `관심 풀 총 ${merged.length}개.`,
    );
  };

  // 그리드 행(__interest)의 keyword_jp + 날짜(lookup_date) 1건만 해제
  const sendSelectedToMargin = () => {
    const api = gridRef.current?.api as any;
    const selected: any[] = api?.getSelectedRows?.() || [];
    if (selected.length === 0) { alert('키워드 행을 체크해주세요.'); return; }
    const n = seedRowsFromKeywords(selected.map((r: any) => ({ keyword_jp: r.keyword_jp, keyword_kr: r.keyword_kr })));
    if (confirm(`${n}개 키워드를 마진 시트로 보냈습니다. 지금 이동할까요?`)) navigate('/margin-sheet');
  };

  const handleRemoveInterest = (jp: string, addedAt?: string | null) => {
    removeInterestEntry(jp, addedAt);
    setInterestTick(t => t + 1);
  };
  const removeSelectedInterest = () => {
    const api = gridRef.current?.api as any;
    const selected: any[] = api?.getSelectedRows?.() || [];
    if (selected.length === 0) { alert('해제할 행을 체크해주세요.'); return; }
    selected.forEach(r => removeInterestEntry(r.keyword_jp, r.lookup_date));
    setInterestTick(t => t + 1);
  };
  const clearAllInterest = () => {
    if (!confirm('관심 키워드를 모두 비우시겠습니까?')) return;
    clearInterestKeywords();
    setInterestTick(t => t + 1);
  };

  // 컬럼 가시성 — 간편 보기 / 관심 모드에 따라 그리드 API로 직접 토글
  // (columnDefs 를 재생성하지 않으므로 너비·순서 저장 로직과 충돌 없음)
  const applyColumnVisibility = () => {
    const api = gridRef.current?.api as any;
    if (!api?.setColumnsVisible) return;
    api.setColumnsVisible(SIMPLE_VIEW_HIDE, !simpleView);
    api.setColumnsVisible(INTEREST_HIDE, !interestOnly);
  };
  useEffect(() => { applyColumnVisibility(); }, [simpleView, interestOnly]);

  // ── 색상 강약(컬러 스케일) ──
  // colorColsRef: 색상 켠 컬럼 / colorStatsRef: 컬럼별 현재 보이는 행의 min~max.
  // 필터(빠른필터=rowData 교체 + ag-grid 컬럼필터) 변동 시 보이는 뷰 기준으로 실시간 재계산.
  const colorColsRef = useRef<Set<string>>(new Set());
  const colorStatsRef = useRef<Record<string, { min: number; max: number }>>({});
  const lastStatsSigRef = useRef('');
  const [colorVer, setColorVer] = useState(0);   // 툴바 재렌더용
  // 헤더 우클릭 메뉴 (색상 강약 토글)
  const [colorMenu, setColorMenu] = useState<{ colId: string; x: number; y: number } | null>(null);
  const openColorMenu = (colId: string, x: number, y: number) => setColorMenu({ colId, x, y });
  // 그리드 헤더에서 우클릭 시 → 해당 컬럼 색상 메뉴 (ag-grid 헤더셀의 col-id 속성 이용)
  const handleGridContextMenu = (e: any) => {
    const cell = (e.target as HTMLElement).closest('.ag-header-cell') as HTMLElement | null;
    if (!cell) return;                                  // 헤더가 아니면 기본(크롬) 메뉴 허용
    const colId = cell.getAttribute('col-id') || '';
    if (!COLOR_COLS.has(colId)) return;                 // 색상 대상 아닌 컬럼도 기본 메뉴
    e.preventDefault();
    openColorMenu(colId, e.clientX, e.clientY);
  };
  useEffect(() => {
    if (!colorMenu) return;
    const close = () => setColorMenu(null);
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setColorMenu(null); };
    window.addEventListener('click', close);
    window.addEventListener('resize', close);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('click', close);
      window.removeEventListener('resize', close);
      window.removeEventListener('keydown', onKey);
    };
  }, [colorMenu]);

  const cellNum = (colId: string, data: any): number | null => {
    if (!data) return null;
    if (colId === 'kr_ratio') {
      const tot = Number(data.total_products) || 0;
      const kr = Number(data.products_kr) || 0;
      return tot > 0 ? (kr / tot) * 100 : null;
    }
    const v = data[colId];
    if (v == null || v === '') return null;
    const n = Number(v);
    return isNaN(n) ? null : n;
  };

  // 보이는(필터 통과) 행만으로 컬럼별 min/max 재계산
  const recomputeColorStats = () => {
    const api = gridRef.current?.api as any;
    const cols = [...colorColsRef.current];
    if (!api || cols.length === 0) { colorStatsRef.current = {}; return; }
    const acc: Record<string, { min: number; max: number }> = {};
    cols.forEach(c => { acc[c] = { min: Infinity, max: -Infinity }; });
    api.forEachNodeAfterFilter((node: any) => {
      const d = node.data;
      if (!d) return;
      cols.forEach(c => {
        const v = cellNum(c, d);
        if (v == null) return;
        const s = acc[c];
        if (v < s.min) s.min = v;
        if (v > s.max) s.max = v;
      });
    });
    cols.forEach(c => { if (acc[c].min === Infinity) acc[c] = { min: 0, max: 0 }; });
    colorStatsRef.current = acc;
  };

  // 필터/모델 변동 시 호출 — 통계가 바뀐 경우에만 셀 새로고침 (루프 방지)
  const refreshColorScales = () => {
    if (colorColsRef.current.size === 0) return;
    recomputeColorStats();
    const sig = JSON.stringify(colorStatsRef.current);
    if (sig === lastStatsSigRef.current) return;
    lastStatsSigRef.current = sig;
    gridRef.current?.api?.refreshCells({ force: true, columns: [...colorColsRef.current] });
  };

  const toggleColorCol = (colId: string) => {
    const s = colorColsRef.current;
    if (s.has(colId)) s.delete(colId); else s.add(colId);
    lastStatsSigRef.current = '';
    recomputeColorStats();
    const api = gridRef.current?.api as any;
    api?.refreshHeader();
    api?.refreshCells({ force: true });
    setColorVer(v => v + 1);
  };
  const clearAllColors = () => {
    colorColsRef.current.clear();
    colorStatsRef.current = {};
    lastStatsSigRef.current = '';
    const api = gridRef.current?.api as any;
    api?.refreshHeader();
    api?.refreshCells({ force: true });
    setColorVer(v => v + 1);
  };

  // 컬럼 셀 배경 — 활성 시 값 위치(t)에 따라 컬럼 고유 색의 음영 강약. 기존 cellStyle 보존.
  // ※ ag-grid 는 새 style 에 backgroundColor 키가 없으면 이전 배경을 안 지움 → 끌 때 항상 '' 로 명시.
  const colorCellStyle = (colId: string, base?: (p: any) => any) => (p: any) => {
    const baseStyle = (base ? base(p) : undefined) || {};
    const off = { ...baseStyle, backgroundColor: (baseStyle as any).backgroundColor ?? '' };
    if (!colorColsRef.current.has(colId)) return off;
    const v = cellNum(colId, p.data);
    if (v == null) return off;
    const st = colorStatsRef.current[colId];
    if (!st || st.max === st.min) return off;
    const t = Math.max(0, Math.min(1, (v - st.min) / (st.max - st.min)));
    const a = (0.1 + 0.5 * t).toFixed(3);
    const hue = COLOR_HUE[colId] ?? 210;
    return { ...baseStyle, backgroundColor: `hsla(${hue}, 75%, 50%, ${a})` };
  };

  const columnDefs: ColDef[] = useMemo(() => [
    // (선택 체크박스 컬럼은 rowSelection 신 API가 자동 생성 — selectionColumnDef로 제어)
    // ── 원본 listKeyword 컬럼 순서 (좌→우, 큐텐 키워드 추출기 v1.4.3 기준) ──
    { field: 'lookup_date', headerName: '조회날짜', width: 78, valueFormatter: (p: any) => p.value ? String(p.value).slice(5) : '' },
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
            {p.value
              ? <a href={`https://www.qoo10.jp/s/?keyword=${encodeURIComponent(jp || p.value)}`} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline" title={jp ? `큐텐 검색: ${jp}` : undefined}>{p.value}</a>
              : '-'}
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
      colId: 'slot', headerName: '구좌', width: 72,
      valueGetter: (p: any) => slotOpen(p.data) ? '열림' : '',
      cellStyle: (p: any) => p.value ? { backgroundColor: '#bbf7d0', fontWeight: 700 } : undefined,
      headerTooltip: '낙찰수 ≤ 3 — 들어가면 바로 상위 노출 가능',
    },
    {
      colId: 'kr_ratio', headerName: '한국비율(%)', width: 110, type: 'numericColumn',
      valueGetter: krRatioGetter, valueFormatter: pctFmt,
    },
    {
      headerName: '', width: 70, sortable: false, filter: false, resizable: false, suppressMovable: true,
      cellRenderer: (p: any) => (
        <button
          onClick={() => p.data?.__interest ? handleRemoveInterest(p.data.keyword_jp, p.data.lookup_date) : handleDelete(p.data.id)}
          className="text-red-500 hover:text-red-700 text-xs"
        >{p.data?.__interest ? '해제' : '삭제'}</button>
      ),
    },
  ], []);

  // 색상 대상 컬럼에 🎨 헤더 토글 + 컬러 스케일 cellStyle 주입 (기존 cellStyle 보존).
  // columnDefs 본체는 재생성 안 하므로 너비/순서/가시성 로직과 충돌 없음.
  const columnDefsWithColor: ColDef[] = useMemo(() => columnDefs.map(def => {
    const colId = (def as any).colId || (def as any).field;
    if (!colId || !COLOR_COLS.has(colId)) return def;
    const base = (def as any).cellStyle;
    const baseFn = typeof base === 'function' ? base : (base ? () => base : undefined);
    return {
      ...def,
      cellStyle: colorCellStyle(colId, baseFn),
    } as ColDef;
  }), [columnDefs]);

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
            onClick={() => fetchKeywords(true)}
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
        {interestOnly && (
          <div className="px-2 pt-2 text-xs text-amber-700 bg-amber-50 rounded mb-1 py-1">
            ★ 관심만 보기 — {interestHistory
              ? '날짜별 흐름: 같은 키워드의 모든 북마크 날짜를 묶어 표시 (시계열 추적).'
              : '키워드별 최신 날짜 1건만, 최신 먼저. 「🕒 날짜별 흐름」 켜면 과거 날짜까지 흐름 추적.'} 담은 시점 데이터 그대로 · <b>카테고리·좋은키워드 필터 사용 가능</b> (날짜·분류 필터만 미적용).
          </div>
        )}
        <div className={`px-2 pt-2 pb-2 border-b border-gray-100 space-y-2 ${fullscreen ? 'shrink-0' : ''}`}>
          <div className={`flex items-center gap-2 flex-wrap ${interestOnly ? 'opacity-40 pointer-events-none select-none' : ''}`}>
            <span className="text-xs font-semibold text-gray-600 w-16">날짜</span>

            {/* 하루씩 선택 (기본 · 가장 최신일) */}
            <div className="flex items-center gap-1">
              <button
                onClick={goPrevDay}
                disabled={dateMode !== 'single' || dateIdx <= 0}
                title="이전 수집일"
                className="px-2 py-1 text-sm rounded border bg-white text-gray-700 disabled:opacity-30 hover:bg-gray-50"
              >◀</button>
              <DataDatePicker
                value={dateMode === 'single' ? singleDate : ''}
                availableDates={sortedDates}
                active={dateMode === 'single'}
                onChange={(d) => { setDateMode('single'); setSingleDate(d); }}
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
          <div className={`flex items-center gap-2 flex-wrap ${interestOnly ? 'opacity-40 pointer-events-none select-none' : ''}`}>
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
              onClick={() => setGoodFilters(new Set())}
              className={`px-2 py-0.5 text-xs rounded border ${goodFilters.size === 0 ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'}`}
            >전체</button>
            {GOOD_CRITERIA.map(c => (
              <button
                key={c.key}
                onClick={() => toggleGood(c.key)}
                title={c.desc}
                className={`px-2 py-0.5 text-xs rounded border ${goodFilters.has(c.key) ? 'bg-amber-500 text-white border-amber-500' : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'}`}
              >{c.label}</button>
            ))}
            {goodFilters.size > 0 && (
              <span className="text-xs text-gray-400">{goodFilters.size}개 기준 동시 충족(AND)</span>
            )}
          </div>
        </div>
        <div className={`px-2 py-2 text-sm text-gray-500 flex items-center gap-3 flex-wrap ${fullscreen ? 'shrink-0' : ''}`}>
          <span>표시 {filteredKeywords.length.toLocaleString()} / 총 {(interestOnly ? interestCount : keywords.length).toLocaleString()}개</span>
          <button
            onClick={resetSort}
            className="px-2 py-1 bg-gray-100 text-gray-600 text-xs rounded border hover:bg-gray-200"
            title="모든 컬럼 정렬 해제 (카테고리·분류 등 남은 다중정렬 클리어)"
          >
            ↕ 정렬 초기화
          </button>
          <button
            onClick={addSelectedToInterest}
            className="px-3 py-1 bg-emerald-600 text-white text-xs rounded hover:bg-emerald-700"
            title="선택한(체크된) 행을 관심 키워드로 북마크"
          >
            🔖 관심 담기 ({interestCount})
          </button>
          <button
            onClick={sendSelectedToMargin}
            className="px-3 py-1 bg-indigo-600 text-white text-xs rounded hover:bg-indigo-700"
            title="선택한(체크된) 키워드를 마진 시트로 보내기 (출처 키워드로 빈 후보행 생성)"
          >
            📋 마진 시트로
          </button>
          <button
            onClick={() => setInterestOnly(v => !v)}
            className={`px-3 py-1 text-xs rounded border ${interestOnly ? 'bg-amber-500 text-white border-amber-500' : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'}`}
            title="북마크한 관심 키워드만 (저장된 스냅샷 그대로) 보기 ↔ 전체 보기"
          >
            {interestOnly ? '★ 관심만 보기 ON' : '☆ 관심만 보기'}
          </button>
          <button
            onClick={() => setSimpleView(v => !v)}
            className={`px-3 py-1 text-xs rounded border ${simpleView ? 'bg-teal-600 text-white border-teal-600' : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'}`}
            title="국가별 상품수 · 낙찰 컬럼 전체 · 전날대비증감 · 일본어 키워드 컬럼을 숨겨 핵심만 표시 (관심만 보기와 병행 가능)"
          >
            {simpleView ? '🔎 간편 보기 ON' : '🔎 간편 보기'}
          </button>
          {(colorVer >= 0 && colorColsRef.current.size > 0) && (
            <button
              onClick={clearAllColors}
              className="px-3 py-1 bg-blue-100 text-blue-700 text-xs rounded hover:bg-blue-200"
              title="색상 강약 표기를 모든 컬럼에서 해제 (컬럼 헤더의 🎨 로 개별 토글)"
            >
              🎨 색상 해제 ({colorColsRef.current.size})
            </button>
          )}
          {interestOnly && (
            <>
              <button
                onClick={() => setInterestHistory(v => !v)}
                className={`px-3 py-1 text-xs rounded border ${interestHistory ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-white text-indigo-700 border-indigo-300 hover:bg-indigo-50'}`}
                title="끄면 키워드별 최신 날짜 1건만, 켜면 모든 날짜를 키워드별로 묶어 시계열 흐름 추적"
              >
                {interestHistory ? '🕒 날짜별 흐름 ON' : '🕒 최신만 (흐름 보기 OFF)'}
              </button>
              <button
                onClick={removeSelectedInterest}
                className="px-3 py-1 bg-gray-200 text-gray-700 text-xs rounded hover:bg-gray-300"
                title="체크한 행을 관심 목록에서 해제"
              >
                선택 북마크 해제
              </button>
              <button
                onClick={clearAllInterest}
                className="px-3 py-1 bg-red-100 text-red-700 text-xs rounded hover:bg-red-200"
                title="관심 키워드 전체 비우기"
              >
                전체 비우기
              </button>
            </>
          )}
          <button
            onClick={() => setFullscreen(f => !f)}
            className="px-3 py-1 bg-gray-800 text-white text-xs rounded hover:bg-black ml-auto"
            title="시트만 전체화면 — 사이드바 숨김, 세로 스크롤 1개. ESC 로 닫기"
          >
            {fullscreen ? '✕ 전체화면 닫기 (ESC)' : '⛶ 전체화면'}
          </button>
          <span className="text-xs text-gray-400">
            행 왼쪽 체크박스로 선택 · 헤더 ≡ 메뉴로 필터 · 헤더 🎨 로 색상 강약(보이는 행 기준)
          </span>
        </div>
        <div
          className={fullscreen ? 'flex-1 min-h-0' : ''}
          style={fullscreen
            ? { width: '100%' }
            : { height: toolsOpen ? 'calc(100vh - 200px)' : 'calc(100vh - 150px)', minHeight: 520, width: '100%' }}
          onContextMenu={handleGridContextMenu}
        >
          <AgGridReact
            ref={gridRef}
            theme={myTheme}
            rowData={filteredKeywords}
            columnDefs={columnDefsWithColor}
            defaultColDef={defaultColDef}
            rowSelection={{
              mode: 'multiRow',
              selectAll: 'filtered',
              enableClickSelection: true,          // 셀 아무 곳이나 클릭해도 행 선택(블록)
              enableSelectionWithoutKeys: true,    // Ctrl/Shift 없이도 클릭마다 토글 → 기존 체크 유지
            }}
            selectionColumnDef={{ pinned: 'left', width: 50, suppressMovable: true, lockPosition: true }}
            animateRows={true}
            pagination={true}
            paginationPageSize={2000}
            paginationPageSizeSelector={[100, 500, 1000, 2000, 5000]}
            loading={gridLoading}
            localeText={{ loadingOoo: '불러오는 중…', noRowsToShow: '표시할 키워드가 없습니다 (날짜·필터 확인)' }}
            onColumnResized={handleColumnResized}
            onColumnMoved={handleColumnMoved}
            onSortChanged={handleSortChanged}
            onFilterChanged={refreshColorScales}
            onModelUpdated={refreshColorScales}
            onGridReady={handleGridReady}
          />
        </div>
      </div>

      {/* 헤더 우클릭 색상 강약 메뉴 */}
      {colorMenu && (
        <div
          className="fixed z-[60] bg-white border border-gray-200 rounded-md shadow-lg py-1 text-sm"
          style={{ left: Math.min(colorMenu.x, window.innerWidth - 200), top: Math.min(colorMenu.y, window.innerHeight - 90) }}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={() => { toggleColorCol(colorMenu.colId); setColorMenu(null); }}
            className="block w-full text-left px-3 py-1.5 hover:bg-blue-50 whitespace-nowrap"
          >
            {colorColsRef.current.has(colorMenu.colId)
              ? '🎨 색상 강약 끄기'
              : '🎨 색상 강약 켜기 (보이는 행 기준)'}
          </button>
          {colorColsRef.current.size > 0 && (
            <button
              onClick={() => { clearAllColors(); setColorMenu(null); }}
              className="block w-full text-left px-3 py-1.5 hover:bg-blue-50 whitespace-nowrap text-gray-500 border-t"
            >
              모든 컬럼 색상 해제
            </button>
          )}
        </div>
      )}
    </div>
  );
}

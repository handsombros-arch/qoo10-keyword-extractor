import { useEffect, useMemo, useRef, useState } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { AllCommunityModule, ModuleRegistry, themeQuartz } from 'ag-grid-community';
import type { ColDef } from 'ag-grid-community';
import { getExchangeRate, getKeywords } from '../api/endpoints';
import { fetchCloud } from '../store/cloudSync';
import {
  loadRows, saveRows, loadSettings, saveSettings, newMarginRow,
  duplicateAsComposition, type MarginRow, type MarginSheetSettings,
} from '../store/marginSheet';
import {
  computeMarginRow, marginVerdict, type MarginRowInput,
} from '../lib/qoo10MarginSheet';

ModuleRegistry.registerModules([AllCommunityModule]);

const theme = themeQuartz.withParams({
  fontSize: 12, headerFontSize: 12, rowHeight: 32, headerHeight: 34,
  headerTextColor: '#111827', headerBackgroundColor: '#f3f4f6',
  foregroundColor: '#1f2937', headerFontWeight: 700,
});

const won = (p: any) => (p.value == null || p.value === '' ? '' : Math.round(Number(p.value)).toLocaleString());
const jpy = (p: any) => (p.value == null || p.value === '' ? '' : `¥${Math.round(Number(p.value)).toLocaleString()}`);
const pct = (p: any) => (p.value == null || p.value === '' ? '' : `${(Number(p.value) * 100).toFixed(1)}%`);

// 입력=흰색, 자동계산=옅은 회색, 등록가·마진율만 강조색.
const CALC_BG = { backgroundColor: '#f1f5f9' };

// 키워드 분석 토글 컬럼 (추출 키워드 기준값 — 출처 키워드 옆에 임시 표시)
const ANALYSIS_COLS = ['an_comp', 'an_sv', 'an_tp', 'an_krr', 'an_bid'];
const ANALYSIS_BG = { backgroundColor: '#eef2ff' };

// ── 엑셀/구글시트 ↔ 시트 클립보드 ──────────────────────────────
// 숫자: 쉼표·통화기호·공백 제거 후 파싱. 빈칸 또는 NaN 은 0(또는 null).
const toNum = (s: any): number => {
  const t = String(s ?? '').replace(/[,\s¥₩%]/g, '');
  if (t === '') return 0;
  const n = Number(t); return isNaN(n) ? 0 : n;
};
const toNumOrNull = (s: any): number | null => {
  const t = String(s ?? '').replace(/[,\s¥₩%]/g, '');
  if (t === '') return null;
  const n = Number(t); return isNaN(n) ? null : n;
};
const toStr = (s: any): string => String(s ?? '').trim();

// 붙여넣기/복사 대상 = 편집 가능한 입력 컬럼 (그리드 표시 순서 = 왼→오).
// 계산열·방식/배송 선택은 제외. key 는 포커스 셀의 field/colId 와 매칭.
type PasteCol = { key: string; set: (r: MarginRow, v: any) => void; get: (r: MarginRow) => string };
const PASTE_COLS: PasteCol[] = [
  { key: 'registered_date',  set: (r, v) => { r.registered_date = toStr(v); },   get: r => toStr(r.registered_date) },
  { key: 'source_keyword',   set: (r, v) => { r.source_keyword = toStr(v); },     get: r => toStr(r.source_keyword) },
  { key: 'product_name',     set: (r, v) => { r.product_name = toStr(v); },       get: r => toStr(r.product_name) },
  { key: 'option_label',     set: (r, v) => { r.option_label = toStr(v); },       get: r => toStr(r.option_label) },
  { key: 'url',              set: (r, v) => { r.url = toStr(v); },                 get: r => toStr(r.url) },
  { key: 'qty',              set: (r, v) => { r.qty = toNum(v) || 1; },            get: r => String(r.qty ?? '') },
  { key: 'weight_g',         set: (r, v) => { r.weight_g = toNum(v); },            get: r => String(r.weight_g ?? '') },
  { key: 'goods_cost_krw',   set: (r, v) => { r.goods_cost_krw = toNum(v); },      get: r => String(r.goods_cost_krw ?? '') },
  { key: 'inbound_ship_krw', set: (r, v) => { r.inbound_ship_krw = toNum(v); },    get: r => String(r.inbound_ship_krw ?? '') },
  { key: 'domestic_ship_krw',set: (r, v) => { r.domestic_ship_krw = toNum(v); },   get: r => String(r.domestic_ship_krw ?? '') },
  { key: 'kse',              set: (r, v) => { r.kse_override_krw = toNumOrNull(v); }, get: r => (r.kse_override_krw == null ? '' : String(r.kse_override_krw)) },
  { key: 'memo',             set: (r, v) => { r.memo = toStr(v); },                get: r => toStr(r.memo) },
];

// 클립보드 텍스트 → 2차원 배열 (행=\n, 열=\t). 엑셀/구글시트 복사 형식.
function parseClipboardMatrix(text: string): string[][] {
  const norm = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').replace(/\n+$/, '');
  if (!norm) return [];
  return norm.split('\n').map(line => line.split('\t'));
}

// 간소화: 배수/목표마진/메가할인은 행 컬럼이 아니라 상단 전역 설정값을 사용.
// 구매가 = 상품원가 + 국내배송비 (자동합산). 구버전 행 호환: purchase_krw 폴백.
function rowPurchaseKrw(r: any): number {
  const sum = (r.goods_cost_krw || 0) + (r.inbound_ship_krw || 0);
  return sum > 0 ? sum : (r.purchase_krw || 0);
}
function toInput(r: MarginRow, s: MarginSheetSettings): MarginRowInput {
  return {
    qty: r.qty, weightG: r.weight_g, purchaseKrw: rowPurchaseKrw(r),
    domesticShipKrw: r.domestic_ship_krw, mode: r.mode,
    markup: s.default_markup, targetMargin: s.default_target_margin,
    kseOverrideKrw: r.kse_override_krw, megaDiscount: s.default_mega_discount,
    shipPaidByBuyer: r.ship_mode === 'paid',
  };
}

export default function MarginSheetPage() {
  const [rows, setRows] = useState<MarginRow[]>(() => loadRows());
  const [settings, setSettings] = useState<MarginSheetSettings>(() => loadSettings());
  const [rateLoading, setRateLoading] = useState(false);
  const [tick, setTick] = useState(0);            // 재계산/경고 갱신
  const [fullscreen, setFullscreen] = useState(false);  // 시트 전체화면 (사이드바까지 덮음)
  const [selectedCount, setSelectedCount] = useState(0);  // 체크된 행 수 (선택 시 표시)
  const [analysisOn, setAnalysisOn] = useState(false);      // 키워드 분석 컬럼 토글
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const gridRef = useRef<AgGridReact>(null);
  const kwMapRef = useRef<Map<string, any>>(new Map());     // keyword_jp → 추출 키워드 분석값(최신)
  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  const rowsRef = useRef(rows);   // 최신 rows (메모된 cellRenderer 의 stale 클로저 방지)
  rowsRef.current = rows;

  // 전체화면 중 ESC 로 닫기
  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setFullscreen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [fullscreen]);

  // 마운트 시 클라우드에서 시트/설정 가져오기 + 환율 자동 조회(미설정 시)
  useEffect(() => {
    (async () => {
      const [cloudRows, cloudSet] = await Promise.all([
        fetchCloud<MarginRow[]>('margin_sheet'),
        fetchCloud<MarginSheetSettings>('margin_sheet_settings'),
      ]);
      if (cloudRows.data && Array.isArray(cloudRows.data)) {
        localStorage.setItem('marginSheet.rows.v1', JSON.stringify(cloudRows.data));
        setRows(cloudRows.data);
      }
      let s = settingsRef.current;
      if (cloudSet.data && typeof cloudSet.data === 'object') {
        s = { ...s, ...cloudSet.data };
        localStorage.setItem('marginSheet.settings.v1', JSON.stringify(s));
        setSettings(s);
      }
      if (!s.exchange_rate) await refreshRate();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refreshRate = async () => {
    setRateLoading(true);
    try {
      const res = await getExchangeRate('JPY');
      const rate = Number(res.data?.rate ?? res.data);
      if (rate > 0) {
        const next = {
          ...settingsRef.current,
          exchange_rate: Number(rate.toFixed(4)),
          rate_source: res.data?.source || 'live',
          rate_date: res.data?.as_of || '',
        };
        setSettings(next); saveSettings(next);
      }
    } catch { /* ignore */ } finally { setRateLoading(false); }
  };

  const rate = settings.exchange_rate;

  // 입력 변경 후: 저장 + 계산열/경고 갱신
  const persist = () => {
    saveRows(rowsRef.current);
    setTick(t => t + 1);
    gridRef.current?.api?.refreshCells({ force: true });
  };
  const updateSettings = (patch: Partial<MarginSheetSettings>) => {
    const next = { ...settingsRef.current, ...patch };
    setSettings(next); saveSettings(next);
    gridRef.current?.api?.refreshCells({ force: true });
    setTick(t => t + 1);
  };

  const addRow = () => {
    const api = gridRef.current?.api as any;
    // 앵커(원본): 체크된 마지막 행 → 없으면 포커스된 셀의 행 → 없으면 맨 끝
    const sel: MarginRow[] = api?.getSelectedRows?.() || [];
    let anchor: MarginRow | undefined = sel.length ? sel[sel.length - 1] : undefined;
    if (!anchor) {
      const fc = api?.getFocusedCell?.();
      const node = fc ? api?.getDisplayedRowAtIndex?.(fc.rowIndex) : null;
      if (node?.data) anchor = node.data;
    }
    // 원본이 있으면 출처 키워드·group_id 를 물려받아 바로 아래에 삽입 (붙어 다니도록)
    const fresh = anchor
      ? newMarginRow({
          source_keyword: anchor.source_keyword,
          source_keyword_jp: anchor.source_keyword_jp,
          group_id: anchor.group_id,
        })
      : newMarginRow({});
    let next: MarginRow[];
    if (anchor) {
      const idx = rows.findIndex(r => r.id === anchor!.id);
      next = [...rows];
      next.splice(idx >= 0 ? idx + 1 : rows.length, 0, fresh);
    } else {
      next = [...rows, fresh];
    }
    setRows(next); saveRows(next);
  };
  const deleteSelected = () => {
    const api = gridRef.current?.api as any;
    const sel: MarginRow[] = api?.getSelectedRows?.() || [];
    if (!sel.length) { alert('삭제할 행을 체크하세요.'); return; }
    const ids = new Set(sel.map(r => r.id));
    const next = rows.filter(r => !ids.has(r.id));
    setRows(next); saveRows(next);
  };
  const duplicateComposition = (qty: number) => {
    const api = gridRef.current?.api as any;
    const sel: MarginRow[] = api?.getSelectedRows?.() || [];
    if (!sel.length) { alert('복제할 기준 행을 체크하세요.'); return; }
    const dups = sel.map(r => duplicateAsComposition(r, qty));
    const next = [...rows, ...dups];
    setRows(next); saveRows(next);
  };

  // 메가와리 최소마진 미달 경고 (tick 으로 갱신)
  const megaWarnings = useMemo(() => {
    void tick;
    const min = settings.mega_min_margin;
    return rows.filter(r => {
      const res = computeMarginRow(toInput(r, settings), rate);
      return res.targetPriceKrw > 0 && res.megaMarginRate < min;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, settings, rate, tick]);

  const onCellValueChanged = (e: any) => {
    // 퍼센트 입력 컬럼은 valueSetter 에서 분수로 저장됨. 여기선 저장만.
    void e;
    persist();
  };

  const onSelectionChanged = () => {
    const api = gridRef.current?.api as any;
    setSelectedCount(api?.getSelectedRows?.()?.length || 0);
  };

  // 포커스된 컬럼의 PASTE_COLS 시작 인덱스 (field 또는 colId 로 매칭)
  const pasteStartIndex = (col: any): number => {
    const key = col?.getColDef?.()?.field || col?.getColId?.();
    const i = PASTE_COLS.findIndex(c => c.key === key);
    return i;
  };

  // 엑셀/구글시트에서 복사한 표를 포커스 셀부터 붙여넣기 (Community엔 기본 미지원 → 직접 구현)
  const onPaste = (e: React.ClipboardEvent) => {
    const api = gridRef.current?.api as any;
    if (!api) return;
    if (api.getEditingCells?.().length) return;   // 셀 편집 중이면 기본 동작에 맡김
    const focused = api.getFocusedCell?.();
    if (!focused || focused.rowIndex == null) return;
    const startCol = pasteStartIndex(focused.column);
    if (startCol < 0) return;   // 편집 불가 셀(계산열 등)에 포커스면 무시 → 입력 셀을 먼저 클릭
    const text = e.clipboardData?.getData('text/plain') || '';
    const matrix = parseClipboardMatrix(text);
    if (!matrix.length) return;

    e.preventDefault();

    const next = [...rows];
    const idToIdx = new Map(next.map((r, i) => [r.id, i]));
    for (let r = 0; r < matrix.length; r++) {
      const node = api.getDisplayedRowAtIndex?.(focused.rowIndex + r);
      let idx = node?.data ? idToIdx.get(node.data.id) : undefined;
      if (idx == null) {            // 행이 모자라면 새 행 추가
        const fresh = newMarginRow({});
        next.push(fresh); idx = next.length - 1; idToIdx.set(fresh.id, idx);
      }
      const row = { ...next[idx] };
      const cells = matrix[r];
      for (let c = 0; c < cells.length; c++) {
        const target = PASTE_COLS[startCol + c];
        if (!target) break;         // 오른쪽 끝 초과분은 버림
        target.set(row, cells[c]);
      }
      next[idx] = row;
    }
    setRows(next); saveRows(next);
    setTick(t => t + 1);
    setTimeout(() => gridRef.current?.api?.refreshCells({ force: true }), 0);
  };

  // 시트 → 엑셀/구글시트 복사: 체크된 행은 입력 컬럼 전체를 TSV로, 없으면 포커스 셀 값만.
  const onCopy = (e: React.ClipboardEvent) => {
    const api = gridRef.current?.api as any;
    if (!api) return;
    if (api.getEditingCells?.().length) return;   // 편집 중이면 기본 복사
    const sel: MarginRow[] = api.getSelectedRows?.() || [];
    let tsv = '';
    if (sel.length) {
      tsv = sel.map(row => PASTE_COLS.map(c => c.get(row)).join('\t')).join('\n');
    } else {
      const f = api.getFocusedCell?.();
      if (!f || f.rowIndex == null) return;
      const node = api.getDisplayedRowAtIndex?.(f.rowIndex);
      if (!node) return;
      let val: any;
      try { val = api.getCellValue?.({ rowNode: node, colKey: f.column }); } catch { /* ignore */ }
      if (val == null) { const fld = f.column?.getColDef?.()?.field; val = fld ? node.data?.[fld] : ''; }
      tsv = val == null ? '' : String(val);
    }
    if (!tsv) return;
    e.preventDefault();
    e.clipboardData?.setData('text/plain', tsv);
  };

  // 행 → 추출 키워드 분석값 (source_keyword_jp = 일본어 키워드로 매칭)
  const kwData = (r: any): any => {
    if (!r) return null;
    const key = r.source_keyword_jp || r.source_keyword;
    return key ? kwMapRef.current.get(key) || null : null;
  };

  // 키워드 분석 컬럼 토글 — 켜면 /api/keywords 최신값을 출처 키워드 옆에 표시, 다시 누르면 숨김
  const toggleAnalysis = async () => {
    const next = !analysisOn;
    setAnalysisOn(next);
    const api = gridRef.current?.api as any;
    if (next && kwMapRef.current.size === 0) {
      setAnalysisLoading(true);
      try {
        const res = await getKeywords();
        // 키워드별로 모든 날짜 행을 모음
        const byKw = new Map<string, any[]>();
        for (const k of (res.data || [])) {
          if (!k.keyword_jp) continue;
          const arr = byKw.get(k.keyword_jp);
          if (arr) arr.push(k); else byKw.set(k.keyword_jp, [k]);
        }
        // 필드별로 "값이 있는 가장 최근 행" 사용. 오늘 수집분에 상품수가 안 채워져도(0)
        // 최근에 채워진 날 값을 보여줌. 상품수·한국비율은 같은 행에서 가져와 일관성 유지.
        const map = new Map<string, any>();
        for (const [kw, list] of byKw) {
          list.sort((a, b) => String(b.lookup_date || '').localeCompare(String(a.lookup_date || ''))); // 최신 먼저
          const latest = list[0];
          const withProducts = list.find(r => Number(r.total_products) > 0);  // 상품수 채워진 최근 행
          const withBid = list.find(r => Number(r.bid_price_1) > 0);           // 낙찰가 있는 최근 행
          map.set(kw, {
            keyword_jp: kw,
            search_volume_weekly: latest.search_volume_weekly,
            competition_intensity: (withProducts || latest).competition_intensity,
            total_products: withProducts ? withProducts.total_products : null,
            products_kr: withProducts ? withProducts.products_kr : null,
            bid_price_1: withBid ? withBid.bid_price_1 : null,
          });
        }
        kwMapRef.current = map;
      } catch {
        alert('키워드 데이터를 불러오지 못했습니다.');
      } finally {
        setAnalysisLoading(false);
      }
    }
    api?.setColumnsVisible?.(ANALYSIS_COLS, next);
    api?.refreshCells?.({ force: true });
  };

  const marginCellStyle = (getter: (r: MarginRow) => number) => (p: any): any => {
    if (!p.data) return undefined;
    const m = getter(p.data);
    if (m < 0) return { backgroundColor: '#fee2e2', color: '#b91c1c', fontWeight: 700 };
    if (m >= 0.30) return { backgroundColor: '#dcfce7' };
    if (m >= 0.20) return { backgroundColor: '#ecfccb' };
    if (m >= 0.10) return { backgroundColor: '#fef9c3' };
    return { backgroundColor: '#fef3c7' };
  };

  const columnDefs: ColDef[] = useMemo(() => {
    const cg = (r: any) => computeMarginRow(toInput(r, settingsRef.current), settingsRef.current.exchange_rate);
    return [
      { field: 'registered_date', headerName: '등록일', width: 76, editable: true, pinned: 'left',
        cellEditor: 'agDateStringCellEditor',
        valueFormatter: (p: any) => { if (!p.value) return ''; const s = String(p.value).split('-'); return s.length === 3 ? `${Number(s[1])}/${Number(s[2])}` : p.value; },
        headerTooltip: '큐텐에 등록한 날짜. 더블클릭 → 달력에서 선택(오타 방지). 표시는 월/일. 대시보드 캘린더와 연동됩니다.' },
      { field: 'source_keyword', headerName: '출처 키워드', width: 130, editable: true, pinned: 'left',        headerTooltip: '키워드(RD)에서 보낸 출처 키워드. 클릭 시 일본어로 큐텐 검색. (표시는 한국어)',
        cellRenderer: (p: any) => {
          if (!p.value) return '';
          const jp = p.data?.source_keyword_jp || p.value;
          return jp
            ? <a href={`https://www.qoo10.jp/s/?keyword=${encodeURIComponent(jp)}`} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline" title={`큐텐 검색: ${jp}`}>{p.value}</a>
            : <span>{p.value}</span>;
        } },
      // ── 키워드 분석 (토글 — 기본 숨김. 추출 키워드 기준 최신값) ──
      { colId: 'an_comp', headerName: '경쟁강도', width: 88, hide: true, type: 'numericColumn', cellStyle: ANALYSIS_BG,
        headerTooltip: '키워드 분석 — 경쟁강도(전체상품수÷주평검색수). 추출 키워드 기준 최신값',
        valueGetter: (p: any) => kwData(p.data)?.competition_intensity ?? null,
        valueFormatter: (p: any) => p.value == null ? '' : Number(p.value).toLocaleString() },
      { colId: 'an_sv', headerName: '검색수(주평)', width: 100, hide: true, type: 'numericColumn', cellStyle: ANALYSIS_BG,
        headerTooltip: '키워드 분석 — 주간 평균 검색수',
        valueGetter: (p: any) => kwData(p.data)?.search_volume_weekly ?? null,
        valueFormatter: (p: any) => p.value == null ? '' : Number(p.value).toLocaleString() },
      { colId: 'an_tp', headerName: '전체상품수', width: 96, hide: true, type: 'numericColumn', cellStyle: ANALYSIS_BG,
        headerTooltip: '키워드 분석 — 큐텐 전체 상품수',
        valueGetter: (p: any) => kwData(p.data)?.total_products ?? null,
        valueFormatter: (p: any) => p.value == null ? '' : Number(p.value).toLocaleString() },
      { colId: 'an_krr', headerName: '한국비율(%)', width: 96, hide: true, type: 'numericColumn', cellStyle: ANALYSIS_BG,
        headerTooltip: '키워드 분석 — 한국상품수 ÷ 전체상품수',
        valueGetter: (p: any) => { const d = kwData(p.data); if (!d) return null; const t = Number(d.total_products) || 0; const kr = Number(d.products_kr) || 0; return t > 0 ? (kr / t) * 100 : null; },
        valueFormatter: (p: any) => p.value == null ? '' : `${Math.round(Number(p.value))}%` },
      { colId: 'an_bid', headerName: '낙찰종가', width: 90, hide: true, type: 'numericColumn', cellStyle: ANALYSIS_BG,
        headerTooltip: '키워드 분석 — 경매 1위 낙찰가(최고가). 낙찰가 수집된 키워드만',
        valueGetter: (p: any) => kwData(p.data)?.bid_price_1 ?? null,
        valueFormatter: (p: any) => p.value == null ? '' : Number(p.value).toLocaleString() },
      { field: 'product_name', headerName: '상품명', width: 190, editable: true, pinned: 'left',        headerTooltip: '소싱할 국내 상품명' },
      { field: 'option_label', headerName: '구성', width: 88, editable: true,        headerTooltip: '구성/세트 라벨 (예: 1개입 / 2개 세트). 세트 복제 버튼으로 자동 생성' },
      { field: 'url', headerName: 'URL', width: 70, editable: true,        headerTooltip: '국내 상품 페이지 URL (입력하면 "링크" 로 표시)',
        cellRenderer: (p: any) => p.value
          ? <a href={p.value} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">링크</a> : '' },
      { field: 'qty', headerName: '개수', width: 60, editable: true, type: 'numericColumn', cellEditor: 'agNumberCellEditor',        headerTooltip: '세트 개수. 개수만큼 무게·상품원가·국내배송·KSE배대지가 곱해짐' },
      { field: 'weight_g', headerName: '무게(g)', width: 78, editable: true, type: 'numericColumn', cellEditor: 'agNumberCellEditor',        headerTooltip: '상품 1개 실제 무게(g). 포장 100g 가산 후 KSE 해상 요금표 자동조회. 무료/유료 모두 운임 산정에 사용.' },
      { field: 'goods_cost_krw', headerName: '상품원가', width: 84, editable: true, type: 'numericColumn', cellEditor: 'agNumberCellEditor', valueFormatter: won,        headerTooltip: '국내 상품 자체 가격(1개)' },
      { field: 'inbound_ship_krw', headerName: '국내배송비', width: 84, editable: true, type: 'numericColumn', cellEditor: 'agNumberCellEditor', valueFormatter: won,        headerTooltip: '국내 상품을 내(배대지)에게 받기까지의 배송비(1개). 놓치기 쉬우니 별도 입력 → 구매가에 자동 합산.' },
      { headerName: '구매가', width: 90, type: 'numericColumn', cellStyle: CALC_BG, valueGetter: (p: any) => p.data && rowPurchaseKrw(p.data), valueFormatter: won,        headerTooltip: '상품원가 + 국내배송비 자동 합산. (자동계산)' },
      { field: 'domestic_ship_krw', headerName: 'KSE배대지 배송+포장', width: 130, editable: true, type: 'numericColumn', cellEditor: 'agNumberCellEditor', valueFormatter: won,        headerTooltip: '한국 KSE 배대지(포워더)까지 보내는 국내 배송비 + 포장비(1개). (큐텐 해상 KSE 운임과는 별개)' },
      { field: 'mode', headerName: '방식', width: 96,
        headerTooltip: '클릭해서 선택. 원가배수=구매가×배수, 목표마진=목표 마진율 역산. 배수/목표마진/메가할인 값은 상단 설정에서 일괄 적용.',
        cellRenderer: (p: any) => (
          <select value={p.data?.mode || 'markup'} onChange={e => { p.data.mode = e.target.value; persist(); }}
            style={{ width: '100%', background: 'transparent', border: 'none', cursor: 'pointer', font: 'inherit' }}>
            <option value="markup">원가배수</option>
            <option value="target">목표마진</option>
          </select>
        ) },
      { field: 'ship_mode', headerName: '배송', width: 80,
        headerTooltip: '클릭해서 선택. 무료배송=셀러가 KSE 운임 부담(고객 무부담). 유료배송=고객이 운임 부담→셀러 운임 0. 둘 다 마진에 반영.',
        cellRenderer: (p: any) => (
          <select value={p.data?.ship_mode || 'free'} onChange={e => { p.data.ship_mode = e.target.value; persist(); }}
            style={{ width: '100%', background: 'transparent', border: 'none', cursor: 'pointer', font: 'inherit' }}>
            <option value="free">무료</option>
            <option value="paid">유료</option>
          </select>
        ) },
      { colId: 'kse', headerName: 'KSE운임', width: 100, editable: true, type: 'numericColumn', cellEditor: 'agNumberCellEditor',
        headerTooltip: '큐텐 KSE 해상운임(한국→일본). 무게로 자동 계산되며 직접 입력해 덮어쓸 수 있음(예외 조정). 비우면 다시 자동. 유료배송이면 고객 부담이라 셀러 마진에서 제외.',
        valueGetter: (p: any) => p.data ? (p.data.kse_override_krw != null ? p.data.kse_override_krw : cg(p.data).kseAutoKrw) : null,
        valueSetter: (p: any) => {
          const n = p.newValue;
          p.data.kse_override_krw = (n === '' || n == null || isNaN(Number(n))) ? null : Number(n);
          return true;
        },
        valueFormatter: won,
        cellStyle: (p: any): any => p.data?.kse_override_krw != null ? { backgroundColor: '#fde68a' } : { color: '#94a3b8' } },

      // ── 계산 (read-only) ──
      { headerName: '발송무게', width: 82, type: 'numericColumn', cellStyle: CALC_BG, headerTooltip: '무게×개수 + 포장 100g', valueGetter: (p: any) => p.data && cg(p.data).effWeightG, valueFormatter: (p: any) => p.value ? `${p.value}g` : '' },
      { headerName: '판매가(원)', width: 96, type: 'numericColumn', cellStyle: CALC_BG, headerTooltip: '원화 목표 판매가 P (마진 기준값)', valueGetter: (p: any) => p.data && cg(p.data).targetPriceKrw, valueFormatter: won },
      // 상시
      { headerName: '상시 등록가(¥)', width: 108, type: 'numericColumn', headerTooltip: '할인 없는 상시 큐텐 등록가(엔). 작성 당일 환율로 산출', valueGetter: (p: any) => p.data && cg(p.data).listJpy, valueFormatter: jpy, cellStyle: { backgroundColor: '#dbeafe', fontWeight: 700 } },
      { headerName: '상시 이익', width: 90, type: 'numericColumn', cellStyle: CALC_BG, headerTooltip: '상시가 기준 순이익(원)', valueGetter: (p: any) => p.data && cg(p.data).profitKrw, valueFormatter: won },
      { headerName: '상시 마진율', width: 92, type: 'numericColumn', headerTooltip: '상시 이익 ÷ 판매가(원)', valueGetter: (p: any) => p.data && cg(p.data).marginRate, valueFormatter: pct, cellStyle: marginCellStyle(r => cg(r).marginRate) },
      // 메가와리
      { headerName: '메가 등록가(¥)', width: 110, type: 'numericColumn', headerTooltip: '메가와리(빅프로모션) 할인 적용 등록가(엔)', valueGetter: (p: any) => p.data && cg(p.data).megaListJpy, valueFormatter: jpy, cellStyle: { backgroundColor: '#f3e8ff', fontWeight: 700 } },
      { headerName: '메가 이익', width: 90, type: 'numericColumn', cellStyle: CALC_BG, headerTooltip: '메가와리 할인 적용 시 순이익(원). 음수면 역마진', valueGetter: (p: any) => p.data && cg(p.data).megaProfitKrw, valueFormatter: won },
      { headerName: '메가 마진율', width: 92, type: 'numericColumn', headerTooltip: '메가 이익 ÷ 판매가(원). 상단 메가 최소마진 미달 시 경고', valueGetter: (p: any) => p.data && cg(p.data).megaMarginRate, valueFormatter: pct, cellStyle: marginCellStyle(r => cg(r).megaMarginRate) },
      { headerName: '평가', width: 64, cellStyle: CALC_BG, headerTooltip: '상시 마진율 정성 평가', valueGetter: (p: any) => p.data && marginVerdict(cg(p.data).marginRate) },
      { field: 'memo', headerName: '메모', width: 130, editable: true, headerTooltip: '자유 메모' },
    ];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const defaultColDef: ColDef = useMemo(() => ({
    sortable: true, resizable: true, suppressMovable: false, minWidth: 48,
    wrapHeaderText: true, autoHeaderHeight: true,   // 컬럼명 너비 따라 2줄까지
  }), []);

  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">📋 큐텐 마진 시트</h2>

      {/* 환율 + 설정 바 */}
      <div className="bg-white rounded-lg shadow p-3 mb-3 flex items-center gap-4 flex-wrap text-sm">
        <div className="flex items-center gap-2">
          <span className="font-semibold">작성 당일 환율</span>
          <span className="text-lg font-bold text-blue-700">{rate ? `${rate} 원/¥` : '미설정'}</span>
          {settings.rate_date && <span className="text-xs text-gray-400">({settings.rate_date} {settings.rate_source})</span>}
          <button onClick={refreshRate} disabled={rateLoading}
            className="px-2 py-1 text-xs rounded border bg-white hover:bg-gray-50 disabled:opacity-50">
            {rateLoading ? '조회중…' : '↻ 당일환율'}
          </button>
          <input type="number" step="0.01" value={rate || ''} onChange={e => updateSettings({ exchange_rate: Number(e.target.value) })}
            className="w-20 border rounded px-2 py-1 text-xs" title="수동 보정" />
        </div>
        <div className="h-5 w-px bg-gray-200" />
        <label className="flex items-center gap-1">기본 배수
          <input type="number" step="0.05" value={settings.default_markup} onChange={e => updateSettings({ default_markup: Number(e.target.value) })} className="w-16 border rounded px-1 py-0.5 text-xs" />
        </label>
        <label className="flex items-center gap-1">기본 목표마진%
          <input type="number" step="1" value={Math.round(settings.default_target_margin * 100)} onChange={e => updateSettings({ default_target_margin: Number(e.target.value) / 100 })} className="w-14 border rounded px-1 py-0.5 text-xs" />
        </label>
        <label className="flex items-center gap-1">메가 할인%
          <input type="number" step="1" value={Math.round(settings.default_mega_discount * 100)} onChange={e => updateSettings({ default_mega_discount: Number(e.target.value) / 100 })} className="w-14 border rounded px-1 py-0.5 text-xs" />
        </label>
        <label className="flex items-center gap-1 text-rose-700">메가 최소마진%
          <input type="number" step="1" value={Math.round(settings.mega_min_margin * 100)} onChange={e => updateSettings({ mega_min_margin: Number(e.target.value) / 100 })} className="w-14 border rounded px-1 py-0.5 text-xs" />
        </label>
      </div>

      {/* 메가와리 경고 배너 */}
      {megaWarnings.length > 0 && (
        <div className="bg-rose-50 border border-rose-300 text-rose-800 rounded-lg p-3 mb-3 text-sm">
          ⚠️ <b>메가와리 최소마진({Math.round(settings.mega_min_margin * 100)}%) 미달 {megaWarnings.length}건</b> —
          메가와리(빅프로모션) 할인 적용 시 마진이 부족하거나 역마진입니다. 판매가·구성·배송비를 조정하세요.
          {megaWarnings.some(r => computeMarginRow(toInput(r, settings), rate).megaMarginRate < 0) &&
            <span className="ml-1 font-bold">(역마진 포함)</span>}
        </div>
      )}

      {/* 툴바 + 그리드 (전체화면 시 사이드바까지 덮는 고정 오버레이) */}
      <div className={fullscreen ? 'fixed inset-0 z-50 bg-white flex flex-col p-2 overflow-hidden' : ''}>
        <div className={`flex items-center gap-2 mb-2 text-sm flex-wrap ${fullscreen ? 'shrink-0' : ''}`}>
          <button onClick={addRow} className="px-3 py-1 bg-blue-600 text-white text-xs rounded hover:bg-blue-700" title="체크(또는 커서)한 원본 행 바로 아래에 새 행을 추가하고 출처 키워드를 물려받습니다. 선택이 없으면 맨 아래에 추가.">+ 행 추가</button>
          <button onClick={() => duplicateComposition(2)} className="px-3 py-1 bg-emerald-600 text-white text-xs rounded hover:bg-emerald-700" title="체크한 행을 2개 세트 구성으로 복제">2개 세트 복제</button>
          <button onClick={() => duplicateComposition(3)} className="px-3 py-1 bg-emerald-600 text-white text-xs rounded hover:bg-emerald-700">3개 세트 복제</button>
          <button onClick={deleteSelected} className="px-3 py-1 bg-red-100 text-red-700 text-xs rounded hover:bg-red-200">선택 삭제</button>
          <button
            onClick={toggleAnalysis}
            disabled={analysisLoading}
            className={`px-3 py-1 text-xs rounded border disabled:opacity-50 ${analysisOn ? 'bg-indigo-600 text-white border-indigo-600 hover:bg-indigo-700' : 'bg-white text-indigo-700 border-indigo-300 hover:bg-indigo-50'}`}
            title="추출 키워드 기준 경쟁강도·검색수(주평)·전체상품수·한국비율·낙찰종가를 출처 키워드 옆에 임시 표시 (다시 누르면 숨김)"
          >
            {analysisLoading ? '불러오는 중…' : analysisOn ? '🔍 키워드 분석 ON' : '🔍 키워드 분석'}
          </button>
          {selectedCount > 0 && (
            <span className="px-2 py-1 bg-blue-50 text-blue-700 text-xs rounded font-semibold border border-blue-200">
              {selectedCount}개 선택됨
            </span>
          )}
          <span className="text-xs text-gray-400">방식·배송 = 클릭 선택 · 등록가·마진율만 색상 · 총 {rows.length}행 · 헤더에 마우스=설명 · 엑셀/구글시트에서 복사 → 입력 셀 클릭 후 Ctrl+V 붙여넣기</span>
          <button
            onClick={() => setFullscreen(f => !f)}
            className="px-3 py-1 bg-gray-800 text-white text-xs rounded hover:bg-black ml-auto"
            title="시트만 전체화면 — 사이드바 숨김. ESC 로 닫기"
          >
            {fullscreen ? '✕ 전체화면 닫기 (ESC)' : '⛶ 전체화면'}
          </button>
        </div>

        <div
          className={fullscreen ? 'flex-1 min-h-0' : ''}
          style={fullscreen ? { width: '100%' } : { height: 'calc(100vh - 230px)', minHeight: 480, width: '100%' }}
          onPaste={onPaste}
          onCopy={onCopy}
        >
          <AgGridReact
            ref={gridRef}
            theme={theme}
            rowData={rows}
            columnDefs={columnDefs}
            defaultColDef={defaultColDef}
            tooltipShowDelay={300}
            rowSelection={{ mode: 'multiRow', selectAll: 'filtered', enableClickSelection: false }}
            selectionColumnDef={{ pinned: 'left', width: 44 }}
            singleClickEdit={false}
            stopEditingWhenCellsLoseFocus={true}
            onCellValueChanged={onCellValueChanged}
            onSelectionChanged={onSelectionChanged}
            getRowId={(p: any) => p.data.id}
            rowClassRules={{
              'mega-loss-row': (p: any) => p.data && computeMarginRow(toInput(p.data, settingsRef.current), settingsRef.current.exchange_rate).megaMarginRate < 0,
            }}
          />
        </div>
      </div>
      <style>{`.mega-loss-row { background-color: #fff1f2 !important; }`}</style>
    </div>
  );
}

import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { AgGridReact } from 'ag-grid-react';
import { themeQuartz } from 'ag-grid-community';
import type { ColDef } from 'ag-grid-community';
import api from '../api/client';
import {
  collectRecommendations, getLoginStatus, getRecommendationReport,
  previewAutoSourcing, runAutoSourcing, fetchQoo10ProductsByKeywords,
  listKeywordCategories,
  type AutoSourcingParams,
} from '../api/endpoints';
import {
  clearInterestKeywords,
  getInterestKeywords,
  removeInterestKeyword,
  type InterestKeyword,
} from '../store/interestKeywords';
import {
  loadSheet, newSheetRow, saveSheet, totalPurchaseKrw, type SheetRow,
  type CompositionOption,
} from '../store/productSheet';
import CompositionsPanel, { summarizeBestComposition } from '../components/common/CompositionsPanel';
import SheetRowDetailPanel from '../components/SheetRowDetailPanel';
import { fetchCloud, makeDebouncedPusher } from '../store/cloudSync';
import {
  calculateMargin, marginVerdict,
  calculateRecommendScore,
  targetSellJpyForMargin,
  PRICE_SWEETSPOT_MIN_JPY, PRICE_SWEETSPOT_MAX_JPY,
} from '../lib/marginCalc';

const TARGET_MARGIN_NORMAL = 0.20;

const myTheme = themeQuartz.withParams({
  fontSize: 12,
  headerFontSize: 12,
  rowHeight: 60,
  headerHeight: 36,
  headerBackgroundColor: '#f3f4f6',
  headerTextColor: '#111827',
  foregroundColor: '#1f2937',
  headerFontWeight: 700,
});

const fmt = {
  krw: (n: number) => (n == null ? '' : Math.round(n).toLocaleString()),
  jpy: (n: number) => (n == null ? '' : Math.round(n).toLocaleString()),
  pct: (n: number) => (n == null ? '' : `${(n * 100).toFixed(1)}%`),
};

const verdictColor: Record<string, string> = {
  우수: { color: '#15803d', backgroundColor: '#dcfce7' } as any,
  양호: { color: '#1d4ed8', backgroundColor: '#dbeafe' } as any,
  애매: { color: '#b45309', backgroundColor: '#fef3c7' } as any,
  부족: { color: '#c2410c', backgroundColor: '#ffedd5' } as any,
  손실: { color: '#b91c1c', backgroundColor: '#fee2e2' } as any,
};

// ─── 가격 분포 히스토그램 ────────────────────────────
function PriceHistogram({ rows }: { rows: SheetRow[] }) {
  const prices = rows.map(r => r.sell_price_jpy).filter(p => p > 0);
  if (prices.length === 0) {
    return (
      <div className="bg-white rounded-lg shadow p-5 mb-5 text-center text-sm text-gray-400">
        시트에 판매가가 있는 상품이 없습니다.
      </div>
    );
  }

  // 버킷: 0~1k, 1~2k, 2~3k, 3~5k, 5~10k, 10k+
  const buckets = [
    { label: '~1k', min: 0, max: 1000 },
    { label: '1~2k', min: 1000, max: 2000 },
    { label: '2~3k', min: 2000, max: 3000 },
    { label: '3~5k', min: 3000, max: 5000 },
    { label: '5~10k', min: 5000, max: 10000 },
    { label: '10k+', min: 10000, max: Infinity },
  ];

  const counts = buckets.map(b => ({
    ...b,
    count: prices.filter(p => p >= b.min && p < b.max).length,
    sweetSpot: b.min >= PRICE_SWEETSPOT_MIN_JPY && b.max <= PRICE_SWEETSPOT_MAX_JPY + 1,
  }));

  const maxCount = Math.max(...counts.map(c => c.count), 1);

  const avg = prices.reduce((s, p) => s + p, 0) / prices.length;
  const sorted = [...prices].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)];
  const min = sorted[0];
  const max = sorted[sorted.length - 1];
  const inSweet = prices.filter(p => p >= PRICE_SWEETSPOT_MIN_JPY && p <= PRICE_SWEETSPOT_MAX_JPY).length;

  return (
    <div className="bg-white rounded-lg shadow p-5 mb-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold">📊 가격 분포 ({prices.length}개 상품)</h3>
        <div className="text-xs text-gray-500">
          스윗스팟 ({PRICE_SWEETSPOT_MIN_JPY.toLocaleString()}~{PRICE_SWEETSPOT_MAX_JPY.toLocaleString()}엔)
          <span className="ml-1 inline-block w-3 h-3 bg-green-200 border border-green-400 rounded-sm align-middle" />
        </div>
      </div>

      <div className="grid grid-cols-5 gap-3 mb-4 text-xs">
        <div className="bg-gray-50 rounded p-2">
          <div className="text-gray-500">최저</div>
          <div className="font-mono font-bold">¥{min.toLocaleString()}</div>
        </div>
        <div className="bg-gray-50 rounded p-2">
          <div className="text-gray-500">중앙값</div>
          <div className="font-mono font-bold">¥{median.toLocaleString()}</div>
        </div>
        <div className="bg-gray-50 rounded p-2">
          <div className="text-gray-500">평균</div>
          <div className="font-mono font-bold">¥{Math.round(avg).toLocaleString()}</div>
        </div>
        <div className="bg-gray-50 rounded p-2">
          <div className="text-gray-500">최고</div>
          <div className="font-mono font-bold">¥{max.toLocaleString()}</div>
        </div>
        <div className="bg-emerald-50 rounded p-2">
          <div className="text-emerald-700">스윗스팟</div>
          <div className="font-mono font-bold text-emerald-700">{inSweet}개 ({((inSweet / prices.length) * 100).toFixed(0)}%)</div>
        </div>
      </div>

      {/* 막대그래프 */}
      <div className="flex items-end gap-2 h-40 border-b border-gray-200 relative">
        {counts.map(b => {
          const height = (b.count / maxCount) * 100;
          return (
            <div key={b.label} className="flex-1 flex flex-col items-center justify-end h-full">
              <div className="text-[10px] text-gray-600 mb-1 font-semibold">{b.count}</div>
              <div
                className={`w-full rounded-t transition-all ${b.sweetSpot ? 'bg-emerald-500' : 'bg-blue-400'}`}
                style={{ height: `${Math.max(height, 2)}%` }}
                title={`${b.label}엔: ${b.count}개`}
              />
            </div>
          );
        })}
      </div>
      <div className="flex gap-2 mt-1">
        {counts.map(b => (
          <div key={b.label} className="flex-1 text-center text-[10px] text-gray-500">{b.label}</div>
        ))}
      </div>

      <div className="mt-3 text-[11px] text-gray-500">
        💡 추천점수의 <b>가격대 적합도(30%)</b>는 스윗스팟 구간에서 만점, 외부로 벗어나면 감소합니다.
        리뷰 점수(10%)와 마진율(60%) 합산으로 정렬됩니다.
      </div>
    </div>
  );
}

// ─── 이미지 확대 모달 ────────────────────────────────
function ImageZoomModal({ src, onClose }: { src: string; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div
      className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4 cursor-zoom-out"
      onClick={onClose}
    >
      <img
        src={src}
        alt=""
        className="max-w-[90vw] max-h-[90vh] object-contain rounded shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      />
      <button
        onClick={onClose}
        className="absolute top-4 right-6 text-white text-3xl hover:text-gray-300"
        aria-label="닫기"
      >✕</button>
    </div>
  );
}

// ─── 상품 시트 (엑셀식 편집) ───────────────────────────
const COL_STATE_KEY = 'productSheet.colState.v1';

function ProductSheet({ rows, setRows }: { rows: SheetRow[]; setRows: (r: SheetRow[]) => void }) {
  const gridRef = useRef<AgGridReact>(null);
  const [zoomImg, setZoomImg] = useState<string | null>(null);
  const [colDropdownOpen, setColDropdownOpen] = useState(false);
  const [colListVersion, setColListVersion] = useState(0);
  const [qoo10ExportOpen, setQoo10ExportOpen] = useState(false);
  const [qoo10ExportRows, setQoo10ExportRows] = useState<SheetRow[]>([]);
  // 구성 편집 패널: 선택된 상품 id (null이면 패널 숨김)
  const [compositionRowId, setCompositionRowId] = useState<string | null>(null);
  // TT-1B 우측 슬라이드 패널 — 키워드 클릭 시 SEO 콘텐츠/옵션/매칭 사유 한 번에
  const [detailRow, setDetailRow] = useState<SheetRow | null>(null);
  const onOpenDetailPanel = (row: SheetRow) => setDetailRow(row);
  const onCloseDetailPanel = () => setDetailRow(null);

  const updateCompositions = (rowId: string, compositions: CompositionOption[]) => {
    setRows(rows.map(r => (r.id === rowId ? { ...r, compositions } : r)));
  };

  // 확장 행 높이 재계산: 선택 상품의 구성 개수 변동에 반응
  useEffect(() => {
    const api = gridRef.current?.api as any;
    if (!api || !compositionRowId) return;
    try { api.resetRowHeights(); } catch { /* ignore */ }
  }, [compositionRowId, rows]);

  // ─ 일자 필터 ─
  const [dateMode, setDateMode] = useState<'all' | 'single' | 'range' | 'today'>('all');
  const [singleDate, setSingleDate] = useState<string>('');
  const [fromDate, setFromDate] = useState<string>('');
  const [toDate, setToDate] = useState<string>('');

  const today = new Date().toISOString().slice(0, 10);

  const filteredRows = useMemo(() => {
    if (dateMode === 'all') return rows;
    return rows.filter(r => {
      const d = r.created_at || '';
      if (dateMode === 'today') return d === today;
      if (dateMode === 'single') return singleDate ? d === singleDate : true;
      if (dateMode === 'range') {
        if (fromDate && d < fromDate) return false;
        if (toDate && d > toDate) return false;
        return true;
      }
      return true;
    });
  }, [rows, dateMode, singleDate, fromDate, toDate, today]);

  // 선택된 행 바로 아래에 구성 편집 확장 행을 주입
  const rowsWithExpansion = useMemo(() => {
    if (!compositionRowId) return filteredRows;
    const out: any[] = [];
    for (const r of filteredRows) {
      out.push(r);
      if (r.id === compositionRowId) {
        out.push({ __expansion: true, __parentId: r.id, id: `__exp_${r.id}` });
      }
    }
    return out;
  }, [filteredRows, compositionRowId]);

  // 일자별 집계 (필터 옵션 표시용)
  const dateGroups = useMemo(() => {
    const map = new Map<string, number>();
    for (const r of rows) {
      const d = r.created_at || '(미지정)';
      map.set(d, (map.get(d) || 0) + 1);
    }
    return Array.from(map.entries()).sort((a, b) => b[0].localeCompare(a[0]));
  }, [rows]);

  const computeRow = (r: SheetRow) => calculateMargin({
    weight_g: r.weight_g,
    purchase_price_krw: totalPurchaseKrw(r),
    shipping_packaging_krw: r.shipping_packaging_krw,
    sell_price_jpy: r.sell_price_jpy,
    exchange_rate: r.exchange_rate ?? 9.5,
    shipping_mode: r.shipping_mode ?? 'auto',
    is_mega: false,
  });
  const computeRowMega = (r: SheetRow) => calculateMargin({
    weight_g: r.weight_g,
    purchase_price_krw: totalPurchaseKrw(r),
    shipping_packaging_krw: r.shipping_packaging_krw,
    sell_price_jpy: r.sell_price_jpy,
    exchange_rate: r.exchange_rate ?? 9.5,
    shipping_mode: r.shipping_mode ?? 'auto',
    is_mega: true,
  });
  const computeTargetJpy = (r: SheetRow, target: number) => targetSellJpyForMargin({
    weight_g: r.weight_g,
    purchase_price_krw: totalPurchaseKrw(r),
    shipping_packaging_krw: r.shipping_packaging_krw,
    sell_price_jpy: r.sell_price_jpy,
    exchange_rate: r.exchange_rate ?? 9.5,
    shipping_mode: r.shipping_mode ?? 'auto',
    is_mega: false,
  }, target);
  const computeScore = (r: SheetRow) => {
    const m = computeRow(r);
    return calculateRecommendScore({
      sell_price_jpy: r.sell_price_jpy,
      exchange_rate: r.exchange_rate ?? 9.5,
      review_count: r.review_count ?? 0,
      margin_rate: m.margin_rate,
    });
  };

  const columnDefs: ColDef[] = useMemo<ColDef[]>(() => ([
    // ─ 핀 고정 영역 ─
    {
      headerName: '선택', width: 55, pinned: 'left', sortable: false, filter: false,
      checkboxSelection: true, headerCheckboxSelection: true,
    },
    {
      field: 'created_at', headerName: '작성일 / 구성', width: 115, pinned: 'left',
      cellRenderer: (p: any) => {
        if (p.data?.__expansion) return null;
        const best = summarizeBestComposition(p.data);
        const count = (p.data?.compositions || []).length;
        const isOpen = compositionRowId === p.data?.id;
        return (
          <div className="flex flex-col h-full justify-center leading-tight py-0.5">
            <span className="text-[11px] text-gray-500">{p.value || ''}</span>
            <button
              onClick={(e) => { e.stopPropagation(); setCompositionRowId(isOpen ? null : (p.data?.id || null)); }}
              className={`text-[10px] mt-0.5 px-1 py-0 rounded border self-start ${
                isOpen
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'bg-white text-blue-700 border-blue-300 hover:bg-blue-50'
              }`}
              title={best ? `최고 마진 구성: ${best.label} ${(best.margin_rate * 100).toFixed(1)}%` : '구성 편집'}
            >
              {isOpen ? '▾ 접기' : (count > 0
                ? `▸ ${count}개${best ? ` ${(best.margin_rate * 100).toFixed(0)}%` : ''}`
                : '▸ 편집')}
            </button>
          </div>
        );
      },
      autoHeight: true,
      cellStyle: { padding: 2 },
    },
    {
      field: 'source', headerName: '출처', width: 120, pinned: 'left',
      cellRenderer: (p: any) => {
        const v = p.value || '';
        const rank = p.data.shop_rank ? ` #${p.data.shop_rank}` : '';
        return <span className="text-xs text-gray-600">{v}{rank}</span>;
      },
    },
    {
      field: 'product_name', headerName: '상품명', width: 300, pinned: 'left', autoHeight: false,
      cellRenderer: (p: any) => {
        const img = p.data.cover_image_url;
        const name = p.value || '';
        const thumb = img ? (
          <img
            src={img}
            alt=""
            className="w-14 h-14 object-cover rounded border border-gray-200 flex-shrink-0 cursor-zoom-in hover:ring-2 hover:ring-blue-400 transition"
            onClick={() => setZoomImg(img)}
            title="클릭 확대"
          />
        ) : (
          <div className="w-14 h-14 rounded bg-gray-100 flex-shrink-0" />
        );
        const text = p.data.product_url
          ? <a href={p.data.product_url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline line-clamp-2 leading-tight">{name}</a>
          : <span className="line-clamp-2 leading-tight">{name}</span>;
        return <div className="flex items-center gap-2 overflow-hidden h-full">{thumb}<div className="flex-1 overflow-hidden">{text}</div></div>;
      },
    },
    {
      field: 'product_name_ko', headerName: '한글명', width: 200, pinned: 'left', editable: true,
      cellStyle: { backgroundColor: '#fefce8' },
      valueFormatter: (p: any) => p.value || '(번역 필요)',
    },

    // ─ 원가 섹션 (엑셀 L, M 근처) ─
    { field: 'weight_g', headerName: '무게(g)', width: 80, editable: true, type: 'numericColumn',
      cellStyle: { backgroundColor: '#fefce8' } },
    { field: 'item_price_krw', headerName: '구매가', width: 90, editable: true, type: 'numericColumn',
      valueFormatter: (p: any) => fmt.krw(p.value),
      cellStyle: { backgroundColor: '#fefce8' } },
    { field: 'domestic_shipping_krw', headerName: '국내배송', width: 85, editable: true, type: 'numericColumn',
      valueFormatter: (p: any) => fmt.krw(p.value),
      cellStyle: { backgroundColor: '#fefce8' } },
    { headerName: '합계', width: 90, type: 'numericColumn',
      valueGetter: (p: any) => totalPurchaseKrw(p.data),
      valueFormatter: (p: any) => fmt.krw(p.value),
      cellStyle: { color: '#374151', fontStyle: 'italic' } },
    { field: 'shipping_packaging_krw', headerName: '포장+KSE', width: 90, editable: true, type: 'numericColumn',
      valueFormatter: (p: any) => fmt.krw(p.value),
      cellStyle: { backgroundColor: '#fefce8' } },

    // ─ 판매가 섹션 (엑셀 Y, AD 근처) ─
    { field: 'competitor_price_jpy', headerName: '경쟁가(¥)', width: 95, type: 'numericColumn',
      valueFormatter: (p: any) => p.value ? `¥${fmt.jpy(p.value)}` : '-',
      cellStyle: { color: '#6b7280', fontStyle: 'italic' },
      headerTooltip: '스크래핑된 경쟁 상품 가격 (참고용, 수정 불가)' },
    { headerName: '예상판매가(¥)', width: 110, type: 'numericColumn',
      valueGetter: (p: any) => {
        const rate = p.data.exchange_rate ?? 9.5;
        const rec = computeRow(p.data).recommended_price_krw_30pct;
        return rate > 0 ? Math.round(rec / rate) : 0;
      },
      valueFormatter: (p: any) => p.value ? `¥${fmt.jpy(p.value)}` : '-',
      cellStyle: { color: '#1d4ed8', fontStyle: 'italic' },
      headerTooltip: '수식 기반 권장가: (구매가+포장) × 1.3 ÷ 환율 → 30% 마진 확보선' },
    { headerName: '차이', width: 70, type: 'numericColumn',
      valueGetter: (p: any) => {
        const comp = p.data.competitor_price_jpy || 0;
        const rate = p.data.exchange_rate ?? 9.5;
        const rec = computeRow(p.data).recommended_price_krw_30pct;
        const expected = rate > 0 ? rec / rate : 0;
        if (!comp || !expected) return 0;
        return ((expected - comp) / comp) * 100;
      },
      valueFormatter: (p: any) => {
        if (!p.value) return '-';
        const v = Math.round(p.value);
        const sign = v > 0 ? '+' : '';
        return `${sign}${v}%`;
      },
      cellStyle: (p: any) => {
        if (!p.value) return {};
        // 예상 > 경쟁 = 내 예상가가 더 비쌈 → 경쟁력 떨어짐 (빨강)
        // 예상 < 경쟁 = 내 예상가가 더 저렴 → 경쟁력 있음 (녹색)
        return p.value > 0
          ? { color: '#b91c1c' } as any
          : { color: '#15803d', fontWeight: 'bold' } as any;
      },
      headerTooltip: '(예상판매가 - 경쟁가) / 경쟁가. 음수일수록 내 예상가가 저렴 = 경쟁력' },
    { headerName: '권장가(20%)', width: 105, type: 'numericColumn',
      valueGetter: (p: any) => Math.round(computeTargetJpy(p.data, TARGET_MARGIN_NORMAL)),
      valueFormatter: (p: any) => p.value > 0 ? `¥${fmt.jpy(p.value)}` : '-',
      cellStyle: (p: any) => {
        const cur = p.data?.sell_price_jpy || 0;
        if (!p.value || !cur) return { color: '#1d4ed8', fontStyle: 'italic' };
        // 내 판매가가 목표가 이상 → 20% 달성 가능 (녹색), 미만 → 경고 (주황)
        return cur >= p.value
          ? { color: '#15803d', fontWeight: 'bold' } as any
          : { color: '#c2410c', fontWeight: 'bold' } as any;
      },
      headerTooltip: '일반마진 20%를 달성하려면 필요한 엔화 판매가. 수수료·배송 모드 반영 정밀 역산. 내 판매가가 이 값 이상이면 녹색.' },
    { field: 'sell_price_jpy', headerName: '내 판매가(¥)', width: 110, editable: true, type: 'numericColumn',
      valueFormatter: (p: any) => `¥${fmt.jpy(p.value)}`,
      cellStyle: { backgroundColor: '#fefce8', fontWeight: 'bold' },
      headerTooltip: '내가 큐텐에 등록할 판매가 (마진 계산 기준). 경쟁가·예상판매가 참고하여 수동 입력' },
    { headerName: '메가가(¥)', width: 95, type: 'numericColumn',
      valueGetter: (p: any) => Math.round((p.data.sell_price_jpy || 0) * 0.9),
      valueFormatter: (p: any) => p.value ? `¥${fmt.jpy(p.value)}` : '-',
      cellStyle: { color: '#b45309', fontStyle: 'italic' },
      headerTooltip: '메가와리 10% 할인가 = 내 판매가 × 0.9 (자동 계산)' },

    // ─ 일반 수익 섹션 (엑셀 AB, AC 근처) ─
    {
      field: 'shipping_mode', headerName: '배송', width: 110, editable: true,
      cellEditor: 'agSelectCellEditor',
      cellEditorParams: { values: ['auto', 'free', 'paid'] },
      valueGetter: (p: any) => p.data?.shipping_mode || 'auto',
      valueFormatter: (p: any) => {
        const mode = p.value;
        if (mode === 'free') return '무료 (수동)';
        if (mode === 'paid') return '유료 (수동)';
        // auto: 20,000원 임계값 기반 자동 판정
        const resolved = computeRow(p.data).shipping_mode_resolved;
        return `자동 (${resolved === 'free' ? '무료' : '유료'})`;
      },
      cellStyle: (p: any) => {
        const mode = p.data?.shipping_mode || 'auto';
        if (mode === 'free') return { backgroundColor: '#ecfdf5', color: '#047857' } as any;
        if (mode === 'paid') return { backgroundColor: '#fef2f2', color: '#b91c1c' } as any;
        return { color: '#6b7280', fontStyle: 'italic' } as any;
      },
      headerTooltip: '자동: 원화 판매가 ≥ 20,000원이면 무료(KSE), 미만이면 유료. 수동으로 무료/유료 고정 가능.',
    },
    { headerName: '배송비', width: 85, type: 'numericColumn',
      valueGetter: (p: any) => computeRow(p.data).shipping_cost_krw,
      valueFormatter: (p: any) => fmt.krw(p.value) },
    { headerName: '수수료(¥)', width: 90, type: 'numericColumn',
      valueGetter: (p: any) => computeRow(p.data).commission_jpy,
      valueFormatter: (p: any) => `¥${fmt.jpy(p.value)}` },
    { headerName: '매출', width: 95, type: 'numericColumn',
      valueGetter: (p: any) => computeRow(p.data).revenue_krw,
      valueFormatter: (p: any) => fmt.krw(p.value),
      cellStyle: { color: '#6b7280' } },
    { headerName: '총원가', width: 95, type: 'numericColumn',
      valueGetter: (p: any) => computeRow(p.data).total_cost_krw,
      valueFormatter: (p: any) => fmt.krw(p.value),
      cellStyle: { color: '#6b7280' } },
    { headerName: '일반이익', width: 95, type: 'numericColumn',
      valueGetter: (p: any) => computeRow(p.data).profit_krw,
      valueFormatter: (p: any) => fmt.krw(p.value),
      cellStyle: (p: any) => ({
        fontWeight: 'bold',
        color: p.value >= 0 ? '#15803d' : '#b91c1c',
      } as any) },
    { headerName: '일반마진', width: 85, type: 'numericColumn',
      valueGetter: (p: any) => computeRow(p.data).margin_rate,
      valueFormatter: (p: any) => fmt.pct(p.value),
      cellStyle: (p: any) => ({
        fontWeight: 'bold',
        color: p.value >= 0 ? '#15803d' : '#b91c1c',
      } as any) },

    // ─ 메가와리 섹션 (엑셀 AD, AE 근처) ─
    { headerName: '메가이익', width: 95, type: 'numericColumn',
      valueGetter: (p: any) => computeRowMega(p.data).profit_krw,
      valueFormatter: (p: any) => fmt.krw(p.value),
      cellStyle: (p: any) => ({
        fontWeight: 'bold',
        color: p.value >= 0 ? '#b45309' : '#b91c1c',
      } as any) },
    { headerName: '메가마진', width: 85, type: 'numericColumn',
      valueGetter: (p: any) => computeRowMega(p.data).margin_rate,
      valueFormatter: (p: any) => fmt.pct(p.value),
      cellStyle: (p: any) => ({ color: p.value >= 0 ? '#b45309' : '#b91c1c' } as any) },

    // ─ 평가·리뷰·점수 ─
    { headerName: '평가', width: 75,
      valueGetter: (p: any) => marginVerdict(computeRow(p.data).margin_rate),
      cellStyle: (p: any) => verdictColor[p.value] || {} },
    { field: 'review_count', headerName: '리뷰수', width: 75, type: 'numericColumn',
      valueFormatter: (p: any) => p.value ? p.value.toLocaleString() : '-' },
    {
      headerName: '🏆점수', width: 80, type: 'numericColumn',
      valueGetter: (p: any) => computeScore(p.data).total,
      valueFormatter: (p: any) => p.value.toFixed(1),
      cellStyle: (p: any) => {
        const v = p.value;
        if (v >= 70) return { backgroundColor: '#dcfce7', color: '#15803d', fontWeight: 'bold' } as any;
        if (v >= 50) return { backgroundColor: '#dbeafe', color: '#1d4ed8', fontWeight: 'bold' } as any;
        if (v >= 30) return { backgroundColor: '#fef3c7', color: '#b45309' } as any;
        return { backgroundColor: '#fee2e2', color: '#b91c1c' } as any;
      },
      tooltipValueGetter: (p: any) => {
        const s = computeScore(p.data);
        return `가격대 ${s.price_component.toFixed(1)}/40 | 마진 ${s.margin_component.toFixed(1)}/40 | 리뷰 ${s.review_component.toFixed(1)}/20`;
      },
    },
    { field: 'notes', headerName: '메모', width: 130, editable: true },

    // ─ 매칭 메타 (TT-1A 신규, hide 기본 — 사장님이 토글 show) ─
    { field: 'match_decision', headerName: '매칭', width: 80, hide: true,
      cellRenderer: (p: any) => {
        const v = p.value || 'pending';
        const cls = v === 'accepted' ? 'bg-emerald-100 text-emerald-800'
          : v === 'rejected' ? 'bg-red-100 text-red-700'
          : v === 'cheapest' ? 'bg-blue-100 text-blue-700'
          : v === 'manual' ? 'bg-gray-100 text-gray-700'
          : 'bg-yellow-50 text-yellow-700';
        return <span className={`text-[10px] px-1.5 py-0.5 rounded ${cls}`}>{v}</span>;
      },
    },
    { field: 'match_image_score', headerName: 'img점수', width: 75, hide: true, type: 'numericColumn',
      valueFormatter: (p: any) => p.value != null ? p.value.toFixed(2) : '-',
      cellStyle: (p: any) => ({
        color: p.value >= 0.7 ? '#15803d' : p.value >= 0.5 ? '#b45309' : '#b91c1c',
      } as any) },
    { field: 'match_name_score', headerName: 'txt점수', width: 75, hide: true, type: 'numericColumn',
      valueFormatter: (p: any) => p.value != null ? p.value.toFixed(2) : '-' },
    { field: 'match_note', headerName: '매칭사유', width: 200, hide: true,
      tooltipField: 'match_note',
      cellStyle: { fontSize: '11px', color: '#6b7280' } as any },

    // ─ 큐텐 SEO 콘텐츠 (Phase 4-B 자동 생성, 인플레이스 편집) ─
    { field: 'qoo10_title_jp', headerName: '큐텐 title', width: 220, hide: true, editable: true,
      cellStyle: { backgroundColor: '#fefce8', fontSize: '12px' } as any },
    { field: 'qoo10_tags', headerName: '큐텐 tags', width: 200, hide: true,
      cellRenderer: (p: any) => {
        const tags: string[] = Array.isArray(p.value) ? p.value : [];
        if (!tags.length) return <span className="text-gray-400 text-xs">-</span>;
        return (
          <div className="flex flex-wrap gap-1 py-1">
            {tags.slice(0, 5).map((t, i) => (
              <span key={i} className="bg-blue-50 text-blue-700 px-1 py-0.5 rounded text-[10px]">{t}</span>
            ))}
            {tags.length > 5 && <span className="text-[10px] text-gray-500">+{tags.length - 5}</span>}
          </div>
        );
      },
    },
    { field: 'qoo10_marketing', headerName: '마케팅포인트', width: 130, hide: true,
      cellRenderer: (p: any) => {
        const items: string[] = Array.isArray(p.value) ? p.value : [];
        if (!items.length) return <span className="text-gray-400 text-xs">-</span>;
        return (
          <button
            onClick={(e) => { e.stopPropagation(); onOpenDetailPanel?.(p.data); }}
            className="text-blue-600 hover:underline text-xs cursor-pointer"
            title={items.join('\n')}
          >
            {items.length}개 포인트 ▸
          </button>
        );
      },
    },
    { field: 'qoo10_option_name', headerName: '큐텐 옵션', width: 130, hide: true, editable: true,
      cellStyle: { backgroundColor: '#fefce8', fontSize: '12px' } as any },
  ] as ColDef[]), [compositionRowId, onOpenDetailPanel]);

  const defaultColDef: ColDef = useMemo(() => ({
    resizable: true, sortable: true, filter: false, suppressHeaderMenuButton: false,
  }), []);

  const onCellValueChanged = (_e: any) => {
    const api = gridRef.current?.api as any;
    if (!api) return;
    try {
      api.applyColumnState?.({ defaultState: { sort: null } });
    } catch { /* ignore */ }
    const newRows: SheetRow[] = [];
    api.forEachNode((node: any) => {
      // __expansion 행(합성 행)은 localStorage에 저장하지 않음
      if (node.data && !node.data.__expansion) newRows.push(node.data);
    });
    setRows(newRows);
    saveSheet(newRows);
    api.refreshCells?.({ force: true });
  };

  // ─── 컬럼 상태 저장/복원 (너비·숨김·순서 localStorage) ───
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
    } catch { /* ignore */ }
  };
  const onColumnResized = (e: any) => {
    if (e.finished) saveColState();
  };
  const onColumnVisible = () => { saveColState(); setColListVersion(v => v + 1); };
  const onColumnMoved = (e: any) => { if (e.finished) saveColState(); };
  const onGridReady = () => { restoreColState(); };

  const toggleColumn = (colId: string) => {
    const api = gridRef.current?.api as any;
    if (!api) return;
    const col = api.getColumn?.(colId);
    if (!col) return;
    api.setColumnsVisible?.([colId], !col.isVisible());
    saveColState();
    setColListVersion(v => v + 1);
  };
  const resetColState = () => {
    localStorage.removeItem(COL_STATE_KEY);
    const api = gridRef.current?.api as any;
    if (api) api.resetColumnState?.();
    setColListVersion(v => v + 1);
  };

  const columnList = useMemo(() => {
    const api = gridRef.current?.api as any;
    if (!api) return [];
    const cols = api.getColumns?.() || [];
    return cols.map((c: any) => ({
      colId: c.getColId(),
      header: c.getColDef?.()?.headerName || c.getColId(),
      visible: c.isVisible(),
    }));
  }, [colListVersion, rows]);

  // ─ CSV 내보내기 ─
  const exportCsv = () => {
    const headers = [
      '작성일', '출처', '상품명', '한글명', '상품URL',
      '경쟁가(¥)', '예상판매가(¥)', '차이%', '내판매가(¥)', '메가가(¥)',
      '무게(g)', '구매가(원)', '국내배송(원)', '합계(원)', '포장+KSE(원)',
      '배송모드', '배송비(원)', '수수료(¥)', '매출(원)', '총원가(원)',
      '일반이익(원)', '일반마진율', '메가이익(원)', '메가마진율',
      '평가', '리뷰수', '추천점수', '메모',
    ];
    const csv: string[] = [];
    csv.push('\ufeff' + headers.join(','));
    for (const r of filteredRows) {
      const m = computeRow(r);
      const mega = computeRowMega(r);
      const score = computeScore(r);
      const expectedJpy = (r.exchange_rate ?? 9.5) > 0
        ? Math.round(m.recommended_price_krw_30pct / (r.exchange_rate ?? 9.5))
        : 0;
      const comp = r.competitor_price_jpy || 0;
      const diffPct = comp > 0 ? Math.round(((expectedJpy - comp) / comp) * 100) : 0;
      const row = [
        r.created_at || '',
        r.source || '',
        (r.product_name || '').replace(/"/g, '""'),
        (r.product_name_ko || '').replace(/"/g, '""'),
        r.product_url || '',
        String(r.competitor_price_jpy || 0),
        String(expectedJpy),
        `${diffPct}%`,
        String(r.sell_price_jpy || 0),
        String(Math.round((r.sell_price_jpy || 0) * 0.9)),
        String(r.weight_g || 0),
        String(r.item_price_krw || 0),
        String(r.domestic_shipping_krw || 0),
        String(totalPurchaseKrw(r)),
        String(r.shipping_packaging_krw || 0),
        m.shipping_mode_resolved === 'free' ? '무료' : '유료',
        String(Math.round(m.shipping_cost_krw)),
        String(Math.round(m.commission_jpy)),
        String(Math.round(m.revenue_krw)),
        String(Math.round(m.total_cost_krw)),
        String(Math.round(m.profit_krw)),
        `${(m.margin_rate * 100).toFixed(1)}%`,
        String(Math.round(mega.profit_krw)),
        `${(mega.margin_rate * 100).toFixed(1)}%`,
        marginVerdict(m.margin_rate),
        String(r.review_count || 0),
        score.total.toFixed(1),
        (r.notes || '').replace(/"/g, '""'),
      ].map(v => `"${v}"`);
      csv.push(row.join(','));
    }
    const blob = new Blob([csv.join('\n')], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const ts = new Date().toISOString().slice(0, 10);
    a.download = `상품시트_${ts}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const sortByScore = () => {
    // 컬럼 sort state 대신 rows 배열 자체를 점수 내림차순으로 재정렬.
    // 편집 후 행 위치 유지를 위해 컬럼 sort는 설정하지 않음.
    const api = gridRef.current?.api as any;
    const current: SheetRow[] = [];
    if (api) {
      api.forEachNode((n: any) => { if (n.data) current.push(n.data); });
    } else {
      current.push(...rows);
    }
    const sorted = [...current].sort(
      (a, b) => computeScore(b).total - computeScore(a).total
    );
    setRows(sorted);
    saveSheet(sorted);
    // 혹시 사용자가 컬럼 헤더 클릭으로 설정한 sort가 남아있으면 해제
    try {
      api?.applyColumnState?.({ defaultState: { sort: null } });
    } catch { /* ignore */ }
  };

  const deleteSelected = () => {
    const api = gridRef.current?.api as any;
    if (!api) return;
    const sel: SheetRow[] = api.getSelectedRows?.() || [];
    if (sel.length === 0) return;
    if (!confirm(`${sel.length}개 행을 삭제하시겠습니까?`)) return;
    const selIds = new Set(sel.map(s => s.id));
    const next = rows.filter(r => !selIds.has(r.id));
    setRows(next);
    saveSheet(next);
  };

  const addEmptyRow = () => {
    const next = [...rows, newSheetRow({ source: '수동', product_name: '새 상품' })];
    setRows(next);
    saveSheet(next);
  };


  // 합계
  const totals = useMemo(() => {
    const computed = filteredRows.map(r => computeRow(r));
    const totalProfit = computed.reduce((s, r) => s + r.profit_krw, 0);
    const avgMargin = computed.length > 0
      ? computed.reduce((s, r) => s + r.margin_rate, 0) / computed.length
      : 0;
    const okCount = computed.filter(r => r.margin_rate >= 0.20).length;
    return { totalProfit, avgMargin, okCount, total: filteredRows.length };
  }, [filteredRows]);

  return (
    <div className="bg-white rounded-lg shadow">
      <div className="px-4 py-3 border-b flex items-center justify-between">
        <div>
          <h3 className="font-bold text-lg">📋 상품 시트</h3>
          <div className="text-xs text-gray-500 mt-0.5">
            노란색 셀만 편집 가능. 편집하면 오른쪽 지표가 즉시 재계산됩니다.
          </div>
        </div>
        <div className="flex gap-2 relative">
          <button onClick={sortByScore} className="px-3 py-1.5 bg-amber-500 text-white text-xs rounded hover:bg-amber-600">
            🔄 점수순 정렬
          </button>
          <div className="relative">
            <button
              onClick={() => setColDropdownOpen(v => !v)}
              className="px-3 py-1.5 bg-gray-600 text-white text-xs rounded hover:bg-gray-700"
            >
              👁 컬럼 표시
            </button>
            {colDropdownOpen && (
              <div className="absolute right-0 top-full mt-1 bg-white border shadow-lg rounded z-10 w-64 max-h-80 overflow-y-auto">
                <div className="p-2 border-b flex justify-between items-center">
                  <span className="text-xs font-semibold">컬럼 선택</span>
                  <button onClick={resetColState} className="text-[10px] text-blue-600 hover:underline">
                    초기화
                  </button>
                </div>
                {columnList.map((c: any) => (
                  <label key={c.colId} className="flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50 cursor-pointer text-xs">
                    <input
                      type="checkbox"
                      checked={c.visible}
                      onChange={() => toggleColumn(c.colId)}
                    />
                    <span>{c.header}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
          <button onClick={addEmptyRow} className="px-3 py-1.5 bg-blue-600 text-white text-xs rounded hover:bg-blue-700">
            ➕ 빈 행 추가
          </button>
          <button onClick={deleteSelected} className="px-3 py-1.5 bg-red-500 text-white text-xs rounded hover:bg-red-600">
            🗑 선택 행 삭제
          </button>
        </div>
      </div>

      {/* 일자 필터 + CSV 내보내기 */}
      <div className="px-4 py-2 bg-gray-50 border-b flex flex-wrap gap-3 items-center text-xs">
        <div className="flex items-center gap-1.5">
          <span className="text-gray-600 font-semibold">📅 일자:</span>
          {[
            { v: 'all', label: '전체' },
            { v: 'today', label: '오늘' },
            { v: 'single', label: '특정일' },
            { v: 'range', label: '기간' },
          ].map(o => (
            <button key={o.v}
              onClick={() => setDateMode(o.v as any)}
              className={`px-2 py-0.5 rounded ${dateMode === o.v ? 'bg-blue-600 text-white' : 'bg-white border border-gray-300 hover:bg-gray-50'}`}
            >{o.label}</button>
          ))}
          {dateMode === 'single' && (
            <select value={singleDate} onChange={e => setSingleDate(e.target.value)}
              className="border rounded px-2 py-0.5">
              <option value="">날짜 선택</option>
              {dateGroups.map(([d, c]) => (
                <option key={d} value={d}>{d} ({c}개)</option>
              ))}
            </select>
          )}
          {dateMode === 'range' && (
            <>
              <input type="date" value={fromDate} onChange={e => setFromDate(e.target.value)}
                className="border rounded px-2 py-0.5" />
              <span>~</span>
              <input type="date" value={toDate} onChange={e => setToDate(e.target.value)}
                className="border rounded px-2 py-0.5" />
            </>
          )}
        </div>
        <div className="ml-auto flex gap-2">
          <button
            onClick={() => {
              const api = gridRef.current?.api as any;
              const selected: SheetRow[] = api?.getSelectedRows?.() || [];
              const target = selected.length > 0 ? selected : filteredRows;
              if (target.length === 0) { alert('내보낼 상품이 없습니다.'); return; }
              setQoo10ExportRows(target);
              setQoo10ExportOpen(true);
            }}
            className="px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700"
            title="선택된 행 있으면 선택 행만, 없으면 현재 표시된 모든 행"
          >
            📤 큐텐 양식
          </button>
          <button onClick={exportCsv}
            className="px-3 py-1 bg-emerald-600 text-white rounded hover:bg-emerald-700">
            📥 CSV ({filteredRows.length}개)
          </button>
        </div>
      </div>

      <div className="px-4 py-2 bg-gradient-to-r from-blue-50 to-emerald-50 border-b flex gap-5 text-xs">
        <span>표시 {filteredRows.length} / 전체 {rows.length}</span>
        <span>양호 이상: <b className="text-emerald-700">{totals.okCount}개</b></span>
        <span>평균 마진: <b>{fmt.pct(totals.avgMargin)}</b></span>
        <span>합계 순이익: <b className={totals.totalProfit >= 0 ? 'text-emerald-700' : 'text-red-600'}>{fmt.krw(totals.totalProfit)}원</b></span>
      </div>

      <div style={{ height: 600, width: '100%' }}>
        <AgGridReact
          ref={gridRef}
          theme={myTheme}
          rowData={rowsWithExpansion}
          columnDefs={columnDefs}
          defaultColDef={defaultColDef}
          rowSelection="multiple"
          suppressRowClickSelection={true}
          stopEditingWhenCellsLoseFocus={true}
          onCellValueChanged={onCellValueChanged}
          onColumnResized={onColumnResized}
          onColumnMoved={onColumnMoved}
          onColumnVisible={onColumnVisible}
          onGridReady={onGridReady}
          animateRows={false}
          getRowId={(p: any) => String(p.data.id)}
          isFullWidthRow={(p: any) => !!p.rowNode?.data?.__expansion}
          fullWidthCellRenderer={(p: any) => {
            const parent = rows.find(r => r.id === p.data?.__parentId);
            if (!parent) return null;
            return (
              <div style={{ padding: 8, background: '#f9fafb' }}>
                <CompositionsPanel
                  row={parent}
                  onChange={(comps) => updateCompositions(parent.id, comps)}
                  onClose={() => setCompositionRowId(null)}
                />
              </div>
            );
          }}
          getRowHeight={(p: any) => {
            if (p.data?.__expansion) {
              const parent = rows.find(r => r.id === p.data?.__parentId);
              const n = parent?.compositions?.length || 0;
              return Math.min(600, 180 + n * 40);
            }
            return 30;
          }}
          isRowSelectable={(p: any) => !p.data?.__expansion}
        />
      </div>

      {zoomImg && <ImageZoomModal src={zoomImg} onClose={() => setZoomImg(null)} />}
      {qoo10ExportOpen && (
        <Qoo10ExportModal rows={qoo10ExportRows} onClose={() => setQoo10ExportOpen(false)} />
      )}
      {detailRow && (
        <SheetRowDetailPanel
          row={detailRow}
          onClose={onCloseDetailPanel}
          onSave={(patch) => {
            // setRows 호출 → 상위 컴포넌트가 cloudSync 자동 push (useEffect)
            const next = rows.map(r => r.id === detailRow.id ? { ...r, ...patch } : r);
            saveSheet(next);
            setRows(next);
          }}
          onReject={() => {
            const next = rows.map(r => r.id === detailRow.id ? { ...r, match_decision: 'rejected' as const } : r);
            saveSheet(next);
            setRows(next);
          }}
        />
      )}
    </div>
  );
}

// ─── 큐텐 엑셀 내보내기 모달 ─────────────────────────
interface Qoo10ExportDefaults {
  category_number: string;
  brand_number: string;
  shipping_number: string;
  end_date: string;
  quantity: number;
  available_shipping_date: number;
  item_condition_type: string;
  origin_type: string;
  origin_country_id: string;
  item_status: string;
  under18s_display: string;
  default_description: string;
}

const DEFAULT_QOO10_EXPORT: Qoo10ExportDefaults = {
  category_number: '',
  brand_number: '',
  shipping_number: '',
  end_date: '',
  quantity: 100,
  available_shipping_date: 7,
  item_condition_type: '1',
  origin_type: '2',
  origin_country_id: 'KR',
  item_status: 'Y',
  under18s_display: 'N',
  default_description: '',
};
const QOO10_EXPORT_KEY = 'qoo10ExportDefaults.v1';

function Qoo10ExportModal({
  rows, onClose,
}: { rows: SheetRow[]; onClose: () => void }) {
  const [defaults, setDefaults] = useState<Qoo10ExportDefaults>(() => {
    try {
      const raw = localStorage.getItem(QOO10_EXPORT_KEY);
      return raw ? { ...DEFAULT_QOO10_EXPORT, ...JSON.parse(raw) } : DEFAULT_QOO10_EXPORT;
    } catch { return DEFAULT_QOO10_EXPORT; }
  });
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    try { localStorage.setItem(QOO10_EXPORT_KEY, JSON.stringify(defaults)); } catch { /* */ }
  }, [defaults]);

  const upd = <K extends keyof Qoo10ExportDefaults>(k: K, v: Qoo10ExportDefaults[K]) =>
    setDefaults(d => ({ ...d, [k]: v }));

  const doExport = async () => {
    if (!defaults.category_number) {
      if (!confirm('카테고리 코드가 비어있습니다. 카테고리 없이 내보내면 큐텐 업로드 시 에러가 납니다. 계속 진행?')) return;
    }
    setLoading(true); setErr(null);
    try {
      const payload = {
        rows: rows.map(r => ({
          product_name: r.product_name || '',
          product_name_ko: r.product_name_ko || '',
          sell_price_jpy: r.sell_price_jpy || 0,
          cover_image_url: r.cover_image_url || '',
          weight_g: r.weight_g || 0,
          notes: r.notes || '',
          source: r.source || '',
          search_keyword: '',
        })),
        defaults,
      };
      const res = await api.post('/products/export-qoo10', payload, { responseType: 'blob' });
      const blob = res.data;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const ts = new Date().toISOString().slice(0, 10);
      a.download = `Qoo10_EditItemList_${ts}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
      onClose();
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || '실패');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="px-5 py-4 border-b flex justify-between items-center sticky top-0 bg-white">
          <h3 className="text-lg font-bold">📤 큐텐 대량등록 양식 내보내기</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl">✕</button>
        </div>
        <div className="px-5 py-4 space-y-4">
          <div className="bg-blue-50 border-l-4 border-blue-400 text-xs p-3 rounded">
            📋 <b>{rows.length}개 상품</b>을 Qoo10_EditItemList.xlsx 양식에 자동 채워서 다운로드합니다.
            아래 공통 기본값을 설정하세요.
          </div>

          <div>
            <h4 className="font-semibold text-sm mb-2">🔑 필수 입력 (큐텐 업로드 필수)</h4>
            <div className="grid grid-cols-2 gap-3 text-xs">
              <label>
                <div className="text-gray-600 mb-0.5">카테고리 코드 <span className="text-red-500">*</span></div>
                <input value={defaults.category_number}
                  onChange={e => upd('category_number', e.target.value)}
                  placeholder="예: 320001873"
                  className="w-full border rounded px-2 py-1.5" />
              </label>
              <label>
                <div className="text-gray-600 mb-0.5">브랜드 코드</div>
                <input value={defaults.brand_number}
                  onChange={e => upd('brand_number', e.target.value)}
                  placeholder="예: 27450"
                  className="w-full border rounded px-2 py-1.5" />
              </label>
              <label>
                <div className="text-gray-600 mb-0.5">배송비 코드 <span className="text-red-500">*</span></div>
                <input value={defaults.shipping_number}
                  onChange={e => upd('shipping_number', e.target.value)}
                  placeholder="0 = 무료, 123456 = 코드"
                  className="w-full border rounded px-2 py-1.5" />
              </label>
              <label>
                <div className="text-gray-600 mb-0.5">판매 종료일</div>
                <input type="date" value={defaults.end_date}
                  onChange={e => upd('end_date', e.target.value)}
                  className="w-full border rounded px-2 py-1.5" />
              </label>
            </div>
          </div>

          <div>
            <h4 className="font-semibold text-sm mb-2">📦 기본값</h4>
            <div className="grid grid-cols-3 gap-3 text-xs">
              <label>
                <div className="text-gray-600 mb-0.5">재고 수량</div>
                <input type="number" value={defaults.quantity}
                  onChange={e => upd('quantity', +e.target.value)}
                  className="w-full border rounded px-2 py-1.5" />
              </label>
              <label>
                <div className="text-gray-600 mb-0.5">발송가능일(일)</div>
                <input type="number" value={defaults.available_shipping_date}
                  onChange={e => upd('available_shipping_date', +e.target.value)}
                  className="w-full border rounded px-2 py-1.5" />
              </label>
              <label>
                <div className="text-gray-600 mb-0.5">판매 상태</div>
                <select value={defaults.item_status}
                  onChange={e => upd('item_status', e.target.value)}
                  className="w-full border rounded px-2 py-1.5">
                  <option value="Y">판매중</option>
                  <option value="N">판매중지</option>
                </select>
              </label>
              <label>
                <div className="text-gray-600 mb-0.5">상품 상태</div>
                <select value={defaults.item_condition_type}
                  onChange={e => upd('item_condition_type', e.target.value)}
                  className="w-full border rounded px-2 py-1.5">
                  <option value="1">새상품</option>
                  <option value="2">중고-미사용</option>
                  <option value="3">중고-리퍼</option>
                  <option value="4">중고-거의새것</option>
                  <option value="5">중고-사용감</option>
                </select>
              </label>
              <label>
                <div className="text-gray-600 mb-0.5">원산지 유형</div>
                <select value={defaults.origin_type}
                  onChange={e => upd('origin_type', e.target.value)}
                  className="w-full border rounded px-2 py-1.5">
                  <option value="1">국내(일본)</option>
                  <option value="2">해외</option>
                  <option value="3">기타</option>
                </select>
              </label>
              {defaults.origin_type === '2' && (
                <label>
                  <div className="text-gray-600 mb-0.5">원산지 국가 (2글자)</div>
                  <input value={defaults.origin_country_id}
                    onChange={e => upd('origin_country_id', e.target.value.toUpperCase())}
                    placeholder="KR / CN / US"
                    className="w-full border rounded px-2 py-1.5" />
                </label>
              )}
              <label>
                <div className="text-gray-600 mb-0.5">18세 제한</div>
                <select value={defaults.under18s_display}
                  onChange={e => upd('under18s_display', e.target.value)}
                  className="w-full border rounded px-2 py-1.5">
                  <option value="N">제한없음</option>
                  <option value="Y">제한</option>
                </select>
              </label>
            </div>
          </div>

          <label className="block text-xs">
            <div className="text-gray-600 mb-0.5">기본 상품 상세 (HTML, 메모 없는 상품에 적용)</div>
            <textarea rows={3} value={defaults.default_description}
              onChange={e => upd('default_description', e.target.value)}
              placeholder="<p>韓国直送の高品質製品</p>"
              className="w-full border rounded px-2 py-1.5 font-mono text-[11px]" />
          </label>

          <div className="bg-amber-50 border-l-4 border-amber-400 text-[11px] p-2 rounded">
            💡 템플릿 5행부터 상품 데이터로 채워집니다. 상세 튜닝은 다운로드 후 엑셀에서 수정하세요.
            카테고리·배송 코드는 큐텐 셀러센터에서 확인.
          </div>

          {err && <div className="bg-red-50 text-red-700 text-xs p-2 rounded">{err}</div>}
        </div>
        <div className="px-5 py-3 border-t bg-gray-50 flex justify-end gap-2 sticky bottom-0">
          <button onClick={onClose} className="px-3 py-1.5 bg-gray-200 text-xs rounded hover:bg-gray-300">취소</button>
          <button onClick={doExport} disabled={loading}
            className="px-4 py-1.5 bg-emerald-600 text-white text-xs rounded hover:bg-emerald-700 disabled:opacity-50">
            {loading ? '생성 중...' : `📥 다운로드 (${rows.length}개 상품)`}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── 자동 소싱 섹션 (키워드→큐텐 상품 자동 시트) ─────
const AUTO_SOURCING_KEY = 'autoSourcingParams.v1';

const DEFAULT_AUTO_PARAMS: AutoSourcingParams = {
  mode: 'auto',
  min_search_volume: 300,
  min_kr_ratio: 0.10,
  max_kr_ratio: 0.70,
  min_competition: 0.5,
  max_competition: 20.0,
  brand_filter: 'general',
  keywords_limit: 20,
  products_per_keyword: 5,
  categories: [],
};

function loadAutoParams(): AutoSourcingParams {
  try {
    const raw = localStorage.getItem(AUTO_SOURCING_KEY);
    return raw ? { ...DEFAULT_AUTO_PARAMS, ...JSON.parse(raw) } : DEFAULT_AUTO_PARAMS;
  } catch {
    return DEFAULT_AUTO_PARAMS;
  }
}
function saveAutoParams(p: AutoSourcingParams) {
  try { localStorage.setItem(AUTO_SOURCING_KEY, JSON.stringify(p)); } catch { /* ignore */ }
}

interface ScoredKeyword {
  keyword_jp: string;
  score: number;
  search_volume: number;
  kr_ratio: number;
  competition_intensity: number;
}

function AutoSourcingBlock({ onAddRows, interestKeywords }: { onAddRows: (rows: SheetRow[]) => void; interestKeywords: string[] }) {
  const [params, setParams] = useState<AutoSourcingParams>(() => loadAutoParams());
  const [previewCount, setPreviewCount] = useState<number | null>(null);
  const [previewKws, setPreviewKws] = useState<string[]>([]);
  const [previewScored, setPreviewScored] = useState<ScoredKeyword[]>([]);
  const [previewTotal, setPreviewTotal] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<CollectProgress | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [availableCategories, setAvailableCategories] = useState<{ category: string; count: number }[]>([]);
  const pollRef = useRef<number | null>(null);

  useEffect(() => { saveAutoParams(params); }, [params]);
  useEffect(() => {
    listKeywordCategories().then(r => setAvailableCategories(r.data)).catch(() => {});
  }, []);

  const toggleCategory = (cat: string) => {
    const cur = params.categories || [];
    const next = cur.includes(cat) ? cur.filter(c => c !== cat) : [...cur, cat];
    setParams(p => ({ ...p, categories: next }));
  };

  const update = <K extends keyof AutoSourcingParams>(k: K, v: AutoSourcingParams[K]) =>
    setParams(p => ({ ...p, [k]: v }));

  const stopPolling = () => {
    if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; }
  };
  useEffect(() => () => stopPolling(), []);

  const doPreview = async () => {
    setErr(null);
    try {
      const body = params.mode === 'interest'
        ? { ...params, interest_keywords: interestKeywords }
        : params;
      const { data } = await previewAutoSourcing(body);
      setPreviewCount(data.count);
      setPreviewKws(data.selected_keywords || []);
      setPreviewScored(data.scored || []);
      setPreviewTotal(typeof data.total_candidates === 'number' ? data.total_candidates : null);
    } catch (e: any) {
      setErr(e?.message || '미리보기 실패');
    }
  };

  const run = async () => {
    setErr(null); setProgress(null); setPreviewCount(null);
    setRunning(true);
    try {
      const body = params.mode === 'interest'
        ? { ...params, interest_keywords: interestKeywords }
        : params;
      const { data } = await runAutoSourcing(body);
      if (data.error) { setErr(data.error); setRunning(false); return; }

      const selected = data.selected_keywords as string[];
      const taskId = data.task_id;
      setProgress({
        task_id: taskId, name: `자동 소싱 (${selected.length}개 키워드)`,
        status: 'running', progress: 0, total: selected.length, message: '시작...',
      });

      // 진행률 폴링
      pollRef.current = window.setInterval(async () => {
        try {
          const { data: t } = await api.get(`/tasks/${taskId}`);
          if (!t) return;
          setProgress(t);
          if (t.status === 'completed' || t.status === 'failed') {
            stopPolling();
            if (t.status === 'completed') {
              // 결과 조회 + 시트 추가
              await fetchAndAddToSheet(selected);
            }
            setRunning(false);
          }
        } catch { /* ignore */ }
      }, 2000);
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || '실패');
      setRunning(false);
    }
  };

  const fetchAndAddToSheet = async (selected: string[]) => {
    try {
      const { data } = await fetchQoo10ProductsByKeywords(selected, params.products_per_keyword);
      const results = data.results as Record<string, any[]>;

      // 모든 상품 flat화 + 상품명 중복 제거
      const allProducts: Array<{ kw: string; p: any }> = [];
      for (const kw of selected) {
        for (const p of results[kw] || []) {
          allProducts.push({ kw, p });
        }
      }
      if (allProducts.length === 0) {
        alert('수집된 상품이 없습니다.');
        return;
      }

      // 일괄 번역
      let translations: string[] = [];
      try {
        const { data: td } = await api.post('/utils/translate-batch', {
          texts: allProducts.map(x => x.p.product_name),
          source: 'ja', target: 'ko',
        });
        translations = td.translations || [];
      } catch {
        translations = allProducts.map(() => '');
      }

      const rows = allProducts.map((x, i) => newSheetRow({
        product_name: x.p.product_name,
        product_name_ko: translations[i] || '',
        product_url: x.p.product_url,
        cover_image_url: x.p.cover_image_url,
        competitor_price_jpy: x.p.price_jpy || 0,
        sell_price_jpy: x.p.price_jpy || 0,
        source: `자동:${x.kw}`,
      }));
      onAddRows(rows);
    } catch (e: any) {
      alert('시트 추가 실패: ' + (e?.message || ''));
    }
  };

  return (
    <div className="bg-white rounded-lg shadow p-5 mb-5">
      <h3 className="font-semibold mb-3">⚡ 자동 소싱 후보 (키워드 → 큐텐 상위 상품)</h3>

      <div className="flex items-center gap-3 mb-3 text-sm">
        <span className="text-gray-600">모드:</span>
        <label className="flex items-center gap-1">
          <input type="radio" checked={params.mode === 'auto'} onChange={() => update('mode', 'auto')} />
          자동 선별 (점수 상위)
        </label>
        <label className="flex items-center gap-1">
          <input type="radio" checked={params.mode === 'interest'} onChange={() => update('mode', 'interest')} />
          관심 키워드만 ({interestKeywords.length}개)
        </label>
      </div>

      {params.mode === 'auto' && (
        <div className="mb-3 bg-indigo-50 border-l-4 border-indigo-400 rounded px-3 py-2 text-xs flex items-center flex-wrap gap-x-4 gap-y-1">
          <span className="font-semibold text-indigo-800">현재 기준</span>
          <span>검색량 ≥ <b className="text-indigo-700">{params.min_search_volume.toLocaleString()}</b></span>
          <span>한국비율 <b className="text-indigo-700">{Math.round(params.min_kr_ratio * 100)}%~{Math.round(params.max_kr_ratio * 100)}%</b></span>
          <span>경쟁강도 <b className="text-indigo-700">{params.min_competition}~{params.max_competition}</b></span>
          <span>브랜드 <b className="text-indigo-700">{params.brand_filter === 'all' ? '전체' : params.brand_filter === 'general' ? '일반만' : '브랜드만'}</b></span>
          <span className="ml-auto text-gray-500">상위 <b className="text-indigo-700">{params.keywords_limit}</b>개 × 상품 <b className="text-indigo-700">{params.products_per_keyword}</b></span>
        </div>
      )}

      {params.mode === 'auto' && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs mb-3 bg-gray-50 p-3 rounded">
          <label>
            <div className="text-gray-600 mb-0.5">최소 검색수(주)</div>
            <input type="number" value={params.min_search_volume}
              onChange={e => update('min_search_volume', +e.target.value)}
              className="w-full border rounded px-2 py-1" />
          </label>
          <label>
            <div className="text-gray-600 mb-0.5">한국비율 (%)</div>
            <div className="flex gap-1 items-center">
              <input type="number" min={0} max={100} value={Math.round(params.min_kr_ratio * 100)}
                onChange={e => update('min_kr_ratio', +e.target.value / 100)}
                className="w-full border rounded px-2 py-1" />
              <span>~</span>
              <input type="number" min={0} max={100} value={Math.round(params.max_kr_ratio * 100)}
                onChange={e => update('max_kr_ratio', +e.target.value / 100)}
                className="w-full border rounded px-2 py-1" />
            </div>
          </label>
          <label>
            <div className="text-gray-600 mb-0.5">경쟁강도 하한</div>
            <input type="number" step="0.1" value={params.min_competition}
              onChange={e => update('min_competition', +e.target.value)}
              className="w-full border rounded px-2 py-1" />
          </label>
          <label>
            <div className="text-gray-600 mb-0.5">경쟁강도 상한</div>
            <input type="number" step="0.1" value={params.max_competition}
              onChange={e => update('max_competition', +e.target.value)}
              className="w-full border rounded px-2 py-1" />
          </label>
          <label>
            <div className="text-gray-600 mb-0.5">브랜드 필터</div>
            <select value={params.brand_filter}
              onChange={e => update('brand_filter', e.target.value as any)}
              className="w-full border rounded px-2 py-1">
              <option value="all">전체</option>
              <option value="general">일반만</option>
              <option value="brand">브랜드만</option>
            </select>
          </label>
          <label>
            <div className="text-gray-600 mb-0.5">대상 키워드 수</div>
            <input type="number" min={1} max={100} value={params.keywords_limit}
              onChange={e => update('keywords_limit', +e.target.value)}
              className="w-full border rounded px-2 py-1" />
          </label>
          <label>
            <div className="text-gray-600 mb-0.5">키워드당 상품수</div>
            <input type="number" min={1} max={30} value={params.products_per_keyword}
              onChange={e => update('products_per_keyword', +e.target.value)}
              className="w-full border rounded px-2 py-1" />
          </label>
          <div className="col-span-2 md:col-span-4 text-[11px] text-gray-500">
            💡 <b>키워드당 상품수</b> = 키워드 하나에서 큐텐 상위 몇 개를 시트에 추가할지.
            예: 키워드 20개 × 상품 5 = 최대 100행
          </div>
          <div className="col-span-2 md:col-span-4">
            <div className="text-gray-600 mb-1 flex items-center justify-between">
              <span>카테고리 <span className="text-gray-400">(비우면 전체)</span></span>
              <div className="flex gap-1">
                <button type="button" onClick={() => setParams(p => ({ ...p, categories: [] }))}
                  className="text-[10px] text-blue-600 hover:underline">전체 해제</button>
                <button type="button" onClick={() => setParams(p => ({ ...p, categories: availableCategories.map(c => c.category) }))}
                  className="text-[10px] text-blue-600 hover:underline">전체 선택</button>
              </div>
            </div>
            <div className="flex flex-wrap gap-1">
              {availableCategories.map(c => {
                const selected = (params.categories || []).includes(c.category);
                return (
                  <button type="button" key={c.category}
                    onClick={() => toggleCategory(c.category)}
                    className={`px-2 py-0.5 rounded border text-[11px] ${
                      selected
                        ? 'bg-blue-600 text-white border-blue-600'
                        : 'bg-white border-gray-300 hover:bg-gray-50'
                    }`}
                  >{c.category} <span className="opacity-60">({c.count})</span></button>
                );
              })}
            </div>
          </div>
        </div>
      )}

      <div className="flex gap-2 items-center flex-wrap">
        <button onClick={doPreview} disabled={running}
          className="px-3 py-1.5 bg-gray-200 text-gray-800 text-xs rounded hover:bg-gray-300 disabled:opacity-50">
          👁 선정 미리보기
        </button>
        <button onClick={run} disabled={running}
          className="px-4 py-1.5 bg-purple-600 text-white text-sm rounded hover:bg-purple-700 disabled:opacity-50">
          {running ? '실행 중...' : '▶ 자동 소싱 실행'}
        </button>
        <span className="text-xs text-gray-500">
          예상 소요: {params.keywords_limit}개 × 약 10초 = {Math.round(params.keywords_limit * 10 / 60)}분
        </span>
      </div>

      {previewCount !== null && (
        <div className="mt-3 bg-blue-50 border-l-4 border-blue-400 text-xs p-3 rounded">
          <div className="flex items-baseline gap-3 mb-2">
            <b>선정된 키워드: {previewCount}개</b>
            {previewTotal !== null && previewTotal !== previewCount && (
              <span className="text-gray-500">필터 통과 총 {previewTotal}개 중 상위 {params.keywords_limit}</span>
            )}
          </div>
          {previewScored.length > 0 ? (
            <div className="overflow-x-auto bg-white border rounded">
              <table className="w-full text-[11px]">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="border-b px-2 py-1 text-left">#</th>
                    <th className="border-b px-2 py-1 text-left">키워드</th>
                    <th className="border-b px-2 py-1 text-right">추천점수</th>
                    <th className="border-b px-2 py-1 text-right">검색수(주)</th>
                    <th className="border-b px-2 py-1 text-right">한국비율</th>
                    <th className="border-b px-2 py-1 text-right">경쟁강도</th>
                  </tr>
                </thead>
                <tbody>
                  {previewScored.map((s, i) => (
                    <tr key={s.keyword_jp} className="hover:bg-blue-50">
                      <td className="border-b px-2 py-0.5 text-gray-500">{i + 1}</td>
                      <td className="border-b px-2 py-0.5">
                        <a href={`https://www.qoo10.jp/s/?keyword=${s.keyword_jp}`} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">{s.keyword_jp}</a>
                      </td>
                      <td className="border-b px-2 py-0.5 text-right font-semibold text-cyan-700">{s.score.toFixed(2)}</td>
                      <td className="border-b px-2 py-0.5 text-right">{s.search_volume.toLocaleString()}</td>
                      <td className="border-b px-2 py-0.5 text-right">{(s.kr_ratio * 100).toFixed(1)}%</td>
                      <td className="border-b px-2 py-0.5 text-right">{s.competition_intensity.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : previewKws.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {previewKws.map(kw => (
                <span key={kw} className="px-1.5 py-0.5 bg-white border rounded">{kw}</span>
              ))}
            </div>
          )}
        </div>
      )}

      {progress && (
        <div className="mt-3 bg-blue-50 border border-blue-200 rounded p-3">
          <div className="flex items-center justify-between mb-1.5 text-xs">
            <div className="flex items-center gap-2">
              <span className={`inline-block w-2 h-2 rounded-full ${
                progress.status === 'running' ? 'bg-blue-500 animate-pulse' :
                progress.status === 'completed' ? 'bg-green-500' :
                progress.status === 'failed' ? 'bg-red-500' : 'bg-gray-400'
              }`} />
              <b>{progress.name}</b>
              <span className="text-gray-500">({progress.progress}/{progress.total || '-'})</span>
            </div>
            <span className={
              progress.status === 'completed' ? 'text-green-700 font-semibold' :
              progress.status === 'failed' ? 'text-red-700 font-semibold' :
              'text-blue-700'
            }>
              {progress.status === 'running' ? '진행 중' :
               progress.status === 'completed' ? '✅ 완료' :
               progress.status === 'failed' ? '❌ 실패' : progress.status}
            </span>
          </div>
          <div className="w-full h-2 bg-blue-100 rounded overflow-hidden">
            <div className={`h-full transition-all ${
              progress.status === 'failed' ? 'bg-red-500' :
              progress.status === 'completed' ? 'bg-green-500' : 'bg-blue-500'
            }`}
              style={{ width: `${progress.total > 0 ? (progress.progress / progress.total) * 100 : 0}%` }} />
          </div>
          {progress.message && (
            <div className="mt-1.5 text-[11px] text-gray-600 truncate">{progress.message}</div>
          )}
        </div>
      )}

      {err && <div className="mt-3 bg-red-50 text-red-700 text-xs p-2 rounded">{err}</div>}
    </div>
  );
}


interface CollectProgress {
  task_id: string;
  name: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  total: number;
  message: string;
}

// ─── 관심 키워드 리포트 섹션 (간소화) ────────────────
function InterestKeywordBlock({ onAddRows }: { onAddRows: (rows: SheetRow[]) => void }) {
  const [items, setItems] = useState<InterestKeyword[]>(() => getInterestKeywords());
  const [loading, setLoading] = useState(false);
  const [collecting, setCollecting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [progress, setProgress] = useState<CollectProgress | null>(null);
  const pollRef = useRef<number | null>(null);

  const refresh = () => setItems(getInterestKeywords());

  const stopPolling = () => {
    if (pollRef.current) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const startPolling = (taskId: string) => {
    stopPolling();
    pollRef.current = window.setInterval(async () => {
      try {
        const { data } = await api.get(`/tasks/${taskId}`);
        if (data?.error) { stopPolling(); return; }
        setProgress(data);
        if (data.status === 'completed' || data.status === 'failed') {
          stopPolling();
        }
      } catch {
        /* ignore transient */
      }
    }, 1500);
  };

  useEffect(() => () => stopPolling(), []);

  const collect = async () => {
    if (items.length === 0) return;
    setCollecting(true); setErr(null); setProgress(null);
    try {
      const { data } = await collectRecommendations(items.map(i => i.keyword_jp));
      if (data.error) { setErr(data.error); return; }
      if (data.task_id) {
        setProgress({
          task_id: data.task_id, name: '상품 수집 시작...',
          status: 'running', progress: 0, total: data.total_steps || 0, message: '',
        });
        startPolling(data.task_id);
      }
    } catch (e: any) {
      setErr(e?.message || '수집 실패');
    } finally {
      setCollecting(false);
    }
  };

  const report = async () => {
    if (items.length === 0) return;
    setLoading(true); setErr(null);
    try {
      const { data } = await getRecommendationReport(items.map(i => i.keyword_jp));
      const filtered = (data.items || [])
        .filter((it: any) => it.cheapest_domestic && it.qoo10_stats.avg_jpy > 0);

      // 옵션 단위 행 펼치기 — 한 큐텐 키워드 + 한국 상품 옵션 N개 → N행
      // (api_only 모드에서는 default 옵션 1개라 1행, 추후 옵션 N개 들어오면 N행 자동)
      const rows = filtered.flatMap((it: any) => {
        const cd = it.cheapest_domestic;
        const opts = (cd.options && cd.options.length > 0)
          ? cd.options
          : [{ name: 'default', price_krw: cd.price_krw, in_stock: true }];
        const matchTag = cd.match_source === 'matched' ? '★ ' : '';
        return opts.map((o: any) => newSheetRow({
          product_name: matchTag + cd.product_name + (o.name !== 'default' ? ` [${o.name}]` : ''),
          product_name_ko: cd.product_name + (o.name !== 'default' ? ` [${o.name}]` : ''),
          product_url: cd.product_url,
          competitor_price_jpy: Math.round(it.qoo10_stats.avg_jpy),
          sell_price_jpy: Math.round(it.qoo10_stats.avg_jpy),
          item_price_krw: o.price_krw || cd.price_krw,
          source: `관심:${it.keyword_kr || it.keyword_jp}` + (o.name !== 'default' ? ` / ${o.name}` : ''),
        }));
      });
      onAddRows(rows);
      alert(`${rows.length}개 행이 시트에 추가되었습니다.`);
    } catch (e: any) {
      setErr(e?.message || '리포트 실패');
    } finally {
      setLoading(false);
    }
  };

  const clearAll = () => {
    if (!confirm('관심 키워드를 모두 비우시겠습니까?')) return;
    clearInterestKeywords();
    refresh();
  };
  const remove = (jp: string) => { removeInterestKeyword(jp); refresh(); };

  return (
    <div className="bg-white rounded-lg shadow p-5 mb-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold">⭐ 관심 키워드 ({items.length}개)</h3>
        <div className="flex gap-2">
          <button onClick={collect} disabled={items.length === 0 || collecting}
            className="px-3 py-1.5 bg-emerald-600 text-white text-xs rounded hover:bg-emerald-700 disabled:opacity-50">
            {collecting ? '수집 중...' : '🛒 상품 수집'}
          </button>
          <button onClick={report} disabled={items.length === 0 || loading}
            className="px-3 py-1.5 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 disabled:opacity-50">
            {loading ? '생성 중...' : '📊 시트에 추가'}
          </button>
          {items.length > 0 && (
            <button onClick={clearAll} className="px-2 py-1.5 text-xs text-red-600 hover:bg-red-50 rounded">비우기</button>
          )}
        </div>
      </div>
      <div className="text-xs text-gray-500 mb-2">
        역직구 추천에서 키워드 선택 → <b>상품 수집</b> 수 분 대기 → <b>시트에 추가</b>로 국내최저가+큐텐평균가 기반 행 생성
      </div>
      {items.length === 0 ? (
        <div className="text-gray-400 text-xs py-3 text-center">
          <Link to="/recommend" className="text-blue-600 underline">역직구 추천</Link>에서 키워드를 선택하세요.
        </div>
      ) : (
        <div className="flex flex-wrap gap-1">
          {items.map(i => (
            <span key={i.keyword_jp} className="inline-flex items-center gap-1 bg-gray-100 px-2 py-0.5 rounded text-xs">
              {i.keyword_jp}
              {i.keyword_kr && <span className="text-gray-400">/{i.keyword_kr}</span>}
              <button onClick={() => remove(i.keyword_jp)} className="text-red-500 hover:text-red-700 font-bold">×</button>
            </span>
          ))}
        </div>
      )}
      {progress && (
        <div className="mt-3 bg-blue-50 border border-blue-200 rounded p-3">
          <div className="flex items-center justify-between mb-1.5 text-xs">
            <div className="flex items-center gap-2">
              <span className={`inline-block w-2 h-2 rounded-full ${
                progress.status === 'running' ? 'bg-blue-500 animate-pulse' :
                progress.status === 'completed' ? 'bg-green-500' :
                progress.status === 'failed' ? 'bg-red-500' : 'bg-gray-400'
              }`} />
              <b>{progress.name}</b>
              <span className="text-gray-500">
                ({progress.progress}/{progress.total || '-'})
              </span>
            </div>
            <span className={
              progress.status === 'completed' ? 'text-green-700 font-semibold' :
              progress.status === 'failed' ? 'text-red-700 font-semibold' :
              'text-blue-700'
            }>
              {progress.status === 'running' ? '진행 중' :
               progress.status === 'completed' ? '✅ 완료' :
               progress.status === 'failed' ? '❌ 실패' : progress.status}
            </span>
          </div>
          <div className="w-full h-2 bg-blue-100 rounded overflow-hidden">
            <div
              className={`h-full transition-all duration-300 ${
                progress.status === 'failed' ? 'bg-red-500' :
                progress.status === 'completed' ? 'bg-green-500' : 'bg-blue-500'
              }`}
              style={{ width: `${progress.total > 0 ? (progress.progress / progress.total) * 100 : 0}%` }}
            />
          </div>
          {progress.message && (
            <div className="mt-1.5 text-[11px] text-gray-600 truncate">{progress.message}</div>
          )}
        </div>
      )}
      {err && <div className="mt-2 bg-red-50 text-red-700 text-xs p-2 rounded">{err}</div>}
    </div>
  );
}

// ─── 로그인 상태 배너 ────────────────────────────────
function LoginBanner() {
  const [status, setStatus] = useState<{ logged_in: boolean; browser_active: boolean } | null>(null);

  useEffect(() => {
    const check = () => getLoginStatus().then(r => setStatus(r.data)).catch(() => {});
    check();
    const id = window.setInterval(check, 10000);
    return () => window.clearInterval(id);
  }, []);

  if (!status) return null;
  if (status.logged_in) {
    return (
      <div className="bg-emerald-50 border-l-4 border-emerald-500 text-xs p-2 mb-4 rounded flex items-center gap-2">
        <span className="w-2 h-2 bg-emerald-500 rounded-full" />
        <span>큐텐 로그인 완료 — 상품 수집 사용 가능</span>
      </div>
    );
  }
  return (
    <div className="bg-red-50 border-l-4 border-red-500 text-sm p-3 mb-4 rounded">
      <div className="flex items-center justify-between">
        <div>
          <b className="text-red-700">⚠️ 큐텐 로그인이 필요합니다</b>
          <div className="text-xs text-gray-700 mt-0.5">
            로그인 없이는 샵 벤치마크·상품 수집이 작동하지 않습니다 (결과 0개 또는 에러).
          </div>
        </div>
        <a href="/auth" className="px-3 py-1.5 bg-red-600 text-white text-xs rounded hover:bg-red-700">
          🔑 로그인 페이지로 이동
        </a>
      </div>
    </div>
  );
}

// ─── 메인 페이지 ─────────────────────────────────────
export default function RecommendProductsPage() {
  const [rows, setRows] = useState<SheetRow[]>(() => loadSheet());
  const [cloudStatus, setCloudStatus] = useState<'idle' | 'syncing' | 'synced' | 'error'>('idle');
  const pusherRef = useRef(makeDebouncedPusher<SheetRow[]>('product_sheet', 1500));

  // 페이지 마운트 시 DB에서 최신 시트·관심키워드·샵캐시 가져오기
  useEffect(() => {
    (async () => {
      setCloudStatus('syncing');
      const [sheet, interest, shop] = await Promise.all([
        fetchCloud<SheetRow[]>('product_sheet'),
        fetchCloud<any[]>('interest_keywords'),
        fetchCloud<any[]>('shop_cache'),
      ]);
      if (sheet.data && Array.isArray(sheet.data)) {
        setRows(sheet.data);
        saveSheet(sheet.data);
      }
      if (interest.data && Array.isArray(interest.data)) {
        localStorage.setItem('interestKeywords.v1', JSON.stringify(interest.data));
      }
      if (shop.data && Array.isArray(shop.data)) {
        localStorage.setItem('shopBenchmarkCache.v1', JSON.stringify(shop.data));
      }
      setCloudStatus('synced');
    })();
  }, []);

  // rows 변경 시 localStorage 즉시 + cloud debounce push
  useEffect(() => {
    saveSheet(rows);
    pusherRef.current.push(rows);
    setCloudStatus('syncing');
    const t = window.setTimeout(() => setCloudStatus('synced'), 1800);
    return () => window.clearTimeout(t);
  }, [rows]);

  // 페이지 떠날 때 flush
  useEffect(() => {
    const handler = () => { pusherRef.current.flush(); };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, []);

  const addRows = (newRows: SheetRow[]) => {
    // 중복 키: 상품명 + 가격. 리뷰수는 변동 가능하므로 제외.
    // 가격은 competitor_price_jpy(스크래핑값) 우선, 없으면 sell_price_jpy.
    const rowKey = (r: SheetRow) => {
      const price = r.competitor_price_jpy || r.sell_price_jpy || 0;
      return `${(r.product_name || '').trim()}|${price}`;
    };
    const keys = new Set(rows.map(rowKey));
    const deduped: SheetRow[] = [];
    for (const r of newRows) {
      const k = rowKey(r);
      if (keys.has(k)) continue;
      keys.add(k);  // 신규 행 간 중복도 제거
      deduped.push(r);
    }
    const skipped = newRows.length - deduped.length;
    const combined = [...rows, ...deduped];
    setRows(combined);
    if (deduped.length > 0) {
      alert(`${deduped.length}개 추가 완료${skipped > 0 ? ` (중복 ${skipped}개 스킵)` : ''}`);
    } else if (skipped > 0) {
      alert(`모두 중복 상품입니다. ${skipped}개 스킵.`);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-2xl font-bold">📊 상품 추천 시트</h2>
        <div className="flex items-center gap-3 text-xs">
          <a
            href={`/api/recommend/auto-collected/${new Date().toISOString().slice(0, 10)}`}
            target="_blank"
            rel="noreferrer"
            className="px-3 py-1.5 bg-indigo-600 text-white rounded hover:bg-indigo-700 text-xs font-semibold"
            title="야간 자동화 결과 — 새 탭"
          >
            🌙 오늘 자동 결과
          </a>
          {cloudStatus === 'syncing' && <span className="text-blue-600">☁ 동기화 중...</span>}
          {cloudStatus === 'synced' && <span className="text-emerald-600">☁ 클라우드 저장됨 (다른 PC에서 접속 가능)</span>}
          {cloudStatus === 'error' && <span className="text-red-600">☁ 동기화 실패 (로컬만 저장됨)</span>}
        </div>
      </div>
      <LoginBanner />
      <div className="bg-blue-50 border-l-4 border-blue-400 text-xs p-3 mb-4 rounded">
        💡 <b>엑셀식 실시간 계산</b>: 샵 벤치마크·관심 키워드·수동 입력으로 시트에 상품 추가 →
        무게/구매가/배송비 편집 → <b>마진·이익·평가 즉시 재계산</b>. 모든 값은 브라우저에 자동 저장됩니다.
      </div>

      <AutoSourcingBlock
        onAddRows={addRows}
        interestKeywords={getInterestKeywords().map(i => i.keyword_jp)}
      />
      <InterestKeywordBlock onAddRows={addRows} />
      <PriceHistogram rows={rows} />
      <ProductSheet rows={rows} setRows={setRows} />
    </div>
  );
}

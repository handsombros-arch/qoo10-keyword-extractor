import { useEffect, useMemo, useRef, useState } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { AllCommunityModule, ModuleRegistry, themeQuartz } from 'ag-grid-community';
import type { ColDef } from 'ag-grid-community';
import { getExchangeRate } from '../api/endpoints';
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

function toInput(r: MarginRow): MarginRowInput {
  return {
    qty: r.qty, weightG: r.weight_g, purchaseKrw: r.purchase_krw,
    domesticShipKrw: r.domestic_ship_krw, mode: r.mode, markup: r.markup,
    targetMargin: r.target_margin, kseOverrideKrw: r.kse_override_krw,
    megaDiscount: r.mega_discount,
  };
}

export default function MarginSheetPage() {
  const [rows, setRows] = useState<MarginRow[]>(() => loadRows());
  const [settings, setSettings] = useState<MarginSheetSettings>(() => loadSettings());
  const [rateLoading, setRateLoading] = useState(false);
  const [tick, setTick] = useState(0);            // 재계산/경고 갱신
  const gridRef = useRef<AgGridReact>(null);
  const settingsRef = useRef(settings);
  settingsRef.current = settings;

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
    saveRows(rows);
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
    const next = [...rows, newMarginRow({}, settingsRef.current)];
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
      const res = computeMarginRow(toInput(r), rate);
      return res.targetPriceKrw > 0 && res.megaMarginRate < min;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, settings.mega_min_margin, rate, tick]);

  const onCellValueChanged = (e: any) => {
    // 퍼센트 입력 컬럼은 valueSetter 에서 분수로 저장됨. 여기선 저장만.
    void e;
    persist();
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

  const pctSetter = (field: 'target_margin' | 'mega_discount') => (p: any) => {
    const n = Number(String(p.newValue).replace('%', ''));
    if (isNaN(n)) return false;
    p.data[field] = n > 1 ? n / 100 : n;   // 30 또는 0.3 모두 허용
    return true;
  };

  const columnDefs: ColDef[] = useMemo(() => {
    const cg = (r: any) => computeMarginRow(toInput(r), settingsRef.current.exchange_rate);
    return [
      { headerName: '등록', width: 56, pinned: 'left', editable: false, sortable: false, filter: false,
        cellRenderer: (p: any) => (
          <input type="checkbox" checked={!!p.data?.registered}
            onChange={() => { p.data.registered = !p.data.registered; persist(); }} />
        ) },
      { field: 'source_keyword', headerName: '출처 키워드', width: 130, editable: true, pinned: 'left',
        cellRenderer: (p: any) => {
          if (!p.value) return '';
          const jp = p.data?.source_keyword_jp || p.value;
          return jp
            ? <a href={`https://www.qoo10.jp/s/?keyword=${encodeURIComponent(jp)}`} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline" title={`큐텐 검색: ${jp}`}>{p.value}</a>
            : <span>{p.value}</span>;
        } },
      { field: 'product_name', headerName: '상품명', width: 200, editable: true, pinned: 'left' },
      { field: 'option_label', headerName: '구성', width: 90, editable: true },
      { field: 'buy_site', headerName: '구매사이트', width: 100, editable: true },
      { field: 'url', headerName: 'URL', width: 150, editable: true,
        cellRenderer: (p: any) => p.value
          ? <a href={p.value} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">링크</a> : '' },
      { field: 'qty', headerName: '개수', width: 64, editable: true, type: 'numericColumn', cellEditor: 'agNumberCellEditor' },
      { field: 'weight_g', headerName: '무게(g)', width: 80, editable: true, type: 'numericColumn', cellEditor: 'agNumberCellEditor' },
      { field: 'purchase_krw', headerName: '구매가', width: 90, editable: true, type: 'numericColumn', cellEditor: 'agNumberCellEditor', valueFormatter: won },
      { field: 'domestic_ship_krw', headerName: '국내배송+포장', width: 110, editable: true, type: 'numericColumn', cellEditor: 'agNumberCellEditor', valueFormatter: won },
      { field: 'mode', headerName: '방식', width: 92, editable: true,
        cellEditor: 'agSelectCellEditor', cellEditorParams: { values: ['markup', 'target'] },
        valueFormatter: (p: any) => p.value === 'target' ? '목표마진' : '원가배수' },
      { field: 'markup', headerName: '배수', width: 70, editable: true, type: 'numericColumn', cellEditor: 'agNumberCellEditor',
        cellStyle: (p: any) => p.data?.mode === 'markup' ? undefined : { color: '#9ca3af' } },
      { field: 'target_margin', headerName: '목표마진', width: 80, editable: true, type: 'numericColumn',
        valueFormatter: pct, valueSetter: pctSetter('target_margin'),
        cellStyle: (p: any) => p.data?.mode === 'target' ? undefined : { color: '#9ca3af' } },
      { field: 'kse_override_krw', headerName: 'KSE직접입력', width: 100, editable: true, type: 'numericColumn',
        cellEditor: 'agNumberCellEditor', valueFormatter: (p: any) => p.value == null ? '(자동)' : won(p) },
      { field: 'mega_discount', headerName: '메가할인', width: 76, editable: true, type: 'numericColumn',
        valueFormatter: pct, valueSetter: pctSetter('mega_discount') },

      // ── 계산 (read-only) ──
      { headerName: '발송무게', width: 84, type: 'numericColumn', valueGetter: (p: any) => p.data && cg(p.data).effWeightG, valueFormatter: (p: any) => p.value ? `${p.value}g` : '' },
      { headerName: 'KSE배송비', width: 92, type: 'numericColumn', valueGetter: (p: any) => p.data && cg(p.data).kseShipKrw, valueFormatter: won },
      { headerName: '판매가(원)', width: 96, type: 'numericColumn', valueGetter: (p: any) => p.data && cg(p.data).targetPriceKrw, valueFormatter: won },
      // 상시
      { headerName: '상시 등록가(¥)', width: 110, type: 'numericColumn', valueGetter: (p: any) => p.data && cg(p.data).listJpy, valueFormatter: jpy, cellStyle: { backgroundColor: '#eff6ff' } },
      { headerName: '상시 이익', width: 92, type: 'numericColumn', valueGetter: (p: any) => p.data && cg(p.data).profitKrw, valueFormatter: won },
      { headerName: '상시 마진율', width: 96, type: 'numericColumn', valueGetter: (p: any) => p.data && cg(p.data).marginRate, valueFormatter: pct, cellStyle: marginCellStyle(r => cg(r).marginRate) },
      // 메가와리
      { headerName: '메가 등록가(¥)', width: 112, type: 'numericColumn', valueGetter: (p: any) => p.data && cg(p.data).megaListJpy, valueFormatter: jpy, cellStyle: { backgroundColor: '#fdf4ff' } },
      { headerName: '메가 이익', width: 92, type: 'numericColumn', valueGetter: (p: any) => p.data && cg(p.data).megaProfitKrw, valueFormatter: won },
      { headerName: '메가 마진율', width: 96, type: 'numericColumn', valueGetter: (p: any) => p.data && cg(p.data).megaMarginRate, valueFormatter: pct, cellStyle: marginCellStyle(r => cg(r).megaMarginRate) },
      { headerName: '평가', width: 70, valueGetter: (p: any) => p.data && marginVerdict(cg(p.data).marginRate) },
      { headerName: '메모', field: 'memo', width: 140, editable: true },
    ];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const defaultColDef: ColDef = useMemo(() => ({ sortable: true, resizable: true, suppressMovable: false, minWidth: 50 }), []);

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
          {megaWarnings.some(r => computeMarginRow(toInput(r), rate).megaMarginRate < 0) &&
            <span className="ml-1 font-bold">(역마진 포함)</span>}
        </div>
      )}

      {/* 툴바 */}
      <div className="flex items-center gap-2 mb-2 text-sm flex-wrap">
        <button onClick={addRow} className="px-3 py-1 bg-blue-600 text-white text-xs rounded hover:bg-blue-700">+ 행 추가</button>
        <button onClick={() => duplicateComposition(2)} className="px-3 py-1 bg-emerald-600 text-white text-xs rounded hover:bg-emerald-700" title="체크한 행을 2개 세트 구성으로 복제">2개 세트 복제</button>
        <button onClick={() => duplicateComposition(3)} className="px-3 py-1 bg-emerald-600 text-white text-xs rounded hover:bg-emerald-700">3개 세트 복제</button>
        <button onClick={deleteSelected} className="px-3 py-1 bg-red-100 text-red-700 text-xs rounded hover:bg-red-200">선택 삭제</button>
        <span className="text-xs text-gray-400 ml-auto">총 {rows.length}행 · 셀 더블클릭 편집 · 방식(원가배수/목표마진) 셀에서 선택</span>
      </div>

      <div style={{ height: 'calc(100vh - 230px)', minHeight: 480, width: '100%' }}>
        <AgGridReact
          ref={gridRef}
          theme={theme}
          rowData={rows}
          columnDefs={columnDefs}
          defaultColDef={defaultColDef}
          rowSelection={{ mode: 'multiRow', selectAll: 'filtered', enableClickSelection: false }}
          selectionColumnDef={{ pinned: 'left', width: 44 }}
          singleClickEdit={false}
          stopEditingWhenCellsLoseFocus={true}
          onCellValueChanged={onCellValueChanged}
          getRowId={(p: any) => p.data.id}
          rowClassRules={{
            'mega-loss-row': (p: any) => p.data && computeMarginRow(toInput(p.data), settingsRef.current.exchange_rate).megaMarginRate < 0,
          }}
        />
      </div>
      <style>{`.mega-loss-row { background-color: #fff1f2 !important; }`}</style>
    </div>
  );
}

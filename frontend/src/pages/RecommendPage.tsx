import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { AgGridReact } from 'ag-grid-react';
import { themeQuartz } from 'ag-grid-community';
import { getInterestKeywords, removeInterestKeyword, clearInterestKeywords, type InterestKeyword } from '../store/interestKeywords';
import { mergeKeywordsToSheet } from '../store/keywordToSheet';
import { loadSheet, saveSheet } from '../store/productSheet';
import { pushCloud } from '../store/cloudSync';

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
import api from '../api/client';
import type { Keyword } from '../types';
import CheckboxSetFilter from '../components/Grid/CheckboxSetFilter';

interface KeywordWithScore extends Keyword {
  kr_ratio: number;
  recommend_score: number;
}

// MMM-1: raw 큐텐 카테고리명 cleanup (e티켓 → 티켓 등 표기 정정)
function cleanCategoryName(c: string): string {
  if (!c) return '';
  return c
    .replace('엔터테인먼트&e티켓', '엔터테인먼트&티켓')
    .replace('e티켓', '티켓');
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

const AUTO_SOURCING_KEY = 'autoSourcingParams.v1';

export default function RecommendPage() {
  const navigate = useNavigate();
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

  // 5/3 드래그 멀티 선택 — mousedown on row → drag → 사이 모든 행 selected
  const dragAnchorRef = useRef<number | null>(null);
  const isDraggingRef = useRef(false);
  useEffect(() => {
    const onUp = () => { isDraggingRef.current = false; dragAnchorRef.current = null; };
    document.addEventListener('mouseup', onUp);
    return () => document.removeEventListener('mouseup', onUp);
  }, []);
  const onCellMouseDown = (e: any) => {
    // 좌클릭만
    if (e.event?.button !== 0) return;
    // link/button/input 클릭은 무시 (각자 동작 보장)
    const tag = (e.event?.target as HTMLElement)?.tagName;
    if (tag === 'A' || tag === 'BUTTON' || tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
    // checkbox 컬럼은 AG Grid 기본 동작 (단일 토글) — 드래그 안 막음
    if (e.colDef?.checkboxSelection) {
      // checkbox 컬럼에서도 드래그 가능하게 anchor 설정 (단 첫 토글은 AG Grid 가)
      isDraggingRef.current = true;
      dragAnchorRef.current = e.rowIndex;
      return;
    }
    isDraggingRef.current = true;
    dragAnchorRef.current = e.rowIndex;
    // 시작 행 select (기존 선택 보존 — append)
    e.node?.setSelected(true, false);
  };
  const onCellMouseOver = (e: any) => {
    if (!isDraggingRef.current || dragAnchorRef.current == null || e.rowIndex == null) return;
    const lo = Math.min(dragAnchorRef.current, e.rowIndex);
    const hi = Math.max(dragAnchorRef.current, e.rowIndex);
    const api = gridRef.current?.api as any;
    if (!api) return;
    api.forEachNodeAfterFilterAndSort((node: any) => {
      if (node.rowIndex == null) return;
      if (node.rowIndex >= lo && node.rowIndex <= hi) {
        if (!node.isSelected()) node.setSelected(true, false);
      }
    });
  };
  const handleSortChanged = () => saveColState();
  const handleGridReady = () => { restoreColState(); };
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [dates, setDates] = useState<{ lookup_date: string; count: number }[]>([]);
  const [interestList, setInterestList] = useState<InterestKeyword[]>(() => getInterestKeywords());
  const interestCount = interestList.length;
  // XXX-1: 관심 풀 row 별 체크
  const [selectedInterests, setSelectedInterests] = useState<Set<string>>(new Set());
  const toggleSelectedInterest = (jp: string) => {
    setSelectedInterests(prev => {
      const next = new Set(prev);
      if (next.has(jp)) next.delete(jp); else next.add(jp);
      return next;
    });
  };
  const toggleAllInterests = () => {
    setSelectedInterests(prev => {
      if (prev.size === interestList.length) return new Set();
      return new Set(interestList.map(k => k.keyword_jp));
    });
  };

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
  // 카테고리 필터 (빈 Set = 전체)
  // YYY-1: 디폴트 카테고리 3개 (raw 큐텐 기준 — 종합/뷰티/식품 사장님 사업 영역)
  const DEFAULT_CATS = ['01.종합', '03.뷰티&화장품', '07.식품'];
  const [selectedCategories, setSelectedCategories] = useState<Set<string>>(() => new Set(DEFAULT_CATS));
  // R-7: "종합" 키워드 중 selected 외 카테고리에도 동시 분류된 것 제외
  //   (예: 종합∩디지털 으로 분류된 키워드는 디지털 키워드로 간주 → 제외)
  const [excludeOverlap, setExcludeOverlap] = useState<boolean>(() => {
    try { return localStorage.getItem('recommend.excludeOverlap') !== '0'; } catch { return true; }
  });
  useEffect(() => {
    try { localStorage.setItem('recommend.excludeOverlap', excludeOverlap ? '1' : '0'); } catch { /* */ }
  }, [excludeOverlap]);

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

  // R-7: keyword_jp → 모든 raw 카테고리 set (excludeOverlap 필터에 사용)
  const keywordAllCategoriesMap = useMemo(() => {
    const m = new Map<string, Set<string>>();
    for (const k of keywords) {
      const jp = k.keyword_jp;
      if (!jp) continue;
      if (!m.has(jp)) m.set(jp, new Set());
      if (k.category) m.get(jp)!.add(k.category);
    }
    return m;
  }, [keywords]);

  // 5/3: 관심 풀 keyword_jp set — enriched 가 먼저 참조하므로 위로 이동 (선언 순서 보장)
  const interestSet = useMemo(() => new Set(interestList.map(k => k.keyword_jp)), [interestList]);

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
        // 5/3: 관심 키워드는 임계값/브랜드 필터 무시 — 사장님이 일부러 추가한 것
        const isInterest = interestSet.has(kw.keyword_jp);
        if (isInterest) {
          // 카테고리 / 일자 필터는 그대로 적용 (위에서 이미 cmpDate)
          // 임계값 + 브랜드 필터만 우회
        } else {
          if ((kw.search_volume_weekly || 0) < minSearch) return false;
          if (kw.kr_ratio < minKrRatio) return false;
          const c = kw.competition_intensity || 0;
          if (c < compMin || c > compMax) return false;
          if (brandFilter === 'general' && isBrand(kw.keyword_jp)) return false;
          if (brandFilter === 'brand' && !isBrand(kw.keyword_jp)) return false;
        }
        // YYY-1: raw 큐텐 카테고리로 필터 (사장님 디폴트 종합/뷰티/식품 = raw)
        const rawCat = kw.category || '';
        if (selectedCategories.size > 0) {
          if (!selectedCategories.has(rawCat)) return false;
          // R-7: excludeOverlap — 키워드의 모든 raw 카테고리가 selected 안에 있어야 통과.
          // 종합∩디지털 키워드는 종합으로도 row 가 있지만 디지털 분류도 있으니 제외.
          if (excludeOverlap) {
            const allCats = keywordAllCategoriesMap.get(kw.keyword_jp);
            if (allCats) {
              for (const cat of allCats) {
                if (!selectedCategories.has(cat)) return false;
              }
            }
          }
        }
        return true;
      });

    // 키워드 중복 제거: 같은 keyword_jp는 최고 점수만, 카테고리 목록 합침
    // categories 는 LLM category_inferred 우선, raw 는 raw_categories 별도
    if (dedupe) {
      const byKw = new Map<string, KeywordWithScore & { categories: string[]; raw_categories?: string[] }>();
      for (const r of rows) {
        const k = r.keyword_jp;
        const existing = byKw.get(k);
        const llmCat = (r as any).category_inferred || '';
        const rawCat = r.category || '';
        if (!existing) {
          byKw.set(k, {
            ...r,
            categories: llmCat ? [llmCat] : [],
            raw_categories: rawCat ? [rawCat] : [],
          });
        } else {
          if (llmCat && !existing.categories.includes(llmCat)) existing.categories.push(llmCat);
          if (rawCat && !(existing.raw_categories || []).includes(rawCat)) {
            existing.raw_categories = [...(existing.raw_categories || []), rawCat];
          }
          if (r.recommend_score > existing.recommend_score) {
            byKw.set(k, {
              ...r,
              categories: existing.categories,
              raw_categories: existing.raw_categories,
            });
          }
        }
      }
      rows = Array.from(byKw.values());
    }

    return rows.sort((a, b) => b.recommend_score - a.recommend_score);
  }, [keywords, mode, singleDate, fromDate, toDate, minSearch, minKrRatio, compMin, compMax, dedupe, brandFilter, selectedCategories, excludeOverlap, keywordAllCategoriesMap, interestSet]);

  // YYY-1: raw 큐텐 카테고리 목록 (필터 버튼용)
  const availableCats = useMemo(() => {
    const s = new Set<string>();
    keywords.forEach(k => { if (k.category) s.add(k.category); });
    return Array.from(s).sort();
  }, [keywords]);
  const toggleCategoryFilter = (cat: string) => {
    setSelectedCategories(prev => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat); else next.add(cat);
      return next;
    });
  };

  const numFmt = (p: any) => p.value == null ? '' : Number(p.value).toLocaleString();
  const pctFmt = (p: any) => p.value == null ? '' : `${Number(p.value).toFixed(1)}%`;
  const scoreFmt = (p: any) => p.value == null ? '' : Number(p.value).toFixed(2);

  const columnDefs: ColDef[] = useMemo(() => [
    {
      headerName: '', width: 50, pinned: 'left', sortable: false, filter: false,
      checkboxSelection: true, headerCheckboxSelection: true, headerCheckboxSelectionFilteredOnly: true,
    },
    {
      headerName: '구분', width: 70, pinned: 'left',
      valueGetter: (p: any) => interestSet.has(p.data?.keyword_jp) ? '관심' : '추천',
      cellRenderer: (p: any) => {
        const v = p.value;
        const cls = v === '관심'
          ? 'bg-amber-100 text-amber-800 font-bold'
          : 'bg-blue-50 text-blue-700';
        return <span className={`text-[10px] px-1.5 py-0.5 rounded ${cls}`}>{v}</span>;
      },
      filter: 'agSetColumnFilter',
      filterParams: { values: ['관심', '추천'] },
    },
    { field: 'lookup_date', headerName: '날짜', width: 110,
      valueGetter: (p: any) => p.data?.added_at || p.data?.lookup_date || '',
    },
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
      field: 'category', headerName: '카테고리 (LLM)', width: 160,
      valueGetter: (p: any) => {
        // LLM 분류 우선 표시
        const cats = p.data?.categories;
        if (Array.isArray(cats) && cats.length > 0) return cats.map(cleanCategoryName).join(', ');
        const eff = p.data?.category_inferred || p.data?.category || '';
        return cleanCategoryName(eff);
      },
      cellRenderer: (p: any) => {
        const cats = p.data?.categories;
        const rawCats = p.data?.raw_categories || [];
        const tooltip = rawCats.length > 0
          ? `LLM: ${(cats || []).map(cleanCategoryName).join(', ')}\n큐텐 raw: ${rawCats.map(cleanCategoryName).join(', ')}`
          : '';
        if (Array.isArray(cats) && cats.length > 0) {
          const first = cleanCategoryName(cats[0]);
          const extra = cats.length - 1;
          return (
            <span className="inline-flex items-center gap-1" title={tooltip || cats.map(cleanCategoryName).join(', ')}>
              <span className="truncate">{first}</span>
              {extra > 0 && (
                <span className="px-1 text-[10px] font-semibold text-blue-700 bg-blue-100 rounded">+{extra}</span>
              )}
            </span>
          );
        }
        const eff = p.data?.category_inferred || p.data?.category || '';
        return <span title={tooltip}>{cleanCategoryName(eff)}</span>;
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

  const [retranslating, setRetranslating] = useState(false);
  const [retransProgress, setRetransProgress] = useState<string | null>(null);

  const retranslateAll = async (onlyMissing: boolean) => {
    const label = onlyMissing ? '한국어 없는 키워드만' : '전체 키워드';
    if (!confirm(`${label}을 구글 번역으로 재번역합니다. 수 분 걸릴 수 있습니다. 진행?`)) return;
    setRetranslating(true); setRetransProgress(null);
    try {
      const { data } = await api.post('/keywords/retranslate', null, { params: { only_missing: onlyMissing } });
      if (data.status === 'empty') { alert('재번역할 키워드가 없습니다.'); return; }
      const taskId = data.task_id;
      const poll = window.setInterval(async () => {
        try {
          const { data: t } = await api.get(`/tasks/${taskId}`);
          if (!t) return;
          setRetransProgress(`${t.message || ''} (${t.progress}/${t.total})`);
          if (t.status === 'completed' || t.status === 'failed') {
            window.clearInterval(poll);
            setRetranslating(false);
            alert(t.message || '완료');
            reload();
          }
        } catch { /* ignore */ }
      }, 2000);
    } catch (e: any) {
      setRetranslating(false);
      alert('재번역 실패: ' + (e?.message || String(e)));
    }
  };

  // VV-3 추천 테이블 → 시트로 직접
  const sendSelectedToSheet = async () => {
    const api = gridRef.current?.api as any;
    if (!api) return;
    const selected: any[] = api.getSelectedRows?.() || [];
    if (selected.length === 0) { alert('키워드를 체크해주세요.'); return; }
    const today = new Date().toISOString().slice(0, 10);
    const result = await mergeKeywordsToSheet(
      selected.map(r => ({
        keyword_jp: r.keyword_jp,
        keyword_kr: r.keyword_kr,
        // R-7: LLM category_inferred 우선 (시트의 6분류 dropdown 과 매칭)
        category: (r as any).category_inferred || r.category,
        search_volume_weekly: r.search_volume_weekly,
      })),
      `keyword:${today}`,
    );
    alert(`✓ ${result.added}건${result.blacklisted ? ` (⛔ 블랙 ${result.blacklisted})` : ''} 시트에 추가 (${selected.length} 중 중복 제외).\n/recommend-products 에서 한국 셀러 URL/원가 입력하세요.`);
  };

  // R-7: 체크된 키워드를 시트에서 삭제 (keyword_jp 매칭)
  const deleteSelectedFromSheet = async () => {
    const api = gridRef.current?.api as any;
    if (!api) return;
    const selected: any[] = api.getSelectedRows?.() || [];
    if (selected.length === 0) { alert('키워드를 체크해주세요.'); return; }
    const targetKws = new Set(selected.map(r => r.keyword_jp).filter(Boolean));
    if (targetKws.size === 0) { alert('체크한 키워드에 keyword_jp 가 없습니다.'); return; }
    const sheet = loadSheet();
    const matched = sheet.filter(r => r.keyword_jp && targetKws.has(r.keyword_jp));
    if (matched.length === 0) {
      alert('체크한 키워드와 매칭되는 시트 행이 없습니다.');
      return;
    }
    const ok = window.confirm(
      `체크한 ${targetKws.size}개 키워드와 매칭되는 시트 행 ${matched.length}개를 삭제합니다.\n\n` +
      `진행하시겠습니까? (이 작업은 되돌릴 수 없습니다)`
    );
    if (!ok) return;
    const next = sheet.filter(r => !(r.keyword_jp && targetKws.has(r.keyword_jp)));
    saveSheet(next);
    try { await pushCloud('product_sheet', next); } catch { /* */ }
    alert(`✓ ${matched.length}개 행 시트에서 삭제. 남은 시트 ${next.length}행.`);
  };

  // R-7: 일자별 추천 키워드 → 시트 추가
  //   1) 일자 입력 (prompt; default 페이지 상단 singleDate 또는 오늘)
  //   2) 그 일자 keywords 만 + 현재 카테고리/임계값 필터 적용
  //   3) 시트에 추가 (덮어쓰기 X — mergeKeywordsToSheet 가 keyword_jp 중복 제외)
  const fetchByDateAndAddToSheet = async () => {
    const defaultDate = singleDate || new Date().toISOString().slice(0, 10);
    const dateStr = window.prompt(
      `어떤 일자의 추천을 가져올까요? (YYYY-MM-DD)\n\n` +
      `현재 카테고리 필터: ${selectedCategories.size > 0 ? Array.from(selectedCategories).join(', ') : '전체'}\n` +
      `임계값: 검색량 ≥${minSearch}, 한국비율 ≥${minKrRatio}%, 경쟁 ${compMin}~${compMax}`,
      defaultDate,
    );
    if (!dateStr) return;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
      alert('일자 형식 잘못됨 (YYYY-MM-DD).');
      return;
    }
    // 그 일자 + 현재 필터 통과 키워드 추출
    // enriched 는 페이지 상단 일자 mode 따라가니 일관성 위해 keywords 원천에서 직접 필터
    const filtered = keywords.filter(k => {
      if (k.lookup_date !== dateStr) return false;
      if ((k.search_volume_weekly || 0) < minSearch) return false;
      const total = k.total_products || 0;
      const kr = k.products_kr || 0;
      const krRatio = total > 0 ? (kr / total) * 100 : 0;
      if (krRatio < minKrRatio) return false;
      const c = k.competition_intensity || 0;
      if (c < compMin || c > compMax) return false;
      const rawCat = k.category || '';
      if (selectedCategories.size > 0) {
        if (!selectedCategories.has(rawCat)) return false;
        if (excludeOverlap) {
          const allCats = keywordAllCategoriesMap.get(k.keyword_jp);
          if (allCats) {
            for (const cat of allCats) {
              if (!selectedCategories.has(cat)) return false;
            }
          }
        }
      }
      return true;
    });
    // dedup keyword_jp (같은 키워드 다른 카테고리 row 가 통과한 경우)
    const seen = new Set<string>();
    const unique = filtered.filter(k => {
      if (seen.has(k.keyword_jp)) return false;
      seen.add(k.keyword_jp);
      return true;
    });
    if (unique.length === 0) {
      alert(`${dateStr} 의 필터 통과 키워드 0개. 카테고리/임계값 또는 일자 확인 후 재시도.`);
      return;
    }
    const ok = window.confirm(
      `${dateStr}\n` +
      `필터 통과 ${unique.length}개 키워드를 시트에 추가합니다.\n\n` +
      `(중복은 자동 제외 — 시트는 비우지 않음)\n\n` +
      `진행?`
    );
    if (!ok) return;
    const result = await mergeKeywordsToSheet(
      unique.map(k => ({
        keyword_jp: k.keyword_jp,
        keyword_kr: k.keyword_kr,
        category: (k as any).category_inferred || k.category,
        search_volume_weekly: k.search_volume_weekly,
      })),
      `keyword:${dateStr}`,
    );
    alert(`✓ ${dateStr} 추천 ${result.added}건${result.blacklisted ? ` (⛔ 블랙 ${result.blacklisted})` : ''} 시트 추가 (${unique.length} 중 중복 제외).`);
  };

  // VV-3 관심 풀 → 시트로 직접 (전체 또는 선택)
  const sendInterestToSheet = async () => {
    const items = interestList;
    if (!items || !items.length) { alert('관심 키워드 풀이 비어있습니다.'); return; }
    if (!confirm(`관심 풀 전체 ${items.length}건을 시트에 추가합니다.`)) return;
    const today = new Date().toISOString().slice(0, 10);
    const result = await mergeKeywordsToSheet(
      items.map(k => ({
        keyword_jp: k.keyword_jp,
        keyword_kr: k.keyword_kr,
        category: (k as any).category_inferred || k.category,
        search_volume_weekly: k.search_volume_weekly,
      })),
      `interest:${today}`,
    );
    alert(`✓ ${result.added}건${result.blacklisted ? ` (⛔ 블랙 ${result.blacklisted})` : ''} 시트에 추가 (관심 풀 ${items.length} 중 중복 제외).`);
  };

  // XXX-1: 관심 풀 — 체크된 row 만 시트로
  const sendSelectedInterestsToSheet = async () => {
    const sel = interestList.filter(k => selectedInterests.has(k.keyword_jp));
    if (!sel.length) { alert('체크된 관심 키워드가 없습니다.'); return; }
    const today = new Date().toISOString().slice(0, 10);
    const result = await mergeKeywordsToSheet(
      sel.map(k => ({
        keyword_jp: k.keyword_jp,
        keyword_kr: k.keyword_kr,
        category: k.category,
        search_volume_weekly: k.search_volume_weekly,
      })),
      `interest:${today}`,
    );
    alert(`✓ ${result.added}건${result.blacklisted ? ` (⛔ 블랙 ${result.blacklisted})` : ''} 시트에 추가 (선택 ${sel.length} 중 중복 제외).`);
    // 시트 보낸 후 선택 해제
    setSelectedInterests(new Set());
  };

  const removeInterest = (jp: string) => {
    const next = removeInterestKeyword(jp);
    setInterestList(next);
  };
  const clearAllInterest = () => {
    if (!confirm('관심 키워드를 모두 삭제할까요?')) return;
    clearInterestKeywords();
    setInterestList([]);
  };
  const sourceInterestList = () => {
    if (interestList.length === 0) {
      alert('관심 키워드가 비어있습니다.');
      return;
    }
    try {
      const raw = localStorage.getItem(AUTO_SOURCING_KEY);
      const cur = raw ? JSON.parse(raw) : {};
      localStorage.setItem(AUTO_SOURCING_KEY, JSON.stringify({
        ...cur,
        mode: 'interest',
        keywords_limit: Math.max(cur.keywords_limit || 20, interestList.length),
      }));
    } catch { /* ignore */ }
    navigate('/recommend-products');
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">⭐ 역직구 추천 키워드</h2>
        <Link
          to="/keywords"
          className="text-xs px-3 py-1.5 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded"
          title="키워드 추출 (RD) — raw 데이터 직접 확인. 자주 사용 X"
        >
          🔬 키워드 추출 (RD)
        </Link>
      </div>

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
              onClick={() => retranslateAll(false)}
              disabled={retranslating}
              className="text-xs px-2 py-1 bg-blue-500 text-white hover:bg-blue-600 rounded disabled:opacity-50"
              title="DB의 모든 키워드를 구글 번역기로 재번역"
            >
              🌐 전체 재번역
            </button>
            <button
              onClick={() => retranslateAll(true)}
              disabled={retranslating}
              className="text-xs px-2 py-1 bg-blue-100 text-blue-700 hover:bg-blue-200 rounded disabled:opacity-50"
              title="한국어가 비어있는 키워드만 번역"
            >
              빈 것만
            </button>
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
            <div className="flex justify-between items-center mb-1">
              <span className="text-xs text-gray-600">최소 검색수(주평)</span>
              <div className="flex items-center gap-1">
                <input
                  type="number" min={0} max={100000} step={1}
                  value={minSearch}
                  onChange={e => setMinSearch(Math.max(0, Number(e.target.value) || 0))}
                  className="w-20 text-xs font-semibold text-blue-700 border rounded px-1 py-0.5 text-right"
                />
                <span className="text-xs text-blue-700">이상</span>
              </div>
            </div>
            <input
              type="range" min={0} max={20000} step={1}
              value={Math.min(minSearch, 20000)}
              onChange={e => setMinSearch(Number(e.target.value))}
              className="w-full accent-blue-600"
            />
            <div className="flex justify-between text-[10px] text-gray-400">
              <span>0</span><span>5,000</span><span>10,000</span><span>15,000</span><span>20,000</span>
            </div>
          </div>

          <div>
            <div className="flex justify-between items-center mb-1">
              <span className="text-xs text-gray-600">최소 한국비율(%)</span>
              <div className="flex items-center gap-1">
                <input
                  type="number" min={0} max={100} step={1}
                  value={minKrRatio}
                  onChange={e => setMinKrRatio(Math.max(0, Math.min(100, Number(e.target.value) || 0)))}
                  className="w-16 text-xs font-semibold text-blue-700 border rounded px-1 py-0.5 text-right"
                />
                <span className="text-xs text-blue-700">% 이상</span>
              </div>
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
            <div className="flex justify-between items-center mb-1">
              <span className="text-xs text-gray-600">경쟁강도 최소</span>
              <div className="flex items-center gap-1">
                <input
                  type="number" min={0} max={50} step={1}
                  value={compMin}
                  onChange={e => {
                    const v = Math.max(0, Math.min(50, Number(e.target.value) || 0));
                    setCompMin(v);
                    if (v > compMax) setCompMax(v);
                  }}
                  className="w-16 text-xs font-semibold text-blue-700 border rounded px-1 py-0.5 text-right"
                />
                <span className="text-xs text-blue-700">이상</span>
              </div>
            </div>
            <input
              type="range" min={0} max={50} step={1}
              value={compMin}
              onChange={e => {
                const v = Number(e.target.value);
                setCompMin(v);
                if (v > compMax) setCompMax(v);
              }}
              className="w-full accent-blue-600"
            />
            <div className="flex justify-between text-[10px] text-gray-400">
              <span>0</span><span>10</span><span>20</span><span>30</span><span>40</span><span>50</span>
            </div>
          </div>

          <div>
            <div className="flex justify-between items-center mb-1">
              <span className="text-xs text-gray-600">경쟁강도 최대</span>
              <div className="flex items-center gap-1">
                <input
                  type="number" min={0} max={50} step={1}
                  value={compMax}
                  onChange={e => {
                    const v = Math.max(0, Math.min(50, Number(e.target.value) || 0));
                    setCompMax(v);
                    if (v < compMin) setCompMin(v);
                  }}
                  className="w-16 text-xs font-semibold text-blue-700 border rounded px-1 py-0.5 text-right"
                />
                <span className="text-xs text-blue-700">이하</span>
              </div>
            </div>
            <input
              type="range" min={0} max={50} step={1}
              value={compMax}
              onChange={e => {
                const v = Number(e.target.value);
                setCompMax(v);
                if (v < compMin) setCompMin(v);
              }}
              className="w-full accent-blue-600"
            />
            <div className="flex justify-between text-[10px] text-gray-400">
              <span>0</span><span>10</span><span>20</span><span>30</span><span>40</span><span>50</span>
            </div>
          </div>
        </div>

        {/* 카테고리 필터 (복수 선택) */}
        <div className="mt-4 pt-3 border-t">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-gray-700">카테고리 필터</span>
            <div className="flex gap-1">
              <button
                onClick={() => setSelectedCategories(new Set())}
                className="text-[11px] px-2 py-0.5 bg-gray-100 hover:bg-gray-200 rounded"
              >전체(초기화)</button>
              <button
                onClick={() => setSelectedCategories(new Set(availableCats))}
                className="text-[11px] px-2 py-0.5 bg-gray-100 hover:bg-gray-200 rounded"
              >전체 선택</button>
            </div>
          </div>
          <div className="flex flex-wrap gap-1">
            {availableCats.map(c => {
              const on = selectedCategories.has(c);
              return (
                <button
                  key={c}
                  onClick={() => toggleCategoryFilter(c)}
                  className={`px-2 py-0.5 text-xs rounded border ${on ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'}`}
                  title={c}
                >{cleanCategoryName(c)}</button>
              );
            })}
          </div>
          {selectedCategories.size > 0 && (
            <div className="mt-1 text-[11px] text-gray-500 flex items-center gap-3 flex-wrap">
              <span>선택: {selectedCategories.size}개 (나머지 카테고리 제외)</span>
              <label className="flex items-center gap-1 cursor-pointer hover:text-gray-700"
                title="키워드의 카테고리 set 중 선택 외 카테고리가 하나라도 있으면 제외. 예: 종합∩디지털 키워드 → 디지털도 분류됐으니 제외.">
                <input type="checkbox" checked={excludeOverlap}
                  onChange={e => setExcludeOverlap(e.target.checked)}
                  className="cursor-pointer" />
                <span>겹침 제외 (종합 ∩ 다른 카테고리 키워드 빼기)</span>
              </label>
            </div>
          )}
        </div>
      </div>

      {/* YYY-1: 관심 풀 별도 테이블 삭제 — 추천 통합 테이블의 "구분" 컬럼으로 대체 */}
      {false && (
      <div className="bg-white rounded-lg shadow p-5 mb-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold">⭐ 관심 키워드 풀</h3>
            <span className="text-xs text-gray-500">({interestList.length}개)</span>
          </div>
          <div className="flex gap-1">
            <button
              onClick={sendSelectedInterestsToSheet}
              disabled={selectedInterests.size === 0}
              className="text-xs px-3 py-1 bg-emerald-600 text-white rounded hover:bg-emerald-700 disabled:opacity-40"
              title="체크된 row 만 시트에 추가"
            >
              📋 선택 {selectedInterests.size > 0 ? `${selectedInterests.size}건 ` : ''}시트로
            </button>
            <button
              onClick={sendInterestToSheet}
              disabled={interestList.length === 0}
              className="text-xs px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-40"
              title="관심 풀 전체를 상품 시트에 추가 (URL/원가 직접 입력)"
            >
              📋 전체 시트로
            </button>
            <button
              onClick={sourceInterestList}
              disabled={interestList.length === 0}
              className="text-xs px-3 py-1 bg-purple-600 text-white rounded hover:bg-purple-700 disabled:opacity-40"
              title="관심 키워드 전체를 interest 모드 자동 소싱 페이지로 이동"
            >
              ⚡ 자동 소싱
            </button>
            <button
              onClick={clearAllInterest}
              disabled={interestList.length === 0}
              className="text-xs px-3 py-1 bg-gray-100 text-gray-700 rounded hover:bg-gray-200 disabled:opacity-40"
            >
              비우기
            </button>
          </div>
        </div>
        {interestList.length === 0 ? (
          <div className="text-center py-4 text-xs text-gray-400 border border-dashed rounded">
            아래 추천 테이블에서 키워드를 체크 후 "⭐ 선택한 키워드를 관심 키워드에 추가" 버튼으로 담으세요.
          </div>
        ) : (
          <div className="overflow-x-auto max-h-[320px] overflow-y-auto border rounded">
            <table className="w-full text-[11px]">
              <thead className="bg-gray-50 sticky top-0 z-10">
                <tr>
                  <th className="border-b px-2 py-1 text-center w-8">
                    <input type="checkbox"
                      checked={selectedInterests.size === interestList.length && interestList.length > 0}
                      ref={el => { if (el) el.indeterminate = selectedInterests.size > 0 && selectedInterests.size < interestList.length; }}
                      onChange={toggleAllInterests}
                      title="전체 선택/해제" />
                  </th>
                  <th className="border-b px-2 py-1 text-left">체크한 날짜</th>
                  <th className="border-b px-2 py-1 text-left">일본어</th>
                  <th className="border-b px-2 py-1 text-left">한국어</th>
                  <th className="border-b px-2 py-1 text-right">한국비율(%)</th>
                  <th className="border-b px-2 py-1 text-left">카테고리</th>
                  <th className="border-b px-2 py-1 text-right">검색수(주평)</th>
                  <th className="border-b px-2 py-1 text-right">검색수(전날)</th>
                  <th className="border-b px-2 py-1 text-right">경쟁강도</th>
                  <th className="border-b px-2 py-1 text-right">전체상품수</th>
                  <th className="border-b px-2 py-1 text-right">일본</th>
                  <th className="border-b px-2 py-1 text-right">한국</th>
                  <th className="border-b px-2 py-1 text-right">중국</th>
                  <th className="border-b px-2 py-1 text-right">그외</th>
                  <th className="border-b px-2 py-1 text-center w-10"></th>
                </tr>
              </thead>
              <tbody>
                {interestList.map(k => {
                  const total = k.total_products || 0;
                  const kr = k.products_kr || 0;
                  const krRatio = total > 0 ? (kr / total) * 100 : 0;
                  const fmtN = (n?: number) => n == null ? '-' : Number(n).toLocaleString();
                  return (
                    <tr key={k.keyword_jp}
                      className={`hover:bg-yellow-50 ${selectedInterests.has(k.keyword_jp) ? 'bg-emerald-50' : ''}`}>
                      <td className="border-b px-2 py-0.5 text-center">
                        <input type="checkbox"
                          checked={selectedInterests.has(k.keyword_jp)}
                          onChange={() => toggleSelectedInterest(k.keyword_jp)} />
                      </td>
                      <td className="border-b px-2 py-0.5 text-gray-600 whitespace-nowrap">{k.added_at || '-'}</td>
                      <td className="border-b px-2 py-0.5 whitespace-nowrap">
                        <a href={`https://www.qoo10.jp/s/?keyword=${k.keyword_jp}`} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">{k.keyword_jp}</a>
                      </td>
                      <td className="border-b px-2 py-0.5 text-gray-700 whitespace-nowrap">{k.keyword_kr || '-'}</td>
                      <td className={`border-b px-2 py-0.5 text-right ${krRatio >= 30 ? 'bg-amber-50 font-semibold' : ''}`}>{krRatio.toFixed(1)}%</td>
                      <td className="border-b px-2 py-0.5 text-gray-700 whitespace-nowrap"
                        title={k.category ? `큐텐 raw: ${cleanCategoryName(k.category)}` : ''}>
                        {cleanCategoryName((k as any).category_inferred || k.category || '') || '-'}
                      </td>
                      <td className="border-b px-2 py-0.5 text-right">{fmtN(k.search_volume_weekly)}</td>
                      <td className="border-b px-2 py-0.5 text-right">{fmtN(k.search_volume_daily)}</td>
                      <td className="border-b px-2 py-0.5 text-right">{k.competition_intensity?.toFixed(2) ?? '-'}</td>
                      <td className="border-b px-2 py-0.5 text-right">{fmtN(k.total_products)}</td>
                      <td className="border-b px-2 py-0.5 text-right">{fmtN(k.products_jp)}</td>
                      <td className="border-b px-2 py-0.5 text-right">{fmtN(k.products_kr)}</td>
                      <td className="border-b px-2 py-0.5 text-right">{fmtN(k.products_cn)}</td>
                      <td className="border-b px-2 py-0.5 text-right">{fmtN(k.products_other)}</td>
                      <td className="border-b px-2 py-0.5 text-center">
                        <button
                          onClick={() => removeInterest(k.keyword_jp)}
                          className="text-red-500 hover:text-red-700 text-xs"
                          title="관심 키워드에서 제거"
                        >
                          ✕
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      )}

      {retranslating && (
        <div className="bg-blue-50 border-l-4 border-blue-400 text-xs p-3 mb-4 rounded flex items-center gap-2">
          <span className="inline-block w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
          <b>구글 번역 중...</b>
          <span className="text-gray-600">{retransProgress}</span>
        </div>
      )}

      <div className="bg-white rounded-lg shadow p-2">
        <div className="px-2 py-2 flex items-center justify-between flex-wrap gap-2">
          <div className="text-sm text-gray-500">
            추천+관심 통합 {enriched.length}개 (관심 {interestCount} / 추천 {enriched.length - interestCount}, 추천점수 내림차순)
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={sendSelectedToSheet}
              className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700"
              title="체크한 키워드를 상품 시트로 추가 (중복 제외)"
            >
              📋 선택 → 시트
            </button>
            <button
              onClick={deleteSelectedFromSheet}
              className="text-xs px-3 py-1.5 bg-red-500 text-white rounded hover:bg-red-600"
              title="체크한 키워드와 매칭되는 시트 행만 삭제 (keyword_jp 기준)"
            >
              🗑 선택 시트 삭제
            </button>
            <button
              onClick={fetchByDateAndAddToSheet}
              className="text-xs px-3 py-1.5 bg-rose-600 text-white rounded hover:bg-rose-700"
              title="특정 일자의 추천 키워드 (현 카테고리/임계값 필터 적용) 시트로 일괄 추가"
            >
              📅 일자별 추천 가져오기
            </button>
            <Link
              to="/recommend-products"
              className="text-xs px-3 py-1.5 bg-indigo-600 text-white rounded hover:bg-indigo-700"
            >
              📋 시트로 이동
            </Link>
          </div>
        </div>
        <div style={{ height: 600, width: '100%' }}>
          <AgGridReact
            ref={gridRef}
            theme={myTheme}
            rowData={enriched}
            columnDefs={columnDefs}
            defaultColDef={defaultColDef}
            animateRows={true}
            rowSelection="multiple"
            suppressRowClickSelection={true}
            pagination={true}
            paginationPageSize={2000}
            paginationPageSizeSelector={[100, 500, 1000, 2000, 5000]}
            autoSizeStrategy={{ type: 'fitCellContents' }}
            onColumnResized={handleColumnResized}
            onColumnMoved={handleColumnMoved}
            onSortChanged={handleSortChanged}
            onGridReady={handleGridReady}
            onCellMouseDown={onCellMouseDown}
            onCellMouseOver={onCellMouseOver}
          />
        </div>
      </div>

      {showCriteria && <CriteriaModal onClose={() => setShowCriteria(false)} />}
    </div>
  );
}

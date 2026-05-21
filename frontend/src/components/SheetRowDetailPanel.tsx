/**
 * 시트 row 우측 슬라이드 상세 패널 (TT-1B).
 *
 * row 클릭 시 시트 우측에 fixed 슬라이드 — 큐텐 cover ↔ 한국 cover 좌우 비교 +
 * SEO 콘텐츠 (title_jp/tags/marketing_points) 인플레이스 편집 + 옵션 풀세트 +
 * 매칭 사유. 모든 필드 사장님이 직접 override 가능.
 *
 * fetch: /api/sheet/row-meta?keyword_jp=... → 큐텐 product/match/options 메타
 */
import { useEffect, useState } from 'react';
import api from '../api/client';
import type { SheetRow } from '../store/productSheet';

type RowMeta = {
  qoo10?: {
    cover_image_url: string;
    product_name_jp: string;
    product_name_ko: string;
    title_jp: string;
    tags: string[];
    marketing_points: string[];
    option_name: string;
    cover_description?: string;
  };
  domestic?: {
    id: number;
    cover_description: string;
    extras?: { file: string; path: string; score: number | null; desc: string }[];
  };
  match?: {
    image_score: number | null;
    name_score: number | null;
    quality_score?: number | null;
    note: string;
    decision: string;
  };
  options_full?: { name: string; price_krw: number | null; in_stock: boolean }[];
  alt_skus?: { id: number; source: string; product_name: string; price_krw: number;
    product_url: string; cover_image_url: string; image_score: number | null;
    cover_description?: string;
    is_current_cheapest: boolean }[];
  qoo10_samples?: { id: number; product_name: string; product_name_ko: string;
    price_jpy: number; product_url: string; cover_image_url: string;
    cover_description?: string }[];
};

type Props = {
  row: SheetRow;
  onClose: () => void;
  onSave: (updated: Partial<SheetRow>) => void;
  onReject?: () => void;
  onBlacklist?: () => void;   // K (5/3): 블랙리스트 추가 + 행 삭제 (부모에서 구현)
};

export type SheetRowDetailPanelProps = Props;

type AltSku = NonNullable<RowMeta['alt_skus']>[number];

export default function SheetRowDetailPanel({ row, onClose, onSave, onReject, onBlacklist }: Props) {
  const [meta, setMeta] = useState<RowMeta | null>(null);
  const [loading, setLoading] = useState(false);
  const [edit, setEdit] = useState<Partial<SheetRow>>({
    qoo10_title_jp: row.qoo10_title_jp || '',
    qoo10_tags: row.qoo10_tags || [],
    qoo10_marketing: row.qoo10_marketing || [],
    qoo10_option_name: row.qoo10_option_name || '',
    product_url: row.product_url || '',
    item_price_krw: row.item_price_krw || 0,
    domestic_shipping_krw: row.domestic_shipping_krw || 0,
    weight_g: row.weight_g || 0,
  });
  const [newTag, setNewTag] = useState('');
  const [newPoint, setNewPoint] = useState('');
  // LLL-1 — alt SKU 클릭 시 즉시 swap 안 하고 한국 슬롯에 preview 확대
  const [previewAlt, setPreviewAlt] = useState<AltSku | null>(null);
  // DDDD-1 — URL 기반 SEO 자동 재생성 상태
  const [regenerating, setRegenerating] = useState(false);
  const [regenMsg, setRegenMsg] = useState<string>('');

  // alt_skus 적합도 (image_score) DESC, 동점은 가격 ASC. cheapest 표식은 보존.
  const sortedAlts: AltSku[] = (meta?.alt_skus || []).slice().sort((a, b) => {
    const sa = a.image_score ?? -1;
    const sb = b.image_score ?? -1;
    if (sa !== sb) return sb - sa;
    return (a.price_krw || 0) - (b.price_krw || 0);
  });

  useEffect(() => {
    const kw = row.keyword_jp || row.product_name;
    if (!kw) return;
    setLoading(true);
    api.get<RowMeta>(`/sheet/row-meta`, { params: { keyword_jp: kw, product_name: row.product_name } })
      .then(r => setMeta(r.data))
      .catch(() => setMeta(null))
      .finally(() => setLoading(false));
  }, [row.id]);  // eslint-disable-line react-hooks/exhaustive-deps

  // H (5/3): row 변경 시 edit 상태 리셋 — 패널 열린 채 다른 행 클릭 시 새 행 데이터 표시
  useEffect(() => {
    setEdit({
      qoo10_title_jp: row.qoo10_title_jp || '',
      qoo10_tags: row.qoo10_tags || [],
      qoo10_marketing: row.qoo10_marketing || [],
      qoo10_marketing_ko: row.qoo10_marketing_ko || [],
      qoo10_option_name: row.qoo10_option_name || '',
      product_url: row.product_url || '',
      qoo10_url: row.qoo10_url || '',
      item_price_krw: row.item_price_krw || 0,
      domestic_shipping_krw: row.domestic_shipping_krw || 0,
      weight_g: row.weight_g || 0,
      product_name: row.product_name || '',
      category: row.category || '',
      cover_image_url: row.cover_image_url || '',
      cover_local_path: row.cover_local_path,
      detail_local_paths: row.detail_local_paths,
      image_folder: row.image_folder,
      // S (5/3) 옵션 비교
      domestic_options: row.domestic_options,
      qoo10_options_raw: row.qoo10_options_raw,
      competitor_price_jpy: row.competitor_price_jpy,
      competitor_shipping_jpy: row.competitor_shipping_jpy,
    });
    setNewTag('');
    setNewPoint('');
    setRegenMsg('');
    setNeedsNaverLogin(false);
  }, [row.id]);  // eslint-disable-line react-hooks/exhaustive-deps

  function patch(p: Partial<SheetRow>) {
    setEdit(prev => ({ ...prev, ...p }));
  }

  function addTag() {
    const t = newTag.trim();
    if (!t) return;
    const tags = [...(edit.qoo10_tags || []), t];
    patch({ qoo10_tags: tags });
    setNewTag('');
  }

  function removeTag(i: number) {
    const tags = (edit.qoo10_tags || []).filter((_, idx) => idx !== i);
    patch({ qoo10_tags: tags });
  }

  function addPoint() {
    const p = newPoint.trim();
    if (!p) return;
    patch({ qoo10_marketing: [...(edit.qoo10_marketing || []), p] });
    setNewPoint('');
  }

  function removePoint(i: number) {
    patch({
      qoo10_marketing: (edit.qoo10_marketing || []).filter((_, idx) => idx !== i),
      qoo10_marketing_ko: (edit.qoo10_marketing_ko || []).filter((_, idx) => idx !== i),
    });
  }

  function updatePoint(i: number, v: string) {
    const arr = [...(edit.qoo10_marketing || [])];
    arr[i] = v;
    patch({ qoo10_marketing: arr });
  }

  // H (5/3) marketing 한글 번역 인플레이스 편집
  function updatePointKo(i: number, v: string) {
    const arr = [...(edit.qoo10_marketing_ko || [])];
    while (arr.length <= i) arr.push('');
    arr[i] = v;
    patch({ qoo10_marketing_ko: arr });
  }

  // DDDD-1 + HHHH-1: URL 기반 SEO 콘텐츠 자동 재생성 (background task + 진행률)
  const [regenProgress, setRegenProgress] = useState<{cur:number,total:number,msg:string}>({cur:0,total:0,msg:''});
  // IIII-1: Naver 로그인 setup
  const [needsNaverLogin, setNeedsNaverLogin] = useState(false);
  const [naverLoginRunning, setNaverLoginRunning] = useState(false);

  async function setupNaverLogin() {
    setNaverLoginRunning(true);
    setRegenMsg('Chrome 창 열림 — 로그인 후 창 닫아주세요 (5분 안)');
    try {
      const start = await api.post<any>('/products/naver-login-setup', {timeout_min: 5});
      const taskId = start.data.task_id;
      // poll
      while (true) {
        await new Promise(r => setTimeout(r, 3000));
        let t;
        try { const r = await api.get<any>(`/tasks/${taskId}`); t = r.data; }
        catch { continue; }
        if (t.status === 'completed') {
          setRegenMsg(`✓ ${t.message}`);
          setNeedsNaverLogin(false);
          break;
        }
        if (t.status === 'failed') {
          setRegenMsg(`✗ ${t.message}`);
          break;
        }
      }
    } catch (e: any) {
      setRegenMsg(`✗ ${e?.message || e}`);
    } finally {
      setNaverLoginRunning(false);
    }
  }

  async function regenerateFromUrl() {
    const url = (edit.product_url || '').trim();
    if (!url) { setRegenMsg('URL 먼저 입력하세요'); return; }
    const isNaver = /naver\.com\/.+\/products\//.test(url);
    const isCoupang = /coupang\.com\//.test(url);
    if (!isNaver && !isCoupang) {
      setRegenMsg('네이버 smartstore/brand 또는 쿠팡 URL 만 지원');
      return;
    }
    const productNameHint = (edit.product_name || '').trim();
    // Coupang 도 메인 Chrome 확장 경유 (AKAMAI 우회) — product_name 강제 입력 불필요
    setRegenerating(true);
    setRegenMsg('백엔드 task 시작...');
    setRegenProgress({cur:0, total:5, msg:''});
    try {
      // 1. 즉시 task_id 받기 — category + qoo10_url (R, 5/3) 도 전달
      const start = await api.post<any>('/products/regenerate-content-from-url', {
        url, async: true, product_name: productNameHint,
        category: (edit.category || '').trim() || undefined,
        qoo10_url: (edit.qoo10_url || '').trim() || undefined,
      });
      const taskId = start.data.task_id;
      const total = start.data.total || 5;
      if (!taskId) {
        setRegenMsg('✗ task 시작 실패');
        return;
      }

      // 2. 폴링 (1.5s 간격)
      const pollOnce = async (): Promise<any> => {
        const r = await api.get<any>(`/tasks/${taskId}`);
        return r.data;
      };

      let result: any = null;
      const pollDeadline = Date.now() + 5 * 60_000; // 안전망: 5분 hard timeout
      while (true) {
        if (Date.now() > pollDeadline) {
          setRegenMsg('✗ 폴링 타임아웃 (5분)');
          return;
        }
        await new Promise(r => setTimeout(r, 1500));
        let t;
        try { t = await pollOnce(); }
        catch { continue; }
        const cur = t.progress || 0;
        const status = t.status || '';
        const msg = (t.message || '').slice(0, 80);
        setRegenProgress({cur, total, msg});
        if (status === 'completed') {
          // message 안에 결과 JSON
          try { result = JSON.parse(t.message); }
          catch { result = null; }
          break;
        }
        if (status === 'failed') {
          setRegenMsg(`✗ ${msg}`);
          return;
        }
        // 주의: cur === total 만으로는 break 하지 않음 — 백엔드 total 과 _progress 호출
        // 횟수가 어긋나면 (E 단계 추가 등) status='running' 인데 break 되어 "결과 파싱 실패" 발생.
        // status 가 명시적으로 completed/failed 가 될 때까지만 continue.
      }

      if (!result) {
        setRegenMsg('✗ 결과 파싱 실패');
        return;
      }
      if (result.error) {
        setRegenMsg(`✗ ${result.error}`);
        // IIII-1: Naver 로그인 필요 에러면 setup 버튼 표시
        if (result.error.includes('로그인 필요') || result.error.includes('nidlogin')) {
          setNeedsNaverLogin(true);
        }
        return;
      }
      setNeedsNaverLogin(false);

      // 시트 row 자동 업데이트
      const updates: any = {
        product_name: result.product_name,
        cover_image_url: result.cover_image_url,
        item_price_krw: result.item_price_krw,
        domestic_shipping_krw: result.domestic_shipping_krw ?? edit.domestic_shipping_krw,
        qoo10_title_jp: result.qoo10_title_jp,
        qoo10_tags: result.qoo10_tags,
        qoo10_marketing: result.qoo10_marketing,
        qoo10_marketing_ko: result.qoo10_marketing_ko ?? undefined,   // H (5/3) 한글 번역
        qoo10_option_name: result.qoo10_option_name,
        // R (5/3) 큐텐 경쟁가/배송 — qoo10_url 채워졌을 때만 응답에 포함
        competitor_price_jpy: result.competitor_price_jpy ?? edit.competitor_price_jpy,
        competitor_shipping_jpy: result.competitor_shipping_jpy ?? edit.competitor_shipping_jpy,
        // S (5/3) raw 옵션 — 빈 배열 도 의미있어 ?? 안 씀, 응답 우선
        domestic_options: result.domestic_options !== undefined ? result.domestic_options : edit.domestic_options,
        qoo10_options_raw: result.qoo10_options_raw !== undefined ? result.qoo10_options_raw : edit.qoo10_options_raw,
        qoo10_jp_detail: result.qoo10_jp_detail,
        match_decision: 'manual',
        // E (5/3): 다운로드된 로컬 이미지 경로 — /image 정적 서빙 (브라우저에서 표시 가능)
        cover_local_path: result.cover_local_path ?? undefined,
        detail_local_paths: result.detail_local_paths ?? undefined,
        image_folder: result.image_folder ?? undefined,
        // G (5/3): LLM 자동 분류 카테고리 — 시트 비어있던 경우만 채움
        category: result.category && !edit.category ? result.category : edit.category,
      };
      // H (5/3): 자동저장 — 사장님 직전 수동 편집 (edit) + 새 결과 (updates) 머지하여 한 번에 저장
      // 패널 닫지 않고도 영구 보존됨 (saveSheet → localStorage + cloudSync push).
      const merged = { ...edit, ...updates };
      onSave(merged);
      patch(updates);
      const tags = result.qoo10_tags?.length || 0;
      const mkt = result.qoo10_marketing?.length || 0;
      const jpDetail = result.qoo10_jp_detail && !result.qoo10_jp_detail.error;
      const shipping = result.shipping_text || '';
      const imgs = (result.cover_local_path ? 1 : 0) + (result.detail_local_paths?.length || 0);
      setRegenMsg(`✓ 자동 저장됨 (tags ${tags}, marketing ${mkt}${jpDetail ? ', JP 카피' : ''}${shipping ? `, 배송:${shipping}` : ''}${imgs ? `, 이미지 ${imgs}장` : ''})`);
    } catch (e: any) {
      setRegenMsg(`✗ ${e?.message || e}`);
    } finally {
      setRegenerating(false);
      setRegenProgress({cur:0, total:0, msg:''});
    }
  }

  function previewAltSku(alt: AltSku) {
    // 클릭 한 번 = preview 만 (한국 슬롯에 확대), 확정은 별도 버튼
    if (alt.is_current_cheapest) {
      setPreviewAlt(null);
      return;
    }
    setPreviewAlt(alt);
  }

  function confirmSwap(alt: AltSku) {
    if (alt.is_current_cheapest) return;
    onSave({
      product_name: alt.product_name,
      product_url: alt.product_url,
      cover_image_url: alt.cover_image_url,
      item_price_krw: alt.price_krw,
      match_decision: 'manual',  // 사장님 직접 선택
    });
    // FFF-2 — 사장님 수정 자동 기록 (학습 데이터)
    api.post('/sheet/correction', {
      keyword_jp: row.keyword_jp || '',
      keyword_kr: row.keyword_kr || '',
      decision_kind: 'swap',
      ai_choice_id: meta?.alt_skus?.find(a => a.is_current_cheapest)?.id || null,
      ai_choice_name: row.product_name || '',
      ai_choice_url: row.product_url || '',
      ai_choice_cover_url: row.cover_image_url || '',
      ai_image_score: meta?.match?.image_score,
      ai_name_score: meta?.match?.name_score,
      user_choice_id: alt.id,
      user_choice_name: alt.product_name,
      user_choice_url: alt.product_url,
      user_choice_cover_url: alt.cover_image_url,
    }).catch(() => { /* 실패해도 UI 영향 X */ });
    // SSS-1 — swap 시 큐텐 SEO 콘텐츠 자동 재생성
    if (row.keyword_jp) {
      api.post('/products/qoo10/generate-content', {
        keywords_jp: [row.keyword_jp],
        reset: true,
      }).catch(() => { /* 실패해도 UI 영향 X */ });
    }
    onClose();
  }

  return (
    <div className="fixed top-0 right-0 h-screen w-[600px] bg-white shadow-2xl border-l border-gray-200 z-30 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b bg-gray-50">
        <div>
          <div className="font-bold text-sm">{row.keyword_jp || row.product_name}</div>
          <div className="text-xs text-gray-500">{row.keyword_kr || row.product_name_ko}</div>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl px-2">×</button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3 text-xs">
        {loading && <div className="text-gray-500">메타 로딩...</div>}

        {/* PPP-1: 한국 검색 결과 0건 — 사장님이 직접 찾아야 하는 row */}
        {row.match_decision === 'needs_search' && (
          <div className="border-2 border-red-300 bg-red-50 rounded p-3">
            <div className="font-bold text-red-800 mb-2">🔍 한국 SKU 직접 검색 필요</div>
            <div className="text-red-700 mb-3 text-[11px]">
              자동화가 한국 쇼핑몰에서 적합한 SKU 를 못 찾았습니다.<br/>
              아래 링크에서 직접 한국 셀러 찾고, URL/가격/이미지를 시트에 입력하세요.
            </div>
            <div className="grid grid-cols-2 gap-2">
              <a href={`https://www.qoo10.jp/s/?keyword=${encodeURIComponent(row.keyword_jp || '')}`}
                target="_blank" rel="noreferrer"
                className="bg-orange-100 hover:bg-orange-200 text-orange-800 text-center py-1.5 rounded font-semibold text-[11px]">
                🛒 큐텐 검색
              </a>
              <a href={`https://search.shopping.naver.com/search/all?query=${encodeURIComponent(row.keyword_kr || row.keyword_jp || '')}`}
                target="_blank" rel="noreferrer"
                className="bg-green-100 hover:bg-green-200 text-green-800 text-center py-1.5 rounded font-semibold text-[11px]">
                🛍 네이버 검색
              </a>
              <a href={`https://www.coupang.com/np/search?q=${encodeURIComponent(row.keyword_kr || row.keyword_jp || '')}`}
                target="_blank" rel="noreferrer"
                className="bg-red-100 hover:bg-red-200 text-red-800 text-center py-1.5 rounded font-semibold text-[11px]">
                🅒 쿠팡 검색
              </a>
              <a href={`https://shopping.daum.net/search?q=${encodeURIComponent(row.keyword_kr || row.keyword_jp || '')}`}
                target="_blank" rel="noreferrer"
                className="bg-yellow-100 hover:bg-yellow-200 text-yellow-800 text-center py-1.5 rounded font-semibold text-[11px]">
                🔎 다음 쇼핑
              </a>
            </div>
            <div className="mt-2 text-[10px] text-gray-600">
              찾은 후 아래 입력란에 URL/가격/무게 직접 입력 → 매칭 라벨 자동 'manual' 변경
            </div>
          </div>
        )}

        {/* 큐텐 ↔ 한국 cover 큰 비교 (h-64) */}
        <div className="grid grid-cols-2 gap-2">
          <div>
            <div className="font-semibold text-gray-600 mb-1">큐텐 (cheapest)</div>
            {meta?.qoo10?.cover_image_url ? (
              <a href={meta.qoo10.cover_image_url} target="_blank" rel="noreferrer">
                <img src={meta.qoo10.cover_image_url} className="w-full h-64 object-contain bg-gray-50 border rounded hover:ring-2 hover:ring-blue-400" />
              </a>
            ) : <div className="w-full h-64 bg-gray-100 border rounded flex items-center justify-center text-gray-400">no image</div>}
            <div className="text-[10px] text-gray-500 mt-1 truncate" title={meta?.qoo10?.product_name_jp}>
              {meta?.qoo10?.product_name_jp || '-'}
            </div>
            {meta?.qoo10?.cover_description && (
              <div className="text-[10px] text-indigo-700 bg-indigo-50 border border-indigo-100 rounded px-1.5 py-1 mt-1"
                title="qwen2.5vl cover description (GGG-1)">
                👁 {meta.qoo10.cover_description}
              </div>
            )}
          </div>
          <div>
            <div className="font-semibold text-gray-600 mb-1 flex items-center justify-between">
              <span>{previewAlt ? <span className="text-amber-700">한국 (미리보기)</span> : '한국 (현재)'}</span>
              {previewAlt && (
                <span className="flex gap-1">
                  <button onClick={() => confirmSwap(previewAlt)}
                    className="text-[10px] bg-emerald-600 text-white px-1.5 py-0.5 rounded hover:bg-emerald-700">
                    ✓ 이 SKU 로 교체
                  </button>
                  <button onClick={() => setPreviewAlt(null)}
                    className="text-[10px] bg-gray-300 text-gray-800 px-1.5 py-0.5 rounded hover:bg-gray-400">
                    ↶ 취소
                  </button>
                </span>
              )}
            </div>
            {(() => {
              const showImg = previewAlt?.cover_image_url || row.cover_image_url;
              const showName = previewAlt?.product_name || row.product_name;
              const showDesc = previewAlt?.cover_description || meta?.domestic?.cover_description;
              return (
                <>
                  {showImg ? (
                    <a href={showImg} target="_blank" rel="noreferrer">
                      <img src={showImg}
                        className={`w-full h-64 object-contain bg-gray-50 border rounded hover:ring-2 hover:ring-blue-400 ${
                          previewAlt ? 'ring-2 ring-amber-400' : ''}`} />
                    </a>
                  ) : <div className="w-full h-64 bg-gray-100 border rounded flex items-center justify-center text-gray-400">no image</div>}
                  <div className="text-[10px] text-gray-500 mt-1 truncate" title={showName}>
                    {showName || '-'}
                    {previewAlt && (
                      <span className="ml-1 text-amber-700 font-bold">— {previewAlt.price_krw.toLocaleString()}원</span>
                    )}
                  </div>
                  {showDesc && (
                    <div className="text-[10px] text-indigo-700 bg-indigo-50 border border-indigo-100 rounded px-1.5 py-1 mt-1"
                      title="qwen2.5vl cover description (GGG-1)">
                      👁 {showDesc}
                    </div>
                  )}
                </>
              );
            })()}
          </div>
        </div>

        {/* 한국 ALT SKU — 적합도 DESC 정렬, 클릭 시 미리보기 → 확정은 한국 슬롯 버튼 (LLL-1) */}
        {sortedAlts.length > 0 && (
          <div className="border rounded p-2">
            <div className="font-semibold text-gray-700 mb-2">
              한국 다른 SKU ({sortedAlts.length}개) — 적합도 순 · 클릭 → 한국 슬롯 미리보기
            </div>
            <div className="grid grid-cols-3 gap-2">
              {sortedAlts.map((alt, idx) => {
                const isPrev = previewAlt?.id === alt.id;
                const isTopMatch = idx === 0 && (alt.image_score ?? 0) > 0;
                return (
                  <button key={alt.id}
                    onClick={() => previewAltSku(alt)}
                    className={`border rounded p-1 text-left hover:ring-2 hover:ring-amber-400 transition ${
                      alt.is_current_cheapest ? 'ring-2 ring-emerald-500 bg-emerald-50' :
                      isPrev ? 'ring-2 ring-amber-500 bg-amber-50' : 'bg-white'}`}
                    title={alt.cover_description ? `${alt.product_name}\n👁 ${alt.cover_description}` : alt.product_name}
                  >
                    <img src={alt.cover_image_url} className="w-full h-24 object-contain bg-gray-50 rounded" />
                    <div className="text-[10px] mt-1 truncate font-semibold flex justify-between">
                      <span>{alt.price_krw.toLocaleString()}원</span>
                      {alt.image_score != null && (
                        <span className={alt.image_score >= 0.7 ? 'text-emerald-700' :
                          alt.image_score >= 0.5 ? 'text-amber-700' : 'text-red-700'}>
                          img {alt.image_score.toFixed(2)}
                        </span>
                      )}
                    </div>
                    <div className="text-[10px] text-gray-500 truncate">{alt.product_name}</div>
                    {alt.cover_description && (
                      <div className="text-[9px] text-indigo-700 truncate" title={alt.cover_description}>
                        👁 {alt.cover_description}
                      </div>
                    )}
                    {alt.is_current_cheapest && <div className="text-[9px] text-emerald-700 font-bold">★ 현재 시트</div>}
                    {isTopMatch && !alt.is_current_cheapest && (
                      <div className="text-[9px] text-amber-700 font-bold">⭐ 적합도 1위</div>
                    )}
                    {isPrev && (
                      <div className="text-[9px] text-amber-800 font-bold">▶ 미리보기 중</div>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* 큐텐 원본 샘플 — 가격 ASC, 시각 비교용 */}
        {meta?.qoo10_samples && meta.qoo10_samples.length > 0 && (
          <div className="border rounded p-2">
            <div className="font-semibold text-gray-700 mb-2">큐텐 원본 ({meta.qoo10_samples.length}개, 가격 ASC)</div>
            <div className="grid grid-cols-4 gap-1">
              {meta.qoo10_samples.map(q => (
                <a key={q.id} href={q.product_url} target="_blank" rel="noreferrer"
                  onClick={(e) => {
                    e.preventDefault();
                    window.open(q.product_url, '_blank', 'popup,width=1400,height=900,left=100,top=50');
                  }}
                  className="border rounded p-1 hover:ring-2 hover:ring-blue-400"
                  title={q.cover_description ? `${q.product_name}\n👁 ${q.cover_description}` : q.product_name}>
                  <img src={q.cover_image_url} className="w-full h-20 object-contain bg-gray-50 rounded" />
                  <div className="text-[10px] mt-1 truncate font-semibold">¥{q.price_jpy.toLocaleString()}</div>
                  {q.cover_description && (
                    <div className="text-[9px] text-indigo-700 truncate" title={q.cover_description}>
                      👁 {q.cover_description}
                    </div>
                  )}
                </a>
              ))}
            </div>
          </div>
        )}

        {/* WWW-1: 한국 SKU 상세 페이지 이미지 (extras) — vision 점수 + 묘사 */}
        {meta?.domestic?.extras && meta.domestic.extras.length > 0 && (
          <div className="border rounded p-2">
            <div className="font-semibold text-gray-700 mb-2 flex items-center justify-between">
              <span>한국 상세 이미지 ({meta.domestic.extras.length}개, 점수순)</span>
              <span className="text-[10px] text-gray-500">vision 평가 (qwen2.5vl)</span>
            </div>
            <div className="grid grid-cols-4 gap-1">
              {meta.domestic.extras.map((ex, i) => {
                const sc = ex.score;
                const scColor = sc == null ? 'text-gray-400'
                  : sc >= 0.9 ? 'text-emerald-700 font-bold'
                  : sc >= 0.6 ? 'text-amber-700'
                  : sc >= 0.3 ? 'text-gray-600'
                  : 'text-red-600';
                const url = ex.path?.startsWith('http')
                  ? ex.path
                  : `/${ex.path?.replace(/\\/g, '/')}`;
                return (
                  <a key={i} href={url} target="_blank" rel="noreferrer"
                    className="border rounded p-1 hover:ring-2 hover:ring-blue-400 block"
                    title={ex.desc ? `score=${sc?.toFixed(2) ?? '-'}\n${ex.desc}` : `score=${sc?.toFixed(2) ?? '-'}`}>
                    <img src={url} className="w-full h-20 object-contain bg-gray-50 rounded" />
                    <div className={`text-[10px] mt-1 truncate ${scColor}`}>
                      {sc != null ? `score ${sc.toFixed(2)}` : '미평가'}
                    </div>
                    {ex.desc && (
                      <div className="text-[9px] text-gray-500 truncate" title={ex.desc}>
                        {ex.desc}
                      </div>
                    )}
                  </a>
                );
              })}
            </div>
            <div className="text-[10px] text-gray-400 mt-1">
              💡 score 0.9+ 녹색 = 좋은 컷 (등록용), 0.3- 빨강 = 텍스트/저화질
            </div>
          </div>
        )}

        {/* 매칭 사유 */}
        {meta?.match && (
          <div className={`border rounded p-2 ${
            meta.match.decision === 'needs_review' ? 'bg-amber-100 border-amber-400' : 'bg-amber-50'}`}>
            <div className="font-semibold text-gray-700 mb-1 flex items-center gap-2">
              매칭
              {meta.match.decision === 'needs_review' && (
                <span className="text-amber-800 text-[10px] font-bold">⚠ 사장님 검수 우선</span>
              )}
            </div>
            <div className="flex gap-3">
              <span>img <b>{meta.match.image_score?.toFixed(2) ?? '-'}</b></span>
              <span>txt <b>{meta.match.name_score?.toFixed(2) ?? '-'}</b></span>
              {meta.match.quality_score != null && (
                <span title="결합 품질 점수 (image+text+description)">
                  Q <b className={
                    meta.match.quality_score >= 0.7 ? 'text-emerald-700' :
                    meta.match.quality_score >= 0.5 ? 'text-amber-700' : 'text-red-700'
                  }>{meta.match.quality_score.toFixed(2)}</b>
                </span>
              )}
              <span className={`px-1 py-0.5 rounded text-[10px] ${
                meta.match.decision === 'accepted' ? 'bg-emerald-100 text-emerald-800' :
                meta.match.decision === 'needs_review' ? 'bg-amber-200 text-amber-900 font-bold' :
                meta.match.decision === 'rejected' ? 'bg-red-100 text-red-700' : 'bg-gray-100'
              }`}>{meta.match.decision}</span>
            </div>
            {meta.match.note && <div className="text-gray-600 mt-1 text-[11px]">{meta.match.note}</div>}
          </div>
        )}

        {/* 한국 URL / 원가 / 무게 (인플레이스 편집) */}
        <div className="border rounded p-2 space-y-2">
          <div className="font-semibold text-gray-700 flex items-center justify-between">
            <span>한국 상품 정보 (직접 편집)</span>
          </div>
          <div>
            <label className="block text-gray-500 mb-0.5">URL</label>
            <div className="flex gap-1">
              <input type="text" value={edit.product_url || ''}
                onChange={e => patch({ product_url: e.target.value })}
                className="flex-1 border rounded px-1 py-0.5 text-[11px]"
                placeholder="https://smartstore.naver.com/.../products/... 또는 brand.naver.com/.../products/..." />
              <button
                onClick={regenerateFromUrl}
                disabled={regenerating || !edit.product_url}
                className="relative px-2 py-0.5 bg-purple-600 text-white text-[11px] rounded hover:bg-purple-700 disabled:bg-gray-400 whitespace-nowrap overflow-hidden min-w-[140px]"
                title="URL 의 한국 SKU 정보 + 큐텐 SEO + JP 상세 카피 자동 재생성"
              >
                {regenerating && regenProgress.total > 0 && (
                  <span
                    className="absolute inset-0 bg-purple-800 transition-all"
                    style={{ width: `${(regenProgress.cur / regenProgress.total) * 100}%` }}
                  />
                )}
                <span className="relative z-10">
                  {regenerating
                    ? `⏳ ${Math.round((regenProgress.cur / Math.max(regenProgress.total, 1)) * 100)}% (${regenProgress.cur}/${regenProgress.total})`
                    : '🔄 URL 로 SEO 재생성'}
                </span>
              </button>
            </div>
            {regenMsg && (
              <div className={`text-[10px] mt-1 ${
                regenMsg.startsWith('✓') ? 'text-emerald-700' :
                regenMsg.startsWith('✗') ? 'text-red-700' :
                'text-gray-500'
              }`}>{regenMsg}</div>
            )}
            {regenerating && regenProgress.msg && (
              <div className="text-[10px] mt-0.5 text-purple-700 truncate" title={regenProgress.msg}>
                ▸ {regenProgress.msg}
              </div>
            )}
            {/* IIII-1: Naver 로그인 setup — 항상 표시 (작은 버튼) */}
            <div className="mt-1 flex items-center gap-2 text-[10px]">
              <button
                onClick={setupNaverLogin}
                disabled={naverLoginRunning}
                className={`px-2 py-0.5 rounded text-[10px] ${
                  needsNaverLogin
                    ? 'bg-amber-600 text-white hover:bg-amber-700'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                } disabled:bg-gray-400`}
                title="Naver 로그인 cookies 1회 설정 (만료 시 재실행)"
              >
                {naverLoginRunning ? '⏳ Chrome 열림 — 로그인 후 닫기' : '🔐 Naver 로그인 setup'}
              </button>
              {needsNaverLogin && (
                <span className="text-amber-700 font-bold">← 클릭 (로그인 필요)</span>
              )}
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className="block text-gray-500 mb-0.5">구매가 (원)</label>
              <input type="number" value={edit.item_price_krw || ''}
                onChange={e => patch({ item_price_krw: Number(e.target.value) || 0 })}
                className="w-full border rounded px-1 py-0.5 text-right"
                title="한국 셀러 상품 단가 (item_price_krw)" />
            </div>
            <div>
              <label className="block text-gray-500 mb-0.5">구매배송 (원)</label>
              <input type="number" value={edit.domestic_shipping_krw || ''}
                onChange={e => patch({ domestic_shipping_krw: Number(e.target.value) || 0 })}
                className="w-full border rounded px-1 py-0.5 text-right"
                title="구매처 → 사장님 사무실 배송비 (domestic_shipping_krw)" />
            </div>
            <div>
              <label className="block text-gray-500 mb-0.5">무게 (g)</label>
              <input type="number" value={edit.weight_g || ''}
                onChange={e => patch({ weight_g: Number(e.target.value) || 0 })}
                className="w-full border rounded px-1 py-0.5 text-right" />
            </div>
          </div>
          <div className="text-[10px] text-gray-500 mt-1">
            합계 (구매가 + 구매배송): {((edit.item_price_krw || 0) + (edit.domestic_shipping_krw || 0)).toLocaleString()}원
          </div>
        </div>

        {/* 큐텐 SEO 콘텐츠 (인플레이스 편집) */}
        <div className="border rounded p-2 space-y-2 bg-yellow-50">
          <div className="font-semibold text-gray-700">큐텐 등록 콘텐츠 (직접 편집)</div>

          <div>
            <label className="block text-gray-500 mb-0.5">
              title_jp (최대 100자, 첫 30자 핵심)
              <span className="ml-2 text-[10px] text-gray-400">
                현재: {(edit.qoo10_title_jp || '').length}자
              </span>
            </label>
            <input type="text" value={edit.qoo10_title_jp || ''}
              onChange={e => patch({ qoo10_title_jp: e.target.value })}
              className="w-full border rounded px-1 py-0.5" maxLength={100}
              title="큐텐 가이드: 100자 이내, 첫 30자에 핵심 키워드, 브랜드 중복 X, 특수문자 X, 이벤트 문구 X (marketing_points 에)" />
          </div>

          <div>
            <label className="block text-gray-500 mb-0.5">tags ({(edit.qoo10_tags || []).length}/10)</label>
            <div className="flex flex-wrap gap-1 mb-1">
              {(edit.qoo10_tags || []).map((t, i) => (
                <span key={i} className="bg-white border border-blue-300 text-blue-700 text-[10px] px-1.5 py-0.5 rounded flex items-center gap-1">
                  {t}
                  <button onClick={() => removeTag(i)} className="hover:text-red-500">×</button>
                </span>
              ))}
            </div>
            <div className="flex gap-1">
              <input value={newTag} onChange={e => setNewTag(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && addTag()}
                placeholder="새 태그 + Enter"
                className="flex-1 border rounded px-1 py-0.5 text-[11px]" />
              <button onClick={addTag} className="bg-blue-600 text-white px-2 rounded text-[11px]">+</button>
            </div>
          </div>

          <div>
            <label className="block text-gray-500 mb-0.5">
              marketing_points ({(edit.qoo10_marketing || []).length}/4)
              <span className="ml-2 text-[10px] text-gray-400">
                각 30자 이내 / 의태어+약사법회피 (qoo10-jp-detail-master 가이드)
              </span>
            </label>
            <ul className="space-y-2 mb-1">
              {(edit.qoo10_marketing || []).map((p, i) => {
                const len = (p || '').length;
                const lenColor = len > 30 ? 'text-red-600' : 'text-gray-400';
                const ko = (edit.qoo10_marketing_ko || [])[i] || '';
                return (
                  <li key={i} className="flex gap-1 items-start">
                    <span className="text-purple-700 font-bold text-[10px] mt-1 w-8 shrink-0">P{i+1}</span>
                    <div className="flex-1 flex flex-col gap-0.5">
                      <textarea value={p} onChange={e => updatePoint(i, e.target.value)}
                        rows={2}
                        placeholder={`패턴 ${['A 효과/편의성','B 성분/기술','C 사용감/디자인','D 이벤트(送料無料 等)'][i] || ''} — 의태어 + 약사법 회피 (印象/サポート)`}
                        className="border rounded px-1.5 py-1 text-[11px] resize-y" />
                      {/* H (5/3) 한글 번역 — 사장님 검수용. 큐텐 등록 X. 인플레이스 편집 가능. */}
                      <input type="text" value={ko} onChange={e => updatePointKo(i, e.target.value)}
                        placeholder="(한글 번역 — 사장님 검수용)"
                        className="border border-gray-200 rounded px-1.5 py-0.5 text-[10px] text-gray-600 bg-gray-50" />
                    </div>
                    <div className="flex flex-col gap-0.5">
                      <span className={`text-[9px] ${lenColor}`}>{len}자</span>
                      <button onClick={() => removePoint(i)} className="text-gray-400 hover:text-red-500 text-xs">×</button>
                    </div>
                  </li>
                );
              })}
            </ul>
            <div className="flex gap-1">
              <textarea value={newPoint} onChange={e => setNewPoint(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) addPoint(); }}
                rows={2}
                placeholder="새 마케팅 포인트 (Ctrl/Cmd + Enter)"
                className="flex-1 border rounded px-1.5 py-1 text-[11px] resize-y" />
              <button onClick={addPoint} className="bg-blue-600 text-white px-2 rounded text-[11px] self-start">+</button>
            </div>
            <div className="text-[9px] text-gray-500 mt-1">
              💡 패턴 분산 권장: <strong>A</strong> 효과 (예: "1日10分で本格ケア♪"),
              <strong> B</strong> 성분 (예: "コラーゲン*配合"),
              <strong> C</strong> 사용감 (예: "ぴたっと密着"),
              <strong> D</strong> 이벤트 (예: "送料無料 正規品")
            </div>
          </div>

          <div>
            <label className="block text-gray-500 mb-0.5">
              option_name (UUU-1: ' | ' separator)
              <span className="ml-2 text-[10px] text-gray-400">
                단품 / 3個セット / 5+1セット / リフィル付き 등
              </span>
            </label>
            <input type="text" value={edit.qoo10_option_name || ''}
              onChange={e => patch({ qoo10_option_name: e.target.value })}
              placeholder="単品 | 3個セット | 5+1セット"
              className="w-full border rounded px-1 py-0.5"
              title="옵션 여러 개면 ' | ' separator. 한국 옵션을 일본어 친숙 표현으로 (UUU-1)" />
          </div>

          {/* S (5/3) 옵션 비교 — 한국 셀러 raw + 큐텐 경쟁자 raw */}
          {((edit.domestic_options?.length || 0) > 0 || (edit.qoo10_options_raw?.length || 0) > 0) && (
            <div>
              <div className="block text-gray-500 mb-1 mt-1.5 flex items-center gap-2">
                <span>옵션 비교</span>
                <span className="text-[9px] text-gray-400">참고용 raw 데이터 (큐텐 등록 옵션 결정 시 활용)</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="border rounded p-1.5 bg-gray-50">
                  <div className="text-[10px] font-semibold text-gray-700 mb-1">
                    한국 ({edit.domestic_options?.length || 0})
                  </div>
                  {(edit.domestic_options?.length || 0) === 0 ? (
                    <div className="text-[10px] text-gray-400 italic">옵션 없음 (또는 미수집)</div>
                  ) : (
                    <ul className="text-[10px] max-h-28 overflow-y-auto space-y-0.5">
                      {edit.domestic_options!.map((o, i) => (
                        <li key={i} className="flex justify-between gap-1">
                          <span className="truncate" title={o.name}>{o.name}</span>
                          <span className="font-mono text-gray-500 shrink-0">
                            {o.price_krw ? `${o.price_krw.toLocaleString()}원` : ''}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="border rounded p-1.5 bg-gray-50">
                  <div className="text-[10px] font-semibold text-gray-700 mb-1">
                    큐텐 경쟁자 ({edit.qoo10_options_raw?.length || 0})
                  </div>
                  {(edit.qoo10_options_raw?.length || 0) === 0 ? (
                    <div className="text-[10px] text-gray-400 italic">옵션 없음 (또는 미수집)</div>
                  ) : (
                    <ul className="text-[10px] max-h-28 overflow-y-auto space-y-0.5">
                      {edit.qoo10_options_raw!.map((o, i) => (
                        <li key={i} className="flex justify-between gap-1">
                          <span className="truncate" title={o.name}>{o.name}</span>
                          <span className="font-mono text-gray-500 shrink-0">
                            {o.price_jpy ? `¥${o.price_jpy.toLocaleString()}` : ''}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* 옵션 풀세트 */}
        {meta?.options_full && meta.options_full.length > 0 && (
          <div className="border rounded p-2">
            <div className="font-semibold text-gray-700 mb-1">한국 옵션 ({meta.options_full.length}개)</div>
            <ul className="text-[11px] text-gray-700 max-h-32 overflow-y-auto">
              {meta.options_full.map((o, i) => (
                <li key={i} className="border-b last:border-0 py-0.5">
                  · {o.name} {o.price_krw ? `— ${o.price_krw.toLocaleString()}원` : ''}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* EEEE-1: JP 상세페이지 카피 + 한글 번역 (qoo10-jp-detail-master.md 가이드) */}
        <details className="border-2 border-purple-300 rounded p-2 bg-purple-50" open>
          <summary className="font-semibold text-purple-800 cursor-pointer">
            📄 JP 상세페이지 카피 (한글 번역 포함, 가이드 준수)
            {!row.qoo10_jp_detail && (
              <span className="ml-2 text-[10px] text-gray-500 font-normal">(데이터 없음 — URL 재생성 필요)</span>
            )}
            {row.qoo10_jp_detail?.error && (
              <span className="ml-2 text-[10px] text-red-600 font-normal">(생성 오류)</span>
            )}
            {row.qoo10_jp_detail && !row.qoo10_jp_detail.error && (
              <span className="ml-2 text-[10px] text-emerald-700 font-normal">✓ 생성됨</span>
            )}
          </summary>
          {!row.qoo10_jp_detail && (
            <div className="mt-2 text-[11px] text-gray-600 bg-white rounded p-2 border border-dashed">
              💡 위 "한국 상품 정보" 섹션에서 <strong>URL 입력 → [🔄 URL 로 SEO 재생성]</strong> 클릭하면<br/>
              여기에 자동 생성됩니다 (qoo10-jp-detail-master.md 가이드 적용).
            </div>
          )}
          {row.qoo10_jp_detail?.error && (
            <div className="mt-2 text-[11px] text-red-700 bg-white rounded p-2 border border-red-200">
              생성 오류: {row.qoo10_jp_detail.error}
            </div>
          )}
        {row.qoo10_jp_detail && !row.qoo10_jp_detail.error && (
          <>
            <div className="mt-2 space-y-3 text-[11px]">
              {/* 인트로 */}
              {row.qoo10_jp_detail.intro && (
                <div>
                  <div className="font-bold text-gray-700 mb-1">[인트로]</div>
                  {row.qoo10_jp_detail.intro.pain_points && (
                    <div className="mb-2">
                      <div className="text-gray-500 text-[10px]">고민 포인트 (4)</div>
                      {row.qoo10_jp_detail.intro.pain_points.map((p: any, i: number) => (
                        <div key={i} className="grid grid-cols-2 gap-1 border-b py-0.5">
                          <span className="text-blue-700">{p.jp}</span>
                          <span className="text-gray-600">{p.ko}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {row.qoo10_jp_detail.intro.official_name && (
                    <div className="grid grid-cols-2 gap-1 mb-1">
                      <span className="text-blue-700"><b>정식명:</b> {row.qoo10_jp_detail.intro.official_name.jp}</span>
                      <span className="text-gray-600">{row.qoo10_jp_detail.intro.official_name.ko}</span>
                    </div>
                  )}
                  {row.qoo10_jp_detail.intro.main_headline && (
                    <div className="grid grid-cols-2 gap-1 mb-1">
                      <span className="text-blue-700"><b>헤드라인:</b><br/>
                        {row.qoo10_jp_detail.intro.main_headline.line1?.jp} / {row.qoo10_jp_detail.intro.main_headline.line2?.jp}
                      </span>
                      <span className="text-gray-600">{row.qoo10_jp_detail.intro.main_headline.line1?.ko} / {row.qoo10_jp_detail.intro.main_headline.line2?.ko}</span>
                    </div>
                  )}
                  {row.qoo10_jp_detail.intro.hero_number && (
                    <div className="grid grid-cols-2 gap-1 mb-1">
                      <span className="text-blue-700 font-bold text-base">{row.qoo10_jp_detail.intro.hero_number.jp}</span>
                      <span className="text-gray-600">{row.qoo10_jp_detail.intro.hero_number.ko}</span>
                    </div>
                  )}
                  {row.qoo10_jp_detail.intro.benefit_description && (
                    <div className="grid grid-cols-2 gap-1 mb-1">
                      <span className="text-blue-700">
                        {row.qoo10_jp_detail.intro.benefit_description.line1?.jp} →<br/>
                        {row.qoo10_jp_detail.intro.benefit_description.line2?.jp}
                      </span>
                      <span className="text-gray-600">
                        {row.qoo10_jp_detail.intro.benefit_description.line1?.ko} →<br/>
                        {row.qoo10_jp_detail.intro.benefit_description.line2?.ko}
                      </span>
                    </div>
                  )}
                </div>
              )}

              {/* POINT 1-3 */}
              {Array.isArray(row.qoo10_jp_detail.points) && row.qoo10_jp_detail.points.map((pt: any, i: number) => (
                <div key={i} className="border-t pt-2">
                  <div className="font-bold text-gray-700 mb-1">
                    [{pt.badge}] <span className="text-[9px] text-gray-500">({pt.type})</span>
                  </div>
                  {pt.headline && (
                    <div className="grid grid-cols-2 gap-1 mb-1">
                      <span className="text-blue-700 font-semibold">
                        {pt.headline.line1?.jp}<br/>{pt.headline.line2?.jp}
                      </span>
                      <span className="text-gray-600">
                        {pt.headline.line1?.ko}<br/>{pt.headline.line2?.ko}
                      </span>
                    </div>
                  )}
                  {Array.isArray(pt.description) && pt.description.map((d: any, j: number) => (
                    <div key={j} className="grid grid-cols-2 gap-1 text-[10px] text-gray-600 ml-2">
                      <span>· {d.jp}</span>
                      <span>· {d.ko}</span>
                    </div>
                  ))}
                </div>
              ))}

              {/* 추천 */}
              {row.qoo10_jp_detail.target && (
                <div className="border-t pt-2">
                  <div className="font-bold text-gray-700 mb-1">
                    [{row.qoo10_jp_detail.target.header?.jp}]
                    <span className="text-[9px] text-gray-500 ml-2">({row.qoo10_jp_detail.target.header?.ko})</span>
                  </div>
                  {Array.isArray(row.qoo10_jp_detail.target.bullets) && row.qoo10_jp_detail.target.bullets.map((b: any, i: number) => (
                    <div key={i} className="grid grid-cols-2 gap-1 border-b py-0.5">
                      <span className="text-blue-700">{b.jp}</span>
                      <span className="text-gray-600">{b.ko}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* 면책 */}
              {Array.isArray(row.qoo10_jp_detail.footnotes) && row.qoo10_jp_detail.footnotes.length > 0 && (
                <div className="border-t pt-2 text-[9px] text-gray-500">
                  <div className="font-bold mb-0.5">[면책]</div>
                  {row.qoo10_jp_detail.footnotes.map((f: any, i: number) => (
                    <div key={i}>{f.jp} <span className="text-gray-400">({f.ko})</span></div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
        </details>
      </div>

      {/* Footer */}
      <div className="border-t p-3 bg-gray-50 flex gap-2">
        <button onClick={() => { onSave(edit); onClose(); }}
          className="flex-1 bg-blue-600 text-white py-1.5 rounded font-semibold hover:bg-blue-700">
          저장
        </button>
        {onReject && (
          <button onClick={() => {
            onReject();
            // FFF-2 — 거부 기록
            api.post('/sheet/correction', {
              keyword_jp: row.keyword_jp || '',
              keyword_kr: row.keyword_kr || '',
              decision_kind: 'reject',
              ai_choice_id: row.id ? Number(row.id) : null,
              ai_choice_name: row.product_name || '',
              ai_choice_url: row.product_url || '',
              ai_choice_cover_url: row.cover_image_url || '',
              ai_image_score: meta?.match?.image_score,
              ai_name_score: meta?.match?.name_score,
            }).catch(() => {});
            onClose();
          }}
            className="px-3 bg-gray-200 hover:bg-gray-300 py-1.5 rounded text-xs">
            거부
          </button>
        )}
        {onBlacklist && (
          <button
            onClick={onBlacklist}
            className="px-3 bg-red-50 text-red-700 border border-red-200 py-1.5 rounded text-xs hover:bg-red-100"
            title="이 상품/키워드를 블랙리스트에 추가하고 시트에서 제거. 자동화에서 더 이상 추가 안 됨."
          >
            ⛔ 블랙리스트
          </button>
        )}
        <button onClick={onClose}
          className="px-3 bg-white border py-1.5 rounded text-xs hover:bg-gray-100">
          닫기
        </button>
      </div>
    </div>
  );
}

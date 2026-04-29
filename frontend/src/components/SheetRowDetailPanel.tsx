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
  };
  match?: {
    image_score: number | null;
    name_score: number | null;
    note: string;
    decision: string;
  };
  options_full?: { name: string; price_krw: number | null; in_stock: boolean }[];
  alt_skus?: { id: number; source: string; product_name: string; price_krw: number;
    product_url: string; cover_image_url: string; image_score: number | null;
    is_current_cheapest: boolean }[];
  qoo10_samples?: { id: number; product_name: string; product_name_ko: string;
    price_jpy: number; product_url: string; cover_image_url: string }[];
};

type Props = {
  row: SheetRow;
  onClose: () => void;
  onSave: (updated: Partial<SheetRow>) => void;
  onReject?: () => void;
};

export default function SheetRowDetailPanel({ row, onClose, onSave, onReject }: Props) {
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

  useEffect(() => {
    const kw = row.keyword_jp || row.product_name;
    if (!kw) return;
    setLoading(true);
    api.get<RowMeta>(`/sheet/row-meta`, { params: { keyword_jp: kw, product_name: row.product_name } })
      .then(r => setMeta(r.data))
      .catch(() => setMeta(null))
      .finally(() => setLoading(false));
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
    patch({ qoo10_marketing: (edit.qoo10_marketing || []).filter((_, idx) => idx !== i) });
  }

  function updatePoint(i: number, v: string) {
    const arr = [...(edit.qoo10_marketing || [])];
    arr[i] = v;
    patch({ qoo10_marketing: arr });
  }

  function selectAltSku(alt: NonNullable<RowMeta['alt_skus']>[number]) {
    if (alt.is_current_cheapest) return;
    if (!confirm(`이 한국 SKU 로 swap?\n${alt.product_name.slice(0, 40)} (${alt.price_krw.toLocaleString()}원)`)) return;
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
          </div>
          <div>
            <div className="font-semibold text-gray-600 mb-1">한국 (cheapest)</div>
            {row.cover_image_url ? (
              <a href={row.cover_image_url} target="_blank" rel="noreferrer">
                <img src={row.cover_image_url} className="w-full h-64 object-contain bg-gray-50 border rounded hover:ring-2 hover:ring-blue-400" />
              </a>
            ) : <div className="w-full h-64 bg-gray-100 border rounded flex items-center justify-center text-gray-400">no image</div>}
            <div className="text-[10px] text-gray-500 mt-1 truncate" title={row.product_name}>
              {row.product_name || '-'}
            </div>
          </div>
        </div>

        {/* 한국 ALT SKU — 클릭 시 swap (FFF-1) */}
        {meta?.alt_skus && meta.alt_skus.length > 0 && (
          <div className="border rounded p-2">
            <div className="font-semibold text-gray-700 mb-2">한국 다른 SKU ({meta.alt_skus.length}개) — 클릭 시 swap</div>
            <div className="grid grid-cols-3 gap-2">
              {meta.alt_skus.map(alt => (
                <button key={alt.id}
                  onClick={() => selectAltSku(alt)}
                  className={`border rounded p-1 text-left hover:ring-2 hover:ring-blue-400 transition ${
                    alt.is_current_cheapest ? 'ring-2 ring-emerald-500 bg-emerald-50' : 'bg-white'}`}
                  title={alt.product_name}
                >
                  <img src={alt.cover_image_url} className="w-full h-24 object-contain bg-gray-50 rounded" />
                  <div className="text-[10px] mt-1 truncate font-semibold">{alt.price_krw.toLocaleString()}원</div>
                  <div className="text-[10px] text-gray-500 truncate">{alt.product_name}</div>
                  {alt.is_current_cheapest && <div className="text-[9px] text-emerald-700 font-bold">★ 현재 시트</div>}
                </button>
              ))}
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
                  className="border rounded p-1 hover:ring-2 hover:ring-blue-400" title={q.product_name}>
                  <img src={q.cover_image_url} className="w-full h-20 object-contain bg-gray-50 rounded" />
                  <div className="text-[10px] mt-1 truncate font-semibold">¥{q.price_jpy.toLocaleString()}</div>
                </a>
              ))}
            </div>
          </div>
        )}

        {/* 매칭 사유 */}
        {meta?.match && (
          <div className="border rounded p-2 bg-amber-50">
            <div className="font-semibold text-gray-700 mb-1">매칭</div>
            <div className="flex gap-3">
              <span>img <b>{meta.match.image_score?.toFixed(2) ?? '-'}</b></span>
              <span>txt <b>{meta.match.name_score?.toFixed(2) ?? '-'}</b></span>
              <span className={`px-1 py-0.5 rounded text-[10px] ${
                meta.match.decision === 'accepted' ? 'bg-emerald-100 text-emerald-800' :
                meta.match.decision === 'rejected' ? 'bg-red-100 text-red-700' : 'bg-gray-100'
              }`}>{meta.match.decision}</span>
            </div>
            {meta.match.note && <div className="text-gray-600 mt-1 text-[11px]">{meta.match.note}</div>}
          </div>
        )}

        {/* 한국 URL / 원가 / 무게 (인플레이스 편집) */}
        <div className="border rounded p-2 space-y-2">
          <div className="font-semibold text-gray-700">한국 상품 정보 (직접 편집)</div>
          <div>
            <label className="block text-gray-500 mb-0.5">URL</label>
            <input type="text" value={edit.product_url || ''}
              onChange={e => patch({ product_url: e.target.value })}
              className="w-full border rounded px-1 py-0.5 text-[11px]" />
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
              <label className="block text-gray-500 mb-0.5">국내배송 (원)</label>
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
            합계 (구매가 + 국내배송): {((edit.item_price_krw || 0) + (edit.domestic_shipping_krw || 0)).toLocaleString()}원
          </div>
        </div>

        {/* 큐텐 SEO 콘텐츠 (인플레이스 편집) */}
        <div className="border rounded p-2 space-y-2 bg-yellow-50">
          <div className="font-semibold text-gray-700">큐텐 등록 콘텐츠 (직접 편집)</div>

          <div>
            <label className="block text-gray-500 mb-0.5">title_jp (40자 이내)</label>
            <input type="text" value={edit.qoo10_title_jp || ''}
              onChange={e => patch({ qoo10_title_jp: e.target.value })}
              className="w-full border rounded px-1 py-0.5" maxLength={40} />
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
            <label className="block text-gray-500 mb-0.5">marketing_points ({(edit.qoo10_marketing || []).length}/4)</label>
            <ul className="space-y-1 mb-1">
              {(edit.qoo10_marketing || []).map((p, i) => (
                <li key={i} className="flex gap-1 items-start">
                  <span className="text-gray-400 mt-0.5">•</span>
                  <input value={p} onChange={e => updatePoint(i, e.target.value)}
                    className="flex-1 border rounded px-1 py-0.5 text-[11px]" />
                  <button onClick={() => removePoint(i)} className="text-gray-400 hover:text-red-500 px-1">×</button>
                </li>
              ))}
            </ul>
            <div className="flex gap-1">
              <input value={newPoint} onChange={e => setNewPoint(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && addPoint()}
                placeholder="새 마케팅 포인트 + Enter"
                className="flex-1 border rounded px-1 py-0.5 text-[11px]" />
              <button onClick={addPoint} className="bg-blue-600 text-white px-2 rounded text-[11px]">+</button>
            </div>
          </div>

          <div>
            <label className="block text-gray-500 mb-0.5">option_name (단품/3個セット 등)</label>
            <input type="text" value={edit.qoo10_option_name || ''}
              onChange={e => patch({ qoo10_option_name: e.target.value })}
              className="w-full border rounded px-1 py-0.5" />
          </div>
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
        <button onClick={onClose}
          className="px-3 bg-white border py-1.5 rounded text-xs hover:bg-gray-100">
          닫기
        </button>
      </div>
    </div>
  );
}

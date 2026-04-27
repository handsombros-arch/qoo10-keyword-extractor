import { useEffect, useState } from 'react';
import { fetchCloud, pushCloud } from '../store/cloudSync';

const DEFAULT_THRESHOLD = 0.9;

const ALL_CATEGORIES = [
  '03.뷰티&화장품',
  '06.홈&생활',
  '07.식품',
  '09.베이비&키즈',
  '12.서플리먼트&다이어트',
  '기타',
];
const DEFAULT_CATEGORIES = [
  '03.뷰티&화장품',
  '07.식품',
  '12.서플리먼트&다이어트',
];

interface ThresholdPayload {
  value: number;
}
interface CategoriesPayload {
  value: string[];
}
interface FilterThresholdsPayload {
  competition_max: number;
  kr_ratio_min: number;
  volume_min: number;
}

const DEFAULT_FILTER_THRESHOLDS: FilterThresholdsPayload = {
  competition_max: 2.0,
  kr_ratio_min: 0.3,
  volume_min: 40,
};

export default function SettingsPage() {
  const [threshold, setThreshold] = useState<number>(DEFAULT_THRESHOLD);
  const [thLoading, setThLoading] = useState<boolean>(true);
  const [thSaving, setThSaving] = useState<boolean>(false);
  const [thSavedAt, setThSavedAt] = useState<string | null>(null);
  const [thError, setThError] = useState<string | null>(null);

  const [categories, setCategories] = useState<string[]>(DEFAULT_CATEGORIES);
  const [catLoading, setCatLoading] = useState<boolean>(true);
  const [catSaving, setCatSaving] = useState<boolean>(false);
  const [catSavedAt, setCatSavedAt] = useState<string | null>(null);
  const [catError, setCatError] = useState<string | null>(null);

  const [filterThresholds, setFilterThresholds] = useState<FilterThresholdsPayload>(DEFAULT_FILTER_THRESHOLDS);
  const [ftLoading, setFtLoading] = useState<boolean>(true);
  const [ftSaving, setFtSaving] = useState<boolean>(false);
  const [ftSavedAt, setFtSavedAt] = useState<string | null>(null);
  const [ftError, setFtError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const t = await fetchCloud<ThresholdPayload>('brand_auto_add_threshold');
      if (!cancelled) {
        if (t.data && typeof t.data.value === 'number') setThreshold(t.data.value);
        setThSavedAt(t.updated_at);
        setThLoading(false);
      }
      const c = await fetchCloud<CategoriesPayload>('auto_filter_categories');
      if (!cancelled) {
        if (c.data && Array.isArray(c.data.value)) setCategories(c.data.value);
        setCatSavedAt(c.updated_at);
        setCatLoading(false);
      }
      const ft = await fetchCloud<FilterThresholdsPayload>('auto_filter_thresholds');
      if (!cancelled) {
        if (ft.data && typeof ft.data.competition_max === 'number') {
          setFilterThresholds({
            competition_max: ft.data.competition_max,
            kr_ratio_min: ft.data.kr_ratio_min,
            volume_min: ft.data.volume_min,
          });
        }
        setFtSavedAt(ft.updated_at);
        setFtLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const saveThreshold = async () => {
    setThSaving(true); setThError(null);
    try {
      const ok = await pushCloud<ThresholdPayload>('brand_auto_add_threshold', { value: threshold });
      if (ok) setThSavedAt(new Date().toISOString());
      else setThError('저장 실패. 백엔드 연결을 확인하세요.');
    } finally { setThSaving(false); }
  };

  const saveCategories = async () => {
    setCatSaving(true); setCatError(null);
    try {
      const ok = await pushCloud<CategoriesPayload>('auto_filter_categories', { value: categories });
      if (ok) setCatSavedAt(new Date().toISOString());
      else setCatError('저장 실패. 백엔드 연결을 확인하세요.');
    } finally { setCatSaving(false); }
  };

  const toggleCategory = (label: string) => {
    setCategories((prev) =>
      prev.includes(label) ? prev.filter((c) => c !== label) : [...prev, label]
    );
  };

  const saveFilterThresholds = async () => {
    setFtSaving(true); setFtError(null);
    try {
      const ok = await pushCloud<FilterThresholdsPayload>('auto_filter_thresholds', filterThresholds);
      if (ok) setFtSavedAt(new Date().toISOString());
      else setFtError('저장 실패. 백엔드 연결을 확인하세요.');
    } finally { setFtSaving(false); }
  };

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <h2 className="text-xl font-bold mb-2">⚙️ AI 설정</h2>
      <p className="text-sm text-gray-600 mb-6">
        두 PC 가 같은 Supabase 를 보므로 변경 사항은 즉시 양쪽에 반영됩니다.
      </p>

      {/* 1) 자동 필터 카테고리 화이트리스트 */}
      <section className="bg-white rounded shadow p-5 border mb-6">
        <h3 className="font-semibold text-base mb-1">자동 필터 카테고리 화이트리스트</h3>
        <p className="text-xs text-gray-500 mb-4">
          야간 자동화 STEP 4 (자동 필터) 에서 통과시킬 카테고리. 체크 안 된 카테고리의 키워드는 제외.
          모두 체크 해제하면 백엔드는 <code>.env</code> <code>AUTO_FILTER_CATEGORIES</code> 또는 전체 통과로 폴백.
        </p>

        {catLoading ? (
          <div className="text-sm text-gray-500">불러오는 중…</div>
        ) : (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mb-4">
              {ALL_CATEGORIES.map((label) => (
                <label key={label} className="flex items-center gap-2 px-3 py-2 border rounded cursor-pointer hover:bg-gray-50">
                  <input
                    type="checkbox"
                    checked={categories.includes(label)}
                    onChange={() => toggleCategory(label)}
                    disabled={catSaving}
                  />
                  <span className="text-sm">{label}</span>
                </label>
              ))}
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={saveCategories}
                disabled={catSaving}
                className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:bg-gray-400"
              >
                {catSaving ? '저장 중…' : '저장'}
              </button>
              <button
                onClick={() => setCategories(DEFAULT_CATEGORIES)}
                disabled={catSaving}
                className="px-4 py-2 bg-gray-100 rounded text-sm hover:bg-gray-200"
              >
                기본값으로 (뷰티/식품/서플리먼트)
              </button>
              {catError && <span className="text-sm text-red-600 ml-2">{catError}</span>}
              {!catError && catSavedAt && (
                <span className="text-xs text-gray-400 ml-2">
                  저장됨: {new Date(catSavedAt).toLocaleString('ko-KR')}
                </span>
              )}
            </div>
            <div className="text-xs text-gray-400 mt-2">
              현재 선택: {categories.length === 0 ? '(없음 — 백엔드 폴백)' : categories.join(', ')}
            </div>
          </>
        )}
      </section>

      {/* 2) 자동 필터 임계값 (3개 슬라이더) */}
      <section className="bg-white rounded shadow p-5 border mb-6">
        <h3 className="font-semibold text-base mb-1">자동 필터 임계값</h3>
        <p className="text-xs text-gray-500 mb-4">
          매일 야간 자동화 시 키워드 필터 기준. 한 가지라도 미달이면 그 날 추천에서 제외.
          기본 — 경쟁강도 ≤ 2.0 / 한국비율 ≥ 0.3 / 검색량 ≥ 40.
        </p>

        {ftLoading ? (
          <div className="text-sm text-gray-500">불러오는 중…</div>
        ) : (
          <>
            {/* 경쟁강도 최대 */}
            <div className="mb-4">
              <div className="flex items-center justify-between mb-1">
                <label className="text-sm">경쟁강도 최대</label>
                <span className="text-xs text-gray-500">현재: <strong>{filterThresholds.competition_max.toFixed(2)}</strong> 이하 통과</span>
              </div>
              <div className="flex items-center gap-3">
                <input type="range" min={0.5} max={5.0} step={0.1}
                  value={filterThresholds.competition_max}
                  onChange={(e) => setFilterThresholds(p => ({...p, competition_max: parseFloat(e.target.value)}))}
                  className="flex-1" disabled={ftSaving}
                />
                <input type="number" min={0} max={10} step={0.1}
                  value={filterThresholds.competition_max}
                  onChange={(e) => {
                    const v = parseFloat(e.target.value);
                    if (!Number.isNaN(v)) setFilterThresholds(p => ({...p, competition_max: Math.max(0, v)}));
                  }}
                  className="w-20 px-2 py-1 border rounded text-right" disabled={ftSaving}
                />
              </div>
              <div className="flex justify-between text-xs text-gray-400 mt-1">
                <span>0.5 (엄격)</span><span>2.0 (기본)</span><span>5.0 (관대)</span>
              </div>
            </div>

            {/* 한국비율 최소 */}
            <div className="mb-4">
              <div className="flex items-center justify-between mb-1">
                <label className="text-sm">한국 상품 비율 최소</label>
                <span className="text-xs text-gray-500">현재: <strong>{(filterThresholds.kr_ratio_min*100).toFixed(0)}%</strong> 이상 통과</span>
              </div>
              <div className="flex items-center gap-3">
                <input type="range" min={0} max={1.0} step={0.05}
                  value={filterThresholds.kr_ratio_min}
                  onChange={(e) => setFilterThresholds(p => ({...p, kr_ratio_min: parseFloat(e.target.value)}))}
                  className="flex-1" disabled={ftSaving}
                />
                <input type="number" min={0} max={1} step={0.05}
                  value={filterThresholds.kr_ratio_min}
                  onChange={(e) => {
                    const v = parseFloat(e.target.value);
                    if (!Number.isNaN(v)) setFilterThresholds(p => ({...p, kr_ratio_min: Math.min(1, Math.max(0, v))}));
                  }}
                  className="w-20 px-2 py-1 border rounded text-right" disabled={ftSaving}
                />
              </div>
              <div className="flex justify-between text-xs text-gray-400 mt-1">
                <span>0% (관대)</span><span>30% (기본)</span><span>100% (엄격)</span>
              </div>
            </div>

            {/* 검색량 최소 */}
            <div className="mb-4">
              <div className="flex items-center justify-between mb-1">
                <label className="text-sm">일 검색량 최소</label>
                <span className="text-xs text-gray-500">현재: <strong>{filterThresholds.volume_min}</strong> 이상 통과</span>
              </div>
              <div className="flex items-center gap-3">
                <input type="range" min={0} max={500} step={5}
                  value={filterThresholds.volume_min}
                  onChange={(e) => setFilterThresholds(p => ({...p, volume_min: parseInt(e.target.value, 10)}))}
                  className="flex-1" disabled={ftSaving}
                />
                <input type="number" min={0} max={10000} step={1}
                  value={filterThresholds.volume_min}
                  onChange={(e) => {
                    const v = parseInt(e.target.value, 10);
                    if (!Number.isNaN(v)) setFilterThresholds(p => ({...p, volume_min: Math.max(0, v)}));
                  }}
                  className="w-24 px-2 py-1 border rounded text-right" disabled={ftSaving}
                />
              </div>
              <div className="flex justify-between text-xs text-gray-400 mt-1">
                <span>0 (관대)</span><span>40 (기본)</span><span>500 (엄격)</span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button onClick={saveFilterThresholds} disabled={ftSaving}
                className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:bg-gray-400">
                {ftSaving ? '저장 중…' : '저장'}
              </button>
              <button onClick={() => setFilterThresholds(DEFAULT_FILTER_THRESHOLDS)} disabled={ftSaving}
                className="px-4 py-2 bg-gray-100 rounded text-sm hover:bg-gray-200">
                기본값으로
              </button>
              {ftError && <span className="text-sm text-red-600 ml-2">{ftError}</span>}
              {!ftError && ftSavedAt && (
                <span className="text-xs text-gray-400 ml-2">
                  저장됨: {new Date(ftSavedAt).toLocaleString('ko-KR')}
                </span>
              )}
            </div>
          </>
        )}
      </section>

      {/* 3) 브랜드 자동 추가 임계값 */}
      <section className="bg-white rounded shadow p-5 border">
        <h3 className="font-semibold text-base mb-1">브랜드 자동 추가 임계값</h3>
        <p className="text-xs text-gray-500 mb-4">
          LLM이 신규 브랜드라고 판별했을 때, <code className="bg-gray-100 px-1 rounded">confidence</code> 가
          이 값 <strong>이상</strong> 이면 <code className="bg-gray-100 px-1 rounded">brands</code> 테이블에 자동 추가합니다.
          높을수록 보수적 (오탐 ↓, 누락 ↑). 기본 {DEFAULT_THRESHOLD}.
        </p>

        {thLoading ? (
          <div className="text-sm text-gray-500">불러오는 중…</div>
        ) : (
          <>
            <div className="flex items-center gap-4 mb-3">
              <input
                type="range" min={0.5} max={1.0} step={0.05}
                value={threshold}
                onChange={(e) => setThreshold(parseFloat(e.target.value))}
                className="flex-1"
                disabled={thSaving}
              />
              <input
                type="number" min={0} max={1} step={0.01}
                value={threshold}
                onChange={(e) => {
                  const v = parseFloat(e.target.value);
                  if (!Number.isNaN(v)) setThreshold(Math.min(1, Math.max(0, v)));
                }}
                className="w-20 px-2 py-1 border rounded text-right"
                disabled={thSaving}
              />
            </div>

            <div className="flex justify-between text-xs text-gray-400 mb-4">
              <span>0.5 (관대)</span>
              <span>0.9 (기본)</span>
              <span>1.0 (엄격)</span>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={saveThreshold}
                disabled={thSaving}
                className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:bg-gray-400"
              >
                {thSaving ? '저장 중…' : '저장'}
              </button>
              <button
                onClick={() => setThreshold(DEFAULT_THRESHOLD)}
                disabled={thSaving}
                className="px-4 py-2 bg-gray-100 rounded text-sm hover:bg-gray-200"
              >
                기본값으로
              </button>
              {thError && <span className="text-sm text-red-600 ml-2">{thError}</span>}
              {!thError && thSavedAt && (
                <span className="text-xs text-gray-400 ml-2">
                  저장됨: {new Date(thSavedAt).toLocaleString('ko-KR')}
                </span>
              )}
            </div>
          </>
        )}
      </section>

      <section className="mt-6 bg-gray-50 rounded p-4 border text-xs text-gray-600">
        <h4 className="font-semibold mb-1">참고</h4>
        <ul className="list-disc list-inside space-y-1">
          <li>카테고리 화이트리스트는 <code>UserData.auto_filter_categories</code> 에 저장.</li>
          <li>설정이 없으면 <code>.env</code> 의 <code>AUTO_FILTER_CATEGORIES</code>, 그것도 없으면 전체 통과.</li>
          <li>임계값은 <code>UserData.brand_auto_add_threshold</code>, 폴백은 <code>.env</code> <code>BRAND_AUTO_ADD_THRESHOLD</code>.</li>
          <li>모델 라우팅(<code>CATEGORY_MODEL</code> 등)은 <code>.env</code> 에서 변경 후 백엔드 재시작 필요.</li>
        </ul>
      </section>
    </div>
  );
}

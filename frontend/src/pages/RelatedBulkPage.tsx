import { useState } from 'react';
import api from '../api/client';
import TaskProgressPanel from '../components/common/TaskProgressPanel';

interface PlatformOpt {
  key: string;
  label: string;
  enabled: boolean;
  defaultChecked: boolean;
}

const LEFT_PLATFORMS: PlatformOpt[] = [
  { key: 'qoo10_ad_related', label: '큐텐 키워드광고 연관 키워드', enabled: true, defaultChecked: true },
  { key: 'qoo10_autocomplete', label: '큐텐 자동완성 키워드', enabled: true, defaultChecked: true },
  { key: 'qoo10_related', label: '큐텐 연관 키워드', enabled: true, defaultChecked: true },
  { key: 'amazon_autocomplete', label: '아마존재팬 자동완성 키워드', enabled: true, defaultChecked: true },
  { key: 'amazon_related', label: '아마존재팬 연관 키워드', enabled: true, defaultChecked: true },
];
const MID_PLATFORMS: PlatformOpt[] = [
  { key: 'yahoo_autocomplete', label: '야후재팬 자동완성 키워드', enabled: true, defaultChecked: true },
  { key: 'yahoo_related', label: '야후재팬 연관 키워드', enabled: true, defaultChecked: true },
  { key: 'yahoo_shopping_autocomplete', label: '야후재팬 쇼핑 자동완성 키워드', enabled: true, defaultChecked: true },
  { key: 'yahoo_shopping_related', label: '야후재팬 쇼핑 연관 키워드', enabled: true, defaultChecked: true },
];
const RIGHT_PLATFORMS: PlatformOpt[] = [
  { key: 'rakuten_autocomplete', label: '라쿠텐 자동완성 키워드', enabled: false, defaultChecked: false },
  { key: 'rakuten_related', label: '라쿠텐 연관 키워드', enabled: false, defaultChecked: false },
  { key: 'hotoku', label: '핫코 키워드 에서 가져오기', enabled: false, defaultChecked: false },
  { key: 'keyword_tool', label: 'Keyword Tool 에서 가져오기', enabled: false, defaultChecked: false },
];

export default function RelatedBulkPage() {
  const [ja, setJa] = useState('');
  const [ko, setKo] = useState('');
  const [platforms, setPlatforms] = useState<Record<string, boolean>>(() => {
    const map: Record<string, boolean> = {};
    [...LEFT_PLATFORMS, ...MID_PLATFORMS, ...RIGHT_PLATFORMS].forEach(p => { map[p.key] = p.defaultChecked; });
    return map;
  });
  const [removeZero, setRemoveZero] = useState(false);
  const [runCompetition, setRunCompetition] = useState(false);
  const [runBid, setRunBid] = useState(false);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const toggle = (key: string) => setPlatforms(prev => ({ ...prev, [key]: !prev[key] }));

  const submit = async () => {
    const jaList = ja.split(/[\n,]/).map(s => s.trim()).filter(Boolean);
    const koList = ko.split(/[\n,]/).map(s => s.trim()).filter(Boolean);
    if (jaList.length === 0 && koList.length === 0) {
      setMsg('키워드를 1개 이상 입력하세요.');
      return;
    }
    setLoading(true);
    setMsg(null);
    try {
      const res = await api.post('/related/collect', {
        keywords_ja: jaList,
        keywords_ko: koList,
        qoo10_ad_related: platforms.qoo10_ad_related,
        qoo10_autocomplete: platforms.qoo10_autocomplete,
        qoo10_related: platforms.qoo10_related,
        amazon_autocomplete: platforms.amazon_autocomplete,
        amazon_related: platforms.amazon_related,
        yahoo_autocomplete: platforms.yahoo_autocomplete,
        yahoo_related: platforms.yahoo_related,
        yahoo_shopping_autocomplete: platforms.yahoo_shopping_autocomplete,
        yahoo_shopping_related: platforms.yahoo_shopping_related,
        remove_zero_search: removeZero,
        run_competition: runCompetition,
        run_bid: runBid,
      });
      if (res.data.error) setMsg(`오류: ${res.data.error}`);
      else setMsg(res.data.message || '수집 시작됨');
    } catch (e: any) {
      setMsg(`오류: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const renderGroup = (list: PlatformOpt[]) => (
    <div className="space-y-1">
      {list.map(p => (
        <label key={p.key} className={`flex items-center gap-2 text-sm ${p.enabled ? '' : 'text-gray-400'}`}>
          <input
            type="checkbox"
            checked={!!platforms[p.key]}
            disabled={!p.enabled}
            onChange={() => toggle(p.key)}
          />
          <span>{p.label}</span>
        </label>
      ))}
    </div>
  );

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">🔗 연관 키워드 일괄 가져오기</h2>

      <TaskProgressPanel />

      <div className="bg-amber-50 border-l-4 border-amber-400 text-xs p-3 mb-4 rounded">
        ※ 주의: QSM에 로그인 후 이용하셔야 정상 동작됩니다.
      </div>

      <div className="bg-white rounded-lg shadow p-5 mb-4">
        <h3 className="font-bold mb-3">1. 키워드 입력란</h3>
        <p className="text-xs text-gray-500 mb-3">
          각 언어에 맞는 입력창에 입력해주세요 (일본어, 한국어 둘 다 입력해도 됩니다). 엔터 또는 콤마로 구분, 최대 20개.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-semibold text-gray-700 mb-1">일본어로 입력</label>
            <textarea
              value={ja}
              onChange={e => setJa(e.target.value)}
              rows={6}
              placeholder="例: カラコン&#10;美容液"
              className="w-full border rounded px-3 py-2 text-sm font-mono"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-700 mb-1">한국어로 입력</label>
            <textarea
              value={ko}
              onChange={e => setKo(e.target.value)}
              rows={6}
              placeholder="예: 컬러렌즈&#10;미용액"
              className="w-full border rounded px-3 py-2 text-sm font-mono"
            />
          </div>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow p-5 mb-4">
        <h3 className="font-bold mb-3">2. 가져올 플랫폼 선택</h3>
        <p className="text-xs text-gray-500 mb-3">
          ※ 연관 키워드를 가져오지 않고 입력한 키워드만 분석하고 싶으면 아무것도 선택하지 않으면 됩니다.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {renderGroup(LEFT_PLATFORMS)}
          {renderGroup(MID_PLATFORMS)}
          {renderGroup(RIGHT_PLATFORMS)}
        </div>
      </div>

      <div className="bg-white rounded-lg shadow p-5 mb-4">
        <h3 className="font-bold mb-3">추가 기능</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={removeZero} onChange={e => setRemoveZero(e.target.checked)} />
            검색수 0 키워드 제거
          </label>
          <label className="flex items-center gap-2 text-gray-400">
            <input type="checkbox" checked={runCompetition} onChange={e => setRunCompetition(e.target.checked)} disabled />
            경쟁강도 분석 이어서 하기 (미구현)
          </label>
          <label className="flex items-center gap-2 text-gray-400">
            <input type="checkbox" checked={runBid} onChange={e => setRunBid(e.target.checked)} disabled />
            경매낙찰가 분석 이어서 하기 (미구현)
          </label>
        </div>
      </div>

      <div className="flex justify-end items-center gap-3">
        {msg && <span className="text-sm text-gray-700">{msg}</span>}
        <button
          onClick={submit}
          disabled={loading}
          className="px-8 py-3 bg-gray-900 text-white text-base rounded hover:bg-black disabled:opacity-50"
        >
          {loading ? '처리 중...' : '가져오기'}
        </button>
      </div>
    </div>
  );
}

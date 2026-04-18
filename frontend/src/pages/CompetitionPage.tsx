import { useState } from 'react';
import { analyzeCompetition } from '../api/endpoints';
import ProgressBar from '../components/common/ProgressBar';
import { useSSE } from '../hooks/useSSE';

export default function CompetitionPage() {
  const [input, setInput] = useState('');
  const [taskId, setTaskId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const task = useSSE(taskId);

  const handleAnalyze = async () => {
    if (!input.trim()) return;
    setLoading(true);
    try {
      const kws = input.split('\n').map(s => s.trim()).filter(Boolean);
      const res = await analyzeCompetition(kws);
      if (res.data.task_id) setTaskId(res.data.task_id);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">경쟁강도 분석</h2>

      <ProgressBar task={task} />

      <div className="bg-white rounded-lg shadow p-5 mb-4">
        <h3 className="font-semibold mb-3">키워드 경쟁강도 분석</h3>
        <p className="text-sm text-gray-500 mb-3">
          키워드별로 Qoo10에서 전체 상품수와 국가별 상품수를 조회하고, 검색수 대비 경쟁강도를 계산합니다.
        </p>
        <div className="flex gap-3 items-end">
          <div className="flex-1">
            <label className="block text-sm text-gray-600 mb-1">키워드 (줄바꿈 구분)</label>
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              rows={4}
              className="border rounded px-3 py-2 text-sm w-full"
              placeholder="분석할 키워드를 입력하세요 (일본어)"
            />
          </div>
          <button
            onClick={handleAnalyze}
            disabled={loading}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
          >
            분석 시작
          </button>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow p-5">
        <p className="text-sm text-gray-500">
          분석 결과는 키워드 페이지의 경쟁강도, 전체상품수 컬럼에 반영됩니다.
        </p>
      </div>
    </div>
  );
}

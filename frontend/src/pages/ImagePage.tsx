import { useEffect, useRef, useState } from 'react';
import api from '../api/client';

interface Capability {
  has_cuda: boolean;
  gpu_name?: string;
  vram_gb?: number;
  device?: string;
}

const REGIONS = [
  { v: 'bottom-right', label: '우하단 (Gemini)' },
  { v: 'bottom-left', label: '좌하단' },
  { v: 'top-right', label: '우상단' },
  { v: 'top-left', label: '좌상단' },
];

export default function ImagePage() {
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [resultUrl, setResultUrl] = useState<string | null>(null);
  const [processing, setProcessing] = useState(false);
  const [region, setRegion] = useState('bottom-right');
  const [marginPct, setMarginPct] = useState(12);
  const [capability, setCapability] = useState<Capability | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.get('/image/capability').then(r => setCapability(r.data)).catch(() => {});
  }, []);

  const onPick = (f: File) => {
    setFile(f);
    setResultUrl(null);
    setError(null);
    const url = URL.createObjectURL(f);
    setPreviewUrl(url);
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const f = e.dataTransfer.files?.[0];
    if (f && f.type.startsWith('image/')) onPick(f);
  };

  const process = async () => {
    if (!file) return;
    setProcessing(true);
    setError(null);
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('region', region);
      form.append('margin_pct', String(marginPct));
      const res = await api.post('/image/remove-watermark', form, {
        responseType: 'blob',
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      const url = URL.createObjectURL(res.data);
      setResultUrl(url);
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || '처리 실패');
    } finally {
      setProcessing(false);
    }
  };

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">🎨 이미지 워터마크 제거 (LaMa)</h2>

      {capability && (
        <div className="text-xs text-gray-600 mb-3">
          실행 환경: {capability.device?.toUpperCase()}
          {capability.gpu_name && <> ({capability.gpu_name}, VRAM {capability.vram_gb}GB)</>}
          {!capability.has_cuda && <span className="text-amber-600 ml-2">⚠ CPU 모드 — 이미지당 5~10초 소요</span>}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* 왼쪽: 업로드/설정 */}
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="font-semibold mb-3">1. 이미지 선택</h3>

          <div
            onDrop={onDrop}
            onDragOver={e => e.preventDefault()}
            onClick={() => inputRef.current?.click()}
            className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center cursor-pointer hover:border-blue-400 hover:bg-blue-50 mb-3"
          >
            {previewUrl ? (
              <img src={previewUrl} alt="원본" className="max-h-80 mx-auto" />
            ) : (
              <div>
                <div className="text-3xl mb-2">📁</div>
                <div className="text-sm text-gray-600">여기에 이미지 드롭 또는 클릭해서 선택</div>
                <div className="text-xs text-gray-400 mt-1">PNG, JPG, WebP</div>
              </div>
            )}
            <input
              ref={inputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={e => { const f = e.target.files?.[0]; if (f) onPick(f); }}
            />
          </div>

          <h3 className="font-semibold mb-2 mt-4">2. 제거 영역 지정</h3>
          <div className="grid grid-cols-2 gap-2 mb-3">
            {REGIONS.map(r => (
              <button
                key={r.v}
                onClick={() => setRegion(r.v)}
                className={`px-3 py-2 text-sm rounded border ${region === r.v ? 'bg-blue-600 text-white border-blue-600' : 'bg-white border-gray-300 hover:bg-gray-50'}`}
              >{r.label}</button>
            ))}
          </div>

          <div className="mb-3">
            <div className="flex justify-between text-xs mb-1">
              <span className="text-gray-600">영역 크기 (가장자리에서부터 %)</span>
              <span className="font-semibold text-blue-700">{marginPct}%</span>
            </div>
            <input
              type="range" min={3} max={30} step={1}
              value={marginPct}
              onChange={e => setMarginPct(Number(e.target.value))}
              className="w-full accent-blue-600"
            />
          </div>

          <button
            onClick={process}
            disabled={!file || processing}
            className="w-full py-3 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {processing ? '⏳ 처리 중... (수 초 소요)' : '🎨 워터마크 제거'}
          </button>

          {error && <div className="mt-3 text-xs text-red-600 bg-red-50 p-2 rounded">{error}</div>}
        </div>

        {/* 오른쪽: 결과 */}
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="font-semibold mb-3">결과</h3>
          {!resultUrl && !processing && (
            <div className="text-center text-gray-400 py-20 text-sm">
              왼쪽에서 이미지 처리하면 여기에 결과 표시
            </div>
          )}
          {processing && (
            <div className="text-center text-gray-500 py-20">
              <div className="text-4xl mb-3 animate-pulse">⏳</div>
              <div className="text-sm">AI 처리 중...</div>
            </div>
          )}
          {resultUrl && (
            <>
              <img src={resultUrl} alt="결과" className="max-h-96 mx-auto mb-3" />
              <a
                href={resultUrl}
                download="cleaned.png"
                className="block w-full text-center py-2 bg-green-600 text-white text-sm rounded hover:bg-green-700"
              >
                💾 다운로드
              </a>
            </>
          )}
        </div>
      </div>

      <div className="bg-amber-50 border-l-4 border-amber-400 text-xs p-3 mt-4 rounded">
        <b>💡 사용 팁</b>
        <ul className="list-disc list-inside mt-1 space-y-0.5 text-gray-700">
          <li>Gemini 반짝이 워터마크: 우하단 12% 정도로 충분</li>
          <li>영역이 너무 작으면 일부 남을 수 있음, 너무 크면 주변이 흐려짐</li>
          <li>배경이 복잡할수록 AI 복원 퀄리티가 중요 (LaMa 기본 수준)</li>
          <li>결과가 아쉬우면 → 영역 조금 키워서 재시도</li>
        </ul>
      </div>
    </div>
  );
}

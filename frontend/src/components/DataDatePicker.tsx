import { useState, useRef, useEffect } from 'react';

/**
 * 데이터가 있는 날짜만 선택 가능한 경량 캘린더 (외부 의존성 없음).
 * 데이터 없는 날은 회색 + disabled(클릭 불가). 네이티브 <input type=date>는
 * 개별 날짜 비활성을 지원 안 해서 직접 구현.
 */
type Props = {
  value: string;             // 'YYYY-MM-DD' (없으면 '')
  availableDates: string[];  // 데이터 있는 날 'YYYY-MM-DD' (정렬됨)
  onChange: (d: string) => void;
  active?: boolean;          // 단일일 모드 강조
};

const WD = ['일', '월', '화', '수', '목', '금', '토'];
const pad = (n: number) => String(n).padStart(2, '0');
const todayStr = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };

export default function DataDatePicker({ value, availableDates, onChange, active }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const avail = new Set(availableDates);
  const baseStr = value || availableDates[availableDates.length - 1] || todayStr();
  const [view, setView] = useState(() => {
    const [y, m] = baseStr.split('-').map(Number);
    return { y, m: m - 1 };
  });

  // 열 때 선택값(또는 최신 데이터월)로 이동
  useEffect(() => {
    if (!open) return;
    const b = value || availableDates[availableDates.length - 1] || todayStr();
    const [y, m] = b.split('-').map(Number);
    setView({ y, m: m - 1 });
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  // 바깥 클릭 시 닫기
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, [open]);

  const firstDow = new Date(view.y, view.m, 1).getDay();
  const daysInMonth = new Date(view.y, view.m + 1, 0).getDate();
  const cells: (number | null)[] = [];
  for (let i = 0; i < firstDow; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);

  const prevMonth = () => setView(v => v.m === 0 ? { y: v.y - 1, m: 11 } : { y: v.y, m: v.m - 1 });
  const nextMonth = () => setView(v => v.m === 11 ? { y: v.y + 1, m: 0 } : { y: v.y, m: v.m + 1 });

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className={`border rounded px-2 py-1 text-sm ${active ? 'border-blue-500 ring-1 ring-blue-200 text-gray-900' : 'border-gray-300 text-gray-600'}`}
      >
        📅 {value ? value.slice(5) : '날짜'}
      </button>
      {open && (
        <div className="absolute z-50 mt-1 left-0 bg-white border rounded-lg shadow-lg p-2 w-60">
          <div className="flex items-center justify-between mb-1">
            <button type="button" onClick={prevMonth} className="px-2 py-0.5 rounded hover:bg-gray-100">◀</button>
            <span className="text-sm font-semibold">{view.y}.{pad(view.m + 1)}</span>
            <button type="button" onClick={nextMonth} className="px-2 py-0.5 rounded hover:bg-gray-100">▶</button>
          </div>
          <div className="grid grid-cols-7 gap-0.5 text-center">
            {WD.map((w, i) => (
              <div key={w} className={`text-[10px] py-0.5 ${i === 0 ? 'text-red-400' : i === 6 ? 'text-blue-400' : 'text-gray-400'}`}>{w}</div>
            ))}
            {cells.map((d, i) => {
              if (d == null) return <div key={`e${i}`} />;
              const ds = `${view.y}-${pad(view.m + 1)}-${pad(d)}`;
              const has = avail.has(ds);
              const sel = ds === value;
              return (
                <button
                  key={ds}
                  type="button"
                  disabled={!has}
                  onClick={() => { onChange(ds); setOpen(false); }}
                  title={has ? ds : '데이터 없음'}
                  className={[
                    'text-xs rounded py-1',
                    sel ? 'bg-blue-600 text-white font-bold'
                      : has ? 'hover:bg-blue-50 text-gray-800'
                      : 'text-gray-300 cursor-not-allowed',
                  ].join(' ')}
                >{d}</button>
              );
            })}
          </div>
          <div className="text-[10px] text-gray-400 mt-1 text-center">회색 날짜 = 수집 데이터 없음</div>
        </div>
      )}
    </div>
  );
}

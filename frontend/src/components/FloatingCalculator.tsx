/**
 * 플로팅 실시간 계산기 — 드래그로 위치 자유 이동.
 * - 자유 식 입력 (3000+500*2 등) → 실시간 계산
 * - ¥ ↔ 원 환산 (환율 사장님 직접 입력)
 * - 콤마 자동 strip
 * - 헤더 드래그로 위치 이동 (localStorage 영속)
 * - 토글 닫기 → 작은 아이콘 / 다시 열기 (드래그 가능)
 */
import { useEffect, useRef, useState } from 'react';
import { Calculator, ChevronDown, GripVertical } from 'lucide-react';

const RATE_KEY = 'floatingCalc.rate.v1';
const OPEN_KEY = 'floatingCalc.open.v1';
const POS_KEY = 'floatingCalc.pos.v1';
const WIDTH = 260;
const COLLAPSED = 44;

function safeCalc(expr: string): { ok: boolean; value: number } {
  if (!expr.trim()) return { ok: false, value: 0 };
  if (!/^[\d+\-*/().,\s]+$/.test(expr)) return { ok: false, value: 0 };
  try {
    const cleaned = expr.replace(/,/g, '');
    // eslint-disable-next-line no-new-func
    const v = Function(`"use strict"; return (${cleaned})`)();
    if (typeof v === 'number' && isFinite(v)) {
      return { ok: true, value: Math.round(v * 100) / 100 };
    }
  } catch { /* ignore */ }
  return { ok: false, value: 0 };
}

function defaultPos() {
  return {
    x: 16,
    y: typeof window !== 'undefined' ? Math.max(16, window.innerHeight - 360) : 200,
  };
}

export default function FloatingCalculator() {
  const [expr, setExpr] = useState('');
  const [rate, setRate] = useState<number>(() => {
    const v = Number(localStorage.getItem(RATE_KEY));
    return isFinite(v) && v > 0 ? v : 9.5;
  });
  const [open, setOpen] = useState<boolean>(() => localStorage.getItem(OPEN_KEY) !== '0');
  const [pos, setPos] = useState<{ x: number; y: number }>(() => {
    try {
      const raw = localStorage.getItem(POS_KEY);
      if (raw) {
        const p = JSON.parse(raw);
        if (typeof p?.x === 'number' && typeof p?.y === 'number') return p;
      }
    } catch { /* ignore */ }
    return defaultPos();
  });

  const setOpenP = (v: boolean) => {
    setOpen(v);
    localStorage.setItem(OPEN_KEY, v ? '1' : '0');
  };
  const setRateP = (v: number) => {
    setRate(v);
    localStorage.setItem(RATE_KEY, String(v));
  };

  // 드래그 — 헤더 또는 collapsed 버튼에서 mousedown
  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null);
  const onDragStart = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    dragRef.current = { startX: e.clientX, startY: e.clientY, origX: pos.x, origY: pos.y };
    e.preventDefault();
  };
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragRef.current) return;
      const dx = e.clientX - dragRef.current.startX;
      const dy = e.clientY - dragRef.current.startY;
      const w = open ? WIDTH : COLLAPSED;
      const h = open ? 280 : COLLAPSED;
      setPos({
        x: Math.max(0, Math.min(window.innerWidth - w, dragRef.current.origX + dx)),
        y: Math.max(0, Math.min(window.innerHeight - h, dragRef.current.origY + dy)),
      });
    };
    const onUp = () => { dragRef.current = null; };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [open]);
  // 위치 영속
  useEffect(() => {
    localStorage.setItem(POS_KEY, JSON.stringify(pos));
  }, [pos]);

  const r = safeCalc(expr);

  if (!open) {
    return (
      <button
        onMouseDown={onDragStart}
        onClick={(e) => {
          // 드래그 직후 click 방지: dragRef.current 가 null 이면 (mouseup 발생) 평범 클릭
          if (Math.abs(e.clientX - (dragRef.current?.startX ?? e.clientX)) < 3) setOpenP(true);
        }}
        className="fixed z-40 bg-apple-bg border rounded-full p-2.5 shadow-lg hover:shadow-xl transition-shadow cursor-move"
        style={{
          left: pos.x, top: pos.y,
          borderColor: 'var(--color-apple-border)',
        }}
        title="계산기 열기 (드래그로 이동)">
        <Calculator size={16} className="text-apple-accent" />
      </button>
    );
  }

  return (
    <div className="fixed z-40 bg-apple-bg border rounded-2xl"
      style={{
        left: pos.x, top: pos.y, width: WIDTH,
        borderColor: 'var(--color-apple-border)',
        boxShadow: '0 8px 30px rgba(0,0,0,0.12)',
      }}>
      {/* Header — 드래그 핸들 */}
      <div
        onMouseDown={onDragStart}
        className="flex items-center justify-between px-3 py-2 border-b cursor-move select-none"
        style={{ borderBottomColor: 'var(--color-apple-border)' }}>
        <div className="flex items-center gap-1.5 text-[12px] font-semibold tracking-tight">
          <GripVertical size={12} className="text-apple-text-3" />
          <Calculator size={13} className="text-apple-accent" /> 계산기
        </div>
        <button onClick={(e) => { e.stopPropagation(); setOpenP(false); }}
          onMouseDown={(e) => e.stopPropagation()}
          className="text-apple-text-3 hover:text-apple-text-1 cursor-pointer"
          title="최소화">
          <ChevronDown size={14} />
        </button>
      </div>
      <div className="p-3 space-y-2">
        <input
          autoFocus
          value={expr}
          onChange={e => setExpr(e.target.value)}
          placeholder="예: 3000+500*2 또는 12,345"
          className="w-full px-2 py-1.5 rounded-lg border text-[13px] font-mono outline-none focus:border-apple-accent"
          style={{ borderColor: 'var(--color-apple-border)', background: 'var(--color-apple-bg-2)' }}
        />
        <div className="text-right text-[18px] font-mono font-semibold tracking-tight">
          {expr.trim() === '' ? (
            <span className="text-apple-text-3 text-[14px]">결과 자동 표시</span>
          ) : r.ok ? (
            <span>= {r.value.toLocaleString()}</span>
          ) : (
            <span className="text-red-500 text-[12px]">식 오류</span>
          )}
        </div>
        {expr.trim() !== '' && (
          <button onClick={() => setExpr('')}
            className="w-full text-[11px] text-apple-text-3 hover:text-apple-accent">
            초기화
          </button>
        )}
        <div className="border-t pt-2" style={{ borderTopColor: 'var(--color-apple-border)' }}>
          <div className="flex items-center justify-between text-[11px] text-apple-text-3 mb-1.5">
            <span>환율 (1¥ = 원)</span>
            <input
              type="number"
              value={rate}
              onChange={e => {
                const v = Number(e.target.value);
                if (isFinite(v) && v > 0) setRateP(v);
              }}
              step="0.1"
              min="0.1"
              className="w-14 px-1.5 py-0.5 text-[11px] border rounded text-right outline-none focus:border-apple-accent"
              style={{ borderColor: 'var(--color-apple-border)', background: 'var(--color-apple-bg-2)' }}
            />
          </div>
          {r.ok && r.value > 0 && (
            <div className="text-[12px] font-mono space-y-0.5">
              <div className="flex justify-between">
                <span className="text-apple-text-3">¥{r.value.toLocaleString()}</span>
                <span className="text-apple-text-1 font-semibold">{Math.round(r.value * rate).toLocaleString()}원</span>
              </div>
              <div className="flex justify-between">
                <span className="text-apple-text-3">{r.value.toLocaleString()}원</span>
                <span className="text-apple-text-1 font-semibold">¥{Math.round(r.value / rate).toLocaleString()}</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

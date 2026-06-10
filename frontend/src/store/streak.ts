/**
 * 큐텐 등록 스트릭(연속일) — freeze 저장.
 * "등록한 날" 은 마진 시트의 registered_date 에서 파생(연동). freeze 만 별도 저장.
 */
import { pushCloud } from './cloudSync';

const FREEZE_KEY = 'streak.freezes.v1';

export function loadFreezes(): string[] {
  try {
    const raw = localStorage.getItem(FREEZE_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch { return []; }
}

export function saveFreezes(list: string[]): void {
  try {
    localStorage.setItem(FREEZE_KEY, JSON.stringify(list));
    pushCloud('streak_freezes', list).catch(() => {});
  } catch { /* ignore */ }
}

// ── 날짜 유틸 (브라우저 로컬 기준) ──
export const ymd = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
export const isWeekday = (d: Date) => { const x = d.getDay(); return x >= 1 && x <= 5; };

/** 현재 연속일(주말 제외, done 또는 freeze 면 유지). 오늘 미완료는 끊지 않음(진행중). */
export function computeStreak(done: Set<string>, frozen: Set<string>, today: Date): number {
  const t = new Date(today); t.setHours(0, 0, 0, 0);
  let cur = new Date(t);
  // 오늘이 평일인데 아직 미완료면 어제부터 카운트(오늘은 진행중 — 끊지 않음)
  if (isWeekday(cur) && !(done.has(ymd(cur)) || frozen.has(ymd(cur)))) cur.setDate(cur.getDate() - 1);
  let streak = 0;
  for (let i = 0; i < 1000; i++) {
    if (isWeekday(cur)) {
      const k = ymd(cur);
      if (done.has(k) || frozen.has(k)) streak++;
      else break;
    }
    cur.setDate(cur.getDate() - 1);
  }
  return streak;
}

/** 해당 달(YYYY-MM)에 이미 쓴 freeze 가 있나 */
export function freezeUsedInMonth(frozen: string[], yyyyMM: string): boolean {
  return frozen.some(d => d.slice(0, 7) === yyyyMM);
}

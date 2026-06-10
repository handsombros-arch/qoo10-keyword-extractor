import { useEffect, useMemo, useState } from 'react';
import { getLoginStatus, getCredentials, saveCredentials, deleteCredentials, startLogin, confirmLogin } from '../api/endpoints';
import type { LoginStatus } from '../types';
import { loadRows, type MarginRow } from '../store/marginSheet';
import { loadFreezes, saveFreezes, ymd, isWeekday, computeStreak, freezeUsedInMonth } from '../store/streak';
import { fetchCloud } from '../store/cloudSync';

const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토'];

// 큐텐 등록 스트릭 캘린더 — 마진 시트 등록일(registered_date) 연동, 주말 제외, 월 1회 freeze
function RegistrationStreak() {
  const today = useMemo(() => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; }, []);
  const [view, setView] = useState(() => new Date(today.getFullYear(), today.getMonth(), 1));
  const [tick, setTick] = useState(0);

  // 클라우드에서 마진시트·freeze 동기화
  useEffect(() => {
    (async () => {
      const [ms, fz] = await Promise.all([
        fetchCloud<MarginRow[]>('margin_sheet'),
        fetchCloud<string[]>('streak_freezes'),
      ]);
      if (ms.data && Array.isArray(ms.data)) localStorage.setItem('marginSheet.rows.v1', JSON.stringify(ms.data));
      if (fz.data && Array.isArray(fz.data)) localStorage.setItem('streak.freezes.v1', JSON.stringify(fz.data));
      setTick(t => t + 1);
    })();
  }, []);

  const { doneSet, frozenSet, frozenList } = useMemo(() => {
    void tick;
    const done = new Set<string>();
    loadRows().forEach((r: any) => {
      const v = r.registered_date;
      if (v && /^\d{4}-\d{2}-\d{2}$/.test(v)) done.add(v);
    });
    const fl = loadFreezes();
    return { doneSet: done, frozenSet: new Set(fl), frozenList: fl };
  }, [tick]);

  const streak = computeStreak(doneSet, frozenSet, today);
  const todayDone = doneSet.has(ymd(today)) || frozenSet.has(ymd(today));
  const todayMonth = ymd(today).slice(0, 7);
  const freezeAvailable = !freezeUsedInMonth(frozenList, todayMonth);
  const yearEnd = new Date(today.getFullYear(), 11, 31);
  const dday = Math.round((yearEnd.getTime() - today.getTime()) / 86400000);

  // 듀오링고식 카운트업 애니메이션 (대시보드 진입/값 변경 시 0 → streak 으로 차오름 + 팝)
  const [displayStreak, setDisplayStreak] = useState(0);
  const [pop, setPop] = useState(false);
  useEffect(() => {
    const duration = Math.min(1400, 350 + streak * 90);
    const start = performance.now();
    let raf = 0;
    const step = (t: number) => {
      const p = Math.min(1, (t - start) / duration);
      const eased = 1 - Math.pow(1 - p, 3);   // easeOutCubic
      setDisplayStreak(Math.round(streak * eased));
      if (p < 1) raf = requestAnimationFrame(step);
      else { setPop(true); window.setTimeout(() => setPop(false), 450); }
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [streak]);

  const applyFreeze = (dateKey: string) => {
    const m = dateKey.slice(0, 7);
    if (freezeUsedInMonth(frozenList, m)) { alert(`${m} 의 freeze 를 이미 사용했습니다. (한 달 1회)`); return; }
    if (!confirm(`${dateKey} 을(를) freeze 할까요?\n빠진 평일을 보호해 연속을 유지합니다. (한 달 1회)`)) return;
    saveFreezes([...frozenList, dateKey]);
    setTick(t => t + 1);
  };

  const y = view.getFullYear(), mo = view.getMonth();
  const firstDay = new Date(y, mo, 1).getDay();
  const daysInMonth = new Date(y, mo + 1, 0).getDate();
  const cells: (Date | null)[] = [];
  for (let i = 0; i < firstDay; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(new Date(y, mo, d));

  const cellClass = (d: Date): { cls: string; label: string; onClick?: () => void; title?: string } => {
    const key = ymd(d);
    const weekend = !isWeekday(d);
    const isToday = key === ymd(today);
    const isFuture = d.getTime() > today.getTime();
    const done = doneSet.has(key);
    const frozen = frozenSet.has(key);
    const base = 'aspect-square flex flex-col items-center justify-center rounded-lg text-sm relative ';
    if (done) return { cls: base + 'bg-green-500 text-white font-bold' + (isToday ? ' ring-2 ring-green-700' : ''), label: '✓', title: `${key} 등록 완료` };
    if (frozen) return { cls: base + 'bg-sky-200 text-sky-700' + (isToday ? ' ring-2 ring-sky-500' : ''), label: '❄️', title: `${key} freeze` };
    if (weekend) return { cls: base + 'text-gray-300', label: '', title: '주말 (제외)' };
    if (isToday) return { cls: base + 'ring-2 ring-amber-400 bg-amber-50 text-amber-700 font-semibold', label: '오늘', title: '오늘 — 아직 미등록' };
    if (isFuture) return { cls: base + 'text-gray-400 border border-dashed border-gray-200', label: '', title: '예정' };
    // 과거 평일 미등록 → freeze 가능
    return { cls: base + 'bg-rose-50 text-rose-400 cursor-pointer hover:bg-rose-100', label: '✕', title: '미등록 — 클릭해 freeze', onClick: () => applyFreeze(key) };
  };

  return (
    <div className="bg-white rounded-lg shadow p-5 mb-6">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <div className="flex items-center gap-3 flex-wrap">
          {/* 강조된 연속일 */}
          <div className={`flex items-center gap-2 px-4 py-2 rounded-2xl bg-gradient-to-br from-orange-400 to-rose-500 text-white shadow-lg transition-shadow ${pop ? 'shadow-orange-300/70 shadow-2xl' : ''}`}>
            <span className={`text-3xl drop-shadow transition-transform ${pop ? 'animate-bounce' : ''}`}>🔥</span>
            <div className="leading-none">
              <div className="flex items-baseline gap-1">
                <span className={`text-4xl font-black tracking-tight tabular-nums inline-block origin-bottom transition-transform duration-300 ${pop ? 'scale-150' : 'scale-100'}`}>{displayStreak}</span>
                <span className="text-sm font-bold opacity-90">일</span>
              </div>
              <div className="text-[11px] font-semibold opacity-90 mt-0.5">연속 등록 중</div>
            </div>
          </div>
          {/* 연말 D-day */}
          <div className="px-3 py-2 rounded-2xl bg-gray-900 text-white text-center shadow min-w-[72px]">
            <div className="text-[10px] opacity-70">{y}년 마감까지</div>
            <div className="text-2xl font-extrabold tabular-nums leading-tight">D-{dday}</div>
          </div>
          <div className="flex flex-col gap-1">
            <span className={`text-xs px-2 py-1 rounded ${todayDone ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'}`}>
              {todayDone ? '오늘 등록 완료 ✓' : '오늘 아직 미등록'}
            </span>
            <span className={`text-xs px-2 py-1 rounded ${freezeAvailable ? 'bg-sky-100 text-sky-700' : 'bg-gray-100 text-gray-400'}`}>
              ❄️ 이번 달 freeze {freezeAvailable ? '사용 가능' : '사용함'}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setView(new Date(y, mo - 1, 1))} className="px-2 py-1 text-sm rounded border hover:bg-gray-50">◀</button>
          <span className="text-sm font-semibold w-24 text-center">{y}년 {mo + 1}월</span>
          <button onClick={() => setView(new Date(y, mo + 1, 1))} className="px-2 py-1 text-sm rounded border hover:bg-gray-50">▶</button>
        </div>
      </div>

      <div className="grid grid-cols-7 gap-1 mb-1">
        {WEEKDAYS.map((w, i) => (
          <div key={w} className={`text-center text-xs font-semibold py-1 ${i === 0 ? 'text-rose-400' : i === 6 ? 'text-blue-400' : 'text-gray-500'}`}>{w}</div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {cells.map((d, i) => {
          if (!d) return <div key={`b${i}`} />;
          const info = cellClass(d);
          return (
            <div key={ymd(d)} className={info.cls} title={info.title} onClick={info.onClick}>
              <span className="absolute top-1 left-1.5 text-[10px] opacity-70">{d.getDate()}</span>
              <span>{info.label}</span>
            </div>
          );
        })}
      </div>

      <div className="flex items-center gap-3 mt-3 text-xs text-gray-500 flex-wrap">
        <span><span className="inline-block w-3 h-3 rounded bg-green-500 align-middle mr-1" />등록 완료</span>
        <span><span className="inline-block w-3 h-3 rounded bg-rose-100 align-middle mr-1" />미등록(평일)</span>
        <span><span className="inline-block w-3 h-3 rounded bg-sky-200 align-middle mr-1" />❄️ freeze</span>
        <span className="text-gray-400">· 주말 제외 · 미등록 평일 클릭 → freeze(월 1회) · 등록일은 마진 시트에서 기록</span>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const [status, setStatus] = useState<LoginStatus>({ logged_in: false, browser_active: false });
  const [userId, setUserId] = useState('');
  const [password, setPassword] = useState('');
  const [hasPassword, setHasPassword] = useState(false);
  const [msg, setMsg] = useState('');

  const refreshStatus = () => {
    getLoginStatus().then((res) => setStatus(res.data)).catch(() => {});
  };

  useEffect(() => {
    refreshStatus();
    getCredentials().then((res) => {
      setUserId(res.data.user_id);
      setHasPassword(res.data.has_password);
    }).catch(() => {});
  }, []);

  const handleSaveCreds = async () => {
    await saveCredentials(userId, password);
    setMsg('저장 완료');
    setHasPassword(!!password);
    setPassword('');
    setTimeout(() => setMsg(''), 2000);
  };

  const handleClearCreds = async () => {
    await deleteCredentials();
    setUserId('');
    setPassword('');
    setHasPassword(false);
    setMsg('삭제 완료');
    setTimeout(() => setMsg(''), 2000);
  };

  const handleLogin = async () => {
    const res = await startLogin();
    setMsg(res.data.message || '로그인 페이지 열림');
    refreshStatus();
  };

  const handleConfirm = async () => {
    const res = await confirmLogin();
    setMsg(res.data.message || '');
    refreshStatus();
  };

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">대시보드</h2>

      <RegistrationStreak />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div className="bg-white rounded-lg shadow p-5">
          <h3 className="text-sm text-gray-500 mb-1">로그인 상태</h3>
          <p className={`text-lg font-bold ${status.logged_in ? 'text-green-600' : 'text-red-500'}`}>
            {status.logged_in ? '연결됨' : '연결 안 됨'}
          </p>
        </div>
        <div className="bg-white rounded-lg shadow p-5">
          <h3 className="text-sm text-gray-500 mb-1">브라우저</h3>
          <p className={`text-lg font-bold ${status.browser_active ? 'text-green-600' : 'text-gray-400'}`}>
            {status.browser_active ? '활성' : '비활성'}
          </p>
        </div>
        <div className="bg-white rounded-lg shadow p-5">
          <h3 className="text-sm text-gray-500 mb-1">버전</h3>
          <p className="text-lg font-bold text-gray-700">v2.0.0</p>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow p-6 mb-4">
        <h3 className="text-lg font-semibold mb-4">Qoo10 계정</h3>
        <p className="text-xs text-gray-500 mb-3">
          저장된 ID/PW는 로그인 페이지에서 자동 입력됩니다. (보안문자·로그인 버튼은 직접 클릭)
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
          <input
            type="text"
            placeholder="Qoo10 ID"
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            className="border rounded px-3 py-2 text-sm"
          />
          <input
            type="password"
            placeholder={hasPassword ? '••••••• (저장됨 - 변경 시에만 입력)' : '비밀번호'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="border rounded px-3 py-2 text-sm"
          />
        </div>
        <div className="flex gap-2">
          <button onClick={handleSaveCreds} className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">
            저장
          </button>
          <button onClick={handleClearCreds} className="px-4 py-2 bg-gray-200 text-gray-700 text-sm rounded hover:bg-gray-300">
            삭제
          </button>
          <button onClick={handleLogin} className="px-4 py-2 bg-green-600 text-white text-sm rounded hover:bg-green-700">
            로그인 창 열기
          </button>
          <button onClick={handleConfirm} className="px-4 py-2 bg-purple-600 text-white text-sm rounded hover:bg-purple-700">
            로그인 완료 확인
          </button>
          {msg && <span className="self-center text-sm text-gray-600">{msg}</span>}
        </div>
      </div>

      <div className="bg-white rounded-lg shadow p-6 mb-4">
        <h3 className="text-lg font-semibold mb-4">사용 안내</h3>
        <ol className="list-decimal list-inside space-y-2 text-sm text-gray-600">
          <li>위 폼에 Qoo10 ID/PW를 저장합니다.</li>
          <li><strong>로그인 창 열기</strong> 클릭 → 크롬 창이 열리고 ID/PW가 자동 입력됩니다.</li>
          <li>보안문자를 입력한 후 로그인 버튼을 클릭합니다.</li>
          <li>로그인이 완료되면 <strong>로그인 완료 확인</strong> 버튼을 누릅니다.</li>
          <li>좌측 메뉴에서 원하는 기능을 선택합니다.</li>
        </ol>
      </div>

      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold mb-4">데이터 내보내기</h3>
        <div className="flex gap-3">
          <a
            href="/api/utils/export/keywords"
            className="px-4 py-2 bg-green-600 text-white text-sm rounded hover:bg-green-700"
          >
            키워드 CSV 다운로드
          </a>
          <a
            href="/api/utils/export/products"
            className="px-4 py-2 bg-green-600 text-white text-sm rounded hover:bg-green-700"
          >
            상품 CSV 다운로드
          </a>
        </div>
      </div>
    </div>
  );
}

import { useState } from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard, FileSpreadsheet, Target,
  Calculator,
  Search, Link2, Settings, Gavel,
  Wrench, Calendar, FileEdit,
  ChevronRight, ChevronDown,
  type LucideIcon,
} from 'lucide-react';

type Item = { path: string; label: string; icon: LucideIcon };

const mainItems: Item[] = [
  { path: '/', label: '대시보드', icon: LayoutDashboard },
  { path: '/keywords', label: '키워드 추출 (RD)', icon: Search },
  { path: '/margin-sheet', label: '마진 시트', icon: FileSpreadsheet },
  { path: '/shop-benchmark', label: '샵 벤치마크', icon: Target },
  { path: '/margin', label: '마진 계산기', icon: Calculator },
];

const moreItems: Item[] = [
  { path: '/related-bulk', label: '연관 키워드 (RD)', icon: Link2 },
  { path: '/bid', label: '경매 낙찰가', icon: Gavel },
  { path: '/settings', label: 'AI 설정', icon: Settings },
];

const rdExternals = [
  { href: '/api/tasks', label: '진행 task', icon: Wrench, title: '모든 backend task list' },
  { href: '/api/review/' + new Date().toISOString().slice(0, 10), label: '오늘 자동화 결과', icon: Calendar, title: '자동화 snapshot raw' },
  { href: '/api/sheet/corrections', label: '사장님 수정 사례', icon: FileEdit, title: '사장님 swap/reject 누적' },
];

const MORE_STATE_KEY = 'sidebar.moreOpen.v1';

function NavItem({ path, label, icon: Icon }: Item) {
  return (
    <NavLink
      to={path}
      end={path === '/'}
      className={({ isActive }) =>
        [
          'flex items-center gap-3 px-3 py-2 rounded-lg text-[15px] transition-colors',
          isActive
            ? 'bg-apple-bg-2 text-apple-text font-semibold'
            : 'text-apple-text-2 hover:bg-apple-bg-2 hover:text-apple-text',
        ].join(' ')
      }
    >
      {({ isActive }) => (
        <>
          <Icon
            size={18}
            strokeWidth={isActive ? 2 : 1.75}
            className={isActive ? 'text-apple-accent' : 'text-apple-text-3'}
          />
          <span className="tracking-tight">{label}</span>
        </>
      )}
    </NavLink>
  );
}

export default function Sidebar() {
  const [moreOpen, setMoreOpen] = useState<boolean>(() => {
    try { return localStorage.getItem(MORE_STATE_KEY) === '1'; } catch { return false; }
  });

  const toggleMore = () => {
    const next = !moreOpen;
    setMoreOpen(next);
    try { localStorage.setItem(MORE_STATE_KEY, next ? '1' : '0'); } catch { /* */ }
  };

  return (
    <aside
      className="app-sidebar w-64 min-h-screen flex flex-col bg-apple-bg border-r"
      style={{ borderRightColor: 'var(--color-apple-border)' }}
    >
      <div className="px-5 pt-7 pb-5">
        <h1 className="text-[17px] font-semibold tracking-tight text-apple-text">
          엘비텐
        </h1>
        <p className="text-[12px] text-apple-text-3 mt-1">키워드 RD · 자동화 · 시트</p>
      </div>

      <nav className="flex-1 px-3 flex flex-col gap-0.5">
        {mainItems.map(item => <NavItem key={item.path} {...item} />)}

        <button
          onClick={toggleMore}
          className="mt-5 flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] text-apple-text-3 hover:bg-apple-bg-2 hover:text-apple-text-2 transition-colors mx-1 border-t pt-4"
          style={{ borderTopColor: 'var(--color-apple-border)' }}
        >
          {moreOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <span>더보기</span>
          <span className="ml-auto text-[11px]">{moreItems.length}</span>
        </button>

        {moreOpen && (
          <div className="flex flex-col gap-0.5 mt-1">
            {moreItems.map(item => <NavItem key={item.path} {...item} />)}
            <div className="text-[10px] text-apple-text-3 px-3 mt-3 mb-1 uppercase tracking-wider font-medium">진단 (외부)</div>
            {rdExternals.map(item => {
              const Icon = item.icon;
              return (
                <a
                  key={item.href}
                  href={item.href}
                  target="_blank"
                  rel="noreferrer"
                  title={item.title}
                  className="flex items-center gap-3 px-3 py-1.5 rounded-lg text-[13px] text-apple-text-3 hover:bg-apple-bg-2 hover:text-apple-text-2 transition-colors"
                >
                  <Icon size={16} strokeWidth={1.75} />
                  <span className="flex-1 tracking-tight">{item.label}</span>
                  <span className="text-[10px]">↗</span>
                </a>
              );
            })}
          </div>
        )}
      </nav>
    </aside>
  );
}

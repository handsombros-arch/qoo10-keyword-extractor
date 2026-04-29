import { useState } from 'react';
import { NavLink } from 'react-router-dom';

const mainItems = [
  { path: '/', label: '대시보드', icon: '📊' },
  { path: '/recommend', label: '역직구 추천', icon: '⭐' },
  { path: '/review', label: '검수', icon: '✅' },
  { path: '/recommend-products', label: '상품 시트', icon: '📋' },
  { path: '/shop-benchmark', label: '샵 벤치마크', icon: '🎯' },
  { path: '/margin', label: '마진 계산기', icon: '💹' },
  { path: '/image', label: '워터마크 제거', icon: '🎨' },
];

// RD (Raw Data) — 자주 사용 X, 데이터 직접 보고 싶을 때만
const moreItems = [
  { path: '/keywords', label: '키워드 추출 (RD)', icon: '🔬' },
  { path: '/insights', label: '시계열 인사이트 (RD)', icon: '📈' },
  { path: '/competition', label: '경쟁강도 (RD)', icon: '📈' },
  { path: '/bid', label: '경매 결과 (RD)', icon: '💰' },
  { path: '/related-bulk', label: '연관 키워드 (RD)', icon: '🔗' },
  { path: '/price-compare', label: '가격비교', icon: '💱' },
  { path: '/products', label: '상품 검색', icon: '🛒' },
  { path: '/tracking', label: '순위 추적', icon: '📍' },
  { path: '/bestsellers', label: '인기상품', icon: '🏆' },
  { path: '/settings', label: 'AI 설정', icon: '⚙️' },
];

// RD 외부 링크 — backend JSON / 작업 진행 / 로그 직접 (새 탭)
const rdExternals = [
  { href: '/api/tasks', label: '진행 task (RD)', icon: '⚙️', title: '모든 backend task list (running/completed/failed)' },
  { href: '/api/review/' + new Date().toISOString().slice(0, 10), label: '오늘 자동화 결과 (JSON)', icon: '🌙', title: '자동화 snapshot raw + 매칭/콘텐츠 enrich' },
];

const MORE_STATE_KEY = 'sidebar.moreOpen.v1';

function NavItem({ path, label, icon }: { path: string; label: string; icon: string }) {
  return (
    <NavLink
      to={path}
      end={path === '/'}
      className={({ isActive }) =>
        `flex items-center gap-2 px-3 py-2 rounded text-sm transition-colors ${
          isActive ? 'bg-blue-600 text-white' : 'text-gray-300 hover:bg-gray-800'
        }`
      }
    >
      <span>{icon}</span>
      <span>{label}</span>
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
    <aside className="w-60 bg-gray-900 text-white min-h-screen p-4 flex flex-col">
      <h1 className="text-lg font-bold mb-6 px-2">Qoo10 키워드 추출기</h1>
      <nav className="flex flex-col gap-1">
        {mainItems.map(item => <NavItem key={item.path} {...item} />)}


        <button
          onClick={toggleMore}
          className="mt-3 flex items-center justify-between px-3 py-2 rounded text-xs text-gray-400 hover:bg-gray-800 border-t border-gray-800 pt-4"
        >
          <span>{moreOpen ? '▾' : '▸'} 더보기</span>
          <span className="text-[10px]">{moreItems.length}</span>
        </button>

        {moreOpen && (
          <div className="flex flex-col gap-1 pl-2 mt-1">
            {moreItems.map(item => <NavItem key={item.path} {...item} />)}
            <div className="text-[10px] text-gray-500 px-3 mt-2 border-t border-gray-700 pt-2">진단 (외부)</div>
            {rdExternals.map(item => (
              <a
                key={item.href}
                href={item.href}
                target="_blank"
                rel="noreferrer"
                title={item.title}
                className="flex items-center gap-2 px-3 py-1.5 rounded text-xs text-gray-400 hover:bg-gray-800 hover:text-gray-200"
              >
                <span>{item.icon}</span>
                <span>{item.label}</span>
                <span className="text-[10px] ml-auto">↗</span>
              </a>
            ))}
          </div>
        )}
      </nav>
    </aside>
  );
}

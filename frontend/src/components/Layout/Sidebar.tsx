import { NavLink } from 'react-router-dom';

const navItems = [
  { path: '/', label: '대시보드', icon: '📊' },
  { path: '/keywords', label: '키워드 추출', icon: '🔍' },
  { path: '/recommend', label: '역직구 추천', icon: '⭐' },
  { path: '/price-compare', label: '가격비교', icon: '💱' },
  { path: '/related-bulk', label: '연관 키워드 일괄', icon: '🔗' },
  { path: '/insights', label: '시계열 인사이트', icon: '📈' },
  { path: '/image', label: '이미지 워터마크 제거', icon: '🎨' },
  { path: '/competition', label: '경쟁강도 분석', icon: '📈' },
  { path: '/bid', label: '경매 결과', icon: '💰' },
  { path: '/products', label: '상품 검색', icon: '🛒' },
  { path: '/tracking', label: '순위 추적', icon: '📍' },
  { path: '/bestsellers', label: '인기상품', icon: '🏆' },
];

export default function Sidebar() {
  return (
    <aside className="w-60 bg-gray-900 text-white min-h-screen p-4 flex flex-col">
      <h1 className="text-lg font-bold mb-6 px-2">Qoo10 키워드 추출기</h1>
      <nav className="flex flex-col gap-1">
        {navItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            className={({ isActive }) =>
              `flex items-center gap-2 px-3 py-2 rounded text-sm transition-colors ${
                isActive
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-300 hover:bg-gray-800'
              }`
            }
          >
            <span>{item.icon}</span>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}

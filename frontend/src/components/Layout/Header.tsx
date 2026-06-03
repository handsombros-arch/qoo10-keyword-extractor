import { useEffect, useState } from 'react';
import { Sun, Moon } from 'lucide-react';
import { getLoginStatus, startLogin, confirmLogin, logout } from '../../api/endpoints';
import type { LoginStatus } from '../../types';

const THEME_KEY = 'apple.theme.v1';
type Theme = 'light' | 'dark' | 'auto';

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  root.classList.remove('light', 'dark');
  if (theme === 'auto') return; // OS preference takes over via @media
  root.classList.add(theme);
}

function loadTheme(): Theme {
  try {
    const saved = localStorage.getItem(THEME_KEY) as Theme | null;
    if (saved === 'light' || saved === 'dark' || saved === 'auto') return saved;
  } catch { /* ignore */ }
  return 'auto';
}

export default function Header() {
  const [status, setStatus] = useState<LoginStatus>({ logged_in: false, browser_active: false });
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [theme, setTheme] = useState<Theme>(loadTheme);

  useEffect(() => { applyTheme(theme); }, [theme]);
  useEffect(() => { applyTheme(loadTheme()); }, []);

  const fetchStatus = async () => {
    try {
      const res = await getLoginStatus();
      setStatus(res.data);
    } catch { /* ignore */ }
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleLogin = async () => {
    setLoading(true);
    setMessage('크롬 브라우저 여는 중...');
    try {
      const res = await startLogin();
      setMessage(res.data.message || '');
      if (res.data.status === 'success') {
        setStatus({ logged_in: true, browser_active: true });
      }
      fetchStatus();
    } catch (err: any) {
      setMessage(`오류: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async () => {
    setLoading(true);
    try {
      const res = await confirmLogin();
      setMessage(res.data.message || '');
      if (res.data.status === 'success') {
        setStatus({ logged_in: true, browser_active: true });
      }
    } catch (err: any) {
      setMessage(`오류: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = async () => {
    await logout();
    setStatus({ logged_in: false, browser_active: false });
    setMessage('');
  };

  const cycleTheme = () => {
    const next: Theme = theme === 'light' ? 'dark' : theme === 'dark' ? 'auto' : 'light';
    setTheme(next);
    try { localStorage.setItem(THEME_KEY, next); } catch { /* ignore */ }
  };

  const themeLabel = theme === 'light' ? '라이트' : theme === 'dark' ? '다크' : '자동';

  return (
    <header
      className="app-header sticky top-0 z-50 h-14 px-7 flex items-center justify-between border-b"
      style={{
        background: 'color-mix(in srgb, var(--color-apple-bg) 72%, transparent)',
        backdropFilter: 'saturate(180%) blur(20px)',
        WebkitBackdropFilter: 'saturate(180%) blur(20px)',
        borderBottomColor: 'var(--color-apple-border)',
      }}
    >
      <div className="text-[13px] text-apple-text-3 tracking-tight">
LV10 · 엘비텐
      </div>

      <div className="flex items-center gap-4">
        <button
          onClick={cycleTheme}
          title={`테마: ${themeLabel} (클릭 → 라이트/다크/자동 순환)`}
          className="apple-btn apple-btn-ghost apple-btn-sm"
          style={{ padding: '6px 10px' }}
        >
          {theme === 'dark' ? <Moon size={16} /> : <Sun size={16} />}
          <span className="text-[12px] ml-1">{themeLabel}</span>
        </button>

        <div className="flex items-center gap-2">
          <span
            className={`inline-block w-1.5 h-1.5 rounded-full ${
              status.logged_in
                ? 'bg-emerald-500'
                : 'bg-apple-text-3'
            }`}
            style={!status.logged_in ? { background: 'var(--color-apple-text-3)' } : undefined}
          />
          <span className="text-[13px] text-apple-text-2 tracking-tight">
            {status.logged_in ? '로그인됨' : '로그아웃'}
          </span>
        </div>

        {!status.logged_in ? (
          <div className="flex gap-2">
            <button
              onClick={handleLogin}
              disabled={loading}
              className="apple-btn apple-btn-primary apple-btn-sm"
            >
              {loading ? '여는 중…' : '로그인'}
            </button>
            {status.browser_active && (
              <button
                onClick={handleConfirm}
                disabled={loading}
                className="apple-btn apple-btn-secondary apple-btn-sm"
              >
                완료
              </button>
            )}
          </div>
        ) : (
          <button
            onClick={handleLogout}
            className="apple-btn apple-btn-ghost apple-btn-sm"
          >
            로그아웃
          </button>
        )}
      </div>

      {message && (
        <div className="absolute left-0 right-0 top-14 mx-7 mt-2 text-[12px] text-apple-text-2 bg-apple-bg-2 border border-apple-border px-3 py-1.5 rounded-lg">
          {message}
        </div>
      )}
    </header>
  );
}

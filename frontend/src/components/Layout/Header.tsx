import { useEffect, useState } from 'react';
import { getLoginStatus, startLogin, confirmLogin, logout } from '../../api/endpoints';
import type { LoginStatus } from '../../types';

export default function Header() {
  const [status, setStatus] = useState<LoginStatus>({ logged_in: false, browser_active: false });
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');

  const fetchStatus = async () => {
    try {
      const res = await getLoginStatus();
      setStatus(res.data);
    } catch {
      // ignore
    }
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

  return (
    <header className="bg-white border-b px-6 py-3">
      <div className="flex items-center justify-between">
        <div className="text-sm text-gray-500">
          Qoo10 Seller Management Tool
        </div>
        <div className="flex items-center gap-3">
          <span
            className={`inline-block w-2.5 h-2.5 rounded-full ${
              status.logged_in ? 'bg-green-500' : 'bg-red-400'
            }`}
          />
          <span className="text-sm">
            {status.logged_in ? '로그인됨' : '로그아웃'}
          </span>
          {!status.logged_in ? (
            <div className="flex gap-2">
              <button
                onClick={handleLogin}
                disabled={loading}
                className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
              >
                {loading ? '여는 중...' : '로그인'}
              </button>
              {status.browser_active && (
                <button
                  onClick={handleConfirm}
                  disabled={loading}
                  className="px-3 py-1.5 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:opacity-50"
                >
                  로그인 완료
                </button>
              )}
            </div>
          ) : (
            <button
              onClick={handleLogout}
              className="px-3 py-1.5 bg-gray-200 text-gray-700 text-sm rounded hover:bg-gray-300"
            >
              로그아웃
            </button>
          )}
        </div>
      </div>
      {message && (
        <div className="mt-2 text-xs text-orange-600 bg-orange-50 px-3 py-1.5 rounded">
          {message}
        </div>
      )}
    </header>
  );
}

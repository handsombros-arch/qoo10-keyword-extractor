import { useEffect, useState } from 'react';
import { getLoginStatus, getCredentials, saveCredentials, deleteCredentials, startLogin, confirmLogin } from '../api/endpoints';
import type { LoginStatus } from '../types';

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

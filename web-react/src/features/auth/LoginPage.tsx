import { passkeyApi, passkeysSupported } from './passkeys';
import { clearOffline } from '../offline/storage';
import { cancelOfflineSync } from '../offline/sync';
import { Bot } from 'lucide-react';
import { FormEvent, useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { authApi } from '../../api/auth';
import { ApiError } from '../../api/client';
import { useAppStore } from '../../stores/appStore';

const authErrorText: Record<string, string> = {
  invalid_credentials: '用户名或密码错误',
  weak_password: '密码至少需要 6 位',
  invalid_username: '用户名需要 2-40 位且不能包含空格',
  username_exists: '用户名已存在',
  admin_already_exists: '管理员已存在，请直接登录',
};

export function LoginPage({ onAuthenticated }: { onAuthenticated?: () => void } = {}) {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const setCurrentUser = useAppStore((state) => state.setCurrentUser);
  const [bootstrapMode, setBootstrapMode] = useState(false);
  const [usernames, setUsernames] = useState<string[]>([]);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [rememberMe, setRememberMe] = useState(false);
  const [confirmPassword, setConfirmPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [passkeyEnabled, setPasskeyEnabled] = useState(false);
  useEffect(() => { void passkeyApi.status().then(s => setPasskeyEnabled(s.enabled)).catch(() => undefined); }, []);

  useEffect(() => {
    let mounted = true;
    authApi
      .bootstrapStatus()
      .then(async (status) => {
        if (!mounted) return;
        setBootstrapMode(!status.admin_exists);
        if (status.admin_exists) {
          const data = await authApi.usernames().catch(() => ({ usernames: [] }));
          if (mounted) setUsernames(data.usernames || []);
        }
      })
      .catch(() => setError('无法读取登录状态'));
    return () => {
      mounted = false;
    };
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    const trimmedUsername = username.trim();
    if (!trimmedUsername || !password) {
      setError('请输入用户名和密码');
      return;
    }
    if (bootstrapMode && password !== confirmPassword) {
      setError('两次输入的密码不一致');
      return;
    }

    setSubmitting(true);
    try {
      const result = bootstrapMode
        ? await authApi.bootstrapAdmin({
            username: trimmedUsername,
            password,
            display_name: displayName.trim() || trimmedUsername,
          })
        : await authApi.login({ username: trimmedUsername, password, remember_me: rememberMe });
      if (useAppStore.getState().currentUser?.id !== result.user.id) {
        cancelOfflineSync(); await clearOffline(true, true).catch(() => undefined); queryClient.clear();
      }
      setCurrentUser(result.user);
      await queryClient.invalidateQueries({ queryKey: ['auth', 'me'] });
      if (onAuthenticated) onAuthenticated();
      else {
        const from = location.state?.from;
        const destination = typeof from?.pathname === 'string' && from.pathname.startsWith('/') && !from.pathname.startsWith('//') && from.pathname !== '/login'
          ? `${from.pathname}${from.search || ''}${from.hash || ''}` : '/home';
        navigate(destination, { replace: true });
      }
    } catch (caught) {
      const apiError = caught as ApiError;
      const code = apiError.data?.error || '';
      setError(authErrorText[code] || apiError.message || '请求失败');
    } finally {
      setSubmitting(false);
    }
  };

  const loginWithPasskey = async () => {
    if (!username.trim()) { setError('请输入用户名后使用通行密钥'); return; }
    setSubmitting(true); setError('');
    try {
      const result = await passkeyApi.login(username.trim());
      if (useAppStore.getState().currentUser?.id !== result.user.id) {
        cancelOfflineSync(); await clearOffline(true, true).catch(() => undefined); queryClient.clear();
      }
      setCurrentUser(result.user);
      await queryClient.invalidateQueries({ queryKey: ['auth', 'me'] });
      if (onAuthenticated) onAuthenticated(); else navigate('/home', { replace: true });
    } catch (caught) { setError(caught instanceof Error ? caught.message : '通行密钥登录失败，请使用密码。'); }
    finally { setSubmitting(false); }
  };

  return (
    <main className="auth-shell">
      <section className="auth-panel">
        <div className="brand-icon" aria-hidden="true">
          <Bot size={19} />
        </div>
        <div className="auth-title">
          <span>Claw</span> Agent
        </div>
        <div className="auth-subtitle">
          {onAuthenticated ? '登录已过期，请重新登录。原页面中的输入仍然保留。' : bootstrapMode ? '首次使用需要初始化管理员账号' : '登录后继续使用工作台'}
        </div>
        {!onAuthenticated && <Link to="/install" className="pwa-back">添加到 iPhone 主屏幕</Link>}

        <form className="auth-form" onSubmit={submit}>
          <label className="field-label">
            用户名
            <input
              className="skill-input"
              list="usernameOptions"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
            <datalist id="usernameOptions">
              {usernames.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
          </label>
          <label className="field-label">
            密码
            <input
              className="skill-input"
              type="password"
              autoComplete={bootstrapMode ? 'new-password' : 'current-password'}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {bootstrapMode ? (
            <>
              <label className="field-label">
                显示名称
                <input
                  className="skill-input"
                  autoComplete="name"
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                />
              </label>
              <label className="field-label">
                确认密码
                <input
                  className="skill-input"
                  type="password"
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                />
              </label>
            </>
          ) : null}
          {!bootstrapMode ? (
            <label className="auth-remember">
              <input
                type="checkbox"
                checked={rememberMe}
                onChange={(event) => setRememberMe(event.target.checked)}
              />
              <span>自动登录</span>
            </label>
          ) : null}
          <div className="skill-form-error">{error}</div>
          <button className="modal-primary auth-submit" type="submit" disabled={submitting}>
            {bootstrapMode ? '创建管理员' : '登录'}
          </button>
        </form>
        {!bootstrapMode && passkeyEnabled && passkeysSupported() && <button type="button" disabled={submitting} onClick={() => void loginWithPasskey()}>使用通行密钥登录</button>}
      </section>
    </main>
  );
}

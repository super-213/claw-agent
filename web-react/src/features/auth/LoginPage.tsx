import { FormEvent, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
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

export function LoginPage() {
  const navigate = useNavigate();
  const setCurrentUser = useAppStore((state) => state.setCurrentUser);
  const [bootstrapMode, setBootstrapMode] = useState(false);
  const [usernames, setUsernames] = useState<string[]>([]);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

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
        : await authApi.login({ username: trimmedUsername, password });
      setCurrentUser(result.user);
      navigate('/', { replace: true });
    } catch (caught) {
      const apiError = caught as ApiError;
      const code = apiError.data?.error || '';
      setError(authErrorText[code] || apiError.message || '请求失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="auth-shell">
      <section className="auth-panel">
        <div className="brand-icon">⚡</div>
        <div className="auth-title">
          <span>Claw</span> Agent
        </div>
        <div className="auth-subtitle">
          {bootstrapMode ? '首次使用需要初始化管理员账号' : '登录后继续使用工作台'}
        </div>

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
          <div className="skill-form-error">{error}</div>
          <button className="modal-primary auth-submit" type="submit" disabled={submitting}>
            {bootstrapMode ? '创建管理员' : '登录'}
          </button>
        </form>
      </section>
    </main>
  );
}

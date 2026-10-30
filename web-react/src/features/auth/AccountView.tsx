import { useState, type FormEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ChevronRight, KeyRound, LogOut } from 'lucide-react';
import { authApi } from '../../api/auth';
import { ApiError } from '../../api/client';
import { isAdmin, useAppStore } from '../../stores/appStore';
import { PasskeySettings } from './PasskeySettings';

const errors: Record<string, string> = {
  incorrect_password: '当前密码不正确，请重新输入。',
  password_unchanged: '新密码需要与当前密码不同。',
  weak_password: '新密码至少需要 6 位。',
  invalid_display_name: '请输入显示名称。',
};
function errorText(error: unknown) {
  if (error instanceof ApiError) return errors[error.data?.error] || (error.status === 422 ? '请检查输入内容后重试。' : '保存失败，请稍后重试。');
  return error instanceof Error ? error.message : '操作失败，请重试。';
}

export function AccountView() {
  const user = useAppStore(s => s.currentUser);
  const client = useQueryClient();
  const [panel, setPanel] = useState<'name' | 'password' | 'passkeys' | null>(null);
  const [name, setName] = useState(user?.display_name || user?.username || '');
  const [currentPassword, setCurrentPassword] = useState('');
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const changePanel = (next: typeof panel) => {
    setPanel(panel === next ? null : next);
    setName(user?.display_name || user?.username || '');
    setCurrentPassword(''); setPassword(''); setConfirmation(''); setError(''); setNotice('');
  };
  const saveName = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      const data = await authApi.updateProfile(name.trim());
      if (useAppStore.getState().currentUser?.id !== data.user.id) return;
      await client.cancelQueries({ queryKey: ['auth', 'me'] });
      if (useAppStore.getState().currentUser?.id !== data.user.id) return;
      useAppStore.getState().setCurrentUser(data.user);
      client.setQueryData(['auth', 'me'], data.user);
      setPanel(null); setNotice('显示名称已更新。');
    } catch (caught) { setError(errorText(caught)); }
    finally { setBusy(false); }
  };
  const changePassword = async (event: FormEvent) => {
    event.preventDefault(); setError('');
    if (password !== confirmation) { setError('两次输入的新密码不一致。'); return; }
    setBusy(true);
    try {
      await authApi.changePassword(currentPassword, password);
      setCurrentPassword(''); setPassword(''); setConfirmation('');
      // Reuse the existing cross-tab logout and offline-data cleanup flow.
      try { await authApi.logout(); } finally { window.location.assign('/login'); }
    } catch (caught) { setError(errorText(caught)); setBusy(false); }
  };
  const logout = async () => {
    setBusy(true); setError('');
    try { await authApi.logout(); window.location.assign('/login'); }
    catch (caught) { setError(errorText(caught)); setBusy(false); }
  };
  return <div className="home-account account-preferences">
    <section aria-labelledby="account-profile-heading">
      <h2 id="account-profile-heading">个人资料</h2>
      <div className="account-info-row"><span>显示名称</span><strong>{user?.display_name || user?.username}</strong>
        <button type="button" disabled={busy} aria-label="修改显示名称" aria-expanded={panel === 'name'} aria-controls="account-name-form" onClick={() => changePanel('name')}>修改<span className="sr-only">显示名称</span></button>
      </div>
      {panel === 'name' && <form id="account-name-form" className="account-edit-form" onSubmit={e => void saveName(e)}>
        <label>显示名称<input autoFocus required maxLength={80} value={name} onChange={e => setName(e.target.value)} disabled={busy} autoComplete="nickname" /></label>
        <p className="home-muted">用于展示你的账号，不会更改家庭成员姓名和称呼。</p>
        <div className="account-form-actions"><button className="home-primary" disabled={busy || !name.trim()}>保存名称</button><button type="button" disabled={busy} onClick={() => changePanel(null)}>取消</button></div>
      </form>}
      <div className="account-info-row"><span>登录账号</span><strong>{user?.username}</strong></div>
      <div className="account-info-row"><span>账号角色</span><strong>{isAdmin(user) ? '管理员' : '普通用户'}</strong></div>
    </section>
    <section aria-labelledby="account-security-heading">
      <h2 id="account-security-heading">登录与安全</h2>
      <button className="account-action-row" type="button" disabled={busy} aria-expanded={panel === 'password'} aria-controls="account-password-form" onClick={() => changePanel('password')}>
        <KeyRound size={20} aria-hidden="true" /><span>修改密码<small>使用当前密码验证身份</small></span><ChevronRight size={18} aria-hidden="true" />
      </button>
      {panel === 'password' && <form id="account-password-form" className="account-edit-form" onSubmit={e => void changePassword(e)}>
        <label>当前密码<input autoFocus required type="password" autoComplete="current-password" value={currentPassword} disabled={busy} onChange={e => setCurrentPassword(e.target.value)} /></label>
        <label>新密码<input required minLength={6} type="password" autoComplete="new-password" value={password} disabled={busy} onChange={e => setPassword(e.target.value)} /></label>
        <label>确认新密码<input required minLength={6} type="password" autoComplete="new-password" value={confirmation} disabled={busy} onChange={e => setConfirmation(e.target.value)} /></label>
        <p className="home-muted">至少 6 位。修改后所有设备需重新登录，已添加的通行密钥保留。忘记当前密码请联系家庭管理员。</p>
        <div className="account-form-actions"><button className="home-primary" disabled={busy}>保存并重新登录</button><button type="button" disabled={busy} onClick={() => changePanel(null)}>取消</button></div>
      </form>}
      <button className="account-action-row" type="button" disabled={busy} aria-expanded={panel === 'passkeys'} aria-controls="account-passkeys" onClick={() => changePanel('passkeys')}>
        <KeyRound size={20} aria-hidden="true" /><span>通行密钥<small>通过设备的指纹、面容或解锁方式登录</small></span><ChevronRight size={18} aria-hidden="true" />
      </button>
      {panel === 'passkeys' && <div id="account-passkeys" className="account-edit-form"><PasskeySettings /></div>}
    </section>
    {notice && <p role="status">{notice}</p>}
    {error && <p role="alert">{error}</p>}
    <div className="account-signout"><button type="button" disabled={busy} onClick={() => void logout()}><LogOut size={18} aria-hidden="true" />退出登录</button></div>
  </div>;
}

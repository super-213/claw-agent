import { useEffect, useState } from 'react';
import { passkeyApi, passkeysSupported } from './passkeys';

export function PasskeySettings() {
  const [enabled, setEnabled] = useState<boolean>();
  const [loading, setLoading] = useState(true);
  const [rows, setRows] = useState<{ id: string; name: string }[]>([]);
  const [password, setPassword] = useState('');
  const [name, setName] = useState('我的设备');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const status = await passkeyApi.status();
        if (!live) return;
        setEnabled(status.enabled);
        if (status.enabled) {
          const data = await passkeyApi.list();
          if (live) setRows(data.credentials);
        }
      } catch { if (live) { setEnabled(undefined); setError('暂时无法读取通行密钥，请收起后重试。'); } }
      finally { if (live) setLoading(false); }
    })();
    return () => { live = false; };
  }, []);
  if (loading) return <p role="status">正在读取通行密钥…</p>;
  if (enabled === false) return <p role="status">通行密钥暂未启用，你仍可使用密码登录。</p>;
  if (enabled === undefined) return <p role="alert">{error}</p>;
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true); setError('');
    try { await action(); setRows((await passkeyApi.list()).credentials); setPassword(''); }
    catch (caught) { setError(caught instanceof Error ? caught.message : '操作失败'); }
    finally { setBusy(false); }
  };
  return <section aria-label="通行密钥"><h3>通行密钥</h3>
    <p>建议登记两个设备。设备丢失后仍可使用密码登录并移除旧密钥；忘记密码请联系家庭管理员重置，重置会撤销全部密钥和登录会话。</p>
    {!passkeysSupported() && <p>此浏览器或当前连接不支持通行密钥，请使用 HTTPS 与支持 WebAuthn 的浏览器。</p>}
    <label>当前密码（新增与移除时验证）<input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></label>
    <label>设备名称<input maxLength={80} value={name} onChange={e => setName(e.target.value)} /></label>
    <button disabled={busy || !password || !name.trim() || !passkeysSupported()} onClick={() => void run(() => passkeyApi.register(password, name.trim()))}>添加通行密钥</button>
    {!rows.length && <p className="home-muted">尚未添加通行密钥。</p>}
    <ul className="account-passkey-list">{rows.map(row => <li key={row.id}>{row.name}<button disabled={busy || !password} onClick={() => void run(() => passkeyApi.remove(row.id, password))}>移除此密钥</button></li>)}</ul>
    {error && <p role="alert">{error}</p>}
  </section>;
}

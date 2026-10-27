import { useEffect, useRef, useState } from 'react';
import { useOnline } from './useOnline';
import { hasUnsavedWork } from './activity';

export function PwaStatus() {
  const online = useOnline();
  const [registration, setRegistration] = useState<ServiceWorkerRegistration>();
  const [available, setAvailable] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [notice, setNotice] = useState('');
  const updatingRef = useRef(false);
  useEffect(() => {
    if (!import.meta.env.PROD || !window.isSecureContext || !('serviceWorker' in window.navigator)) return;
    let live = true;
    let reg: ServiceWorkerRegistration | undefined;
    const check = () => {
      if (document.visibilityState === 'visible' && window.navigator.onLine) void reg?.update().catch(() => undefined);
    };
    const onController = () => {
      if (live && updatingRef.current) window.location.reload();
    };
    const watch = () => {
      if (!reg) return;
      if (live) { setRegistration(reg); setAvailable(Boolean(reg.waiting && window.navigator.serviceWorker.controller)); }
      reg.installing?.addEventListener('statechange', () => {
        if (live) setAvailable(Boolean(reg?.waiting && window.navigator.serviceWorker.controller));
      });
    };
    void window.navigator.serviceWorker.register('/sw.js', { scope: '/', updateViaCache: 'none' })
      .then(value => { reg = value; watch(); reg.addEventListener('updatefound', watch); })
      .catch(() => { if (live) setNotice('离线支持暂时未就绪，联网使用不受影响。'); });
    document.addEventListener('visibilitychange', check);
    window.navigator.serviceWorker.addEventListener('controllerchange', onController);
    return () => {
      live = false;
      reg?.removeEventListener('updatefound', watch);
      document.removeEventListener('visibilitychange', check);
      window.navigator.serviceWorker.removeEventListener('controllerchange', onController);
    };
  }, []);
  // Mutable guard also covers controllerchange during an update handshake.
  const update = () => {
    if (!registration?.waiting) return;
    if (hasUnsavedWork()) { setNotice('请先完成生成、上传并保存草稿或表单，再更新。'); return; }
    if (!online) { setNotice('请联网后更新。'); return; }
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    setUpdating(true);
    updatingRef.current = true;
    const channel = new window.MessageChannel();
    const timeout = window.setTimeout(() => {
      channel.port1.close(); updatingRef.current = false; setUpdating(false);
      setNotice('更新未完成，请稍后重试。');
    }, 10000);
    channel.port1.onmessage = (event) => {
      if (event.data?.ok) return; // controllerchange completes the update.
      window.clearTimeout(timeout); channel.port1.close(); updatingRef.current = false; setUpdating(false);
      setNotice('请关闭本站的其他窗口后再更新，以免打断其中的操作。');
    };
    registration.waiting.postMessage({ type: 'APPLY_UPDATE' }, [channel.port2]);
  };
  return <>
    {!online && <div className="pwa-status pwa-offline" role="status">当前离线，输入暂留本页。<a href="/offline">查看已授权离线数据与个人备忘</a></div>}
    {(available || notice) && <aside className="pwa-status" aria-label="应用状态"><span role="status">{notice || '有新版本可用'}</span>{available && <button type="button" disabled={updating || !online} onClick={update}>更新</button>}<button type="button" aria-label="关闭提示" onClick={() => { setNotice(''); setAvailable(false); }}>关闭</button></aside>}
    {updating && <div className="pwa-update-cover" role="alert" aria-busy="true">正在更新，请稍候…</div>}
  </>;
}

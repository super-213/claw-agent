import { useEffect, useRef, useState } from 'react';
import { connectionNotice, useConnectionStatus } from './useConnectionStatus';
import { setImmediateUpdate } from './updateState';

export function PwaStatus() {
  const { online, disconnected } = useConnectionStatus();
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
    if (!online) { setNotice('请联网后更新。'); return; }
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    setNotice('');
    setImmediateUpdate(true);
    setUpdating(true);
    updatingRef.current = true;
    const channel = new window.MessageChannel();
    const timeout = window.setTimeout(() => {
      channel.port1.close(); updatingRef.current = false; setImmediateUpdate(false); setUpdating(false);
      setNotice('更新未完成，请稍后重试。');
    }, 10000);
    channel.port1.onmessage = (event) => {
      if (event.data?.ok) return; // controllerchange completes the update.
      window.clearTimeout(timeout); channel.port1.close(); updatingRef.current = false; setImmediateUpdate(false); setUpdating(false);
      setNotice('更新未完成，请重试。');
    };
    registration.waiting.postMessage({ type: 'APPLY_UPDATE' }, [channel.port2]);
  };
  return <>
    {disconnected && <div className="pwa-status pwa-offline" role="status">{online ? '网络暂时不可用' : '当前离线'}，{connectionNotice}</div>}
    {(available || notice) && <aside className="pwa-status" aria-label="应用状态"><span role="status">{notice || '有新版本可用'}</span>{available && <button type="button" disabled={updating || !online} onClick={update}>更新</button>}<button type="button" aria-label="关闭提示" onClick={() => { setNotice(''); setAvailable(false); }}>关闭</button></aside>}
    {updating && <div className="pwa-update-cover" role="alert" aria-busy="true">正在更新，请稍候…</div>}
  </>;
}

import { Fragment, useEffect, useState } from 'react';
import { useRoutes } from 'react-router-dom';
import { routes } from './router';
import { PwaStatus } from '../features/pwa/PwaStatus';
import { useMobileViewport } from '../features/pwa/useMobileViewport';
import { LoginPage } from '../features/auth/LoginPage';
import { useAppStore } from '../stores/appStore';
import { useDialog } from '../components/ui/useDialog';
import { initializeTheme } from '../stores/themeStore';

function Reauthenticate({ onClose }: { onClose: () => void }) {
  const { ref, dismiss } = useDialog(true, onClose);
  return <div ref={ref} className="pwa-reauth" role="dialog" aria-modal="true" aria-label="登录已过期" tabIndex={-1}>
    <div><LoginPage onAuthenticated={() => { dismiss(); window.dispatchEvent(new Event('claw-auth-restored')); }} />
      <button type="button" onClick={dismiss}>稍后登录，返回原页面</button></div>
  </div>;
}

export function App() {
  const element = useRoutes(routes);
  const userId = useAppStore(state => state.currentUser?.id);
  const [expired, setExpired] = useState(false);
  useMobileViewport();
  useEffect(() => initializeTheme(), []);

  useEffect(() => {
    const onUnauthorized = () => {
      if (window.location.pathname !== '/login' && useAppStore.getState().currentUser) {
        // Preserve drafts in memory across reauthentication, including upload errors.
        setExpired(true);
      }
    };
    window.addEventListener('claw-api-unauthorized', onUnauthorized);
    return () => window.removeEventListener('claw-api-unauthorized', onUnauthorized);
  }, []);

  return <div className="react-route-shell"><Fragment key={userId}>{element}</Fragment><PwaStatus />
    {expired && <Reauthenticate onClose={() => setExpired(false)} />}
  </div>;
}

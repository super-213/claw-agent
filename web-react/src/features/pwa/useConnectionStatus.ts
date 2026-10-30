import { useSyncExternalStore } from 'react';
import { useOnline } from './useOnline';

// Shared by the global notice and chat header, including chats opened after a fallback.
let cached = false;
const subscribe = (notify: () => void) => {
  const fallback = () => { cached = true; notify(); };
  const fresh = () => { cached = false; notify(); };
  window.addEventListener('claw-cache-fallback', fallback);
  window.addEventListener('claw-cache-fresh', fresh);
  return () => {
    window.removeEventListener('claw-cache-fallback', fallback);
    window.removeEventListener('claw-cache-fresh', fresh);
  };
};

export function useConnectionStatus() {
  const online = useOnline();
  const usingCache = useSyncExternalStore(subscribe, () => cached, () => false);
  return { online, disconnected: !online || usingCache };
}

export const connectionNotice = '已缓存的数据可继续查看，内容可能不是最新。修改与 AI 操作需要联网。';

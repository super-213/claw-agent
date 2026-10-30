import { useAppStore } from '../stores/appStore';
import { clearOffline } from '../features/offline/storage';
import { cancelOfflineSync } from '../features/offline/sync';
import { jsonRequest } from './client';
import { clearLocalPush } from '../features/pwa/chatNotifications';
import type { User } from './types';

export interface LoginPayload {
  username: string;
  password: string;
  remember_me?: boolean;
}

export interface BootstrapAdminPayload extends LoginPayload {
  display_name?: string;
}

export const authApi = {
  bootstrapStatus: () => jsonRequest<{ admin_exists: boolean }>('/api/auth/bootstrap-status'),
  usernames: () => jsonRequest<{ usernames: string[] }>('/api/auth/usernames'),
  bootstrapAdmin: (payload: BootstrapAdminPayload) =>
    jsonRequest<{ ok: true; user: User }>('/api/auth/bootstrap-admin', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  login: (payload: LoginPayload) =>
    jsonRequest<{ ok: true; user: User }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  logout: async () => {
    cancelOfflineSync();
    useAppStore.getState().setCurrentUser(null);
    await clearOffline(true, true).catch(() => undefined);
    const result = await jsonRequest<{ ok: true }>('/api/auth/logout', { method: 'POST' });
    useAppStore.getState().setCurrentUser(null);
    window.dispatchEvent(new Event('claw-auth-cleared'));
    await Promise.race([clearLocalPush().catch(() => undefined), new Promise(resolve => window.setTimeout(resolve, 2000))]);
    return result;
  },
  me: (signal?: AbortSignal) => jsonRequest<{ user: User }>('/api/auth/me', { signal }),
};

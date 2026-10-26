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
    const result = await jsonRequest<{ ok: true }>('/api/auth/logout', { method: 'POST' });
    await Promise.race([clearLocalPush().catch(() => undefined), new Promise(resolve => window.setTimeout(resolve, 2000))]);
    return result;
  },
  me: () => jsonRequest<{ user: User }>('/api/auth/me'),
};

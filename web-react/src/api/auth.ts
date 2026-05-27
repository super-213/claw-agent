import { jsonRequest } from './client';
import type { User } from './types';

export interface LoginPayload {
  username: string;
  password: string;
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
  logout: () => jsonRequest<{ ok: true }>('/api/auth/logout', { method: 'POST' }),
  me: () => jsonRequest<{ user: User }>('/api/auth/me'),
};

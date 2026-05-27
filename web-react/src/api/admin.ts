import { jsonRequest } from './client';
import type { User } from './types';

export interface UserUpsertPayload {
  username: string;
  password?: string;
  display_name?: string;
  role?: string;
  status?: string;
}

export const adminApi = {
  shareableUsers: () => jsonRequest<{ users: User[] }>('/api/users'),
  users: () => jsonRequest<{ users: User[] }>('/api/admin/users'),
  createUser: (payload: UserUpsertPayload) =>
    jsonRequest<{ ok: true; user: User }>('/api/admin/users', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateUser: (userId: string, payload: UserUpsertPayload) =>
    jsonRequest<{ ok: true; user: User }>(`/api/admin/users/${encodeURIComponent(userId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  deleteUser: (userId: string) =>
    jsonRequest<{ ok: true }>(`/api/admin/users/${encodeURIComponent(userId)}`, { method: 'DELETE' }),
  resetPassword: (userId: string, password: string) =>
    jsonRequest<{ ok: true; user: User }>(`/api/admin/users/${encodeURIComponent(userId)}/reset-password`, {
      method: 'POST',
      body: JSON.stringify({ password }),
    }),
};

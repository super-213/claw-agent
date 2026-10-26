import { jsonRequest } from './client';
export type InventoryLocation = 'fridge' | 'freezer' | 'pantry' | 'medicine';
export interface HomeActivity {
  id: string;
  at: string;
  action: string;
  actor_name?: string;
  before?: { name?: string };
  after?: { name?: string };
}

import type {
  HomeInventoryDoc,
  HomeInventoryItem,
  HomeNotification,
  HomeReminder,
  HomeTaskSummary,
} from './types';

export const homeApi = {
  inventory: (location: InventoryLocation = 'fridge') =>
    jsonRequest<HomeInventoryDoc>(`/api/home/inventory/${location}`),
  expiring: (days = 3, location: InventoryLocation = 'fridge') =>
    jsonRequest<{ generated_at?: string; items: HomeInventoryItem[] }>(
      `/api/home/inventory/expiring?days=${days}&location=${location}`,
    ),
  addInventoryItem: (
    payload: Partial<HomeInventoryItem>,
    location: InventoryLocation = 'fridge',
  ) =>
    jsonRequest<{ ok: boolean; item: HomeInventoryItem }>(
      `/api/home/inventory/${location}/items`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
    ),
  updateInventoryItem: (
    itemId: string,
    payload: Partial<HomeInventoryItem>,
    location: InventoryLocation = 'fridge',
  ) =>
    jsonRequest<{ ok: boolean; item: HomeInventoryItem }>(
      `/api/home/inventory/${location}/items/${encodeURIComponent(itemId)}`,
      {
        method: 'PATCH',
        body: JSON.stringify(payload),
      },
    ),
  deleteInventoryItem: (
    itemId: string,
    location: InventoryLocation = 'fridge',
  ) =>
    jsonRequest<{ ok: boolean }>(
      `/api/home/inventory/${location}/items/${encodeURIComponent(itemId)}`,
      { method: 'DELETE' },
    ),
  consumeInventoryItem: (
    itemId: string,
    quantity?: number | null,
    location: InventoryLocation = 'fridge',
  ) =>
    jsonRequest<{ ok: boolean; item: HomeInventoryItem }>(
      `/api/home/inventory/${location}/items/${encodeURIComponent(itemId)}/consume`,
      {
        method: 'POST',
        body: JSON.stringify({ quantity }),
      },
    ),
  activity: () =>
    jsonRequest<{ activity: HomeActivity[] }>(
      '/api/home/activity-log?limit=100',
    ),
  restoreInventoryItem: (
    itemId: string,
    location: InventoryLocation = 'fridge',
  ) =>
    jsonRequest(
      `/api/home/inventory/${location}/items/${encodeURIComponent(itemId)}/restore`,
      { method: 'POST' },
    ),
  reminders: () =>
    jsonRequest<{ reminders: HomeReminder[] }>('/api/home/reminders'),
  createReminder: (payload: Partial<HomeReminder> & { raw_text?: string }) =>
    jsonRequest<{ ok: boolean; reminder: HomeReminder; receipt?: string }>(
      '/api/home/reminders',
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
    ),
  completeReminder: (id: string) =>
    jsonRequest<{ ok: boolean }>(`/api/home/reminders/${id}/complete`, {
      method: 'POST',
    }),
  snoozeReminder: (id: string, minutes = 10) =>
    jsonRequest<{ ok: boolean }>(`/api/home/reminders/${id}/snooze`, {
      method: 'POST',
      body: JSON.stringify({ minutes }),
    }),
  cancelReminder: (id: string) =>
    jsonRequest<{ ok: boolean }>(`/api/home/reminders/${id}/cancel`, {
      method: 'POST',
    }),
  notifications: () =>
    jsonRequest<{ notifications: HomeNotification[] }>(
      '/api/home/notifications?limit=40',
    ),
  readNotification: (id: string) =>
    jsonRequest<{ ok: boolean }>(`/api/home/notifications/${id}/read`, {
      method: 'POST',
    }),
  taskSummary: () =>
    jsonRequest<HomeTaskSummary>('/api/dashboard/home/tasks/summary'),
  vapidKey: () =>
    jsonRequest<{ public_key: string; configured: boolean }>(
      '/api/push/vapid-public-key',
    ),
  subscriptions: () =>
    jsonRequest<{
      subscriptions: Array<Record<string, unknown>>;
    }>('/api/push/subscriptions'),
  saveSubscription: (payload: Record<string, unknown>) =>
    jsonRequest<{ ok: boolean; subscription: Record<string, unknown> }>(
      '/api/push/subscriptions',
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
    ),
  sendTestPush: (payload: Record<string, unknown> = {}) =>
    jsonRequest<{
      ok: boolean;
      notification: HomeNotification;
      web_push_configured: boolean;
    }>('/api/push/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
};

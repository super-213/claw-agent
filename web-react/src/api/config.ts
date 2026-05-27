import { jsonRequest } from './client';
import type { ModelConfig } from './types';

export const configApi = {
  get: () => jsonRequest<ModelConfig>('/api/config'),
  update: (payload: { api_key?: string; base_url?: string; model?: string }) =>
    jsonRequest<{ ok: true; config: ModelConfig }>('/api/config', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
};

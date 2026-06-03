import { jsonRequest } from './client';
import type { ModelConfig } from './types';

export interface ConfigUpdatePayload {
  api_key?: string;
  base_url?: string;
  model?: string;
  home_assistant?: {
    base_url?: string;
    token?: string;
    allowed_entities?: string;
    request_timeout?: number;
  };
}

export const configApi = {
  get: () => jsonRequest<ModelConfig>('/api/config'),
  update: (payload: ConfigUpdatePayload) =>
    jsonRequest<{ ok: true; config: ModelConfig }>('/api/config', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
};

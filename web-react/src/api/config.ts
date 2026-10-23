import { jsonRequest } from './client';
import type { ModelConfig } from './types';

export interface ConfigUpdatePayload {
  api_key?: string;
  base_url?: string;
  model?: string;
  vision_model?: string;
  home_assistant?: {
    base_url?: string;
    token?: string;
    allowed_entities?: string;
    request_timeout?: number;
  };
}

export interface AvailableModel {
  id: string;
  owned_by: string;
}

export interface ModelListPayload {
  base_url?: string;
  api_key?: string;
}

export const configApi = {
  get: () => jsonRequest<ModelConfig>('/api/config'),
  models: (payload: ModelListPayload = {}, signal?: AbortSignal) =>
    jsonRequest<{ models: AvailableModel[] }>('/api/config/models', {
      method: 'POST',
      body: JSON.stringify(payload),
      signal,
    }),
  update: (payload: ConfigUpdatePayload) =>
    jsonRequest<{ ok: true; config: ModelConfig }>('/api/config', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
};

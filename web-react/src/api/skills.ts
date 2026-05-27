import { jsonRequest } from './client';
import type { Skill } from './types';

export const skillsApi = {
  list: () => jsonRequest<{ skills: Skill[] }>('/api/skills'),
  reload: () => jsonRequest<{ ok: true; skills: Skill[] }>('/api/skills/reload', { method: 'POST' }),
  create: (payload: { name: string; content: string }) =>
    jsonRequest<{ ok: true; skill: Skill }>('/api/skills', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
};

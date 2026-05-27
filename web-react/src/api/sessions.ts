import { jsonRequest } from './client';
import type { BranchTree, SessionDetail, SessionSummary, ShareConfig } from './types';

export const sessionsApi = {
  list: () => jsonRequest<SessionSummary[]>('/api/sessions'),
  create: (title?: string) =>
    jsonRequest<SessionDetail>('/api/sessions', {
      method: 'POST',
      body: JSON.stringify({ title }),
    }),
  get: (sessionId: string) => jsonRequest<SessionDetail>(`/api/sessions/${encodeURIComponent(sessionId)}`),
  delete: (sessionId: string) =>
    jsonRequest<{ ok: true }>(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' }),
  copy: (sessionId: string) =>
    jsonRequest<SessionDetail>(`/api/sessions/${encodeURIComponent(sessionId)}/copy`, { method: 'POST' }),
  share: (sessionId: string) =>
    jsonRequest<{ sharing: ShareConfig }>(`/api/sessions/${encodeURIComponent(sessionId)}/share`),
  updateShare: (sessionId: string, payload: ShareConfig) =>
    jsonRequest<{ ok: true; sharing: ShareConfig }>(`/api/sessions/${encodeURIComponent(sessionId)}/share`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  tree: (sessionId: string) => jsonRequest<BranchTree>(`/api/sessions/${encodeURIComponent(sessionId)}/tree`),
  createBranch: (sessionId: string, branchPointNodeId: string) =>
    jsonRequest<Record<string, unknown>>(`/api/sessions/${encodeURIComponent(sessionId)}/branch`, {
      method: 'POST',
      body: JSON.stringify({ branch_point_node_id: branchPointNodeId }),
    }),
  switchBranch: (sessionId: string, targetNodeId: string) =>
    jsonRequest<SessionDetail & { ok?: boolean; active_node_id?: string }>(
      `/api/sessions/${encodeURIComponent(sessionId)}/switch`,
      {
        method: 'POST',
        body: JSON.stringify({ target_node_id: targetNodeId }),
      },
    ),
  deleteBranch: (sessionId: string, nodeId: string) =>
    jsonRequest<{ ok: true }>(
      `/api/sessions/${encodeURIComponent(sessionId)}/branch/${encodeURIComponent(nodeId)}`,
      { method: 'DELETE' },
    ),
};

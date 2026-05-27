import { jsonRequest } from './client';
import type { DashboardSessionDetail, DashboardSessionsResponse, DashboardSummary } from './types';

export type DashboardRange = 'all' | '30d' | '7d' | 'today';
export type WordScope = 'all' | 'user' | 'assistant' | 'tool';

export const dashboardApi = {
  summary: (range: DashboardRange) =>
    jsonRequest<DashboardSummary>(`/api/dashboard/summary?${new URLSearchParams({ range })}`),
  sessions: (range: DashboardRange, sort = 'total_tokens', limit = 120) =>
    jsonRequest<DashboardSessionsResponse>(
      `/api/dashboard/sessions?${new URLSearchParams({ range, sort, limit: String(limit) })}`,
    ),
  sessionDetail: (sessionId: string) =>
    jsonRequest<DashboardSessionDetail>(`/api/dashboard/sessions/${encodeURIComponent(sessionId)}`),
  wordCloud: (scope: WordScope, limit = 90) =>
    jsonRequest<{ words: Array<Record<string, unknown>> }>(
      `/api/dashboard/word-cloud?${new URLSearchParams({ scope, limit: String(limit) })}`,
    ),
};

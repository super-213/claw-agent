import { jsonRequest } from './client';

export const taskCommands = ['日程', '备忘', '家庭日程', '家庭备忘'] as const;
export type TaskCommand = typeof taskCommands[number];
export interface TaskMention { member_id: string; label: string; start: number; end: number }
export interface TaskInvocation {
  command: TaskCommand; space_type: 'personal' | 'household'; temporal_type: 'timed' | 'undated';
  mentions: TaskMention[]; actionable: boolean; completion_mode: 'all' | 'any'; literal_time_text?: boolean;
}
export interface FamilyMember { member_id: string; user_id: string; display_name: string; aliases: string[]; status: string }
export interface TaskDefinition {
  id: string; title: string; description: string; category: string | null; created_by: string;
  space_type: 'personal' | 'household'; space_owner_id: string; temporal_type: 'timed' | 'undated';
  actionable: boolean; assignee_ids: string[]; related_member_ids: string[]; completion_mode: 'all' | 'any' | null;
  history_before_migration?: string; migration_review?: string[];
  lifecycle: 'active' | 'paused' | 'archived'; version: number; starts_on: string | null;
  due_date: string | null; due_at: string | null;
  recurrence: { frequency: 'weekly'; weekday: string | null } | null;
}
export interface TaskOccurrence {
  id: string; task_id: string; due_date: string | null; due_at: string | null;
  status: 'open' | 'completed' | 'cancelled' | 'skipped'; version: number; title_snapshot: string;
  completion_mode: 'all' | 'any'; assignee_ids: string[];
  member_progress: Record<string, { status: string; completed_at: string | null }>;
  projected?: boolean; legacy_completion_unknown_actor?: boolean;
}
export interface TaskRow { task: TaskDefinition; occurrence: TaskOccurrence | null; overdue: boolean; assignee_unavailable: string[] }
export interface TaskList { items: TaskRow[]; today: string; revision: number; timezone: string; as_of: string;
  history_complete: boolean; next_cursor: string | null; total: number | null }
export interface TaskSummary { counts: Record<string, number | null>; revision: number; timezone: string; as_of: string; history_complete: boolean }
export interface TaskDetail { task: TaskDefinition; occurrences: TaskOccurrence[]; preview: TaskOccurrence[]; history_complete: boolean }
export interface TaskMutation { expected_version: number; patch?: Record<string, unknown> }
export const requestId = () => window.crypto.randomUUID();
export const invocationFor = (command: TaskCommand, mentions: TaskMention[] = []): TaskInvocation => ({
  command, space_type: command.startsWith('家庭') ? 'household' : 'personal',
  temporal_type: command.endsWith('日程') ? 'timed' : 'undated', mentions, actionable: true, completion_mode: 'all',
});
export function commandFromText(text: string): TaskCommand | null {
  return /^\/ (家庭日程|家庭备忘|日程|备忘)(?: |$)/.exec(text)?.[1] as TaskCommand || null;
}
export const tasksApi = {
  members: () => jsonRequest<{ members: FamilyMember[]; current_member_id: string | null }>('/api/home/members'),
  migrationReview: () => jsonRequest<{ records: Record<string, { reasons: string[]; source: { title?: string } }> }>('/api/home/tasks-migration/review'),
  bindMember: (memberId: string, patch: Record<string, unknown>) => jsonRequest<FamilyMember>(`/api/home/members/${memberId}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  list: (filters: Record<string, string | boolean | undefined> = {}) => {
    const query = new URLSearchParams(Object.entries(filters).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]));
    return jsonRequest<TaskList>(`/api/home/tasks?${query}`);
  },
  summary: (filters: Record<string, string> = {}) => jsonRequest<TaskSummary>(`/api/home/tasks/summary?${new URLSearchParams(filters)}`),
  get: (taskId: string) => jsonRequest<TaskDetail>(`/api/home/tasks/${taskId}`),
  create: (items: Record<string, unknown>[], invocation: TaskInvocation, id: string = requestId()) => jsonRequest('/api/home/tasks', {
    method: 'POST', body: JSON.stringify({ items, invocation, request_id: id }),
  }),
  change: (taskId: string, action: string, payload: TaskMutation, occurrenceId?: string) => {
    const base = `/api/home/tasks/${taskId}${occurrenceId ? `/occurrences/${encodeURIComponent(occurrenceId)}` : ''}`;
    return jsonRequest(action === 'update' ? base : `${base}/${action}`, {
      method: action === 'update' ? 'PATCH' : 'POST', body: JSON.stringify({ ...payload, request_id: requestId() }),
    });
  },
};

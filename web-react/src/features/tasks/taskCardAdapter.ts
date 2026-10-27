import { jsonRequest } from '../../api/client';
import type { FamilyMember, TaskDefinition, TaskOccurrence } from '../../api/tasks';
import type { CardAdapter, CardContext, CardView, InteractiveCardRef } from '../interactive-cards/types';
import { TaskChatCard } from './TaskChatCard';

export interface DraftTaskItem { title: string; description?: string; due_date?: string | null; due_at?: string | null; recurrence?: TaskDefinition['recurrence']; starts_on?: string | null }
export interface TaskCardView extends CardView {
  timezone: string; time_state: string; revision?: number;
  current_member_id: string; members: Array<Omit<FamilyMember, 'user_id'>>;
  task?: TaskDefinition; occurrence?: TaskOccurrence | null; effective_on?: string | null;
  draft?: { id: string; version: number; items: DraftTaskItem[]; invocation?: { space_type: string; temporal_type: string; mentions?: Array<{ member_id: string }>; completion_mode?: string; literal_time_text?: boolean } };
  additional_cards?: InteractiveCardRef[];
}
export interface TaskCardAction {
  expected_task_version?: number; occurrence_id?: string; expected_occurrence_version?: number;
  definition_patch?: Record<string, unknown>; occurrence_patch?: Record<string, unknown>;
  occurrence_action?: { action: string; expected_version: number };
  action?: string; scope?: string; audience_confirmed?: boolean;
  expected_version?: number; items?: DraftTaskItem[]; space_type?: string; temporal_type?: string;
  assignee_ids?: string[]; completion_mode?: string;
  literal_time_text?: boolean;
  // The original draft placement remains stable after it is committed.
  target?: { resource: TaskCardView['resource'] };
}
const queryFor = (context: CardContext, instance?: string) => {
  const query = new URLSearchParams();
  if (context.sessionId) query.set('session_id', context.sessionId);
  if (instance) query.set('instance_id', instance);
  return query.size ? `?${query}` : '';
};
export const taskCardAdapter: CardAdapter<TaskCardView, TaskCardAction> = {
  kind: 'task', resourceTypes: ['family_task', 'task_draft'], supportedSchemaVersions: [1], Renderer: TaskChatCard,
  invalidate: () => window.dispatchEvent(new CustomEvent('task_changed')),
  load: (ref: InteractiveCardRef, context) => {
    const id = encodeURIComponent(ref.resource.id);
    if (ref.resource.type === 'task_draft') {
      if (!context.sessionId) return Promise.reject(new Error('草稿需要在原会话中读取。'));
      return jsonRequest(`/api/home/task-drafts/${id}${queryFor(context)}`);
    }
    return jsonRequest(`/api/home/tasks/${id}/card${queryFor(context, ref.resource.instance_id)}`);
  },
  submit: (ref, action, context, id) => {
    const { target, ...payload } = action;
    const resource = target?.resource || ref.resource;
    const draft = resource.type === 'task_draft';
    const path = draft ? `/api/home/task-drafts/${encodeURIComponent(resource.id)}/commit` : `/api/home/tasks/${encodeURIComponent(resource.id)}/card`;
    return jsonRequest(path + queryFor(context), { method: draft ? 'POST' : 'PATCH', body: JSON.stringify({ ...payload, request_id: id }) });
  },
};

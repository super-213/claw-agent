import { jsonRequest } from './client';
import type { CardContext, CardResource, CardView, InteractiveCardRef } from '../features/interactive-cards/types';
export type ActivityKind = 'poll' | 'relay';
export interface ActivityField { id: string; label: string; type: 'text' | 'number'; required: boolean }
export interface ActivityData {
  title: string; description: string; participation_deadline_at: string | null; expires_at: string | null;
  participation_duration_hours: number | null; retention_duration_hours: number | null;
  required_time_fields: string[]; auto_close: boolean; notify_creator: boolean; options: Array<{ id: string; text: string }>;
  multiple: boolean; min_choices: number; max_choices: number; allow_change: boolean; fields: ActivityField[]; capacity: number | null;
}
export interface Participation { member_id: string; version: number; option_ids?: string[]; values?: Record<string, string | number | null>; sequence?: number }
export interface ActivityView extends CardView {
  destroyed?: boolean;
  activity: ActivityData & { id: string; created_by: string; kind: ActivityKind; version: number; revision: number; state: 'draft' | 'open' | 'closed'; close_reason: string | null;
    completion_member_ids: string[]; missing_fields: string[]; counts?: Record<string, number> };
  participants: Participation[]; own_participation: Participation | null; participation_version: number;
  current_member_id: string; timezone: string; members: Array<{ member_id: string; display_name: string; status: string }>;
}
export interface ActivityAction { action: 'save' | 'save_draft' | 'publish' | 'participate' | 'withdraw' | 'close' | 'delete'; target: CardResource; expected_version: number; participation_version: number; data: Partial<ActivityData> | { option_ids: string[] } | { values: Record<string, string | number | null> } }
export const emptyActivity = (): ActivityData => ({ title: '', description: '', participation_deadline_at: null, expires_at: null,
  participation_duration_hours: null, retention_duration_hours: null, required_time_fields: [], auto_close: true, notify_creator: true, options: [], multiple: false, min_choices: 1, max_choices: 1, allow_change: true, fields: [], capacity: null });
export const activityData = (data: ActivityData): ActivityData => Object.fromEntries(Object.keys(emptyActivity()).map(key => [key, data[key as keyof ActivityData]])) as unknown as ActivityData;
export const activityRef = (view: ActivityView): InteractiveCardRef => ({ type: 'interactive_card', schema_version: 1, kind: view.activity.kind,
  mode: view.mode, card_id: `workbench-${view.resource.id}`, resource: view.resource });
const base = (kind: ActivityKind) => `/api/home/${kind === 'poll' ? 'polls' : 'relays'}`;
const query = (context?: CardContext) => context?.sessionId ? `?session_id=${encodeURIComponent(context.sessionId)}` : '';
export const kindForResource = (resource: CardResource): ActivityKind => resource.type.startsWith('family_poll') ? 'poll' : 'relay';
export const activityApi = {
  get: (kind: ActivityKind, id: string, draft = false, context?: CardContext) => jsonRequest<ActivityView>(`${base(kind)}/${draft ? 'drafts/' : ''}${encodeURIComponent(id)}${query(context)}`, { cache: 'no-store' }),
  draft: (kind: ActivityKind, requestId: string) => jsonRequest<ActivityView>(`${base(kind)}/drafts`, { method: 'POST', body: JSON.stringify({ request_id: requestId, data: {} }) }),
  mutate: (action: ActivityAction, requestId: string, context?: CardContext) => {
    const kind = kindForResource(action.target);
    const draft = action.target.type.endsWith('_draft');
    const suffix = action.action === 'publish' ? '/commit' : action.action === 'close' ? '/close' : ['participate', 'withdraw'].includes(action.action) ? `/my-${kind === 'poll' ? 'vote' : 'entry'}` : '';
    const method = ['delete', 'withdraw'].includes(action.action) ? 'DELETE' : action.action === 'participate' ? 'PUT' : suffix ? 'POST' : 'PATCH';
    return jsonRequest<ActivityView>(`${base(kind)}/${draft ? 'drafts/' : ''}${encodeURIComponent(action.target.id)}${suffix}${query(context)}`, {
      method, body: JSON.stringify({ request_id: requestId, data: action.data, expected_version: action.expected_version, participation_version: action.participation_version }),
    });
  },
};

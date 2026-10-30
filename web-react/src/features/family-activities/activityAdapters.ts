import { activityApi, kindForResource, type ActivityAction, type ActivityKind, type ActivityView } from '../../api/familyActivities';
import type { CardAdapter } from '../interactive-cards/types';
import { ActivityCard } from './ActivityCard';
export const activityAdapters: CardAdapter<ActivityView, ActivityAction>[] = (['poll', 'relay'] as ActivityKind[]).map(kind => ({
  kind, resourceTypes: [`family_${kind}`, `family_${kind}_draft`], supportedSchemaVersions: [1], Renderer: ActivityCard,
  load: (ref, context) => activityApi.get(kindForResource(ref.resource), ref.resource.id, ref.resource.type.endsWith('_draft'), context),
  submit: (_ref, action, context, requestId) => activityApi.mutate(action, requestId, context),
}));

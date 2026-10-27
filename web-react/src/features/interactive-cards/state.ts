import type { CardResource } from './types';

const edits = new Map<string, unknown>();
export interface PendingCardSubmission { id: string; action: unknown; signature: string }
const submissions = new Map<string, PendingCardSubmission>();
export const readCardEdit = <T,>(key: string) => edits.get(key) as T | undefined;
export const writeCardEdit = (key: string, value: unknown) => { edits.set(key, value); };
export const forgetCardEdit = (key: string) => { edits.delete(key); };
export const readCardSubmission = (key: string) => submissions.get(key);
export const writeCardSubmission = (key: string, value: PendingCardSubmission) => { submissions.set(key, value); };
export const forgetCardSubmission = (key: string, id: string) => { if (submissions.get(key)?.id === id) submissions.delete(key); };
export const clearCardEdits = () => { edits.clear(); submissions.clear(); };

export function announceResourceChange(resource: CardResource, revision?: number) {
  window.dispatchEvent(new CustomEvent('resource_changed', { detail: { resource_type: resource.type, resource_id: resource.id, revision } }));
}

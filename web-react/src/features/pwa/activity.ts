import { useAppStore } from '../../stores/appStore';

// Transient work only. No personal data is written to persistent browser storage.
const activities = new Set<symbol>();

export function beginActivity() {
  const token = Symbol();
  activities.add(token);
  return () => { activities.delete(token); };
}

export function hasUnsavedWork() {
  const state = useAppStore.getState();
  if (activities.size || Object.keys(state.streams).length || state.homeDraft.trim() ||
    state.pendingChatMessage || Object.values(state.chatDrafts).some(value => value.trim())) return true;
  if (document.querySelector('[role=dialog]')) return true;
  // Includes other feature forms, not just the chat composer.
  return Array.from(document.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>('input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=file]), textarea'))
    .some(input => Boolean(input.value.trim()));
}

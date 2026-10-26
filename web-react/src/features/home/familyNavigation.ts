import { Navigate } from 'react-router-dom';
import { createElement } from 'react';
import { useAppStore } from '../../stores/appStore';

export type FamilySection = 'tasks' | 'items' | 'library' | 'memories';
const storageKey = (userId: string) => `claw.home.family.v1.${userId}`;

export function familyPath(userId: string) {
  try {
    const section = localStorage.getItem(storageKey(userId));
    return section && ['items', 'library', 'memories'].includes(section) ? `/home/${section}` : '/home/tasks';
  } catch {
    return '/home/tasks';
  }
}

export function rememberFamilySection(userId: string, section: FamilySection) {
  try {
    localStorage.setItem(storageKey(userId), section);
  } catch {
    // Navigation remains available when browser storage is disabled.
  }
}

export function FamilyRedirect() {
  const userId = useAppStore((state) => state.currentUser?.id || 'guest');
  return createElement(Navigate, { to: familyPath(userId), replace: true });
}

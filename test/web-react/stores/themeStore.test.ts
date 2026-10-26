import React from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ThemeSelector } from '../../../web-react/src/components/ui/ThemeSelector';
import { initializeTheme, THEME_STORAGE_KEY, useThemeStore } from '../../../web-react/src/stores/themeStore';

let dark: boolean;
let stop: (() => void) | undefined;
let systemChange: (() => void) | undefined;
const removeListener = vi.fn();

beforeEach(() => {
  dark = false;
  systemChange = undefined;
  localStorage.clear();
  window.matchMedia = vi.fn().mockImplementation(() => ({
    get matches() { return dark; },
    addEventListener: (_: string, listener: () => void) => { systemChange = listener; },
    removeEventListener: removeListener,
  }));
});

afterEach(() => {
  cleanup();
  stop?.();
  stop = undefined;
  vi.restoreAllMocks();
  document.documentElement.removeAttribute('data-theme');
});

it('defaults to auto and follows system changes', () => {
  stop = initializeTheme();
  render(React.createElement(ThemeSelector));
  expect(screen.getByRole('radio', { name: '自动' })).toBeChecked();
  expect(screen.getAllByRole('radio')).toHaveLength(3);
  expect(document.documentElement.dataset.theme).toBe('light');
  dark = true;
  act(() => systemChange?.());
  expect(document.documentElement.dataset.theme).toBe('dark');
  expect(useThemeStore.getState().preference).toBe('auto');
});

it('selects any mode directly, persists each choice and restores it on reopening', () => {
  stop = initializeTheme();
  render(React.createElement(ThemeSelector));
  for (const [label, preference, resolved] of [
    ['浅色', 'light', 'light'],
    ['深色', 'dark', 'dark'],
    ['自动', 'auto', 'light'],
  ]) {
    fireEvent.click(screen.getByRole('radio', { name: label }));
    expect(screen.getByRole('radio', { name: label })).toBeChecked();
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe(preference);
    expect(document.documentElement.dataset.theme).toBe(resolved);
    stop();
    act(() => { stop = initializeTheme(); });
    expect(useThemeStore.getState().preference).toBe(preference);
    expect(document.documentElement.dataset.theme).toBe(resolved);
  }
});

it.each(['light', 'dark'] as const)('keeps explicit %s mode regardless of the system', (preference) => {
  localStorage.setItem(THEME_STORAGE_KEY, preference);
  stop = initializeTheme();
  dark = true;
  systemChange?.();
  expect(document.documentElement.dataset.theme).toBe(preference);
  dark = false;
  systemChange?.();
  expect(document.documentElement.dataset.theme).toBe(preference);
});

it('syncs other tabs and returns to auto when storage is cleared', () => {
  stop = initializeTheme();
  window.dispatchEvent(new StorageEvent('storage', { key: THEME_STORAGE_KEY, newValue: 'dark' }));
  expect(useThemeStore.getState().preference).toBe('dark');
  expect(document.documentElement.dataset.theme).toBe('dark');
  window.dispatchEvent(new StorageEvent('storage', { key: null }));
  expect(useThemeStore.getState().preference).toBe('auto');
  expect(document.documentElement.dataset.theme).toBe('light');
});

it('falls back to auto for an invalid preference and still switches if storage is blocked', () => {
  localStorage.setItem(THEME_STORAGE_KEY, 'invalid');
  dark = true;
  stop = initializeTheme();
  expect(useThemeStore.getState().preference).toBe('auto');
  expect(document.documentElement.dataset.theme).toBe('dark');
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
  stop();
  stop = initializeTheme();
  useThemeStore.getState().setPreference('light');
  expect(useThemeStore.getState().preference).toBe('light');
  expect(document.documentElement.dataset.theme).toBe('light');
});

import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { SkillsView } from '../../../web-react/src/features/plugins/SkillsView';
import { skillsApi } from '../../../web-react/src/api/skills';
import { sessionsApi } from '../../../web-react/src/api/sessions';
import { useAppStore } from '../../../web-react/src/stores/appStore';

let client: QueryClient;
beforeEach(() => {
  window.history.replaceState(null, '', '/home/more?section=skills');
  useAppStore.setState({ currentSessionId: 's1', sessions: [], chatDrafts: { s1: '整理资料' } });
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});
afterEach(() => { cleanup(); client.clear(); vi.restoreAllMocks(); });
const mount = () => render(React.createElement(QueryClientProvider, { client }, React.createElement(BrowserRouter, {}, React.createElement(SkillsView))));
it('returns to the current conversation with its draft preserved', async () => {
  vi.spyOn(skillsApi, 'list').mockResolvedValue({ skills: [{ name: 'demo' }] });
  mount();
  fireEvent.click(await screen.findByRole('button', { name: '使用技能 demo' }));
  await waitFor(() => expect(window.location.pathname).toBe('/sessions/s1'));
  expect(useAppStore.getState().chatDrafts.s1).toBe('调用 demo skill 整理资料');
});
it('creates a conversation when none exists and keeps the selected skill draft', async () => {
  useAppStore.setState({ currentSessionId: null });
  vi.spyOn(skillsApi, 'list').mockResolvedValue({ skills: [{ name: 'demo' }] });
  vi.spyOn(sessionsApi, 'create').mockResolvedValue({ id: 'new', messages: [] } as Awaited<ReturnType<typeof sessionsApi.create>>);
  mount();
  fireEvent.click(await screen.findByRole('button', { name: '使用技能 demo' }));
  await waitFor(() => expect(window.location.pathname).toBe('/sessions/new'));
  expect(useAppStore.getState().chatDrafts.new).toBe('调用 demo skill ');
});
it('reloads the list and opens the existing add-skill dialog', async () => {
  vi.spyOn(skillsApi, 'list').mockResolvedValueOnce({ skills: [] }).mockResolvedValue({ skills: [{ name: 'updated' }] });
  const reload = vi.spyOn(skillsApi, 'reload').mockResolvedValue({ ok: true, skills: [{ name: 'updated' }] });
  mount();
  await screen.findByText('暂无技能，可以添加一个。');
  fireEvent.click(screen.getByRole('button', { name: '重载技能' }));
  await screen.findByRole('button', { name: '使用技能 updated' });
  expect(reload).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: '添加技能' }));
  expect(screen.getByRole('dialog', { name: '添加技能' })).toBeTruthy();
});

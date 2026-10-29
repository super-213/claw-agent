import React, { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { fireEvent, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { Composer } from '../../../web-react/src/features/chat/Composer';
import { skillsApi } from '../../../web-react/src/api/skills';
import { tasksApi } from '../../../web-react/src/api/tasks';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const cleanups: (() => void)[] = [];
afterEach(() => { cleanups.splice(0).forEach(fn => fn()); vi.restoreAllMocks(); });
async function composer(initial: string) {
  vi.spyOn(tasksApi, 'members').mockResolvedValue({ current_member_id: 'a', members: [] });
  const onSend = vi.fn();
  const container = document.createElement('div'); document.body.appendChild(container);
  const root = createRoot(container);
  function Harness() {
    const [draft, setDraft] = useState(initial);
    return React.createElement(Composer, { disabled: false, draft, onDraftChange: setDraft, onSend, onUploadFiles: async () => [] });
  }
  await act(async () => root.render(React.createElement(Harness)));
  cleanups.push(() => { act(() => root.unmount()); container.remove(); });
  return { input: container.querySelector('textarea')!, onSend };
}
it('requires dollar plus space, selects with keyboard, then sends the explicit skill syntax', async () => {
  const list = vi.spyOn(skillsApi, 'list').mockResolvedValue({ skills: [{ name: 'demo', summary: '处理报告' }, { name: 'search' }] });
  const { input, onSend } = await composer('$');
  expect(screen.queryByRole('listbox')).toBeNull(); expect(list).not.toHaveBeenCalled();
  await act(async () => fireEvent.change(input, { target: { value: '$ ' } }));
  expect(screen.getByRole('listbox', { name: '已注册技能' })).toBeTruthy();
  expect(screen.getAllByRole('option')).toHaveLength(2);
  act(() => fireEvent.keyDown(input, { key: 'ArrowDown' }));
  expect(input.getAttribute('aria-activedescendant')).toBe(screen.getByRole('option', { name: /search/ }).id);
  act(() => fireEvent.keyDown(input, { key: 'Enter' }));
  expect(input.value).toBe('$ search '); expect(onSend).not.toHaveBeenCalled();
  expect(screen.queryByRole('listbox')).toBeNull();
  act(() => fireEvent.change(input, { target: { value: '$ search 查资料' } }));
  await act(async () => fireEvent.click(screen.getByTitle('发送 (Enter)')));
  expect(onSend).toHaveBeenCalledWith('$ search 查资料', []);
});
it('refreshes installed skills whenever the palette opens and supports click selection', async () => {
  const list = vi.spyOn(skillsApi, 'list').mockResolvedValueOnce({ skills: [] }).mockResolvedValue({ skills: [{ name: 'new-skill', allow_auto: false }] });
  const { input, onSend } = await composer('$ ');
  expect(screen.getByText('尚未注册技能')).toBeTruthy();
  act(() => fireEvent.keyDown(input, { key: 'Enter' })); expect(onSend).not.toHaveBeenCalled();
  await act(async () => fireEvent.change(input, { target: { value: '' } }));
  await act(async () => fireEvent.change(input, { target: { value: '$ ' } }));
  expect(list).toHaveBeenCalledTimes(2);
  act(() => fireEvent.click(screen.getByRole('option', { name: /new-skill/ })));
  expect(input.value).toBe('$ new-skill ');
});
it('filters, dismisses, reopens after editing, and retries failed requests', async () => {
  vi.spyOn(skillsApi, 'list').mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ skills: [{ name: 'demo', summary: '报告' }] });
  const { input } = await composer('$ ');
  expect(screen.getByText('技能列表加载失败')).toBeTruthy();
  await act(async () => fireEvent.click(screen.getByRole('button', { name: '重试' })));
  act(() => fireEvent.keyDown(input, { key: 'Escape' }));
  expect(screen.queryByRole('listbox')).toBeNull();
  await act(async () => fireEvent.change(input, { target: { value: '$ 报告' } }));
  expect(screen.getByRole('option', { name: /demo/ })).toBeTruthy();
  await act(async () => fireEvent.change(input, { target: { value: '$ ' } }));
  expect(screen.getByRole('listbox')).toBeTruthy();
});

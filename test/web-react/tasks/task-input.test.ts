import React, { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Composer } from '../../../web-react/src/features/chat/Composer';
import { commandFromText, tasksApi } from '../../../web-react/src/api/tasks';
import { mentionBoundary, validMentions } from '../../../web-react/src/features/tasks/taskSyntax';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const unmounts: (() => void)[] = [];
afterEach(() => { unmounts.forEach(f => f()); unmounts.length = 0; vi.restoreAllMocks(); });

async function composer(initial: string) {
  vi.spyOn(tasksApi, 'members').mockResolvedValue({ current_member_id: 'A', members: [
    { member_id: 'A', user_id: 'ua', display_name: '爸爸', status: 'active', aliases: [] },
    { member_id: 'B', user_id: 'ub', display_name: '妈妈', status: 'active', aliases: [] },
  ] });
  const onSend = vi.fn();
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  function Harness() {
    const [draft, setDraft] = useState(initial);
    return React.createElement(Composer, { disabled: false, draft, onDraftChange: setDraft, onSend, onUploadFiles: async () => [] });
  }
  await act(async () => root.render(React.createElement(Harness)));
  unmounts.push(() => { act(() => root.unmount()); container.remove(); });
  return { onSend, input: container.querySelector('textarea')! };
}

describe('literal command and mention grammar', () => {
  it('requires ASCII spaces and does not scan URLs, emails or quoted code', () => {
    for (const text of ['/', '/日程 明天', '/\t日程 明天', 'https://site/ 日程', '`/ 日程`', '@小明']) expect(commandFromText(text)).toBeNull();
    expect(commandFromText('/ 日程 明天买奶')).toBe('日程');
    expect(mentionBoundary('/ 备忘 引用“文字 @ 小明”', 11)).toBe(false);
    const inline = '/ 日程 明天 @ Alice A 买牛奶';
    expect(validMentions(inline, [{ member_id: 'A', label: 'Alice A', start: inline.indexOf('@ '), end: inline.indexOf('@ ') + 9 }])).toHaveLength(1);
    expect(validMentions('/ 备忘 a@b.com https://site/@ 爸爸', [{ member_id: 'A', label: '爸爸', start: 27, end: 31 }])).toEqual([]);
  });
  it('opens command menu and supports keyboard selection without sending', async () => {
    const { input, onSend } = await composer('/ ');
    expect(screen.getByRole('listbox', { name: '事项命令' })).toBeTruthy();
    input.focus();
    act(() => fireEvent.keyDown(input, { key: 'ArrowDown' }));
    expect(document.activeElement).toBe(input);
    expect(screen.getByRole('option', { name: '/ 备忘' }).getAttribute('aria-selected')).toBe('true');
    expect(input.getAttribute('aria-activedescendant')).toBe(screen.getByRole('option', { name: '/ 备忘' }).id);
    act(() => fireEvent.keyDown(input, { key: 'ArrowDown' }));
    act(() => fireEvent.keyDown(input, { key: 'Enter' }));
    expect(onSend).not.toHaveBeenCalled();
    expect(input.value).toBe('/ 家庭日程 ');
    expect(document.activeElement).toBe(input);
    expect(screen.queryByRole('listbox')).toBeNull();
  });
  it('binds multiple stable member IDs and removes deleted labels', async () => {
    const { input, onSend } = await composer('/ 家庭日程 @ ');
    act(() => fireEvent.click(screen.getByRole('option', { name: '爸爸' })));
    act(() => fireEvent.change(input, { target: { value: input.value + '@ ' } }));
    act(() => fireEvent.click(screen.getByRole('option', { name: '妈妈' })));
    act(() => fireEvent.change(input, { target: { value: input.value + '每周六大扫除' } }));
    await act(async () => fireEvent.click(screen.getByTitle('发送 (Enter)')));
    expect(onSend.mock.calls[0][2]).toMatchObject({ space_type: 'household', temporal_type: 'timed', completion_mode: 'all', mentions: [
      { member_id: 'A', label: '爸爸' }, { member_id: 'B', label: '妈妈' },
    ] });
    expect(validMentions('/ 家庭日程 每周六大扫除', onSend.mock.calls[0][2].mentions)).toEqual([]);
  });
  it('treats no-space @ text as ordinary prose', async () => {
    const { input, onSend } = await composer('/ 备忘 联系 @小明 或 mail@example.com');
    expect(screen.queryByRole('listbox')).toBeNull();
    await act(async () => fireEvent.click(screen.getByTitle('发送 (Enter)')));
    expect(onSend.mock.calls[0][2].mentions).toEqual([]);
    expect(input.value).toBe('');
  });
});

it('removing the visible member tag removes the assignment from the next submit', async () => {
  const { input, onSend } = await composer('/ 家庭备忘 @ ');
  act(() => fireEvent.click(screen.getByRole('option', { name: '爸爸' })));
  act(() => fireEvent.click(screen.getByRole('button', { name: '移除负责人 爸爸' })));
  act(() => fireEvent.change(input, { target: { value: input.value + '补充洗衣液' } }));
  await act(async () => fireEvent.click(screen.getByTitle('发送 (Enter)')));
  expect(onSend.mock.calls[0][2].mentions).toEqual([]);
});


it('keeps an empty palette open, suppresses Enter, and resets dismissal after editing', async () => {
  const { input, onSend } = await composer('/ 不存在');
  expect(screen.getByText('没有匹配的事项类型')).toBeTruthy();
  act(() => fireEvent.keyDown(input, { key: 'Enter' }));
  expect(onSend).not.toHaveBeenCalled();
  act(() => fireEvent.keyDown(input, { key: 'Escape' }));
  expect(screen.queryByRole('listbox')).toBeNull();
  expect(input.value).toBe('/ 不存在');
  act(() => fireEvent.change(input, { target: { value: '/ ' } }));
  expect(screen.getAllByRole('option')).toHaveLength(4);
  act(() => fireEvent.keyDown(input, { key: 'ArrowUp' }));
  act(() => fireEvent.keyDown(input, { key: 'Enter' }));
  expect(input.value).toBe('/ 家庭备忘 ');
});

it('switches command from its chip while preserving stable member bindings', async () => {
  const { input, onSend } = await composer('/ 日程 @ ');
  act(() => fireEvent.click(screen.getByRole('option', { name: '爸爸' })));
  act(() => fireEvent.change(input, { target: { value: input.value + '明天买奶' } }));
  act(() => fireEvent.click(screen.getByRole('button', { name: '切换事项命令' })));
  act(() => fireEvent.click(screen.getByRole('option', { name: '/ 家庭日程' })));
  expect(input.value).toBe('/ 家庭日程 @ 爸爸 明天买奶');
  expect(document.activeElement).toBe(input);
  await act(async () => fireEvent.click(screen.getByTitle('发送 (Enter)')));
  const invocation = onSend.mock.calls[0][2];
  expect(invocation.space_type).toBe('household');
  expect(validMentions(onSend.mock.calls[0][0], invocation.mentions)).toMatchObject([{ member_id: 'A', label: '爸爸' }]);
});

it('keeps completion and information options available in the compact popover', async () => {
  const { onSend } = await composer('/ 备忘 Wi-Fi 密码');
  expect(screen.queryByRole('combobox', { name: '多人完成规则' })).toBeNull();
  act(() => fireEvent.click(screen.getByRole('button', { name: '事项选项' })));
  act(() => fireEvent.click(screen.getByRole('checkbox', { name: /仅作信息记录/ })));
  act(() => fireEvent.change(screen.getByRole('combobox', { name: '多人完成规则' }), { target: { value: 'any' } }));
  act(() => fireEvent.click(screen.getByRole('button', { name: '关闭事项选项' })));
  await act(async () => fireEvent.click(screen.getByTitle('发送 (Enter)')));
  expect(onSend.mock.calls[0][2]).toMatchObject({ actionable: false, completion_mode: 'any' });
});


it('dismisses the palette on outside interaction without changing the draft', async () => {
  const { input } = await composer('/ ');
  act(() => fireEvent.pointerDown(document.body));
  expect(screen.queryByRole('listbox')).toBeNull();
  expect(input.value).toBe('/ ');
  act(() => fireEvent.change(input, { target: { value: '/ 家庭' } }));
  expect(screen.getAllByRole('option')).toHaveLength(2);
});

it('retains the explicit choice for time descriptions in memos', async () => {
  const { input, onSend } = await composer('/ 家庭备忘 明天的想法');
  act(() => fireEvent.click(screen.getByRole('checkbox', { name: '仅作文字' })));
  expect(screen.getByText('时间描述仅作文字保存')).toBeTruthy();
  await act(async () => fireEvent.click(screen.getByTitle('发送 (Enter)')));
  expect(onSend.mock.calls[0][2]).toMatchObject({ temporal_type: 'undated', literal_time_text: true });
  act(() => fireEvent.change(input, { target: { value: '/ 家庭备忘 明天买奶' } }));
  act(() => fireEvent.click(screen.getByRole('button', { name: '转为日程' })));
  expect(input.value).toBe('/ 家庭日程 明天买奶');
});

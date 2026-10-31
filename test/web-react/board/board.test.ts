import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { BoardChatCard } from '../../../web-react/src/features/board/BoardChatCard';
import { BoardMentionInput } from '../../../web-react/src/features/board/BoardMentionInput';
import { WorkbenchPanels } from '../../../web-react/src/features/board/WorkbenchPanels';
import { boardApi, emptyBoardData, type BoardView } from '../../../web-react/src/api/board';
import { clearCardEdits } from '../../../web-react/src/features/interactive-cards/state';
import { useAppStore } from '../../../web-react/src/stores/appStore';

vi.mock('../../../web-react/src/features/chat/preparePhoto', () => ({ MAX_ATTACHMENT_BYTES: 25 * 1024 * 1024, preparePhoto: vi.fn(async (file: File) => ({ file })) }));

let client: QueryClient;
let current: BoardView;
let submit: ReturnType<typeof vi.fn>;
beforeEach(() => {
  clearCardEdits(); localStorage.clear();
  useAppStore.setState({ currentUser: { id: 'alice', username: 'alice', role: 'user' } });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  current = { resource: { type: 'board_post_draft', id: 'draft' }, mode: 'draft', post: {
    ...emptyBoardData(), title: '饭在冰箱里', content_blocks: [{ type: 'text', text: '热一下即可。' }],
    id: 'draft', created_by: 'A', version: 1, state: 'draft', created_at: '2026-10-27T04:00:00Z',
  }, server_now: '2026-10-27T04:00:00Z', timezone: 'Asia/Shanghai', valid_until: null, next_transition_at: null,
    current_member_id: 'A', members: [{ member_id: 'A', display_name: '小林', status: 'active' }, { member_id: 'B', display_name: '小陈', status: 'active' }],
    read_only: false, read_only_reason: null, capabilities: { editable_fields: ['title'], actions: ['publish', 'save_draft'] } };
  submit = vi.fn(async () => current);
});
afterEach(() => { cleanup(); client.clear(); clearCardEdits(); vi.restoreAllMocks(); });
function mountCard(verifying = false) {
  return render(React.createElement(MemoryRouter, null, React.createElement(BoardChatCard, {
    view: current, context: { surface: 'chat', sessionId: 'session' }, editKey: 'alice:board-card',
    reference: { type: 'interactive_card', schema_version: 1, kind: 'board_post', card_id: 'card', mode: 'draft', resource: current.resource },
    busy: false, verifying, uncertain: false, error: '', retry: vi.fn(), refresh: vi.fn(), submit, savedSequence: 0,
  })));
}
it('submits chosen recipients and relative retention to the original draft without asking a model', async () => {
  mountCard();
  fireEvent.click(screen.getByLabelText('小陈', { exact: true }));
  fireEvent.change(screen.getByLabelText('便笺保留方式'), { target: { value: 'until' } });
  fireEvent.click(screen.getByRole('button', { name: '1 天', exact: true }));
  fireEvent.click(screen.getByRole('button', { name: '发布便笺', exact: true }));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  expect(submit.mock.calls[0][0]).toMatchObject({ action: 'publish', target: { id: 'draft', type: 'board_post_draft' }, expected_version: 1,
    data: { recipient_ids: ['B'], retention_mode: 'until', duration_hours: 24, expires_at: null } });
});
it('preserves local edits when a draft editor is closed and opened', () => {
  const mounted = mountCard();
  fireEvent.change(screen.getByLabelText('便笺标题'), { target: { value: '还未保存的文字' } });
  mounted.unmount();
  mountCard();
  expect(screen.getByLabelText('便笺标题')).toHaveValue('还未保存的文字');
});
it('blocks publication after failed image upload until the image is explicitly removed', async () => {
  vi.spyOn(boardApi, 'upload').mockRejectedValue(new Error('上传中断'));
  const mounted = mountCard();
  const file = new File(['png'], 'photo.png', { type: 'image/png' });
  fireEvent.change(mounted.container.querySelector('input[type=file]')!, { target: { files: [file] } });
  await screen.findByText('photo.png：上传中断');
  expect(screen.getByRole('button', { name: '发布便笺', exact: true })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: '移除失败图片' }));
  await waitFor(() => expect(screen.getByRole('button', { name: '发布便笺', exact: true })).toBeEnabled());
});
it('hides expired note contents even for the original author', () => {
  current.mode = 'saved'; current.post.state = 'expired'; current.read_only = true;
  current.capabilities = { editable_fields: [], actions: [] };
  mountCard();
  expect(screen.getByText('便笺已到期，无法查看。')).toBeTruthy();
  expect(screen.queryByText('热一下即可。')).toBeNull();
  expect(screen.queryByRole('button', { name: '编辑便笺' })).toBeNull();
  expect(screen.queryByRole('button', { name: '发布便笺' })).toBeNull();
});
it('offers all household members for bare @ without converting the input to a task command', () => {
  const change = vi.fn();
  render(React.createElement(BoardMentionInput, { text: '@ ', onChange: change,
    members: [{ member_id: 'B', user_id: 'bob', display_name: '小陈', aliases: [], status: 'active' }], disabled: false,
    children: () => React.createElement('textarea') }));
  fireEvent.click(screen.getByRole('option', { name: '小陈', exact: true }));
  expect(change).toHaveBeenCalledWith('@ 小陈 ');
});
it('switches workbench panels without discarding widget layout or leaking data across accounts', async () => {
  vi.spyOn(boardApi, 'feed').mockResolvedValue({ items: [], next_cursor: null, server_now: '2026-10-27T04:00:00Z' });
  const FixtureWidgets = ({ panelSwitch }: { panelSwitch?: React.ReactNode }) => React.createElement('div', null, panelSwitch, '原来的小组件');
  const child = React.createElement(FixtureWidgets);
  render(React.createElement(MemoryRouter, null, React.createElement(QueryClientProvider, { client }, React.createElement(WorkbenchPanels, { userId: 'alice', children: child }))));
  expect(screen.getByText('原来的小组件')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: '留言板', exact: true }));
  await screen.findByRole('button', { name: '写便笺', exact: true });
  expect(screen.queryByRole('combobox', { name: '便笺来源' })).toBeNull();
  expect(screen.queryByRole('combobox', { name: '便笺状态' })).toBeNull();
  expect(boardApi.feed).toHaveBeenCalledWith(null);
  expect(localStorage.getItem('claw.home.panel.v1.alice')).toBe('board');
  expect(localStorage.getItem('claw.home.panel.v1.bob')).toBeNull();
});

it('keeps every uploaded image in the publication when upload replies arrive before React renders', async () => {
  let sequence = 0;
  vi.spyOn(boardApi, 'upload').mockImplementation(async () => ({ asset_id: `asset_${String(++sequence).padStart(32, '0')}` }));
  const mounted = mountCard();
  fireEvent.change(mounted.container.querySelector('input[type=file]')!, { target: { files: [
    new File(['a'], 'one.png', { type: 'image/png' }),
    new File(['b'], 'two.png', { type: 'image/png' }),
  ] } });
  await waitFor(() => expect(screen.getByRole('button', { name: '发布便笺', exact: true })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: '发布便笺', exact: true }));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  expect(submit.mock.calls[0][0].data.content_blocks.filter((b: {type: string}) => b.type === 'image'))
    .toEqual([{ type: 'image', asset_id: 'asset_00000000000000000000000000000001', alt: 'one.png' }, { type: 'image', asset_id: 'asset_00000000000000000000000000000002', alt: 'two.png' }]);
});

it('does not publish an image reference when the upload response is missing its saved asset id', async () => {
  vi.spyOn(boardApi, 'upload').mockResolvedValue({} as { asset_id: string });
  const mounted = mountCard();
  fireEvent.change(mounted.container.querySelector('input[type=file]')!, { target: { files: [new File(['a'], 'one.png', { type: 'image/png' })] } });
  await screen.findByText('one.png：图片未确认保存成功，请重试上传。');
  await waitFor(() => expect(screen.getByRole('button', { name: '发布便笺', exact: true })).toBeDisabled());
  expect(submit).not.toHaveBeenCalled();
});

it('resumes an interrupted selection after closing and reopening the editor', async () => {
  let finish!: (value: { asset_id: string }) => void;
  const uploaded = { asset_id: 'asset_00000000000000000000000000000003' };
  vi.spyOn(boardApi, 'upload').mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })).mockResolvedValue(uploaded);
  const mounted = mountCard();
  fireEvent.change(mounted.container.querySelector('input[type=file]')!, { target: { files: [new File(['a'], 'saved.png', { type: 'image/png' })] } });
  expect(screen.getByRole('button', { name: '发布便笺', exact: true })).toBeDisabled();
  expect(screen.getByRole('button', { name: '重新读取', exact: true })).toBeDisabled();
  await waitFor(() => expect(boardApi.upload).toHaveBeenCalledTimes(1));
  mounted.unmount();
  finish(uploaded);
  mountCard();
  await waitFor(() => expect(boardApi.upload).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.getByRole('button', { name: '发布便笺', exact: true })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: '发布便笺', exact: true }));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  expect(submit.mock.calls[0][0].data.content_blocks).toContainEqual({ type: 'image', asset_id: uploaded.asset_id, alt: 'saved.png' });
});

it('keeps a failed selection blocking publication after the editor is reopened', async () => {
  vi.spyOn(boardApi, 'upload').mockRejectedValue(new Error('上传中断'));
  const mounted = mountCard();
  fireEvent.change(mounted.container.querySelector('input[type=file]')!, { target: { files: [new File(['a'], 'failed.png', { type: 'image/png' })] } });
  await screen.findByText('failed.png：上传中断');
  mounted.unmount(); mountCard();
  await screen.findByText('failed.png：上传中断');
  expect(screen.getByRole('button', { name: '发布便笺', exact: true })).toBeDisabled();
  expect(submit).not.toHaveBeenCalled();
});


it('restores a saved-note image edit even when closed before the first upload finishes', async () => {
  current.mode = 'saved'; current.resource = { type: 'board_post', id: 'post' };
  current.post.state = 'active';
  const upload = vi.spyOn(boardApi, 'upload').mockImplementationOnce(() => new Promise(() => {}))
    .mockResolvedValue({ asset_id: 'asset_00000000000000000000000000000004' });
  const mounted = mountCard();
  fireEvent.click(screen.getByRole('button', { name: '编辑便笺' }));
  fireEvent.change(mounted.container.querySelector('input[type=file]')!, { target: { files: [new File(['a'], 'edit.png', { type: 'image/png' })] } });
  await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
  mounted.unmount(); mountCard();
  await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.getByRole('button', { name: '保存修改' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: '保存修改' }));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  expect(submit.mock.calls[0][0].data.content_blocks).toContainEqual({ type: 'image', asset_id: 'asset_00000000000000000000000000000004', alt: 'edit.png' });
});

it('shows a local preview before upload completes, keeps it on failure, and frees its object URL', async () => {
  const OriginalURL = URL;
  const create = vi.fn(() => 'blob:selected-photo');
  const revoke = vi.fn();
  vi.stubGlobal('URL', class extends OriginalURL { static createObjectURL = create; static revokeObjectURL = revoke; });
  try {
    let rejectUpload!: (error: Error) => void;
    vi.spyOn(boardApi, 'upload').mockImplementation(() => new Promise((_, reject) => { rejectUpload = reject; }));
    const mounted = mountCard();
    fireEvent.change(mounted.container.querySelector('input[type=file]')!, { target: { files: [new File(['photo'], 'local.jpg', { type: 'image/jpeg' })] } });
    expect(await screen.findByAltText('所选图片：local.jpg')).toHaveAttribute('src', 'blob:selected-photo');
    expect(screen.getByText('正在上传 0%')).toBeTruthy();
    rejectUpload(new Error('网络中断'));
    await screen.findByText('上传失败，图片尚未保存');
    expect(screen.getByAltText('所选图片：local.jpg')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '移除失败图片' }));
    await waitFor(() => expect(revoke).toHaveBeenCalledWith('blob:selected-photo'));
    expect(screen.queryByAltText('所选图片：local.jpg')).toBeNull();
    mounted.unmount();
  } finally { vi.unstubAllGlobals(); }
});


it('accepts a photo selection while focus return is rechecking card permissions', async () => {
  vi.spyOn(boardApi, 'upload').mockResolvedValue({ asset_id: 'asset_00000000000000000000000000000005' });
  const mounted = mountCard(true);
  const input = mounted.container.querySelector('input[type=file]')!;
  expect(input).not.toBeDisabled();
  expect(screen.getByRole('button', { name: '发布便笺', exact: true })).toBeDisabled();
  fireEvent.change(input, { target: { files: [new File(['photo'], 'return-from-picker.jpg', { type: 'image/jpeg' })] } });
  expect(screen.getByText('已读取 1 张图片')).toBeTruthy();
  await waitFor(() => expect(boardApi.upload).toHaveBeenCalledTimes(1));
  expect(await screen.findByText('图片已上传，发布便笺后生效')).toBeTruthy();
  expect(screen.getByRole('button', { name: '发布便笺', exact: true })).toBeDisabled();
});

it('shows actual transfer progress and aborts the request when cancelled', async () => {
  let report!: (loaded: number, total: number) => void;
  let signal!: AbortSignal;
  vi.spyOn(boardApi, 'upload').mockImplementation((_file, options) => new Promise((_, reject) => {
    report = options!.onProgress!; signal = options!.signal!;
    signal.addEventListener('abort', () => reject(new DOMException('cancel', 'AbortError')));
  }));
  const mounted = mountCard();
  fireEvent.change(mounted.container.querySelector('input[type=file]')!, { target: { files: [new File(['photo'], 'progress.jpg', { type: 'image/jpeg' })] } });
  await waitFor(() => expect(boardApi.upload).toHaveBeenCalledTimes(1));
  const { act } = await import('@testing-library/react');
  act(() => report(50, 100));
  expect(screen.getByText('正在上传 50%')).toBeTruthy();
  expect(screen.getByRole('progressbar', { name: 'progress.jpg 上传进度' })).toHaveAttribute('value', '50');
  act(() => report(100, 100));
  expect(screen.getByText('已传输 100%，等待服务器保存…')).toBeTruthy();
  const cancel = screen.getByRole('button', { name: '取消上传', exact: true });
  expect(cancel).toBeEnabled(); fireEvent.click(cancel);
  expect(signal.aborted).toBe(true);
  await screen.findByText('已取消上传，图片尚未保存');
  expect(screen.getByRole('button', { name: '发布便笺', exact: true })).toBeDisabled();
  mounted.unmount(); mountCard();
  await screen.findByText('已取消上传，图片尚未保存');
  expect(boardApi.upload).toHaveBeenCalledTimes(1);
});

it('sends the compressed copy and reports its size, keeping the original for preview', async () => {
  const { preparePhoto } = await import('../../../web-react/src/features/chat/preparePhoto');
  const compressed = new File(['x'], 'small.jpg', { type: 'image/jpeg' });
  vi.mocked(preparePhoto).mockResolvedValueOnce({ file: compressed, note: '已压缩' });
  vi.spyOn(boardApi, 'upload').mockResolvedValue({ asset_id: 'asset_00000000000000000000000000000006' });
  const mounted = mountCard();
  const original = new File([new Uint8Array(2048)], 'original.jpg', { type: 'image/jpeg' });
  fireEvent.change(mounted.container.querySelector('input[type=file]')!, { target: { files: [original] } });
  await waitFor(() => expect(boardApi.upload).toHaveBeenCalledWith(compressed, expect.objectContaining({ signal: expect.any(AbortSignal), onProgress: expect.any(Function) })));
  expect(preparePhoto).toHaveBeenCalledWith(original, true);
  expect(await screen.findByText('2 KB → 0 KB')).toBeTruthy();
});

it('does not interrupt an explicitly requested update with an unsaved-card prompt', async () => {
  const { setImmediateUpdate } = await import('../../../web-react/src/features/pwa/updateState');
  mountCard();
  fireEvent.change(screen.getByLabelText('便笺标题'), { target: { value: '未保存修改' } });
  const normalLeave = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(normalLeave);
  expect(normalLeave.defaultPrevented).toBe(true);
  try {
    setImmediateUpdate(true);
    const updateLeave = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(updateLeave);
    expect(updateLeave.defaultPrevented).toBe(false);
  } finally { setImmediateUpdate(false); }
});

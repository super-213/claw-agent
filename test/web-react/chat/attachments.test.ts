import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Composer } from '../../../web-react/src/features/chat/Composer';
import { tasksApi } from '../../../web-react/src/api/tasks';
import type { UploadOptions } from '../../../web-react/src/api/chat';
import type { MessageMedia } from '../../../web-react/src/api/types';

beforeEach(() => {
  vi.spyOn(tasksApi, 'members').mockResolvedValue({ members: [] });
  Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: true });
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:preview') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it('uploads sequentially, retries only the failed attachment and retains media when sending fails', async () => {
  const upload = vi.fn().mockResolvedValueOnce([{ name: 'first.txt', path: 'first.txt' }])
    .mockRejectedValueOnce(new Error('网络断开'))
    .mockResolvedValueOnce([{ name: 'second.txt', path: 'second.txt' }]);
  const send = vi.fn().mockResolvedValue(false);
  const draft = vi.fn();
  const view = render(React.createElement(Composer, { disabled: false, draft: 'hello', onDraftChange: draft, onSend: send, onUploadFiles: upload }));
  fireEvent.change(view.container.querySelector('#composer-file-input')!, { target: { files: [new File(['a'], 'first.txt'), new File(['b'], 'second.txt')] } });
  await screen.findByText('网络断开');
  expect(upload).toHaveBeenCalledTimes(2);
  expect(screen.getByRole('button', { name: '发送' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: '重试' }));
  await waitFor(() => expect(screen.getByRole('button', { name: '发送' })).toBeEnabled());
  expect(upload.mock.calls[2][0][0].name).toBe('second.txt');
  fireEvent.click(screen.getByRole('button', { name: '发送' }));
  await screen.findByText('发送未完成，附件已保留。请先核对会话中的结果。');
  expect(screen.getByText('first.txt')).toBeVisible();
  expect(screen.getByText('second.txt')).toBeVisible();
  expect(draft).toHaveBeenLastCalledWith('hello');
});

it('can cancel an active upload and remove a queued attachment without sending it', async () => {
  let signal: AbortSignal | undefined;
  const upload = vi.fn((_files: File[], options?: UploadOptions) => new Promise<MessageMedia[]>((_resolve, reject) => {
    signal = options?.signal;
    signal?.addEventListener('abort', () => reject(new Error('已取消上传')));
  }));
  const view = render(React.createElement(Composer, { disabled: false, draft: '', onDraftChange: vi.fn(), onSend: vi.fn(), onUploadFiles: upload }));
  fireEvent.change(view.container.querySelector('#composer-file-input')!, { target: { files: [new File(['a'], 'first.txt'), new File(['b'], 'second.txt')] } });
  await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByTitle('移除附件'));
  await act(async () => { fireEvent.click(screen.getByTitle('取消上传并移除')); });
  expect(signal?.aborted).toBe(true);
  expect(upload).toHaveBeenCalledTimes(1);
  expect(screen.queryByText('first.txt')).toBeNull();
  expect(screen.queryByText('second.txt')).toBeNull();
});

import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { beginActivity, hasUnsavedWork } from '../../../web-react/src/features/pwa/activity';
import { useAppStore } from '../../../web-react/src/stores/appStore';
import { jsonRequest } from '../../../web-react/src/api/client';

beforeEach(() => {
  document.body.innerHTML = '';
  useAppStore.setState({ streams: {}, homeDraft: '', chatDrafts: {}, pendingChatMessage: null });
});
afterEach(() => { document.body.innerHTML = ''; vi.restoreAllMocks(); });

it('blocks updates for work in inactive chats and pending uploads until it is finished', () => {
  expect(hasUnsavedWork()).toBe(false);
  const finish = beginActivity();
  expect(hasUnsavedWork()).toBe(true);
  finish();
  expect(hasUnsavedWork()).toBe(false);
  useAppStore.getState().setChatDraft('other-session', '未发送');
  expect(hasUnsavedWork()).toBe(true);
  useAppStore.getState().setChatDraft('other-session', '');
  expect(hasUnsavedWork()).toBe(false);
});

it('protects non-chat forms and dialogs as well as active generation', () => {
  document.body.innerHTML = '<form><input value="尚未保存的资料标题"></form>';
  expect(hasUnsavedWork()).toBe(true);
  document.body.innerHTML = '<section role="dialog"></section>';
  expect(hasUnsavedWork()).toBe(true);
  document.body.innerHTML = '';
  useAppStore.getState().beginStream('session', 'message');
  expect(hasUnsavedWork()).toBe(true);
  useAppStore.getState().endStream('session');
  expect(hasUnsavedWork()).toBe(false);
});

it('blocks updates during a pending write even after its form has been closed', async () => {
  let resolve!: (response: Response) => void;
  vi.spyOn(globalThis, 'fetch').mockImplementation(() => new Promise<Response>(done => { resolve = done; }));
  const write = jsonRequest('/api/example', { method: 'POST' });
  expect(hasUnsavedWork()).toBe(true);
  resolve(new Response('{"ok":true}', { headers: { 'Content-Type': 'application/json' } }));
  await write;
  expect(hasUnsavedWork()).toBe(false);
});

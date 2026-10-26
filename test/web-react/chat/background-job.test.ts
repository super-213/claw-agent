import { afterEach, expect, it, vi } from 'vitest';
import { AcceptedJobError, chatApi, isViewingChat } from '../../../web-react/src/api/chat';
import { useAppStore } from '../../../web-react/src/stores/appStore';

afterEach(() => { vi.restoreAllMocks(); document.body.innerHTML = ''; });

it('retains the accepted task identity when an event reader fails, without resending the question', async () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({ job: { id: 'job-1', session_id: 'session', status: 'running' } })))
    .mockRejectedValueOnce(new Error('connection closed'));
  const events = vi.fn();
  const result = chatApi.stream({ sessionId: 'session', message: 'question', requestId: 'request-0001' }, events);
  await expect(result).rejects.toBeInstanceOf(AcceptedJobError);
  expect(events).toHaveBeenCalledWith(expect.objectContaining({ type: 'job_started', job: expect.objectContaining({ id: 'job-1' }) }));
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(fetcher.mock.calls[0][0]).toBe('/api/chat/jobs');
  expect(fetcher.mock.calls[1][0]).toBe('/api/chat/jobs/job-1/events');
});

it('acknowledges completion only if the conversation is actually visible', async () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({ job: { id: 'job-1', session_id: 'session', status: 'running' } })))
    .mockResolvedValueOnce(new Response('{"type":"done"}\n'));
  useAppStore.getState().setCurrentSessionId('session');
  document.body.innerHTML = '<main>用户已经切到家庭首页</main>';
  await chatApi.stream({ sessionId: 'session', message: 'question' }, vi.fn());
  expect(fetcher).toHaveBeenCalledTimes(2);
  const chat = document.createElement('div');
  chat.className = 'chat-workspace'; chat.dataset.sessionId = 'session';
  chat.getClientRects = () => [{ width: 100, height: 100 }] as unknown as DOMRectList;
  document.body.appendChild(chat);
  expect(isViewingChat('session')).toBe(true);
  expect(isViewingChat('another')).toBe(false);
});

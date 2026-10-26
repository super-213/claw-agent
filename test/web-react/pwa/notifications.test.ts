import { afterEach, expect, it, vi } from 'vitest';
import { enableChatNotifications } from '../../../web-react/src/features/pwa/chatNotifications';

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('requests permission during the click call before awaiting worker readiness and binds the subscription to the backend', async () => {
  const permission = vi.fn().mockResolvedValue('granted');
  vi.stubGlobal('Notification', { requestPermission: permission });
  const subscription = { toJSON: () => ({ endpoint: 'https://web.push.apple.com/test' }) };
  const subscribe = vi.fn().mockResolvedValue(subscription);
  Object.defineProperty(window.navigator, 'serviceWorker', { configurable: true, value: { getRegistration: vi.fn().mockResolvedValue({ active: {}, pushManager: { getSubscription: vi.fn().mockResolvedValue(null), subscribe } }) } });
  const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"id":"device","enabled":true}'));
  const promise = enableChatNotifications({ configured: true, public_key: 'BA', devices: [] });
  expect(permission).toHaveBeenCalledTimes(1);
  expect(subscribe).not.toHaveBeenCalled();
  await promise;
  expect(subscribe).toHaveBeenCalledWith(expect.objectContaining({ userVisibleOnly: true }));
  expect(fetcher.mock.calls[0][0]).toBe('/api/chat-notifications/subscribe');
});

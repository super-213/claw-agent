import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { PwaStatus } from '../../../web-react/src/features/pwa/PwaStatus';
import { beginActivity } from '../../../web-react/src/features/pwa/activity';
import { isImmediateUpdate, setImmediateUpdate } from '../../../web-react/src/features/pwa/updateState';
vi.mock('../../../web-react/src/features/pwa/useConnectionStatus', () => ({ useConnectionStatus: () => ({ online: true, disconnected: false }), connectionNotice: '' }));
afterEach(() => { cleanup(); setImmediateUpdate(false); vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

it('starts updating immediately with unfinished uploads and form values', async () => {
  vi.stubEnv('PROD', true); vi.stubGlobal('isSecureContext', true);
  vi.stubGlobal('MessageChannel', class { port1 = { close: vi.fn(), onmessage: null }; port2 = {}; });
  const postMessage = vi.fn();
  const registration = { waiting: { postMessage }, addEventListener: vi.fn(), removeEventListener: vi.fn() };
  const original = Object.getOwnPropertyDescriptor(navigator, 'serviceWorker');
  Object.defineProperty(navigator, 'serviceWorker', { configurable: true, value: { controller: {}, register: vi.fn().mockResolvedValue(registration), addEventListener: vi.fn(), removeEventListener: vi.fn() } });
  const finish = beginActivity();
  try {
    render(React.createElement(React.Fragment, null, React.createElement('textarea', { defaultValue: '未保存输入' }), React.createElement(PwaStatus)));
    fireEvent.click(await screen.findByRole('button', { name: '更新', exact: true }));
    expect(postMessage).toHaveBeenCalledWith({ type: 'APPLY_UPDATE' }, expect.any(Array));
    expect(isImmediateUpdate()).toBe(true);
    expect(screen.getByText('正在更新，请稍候…')).toBeTruthy();
    expect(screen.queryByText(/先完成|先保存|关闭本站/)).toBeNull();
  } finally {
    finish(); cleanup();
    if (original) Object.defineProperty(navigator, 'serviceWorker', original);
    else Reflect.deleteProperty(navigator, 'serviceWorker');
  }
});

it('activates the waiting worker without requiring other windows to close', async () => {
  const listeners: Record<string, (event: any) => void> = {};
  const skipWaiting = vi.fn().mockResolvedValue(undefined);
  const matchAll = vi.fn().mockResolvedValue([{}, {}]);
  const self = { __WB_MANIFEST: [], clients: { matchAll }, skipWaiting, addEventListener: (name: string, listener: (event: any) => void) => { listeners[name] = listener; } };
  const source = readFileSync(resolve(process.cwd(), 'src/pwa/sw.js'), 'utf8').replace(/^import .*;$/gm, '');
  new Function('self', 'setCacheNameDetails', 'precacheAndRoute', 'registerRoute', 'NavigationRoute', 'createHandlerBoundToURL', 'clientsClaim', source)(self, vi.fn(), vi.fn(), vi.fn(), function () {}, vi.fn(), vi.fn());
  let completed: Promise<unknown> = Promise.resolve();
  const postMessage = vi.fn();
  listeners.message({ data: { type: 'APPLY_UPDATE' }, ports: [{ postMessage }], waitUntil: (promise: Promise<unknown>) => { completed = promise; } });
  await completed;
  expect(skipWaiting).toHaveBeenCalledOnce();
  expect(matchAll).not.toHaveBeenCalled();
  expect(postMessage).toHaveBeenCalledWith({ ok: true });
});

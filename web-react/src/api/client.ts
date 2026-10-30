import { useAppStore } from '../stores/appStore';
import { cacheableRead, cacheContext, cachedResponse, saveResponse, clearResponseCache, invalidateResponseCache } from '../features/offline/responseCache';
import { createNdjsonParseState, flushNdjson, isTerminalStreamError, parseNdjsonChunk } from './stream';
import type { ChatStreamEvent } from './types';
import { beginActivity } from '../features/pwa/activity';

export class ApiError extends Error {
  status: number;
  data: any;
  response: Response;

  constructor(message: string, response: Response, data: any) {
    super(message);
    this.name = 'ApiError';
    this.status = response.status;
    this.data = data;
    this.response = response;
  }
}

const emitUnauthorized = () => {
  window.dispatchEvent(new CustomEvent('claw-api-unauthorized'));
};

const parseJson = async (response: Response): Promise<any> => {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if ([401, 403].includes(response.status)) await clearResponseCache();
    if (response.status === 401) emitUnauthorized();
    throw new ApiError(data.message || data.error || '请求失败', response, data);
  }
  return data;
};

export const jsonRequest = async <T>(url: string, options: RequestInit = {}): Promise<T> => {
  const writing = options.method && !['GET', 'HEAD'].includes(options.method.toUpperCase());
  if (writing && !window.navigator.onLine) throw new Error('当前离线，请联网后重试。');
  const finish = writing ? beginActivity() : () => undefined;
  const context = cacheContext(useAppStore.getState().currentUser?.id);
  const cacheRead = options.cache !== 'no-store' && !writing && (options.method || 'GET').toUpperCase() === 'GET' && cacheableRead(url);
  try {
    let response: Response;
    try {
      response = await fetch(url, {
        ...options,
        headers: {
          Accept: 'application/json',
          ...(options.body ? { 'Content-Type': 'application/json' } : {}),
          ...(options.headers || {}),
        },
      });
    } catch (error) {
      if (cacheRead && !options.signal?.aborted && error instanceof TypeError) {
        const cached = await cachedResponse(url, context);
        if (cached) {
          window.dispatchEvent(new Event('claw-cache-fallback'));
          return cached.data as T;
        }
      }
      throw error;
    }
    const data = await parseJson(response) as T;
    if (cacheRead) window.dispatchEvent(new Event('claw-cache-fresh'));
    if (writing) await invalidateResponseCache(url);
    else if (cacheRead && url !== '/api/auth/me') await saveResponse(url, data, context);
    return data;
  } finally { finish(); }
};

export const formRequest = async <T>(url: string, formData: FormData, options: RequestInit = {}): Promise<T> => {
  if (!window.navigator.onLine) throw new Error('当前离线，请联网后上传。');
  const finish = beginActivity();
  try {
    const response = await fetch(url, {
      ...options,
      method: options.method || 'POST',
      body: formData,
      headers: { Accept: 'application/json', ...(options.headers || {}) },
    });
    const data = await parseJson(response) as T;
    await invalidateResponseCache(url);
    return data;
  } finally { finish(); }
};

interface StreamOptions extends RequestInit {
  onEvent?: (event: ChatStreamEvent) => void;
}

export const streamRequest = async (url: string, options: StreamOptions = {}): Promise<ChatStreamEvent | null> => {
  if (!window.navigator.onLine) throw new Error('当前离线，请联网后发送。');
  const { onEvent = () => undefined, ...requestOptions } = options;
  const response = await fetch(url, {
    ...requestOptions,
    headers: {
      Accept: 'application/x-ndjson, application/json',
      ...(requestOptions.body ? { 'Content-Type': 'application/json' } : {}),
      ...(requestOptions.headers || {}),
    },
  });

  if (!response.ok) {
    await parseJson(response);
    return null;
  }

  if (!response.body) {
    const data = (await response.json()) as ChatStreamEvent;
    onEvent(data);
    return data;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const state = createNdjsonParseState();
  let finalEvent: ChatStreamEvent | null = null;

  const emit = (event: ChatStreamEvent) => {
    onEvent(event);
    if (event.type === 'done') finalEvent = event;
    if (isTerminalStreamError(event)) {
      throw new Error(event.message || '请求失败');
    }
  };

  while (true) {
    let timer = 0;
    const { value, done } = await Promise.race([
      reader.read(),
      new Promise<never>((_resolve, reject) => {
        timer = window.setTimeout(() => {
          void reader.cancel().catch(() => undefined);
          reject(new Error('长时间未收到新内容，连接已结束。请重新读取会话核对结果。'));
        }, 240000);
      }),
    ]).finally(() => window.clearTimeout(timer));
    if (done) break;
    parseNdjsonChunk<ChatStreamEvent>(state, decoder.decode(value, { stream: true }), emit);
  }

  parseNdjsonChunk<ChatStreamEvent>(state, decoder.decode(), emit);
  flushNdjson<ChatStreamEvent>(state, emit);
  if (!finalEvent) throw new Error('连接已中断。请重新读取会话，确认结果后再决定是否重试。');
  return finalEvent;
};

import { createNdjsonParseState, flushNdjson, isTerminalStreamError, parseNdjsonChunk } from './stream';
import type { ChatStreamEvent } from './types';

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
    if (response.status === 401) emitUnauthorized();
    throw new ApiError(data.message || data.error || '请求失败', response, data);
  }
  return data;
};

export const jsonRequest = async <T>(url: string, options: RequestInit = {}): Promise<T> => {
  const response = await fetch(url, {
    ...options,
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });
  return parseJson(response) as Promise<T>;
};

interface StreamOptions extends RequestInit {
  onEvent?: (event: ChatStreamEvent) => void;
}

export const streamRequest = async (url: string, options: StreamOptions = {}): Promise<ChatStreamEvent | null> => {
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
    const { value, done } = await reader.read();
    if (done) break;
    parseNdjsonChunk<ChatStreamEvent>(state, decoder.decode(value, { stream: true }), emit);
  }

  parseNdjsonChunk<ChatStreamEvent>(state, decoder.decode(), emit);
  flushNdjson<ChatStreamEvent>(state, emit);
  return finalEvent;
};

import type { ChatStreamEvent } from './types';

export interface NdjsonParseState {
  buffer: string;
}

export const createNdjsonParseState = (): NdjsonParseState => ({ buffer: '' });

export const parseNdjsonChunk = <T>(
  state: NdjsonParseState,
  chunk: string,
  emit: (event: T) => void,
): void => {
  state.buffer += chunk;
  const lines = state.buffer.split('\n');
  state.buffer = lines.pop() || '';

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    emit(JSON.parse(trimmed) as T);
  }
};

export const flushNdjson = <T>(
  state: NdjsonParseState,
  emit: (event: T) => void,
): void => {
  const trimmed = state.buffer.trim();
  state.buffer = '';
  if (trimmed) {
    emit(JSON.parse(trimmed) as T);
  }
};

export const isTerminalStreamError = (event: ChatStreamEvent): event is Extract<ChatStreamEvent, { type: 'error' }> =>
  event.type === 'error';

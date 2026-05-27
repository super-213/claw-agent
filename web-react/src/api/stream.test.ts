import { describe, expect, it } from 'vitest';
import { createNdjsonParseState, flushNdjson, parseNdjsonChunk } from './stream';

describe('NDJSON stream parser', () => {
  it('parses full and split lines without losing buffered content', () => {
    const state = createNdjsonParseState();
    const events: Array<Record<string, unknown>> = [];

    parseNdjsonChunk<Record<string, unknown>>(state, '{"type":"step","message":"a"}\n{"type":"model_', (event) => events.push(event));
    expect(events).toEqual([{ type: 'step', message: 'a' }]);

    parseNdjsonChunk<Record<string, unknown>>(state, 'delta","delta":"b"}\n', (event) => events.push(event));
    flushNdjson<Record<string, unknown>>(state, (event) => events.push(event));

    expect(events).toEqual([
      { type: 'step', message: 'a' },
      { type: 'model_delta', delta: 'b' },
    ]);
    expect(state.buffer).toBe('');
  });
});

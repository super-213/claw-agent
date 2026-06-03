import { beforeEach, describe, expect, it } from 'vitest';
import type { Message } from '../../../web-react/src/api/types';
import { useAppStore } from '../../../web-react/src/stores/appStore';

const resetStore = () => {
  useAppStore.setState({
    currentUser: null,
    sessions: [],
    skills: [],
    config: null,
    currentSessionId: null,
    messages: [],
    sessionMessages: {},
    streams: {},
    statusText: '就绪',
  });
};

const message = (role: string, content: string): Message => ({ role, content });

describe('appStore session message cache', () => {
  beforeEach(() => {
    resetStore();
  });

  it('updates a background session without replacing the visible session messages', () => {
    const state = useAppStore.getState();

    state.setSessionMessages('session-a', [message('assistant', '当前会话内容')]);
    state.setCurrentSessionId('session-a');
    useAppStore.getState().setSessionMessages('session-b', [message('assistant', '后台正在输出')]);

    expect(useAppStore.getState().messages).toEqual([message('assistant', '当前会话内容')]);
    expect(useAppStore.getState().sessionMessages['session-b']).toEqual([message('assistant', '后台正在输出')]);
  });

  it('shows cached streamed content immediately when switching back to that session', () => {
    const state = useAppStore.getState();

    state.setSessionMessages('session-a', [message('assistant', '当前会话内容')]);
    state.setSessionMessages('session-b', [message('assistant', '流式输出片段')]);
    state.setCurrentSessionId('session-a');
    useAppStore.getState().setCurrentSessionId('session-b');

    expect(useAppStore.getState().messages).toEqual([message('assistant', '流式输出片段')]);
  });
});

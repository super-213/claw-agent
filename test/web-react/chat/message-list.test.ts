import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it } from 'vitest';
import type { Message } from '../../../web-react/src/api/types';
import { MessageList } from '../../../web-react/src/features/chat/MessageList';
import { isNearBottom } from '../../../web-react/src/features/chat/scrollBehavior';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const noop = () => {};

const messagesWithAssistant = (content: string): Message[] => [
  { role: 'user', content: '写一段长文本', node_id: 'user-1' },
  { role: 'assistant', content, node_id: 'assistant-1' },
];

const setScrollMetrics = (
  element: HTMLElement,
  metrics: {
    clientHeight: number;
    scrollHeight: () => number;
  },
) => {
  Object.defineProperty(element, 'clientHeight', {
    configurable: true,
    get: () => metrics.clientHeight,
  });
  Object.defineProperty(element, 'scrollHeight', {
    configurable: true,
    get: metrics.scrollHeight,
  });
};

const renderMessageList = (messages: Message[], conversationKey = 'session-1') => {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);

  const rerender = (nextMessages: Message[], nextConversationKey = conversationKey) => {
    act(() => {
      root.render(
        React.createElement(MessageList, {
          messages: nextMessages,
          conversationKey: nextConversationKey,
          onCreateBranch: noop,
        }),
      );
    });
  };

  rerender(messages, conversationKey);

  return {
    container,
    rerender,
    unmount: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
};

describe('MessageList auto-scroll behavior', () => {
  it('detects whether the scroll position is close enough to the bottom', () => {
    expect(isNearBottom({ scrollHeight: 1000, scrollTop: 420, clientHeight: 500 })).toBe(true);
    expect(isNearBottom({ scrollHeight: 1000, scrollTop: 300, clientHeight: 500 })).toBe(false);
  });

  it('does not force the user back to the bottom while streamed content updates', () => {
    let scrollHeight = 1000;
    const view = renderMessageList(messagesWithAssistant('开头'));
    const scrollNode = view.container.querySelector('.chat-window') as HTMLElement;
    setScrollMetrics(scrollNode, { clientHeight: 500, scrollHeight: () => scrollHeight });

    scrollNode.scrollTop = 180;
    scrollNode.dispatchEvent(new Event('scroll', { bubbles: true }));

    scrollHeight = 1600;
    view.rerender(messagesWithAssistant('开头\n\n正在持续输出更多内容...'));

    expect(scrollNode.scrollTop).toBe(180);
    view.unmount();
  });

  it('continues following streamed content when the user is already at the bottom', () => {
    let scrollHeight = 1000;
    const view = renderMessageList(messagesWithAssistant('开头'));
    const scrollNode = view.container.querySelector('.chat-window') as HTMLElement;
    setScrollMetrics(scrollNode, { clientHeight: 500, scrollHeight: () => scrollHeight });

    scrollNode.scrollTop = 500;
    scrollNode.dispatchEvent(new Event('scroll', { bubbles: true }));

    scrollHeight = 1600;
    view.rerender(messagesWithAssistant('开头\n\n正在持续输出更多内容...'));

    expect(scrollNode.scrollTop).toBe(1600);
    view.unmount();
  });
});

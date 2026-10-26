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
    act(() => scrollNode.dispatchEvent(new Event('scroll', { bubbles: true })));

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
    act(() => scrollNode.dispatchEvent(new Event('scroll', { bubbles: true })));

    scrollHeight = 1600;
    view.rerender(messagesWithAssistant('开头\n\n正在持续输出更多内容...'));

    expect(scrollNode.scrollTop).toBe(1600);
    view.unmount();
  });
});


it('keeps execution arguments and output behind an accessible disclosure', () => {
  const view = renderMessageList([
    { role: 'assistant', content: '', node_id: 'call', tool_calls: [{ id: 'call-1', type: 'function', function: { name: 'family_task_get', arguments: '{"task_id":"t"}' } }] },
    { role: 'tool', content: '{"status":"success","output":{"title":"真实事项"}}', tool_call_id: 'call-1', name: 'family_task_get' },
  ]);
  const disclosure = view.container.querySelector('details')!;
  expect(disclosure.open).toBe(false);
  expect(disclosure.querySelector('summary')?.textContent).toContain('查询事项');
  expect(disclosure.querySelector('pre')?.textContent).toContain('真实事项');
  disclosure.open = true;
  expect(disclosure.open).toBe(true);
  view.unmount();
});

it('folds process records while keeping their content and the assistant reply accessible', () => {
  const view = renderMessageList([
    { role: 'process', content: '已完成事项查询', node_id: 'process-1' },
    { role: 'assistant', content: '**周末清单**已经整理好了。', node_id: 'assistant-1' },
  ]);
  const record = view.container.querySelector<HTMLDetailsElement>('.chat-process-record')!;
  expect(record.open).toBe(false);
  expect(record.querySelector('summary')?.textContent).toBe('处理记录');
  expect(record.textContent).toContain('已完成事项查询');
  expect(view.container.querySelector('[data-node-id="process-1"]')).toBeTruthy();
  expect(view.container.querySelector('.message.final strong')?.textContent).toBe('周末清单');
  view.unmount();
});

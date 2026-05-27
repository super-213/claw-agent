import { useEffect, useRef } from 'react';
import type { Message } from '../../api/types';
import { MessageRows } from './MessageRows';

export function MessageList({
  messages,
  onCreateBranch,
}: {
  messages: Message[];
  onCreateBranch: (nodeId: string) => void | Promise<void>;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const visibleMessages = messages.filter((message) => message.role !== 'system');

  useEffect(() => {
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages]);

  return (
    <div className="chat-window" ref={scrollRef}>
      <div className="messages-wrap">
        <div className="empty-state" style={{ display: visibleMessages.length === 0 ? 'flex' : 'none' }}>
          <div className="empty-icon">◈</div>
          <div className="empty-text">// 开始输入以启动对话</div>
        </div>
        {visibleMessages.length ? <MessageRows messages={messages} onCreateBranch={onCreateBranch} /> : null}
      </div>
    </div>
  );
}

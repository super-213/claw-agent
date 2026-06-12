import { Bot } from 'lucide-react';
import { useCallback, useLayoutEffect, useRef } from 'react';
import type { Message } from '../../api/types';
import { MessageRows, type BranchActionState } from './MessageRows';
import { isNearBottom } from './scrollBehavior';

export function MessageList({
  messages,
  conversationKey = 'default',
  onCreateBranch,
  branchActionStates,
  branchCreationLocked = false,
}: {
  messages: Message[];
  conversationKey?: string | null;
  onCreateBranch: (nodeId: string) => void | Promise<void>;
  branchActionStates?: Record<string, BranchActionState>;
  branchCreationLocked?: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const shouldFollowOutputRef = useRef(true);
  const conversationKeyRef = useRef<string | null>(conversationKey);
  const visibleMessages = messages.filter((message) => message.role !== 'system');

  const handleScroll = useCallback(() => {
    const node = scrollRef.current;
    if (!node) return;
    shouldFollowOutputRef.current = isNearBottom(node);
  }, []);

  useLayoutEffect(() => {
    const node = scrollRef.current;
    if (!node) return;

    if (conversationKeyRef.current !== conversationKey) {
      conversationKeyRef.current = conversationKey;
      shouldFollowOutputRef.current = true;
    }

    if (shouldFollowOutputRef.current) {
      node.scrollTop = node.scrollHeight;
    }
  }, [conversationKey, messages]);

  return (
    <div className="chat-window" ref={scrollRef} onScroll={handleScroll}>
      <div className="messages-wrap">
        <div className="empty-state" style={{ display: visibleMessages.length === 0 ? 'flex' : 'none' }}>
          <div className="empty-icon" aria-hidden="true">
            <Bot size={25} />
          </div>
          <div className="empty-copy">
            <strong>Claw Agent</strong>
            <span>输入任务，开始新的工作流。</span>
          </div>
        </div>
        {visibleMessages.length ? (
          <MessageRows
            messages={messages}
            onCreateBranch={onCreateBranch}
            branchActionStates={branchActionStates}
            branchCreationLocked={branchCreationLocked}
          />
        ) : null}
      </div>
    </div>
  );
}

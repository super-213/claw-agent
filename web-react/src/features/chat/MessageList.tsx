import { ArrowDown, Bot } from 'lucide-react';
import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import type { Message } from '../../api/types';
import { MessageRows, type BranchActionState } from './MessageRows';
import { isNearBottom } from './scrollBehavior';
import { useAppStore } from '../../stores/appStore';

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
  const [showLatest, setShowLatest] = useState(false);
  const initialized = useRef(false);
  const visibleMessages = messages.filter((message) => message.role !== 'system');

  const handleScroll = useCallback(() => {
    const node = scrollRef.current;
    if (!node) return;
    shouldFollowOutputRef.current = isNearBottom(node);
    setShowLatest(!shouldFollowOutputRef.current);
    useAppStore.getState().rememberHomeScroll(`chat:${conversationKeyRef.current}`, shouldFollowOutputRef.current ? -1 : node.scrollTop);
  }, []);

  useLayoutEffect(() => {
    const node = scrollRef.current;
    if (!node) return;

    if (!initialized.current || conversationKeyRef.current !== conversationKey) {
      initialized.current = true;
      conversationKeyRef.current = conversationKey;
      const saved = useAppStore.getState().homeScrollPositions[`chat:${conversationKey}`];
      shouldFollowOutputRef.current = saved === undefined || saved === -1;
      if (!shouldFollowOutputRef.current) node.scrollTop = saved;
      setShowLatest(!shouldFollowOutputRef.current);
    }

    if (shouldFollowOutputRef.current) {
      node.scrollTop = node.scrollHeight;
    }
  }, [conversationKey, messages]);

  useLayoutEffect(() => {
    const node = scrollRef.current;
    if (!node || typeof ResizeObserver === 'undefined') return;
    const keepPosition = () => {
      if (shouldFollowOutputRef.current) node.scrollTop = node.scrollHeight;
    };
    const observer = new ResizeObserver(keepPosition);
    observer.observe(node);
    if (node.firstElementChild) observer.observe(node.firstElementChild);
    node.addEventListener('load', keepPosition, true);
    return () => { observer.disconnect(); node.removeEventListener('load', keepPosition, true); };
  }, []);

  return (
    <div className="chat-window" ref={scrollRef} onScroll={handleScroll}>
      <div className="messages-wrap">
        <div className="empty-state" style={{ display: visibleMessages.length === 0 ? 'flex' : 'none' }}>
          <div className="empty-icon" aria-hidden="true">
            <Bot size={25} />
          </div>
          <div className="empty-copy">
            <strong>今天，有什么需要帮忙？</strong>
            <span>发张图片、读份说明书，或记住家里的事。</span>
          </div>
        </div>
        {visibleMessages.length ? (
          <MessageRows
            cardContext={{ surface: 'chat', sessionId: conversationKey && conversationKey !== 'default' ? conversationKey : undefined }}
            messages={messages}
            onCreateBranch={onCreateBranch}
            branchActionStates={branchActionStates}
            branchCreationLocked={branchCreationLocked}
          />
        ) : null}
      </div>
      {showLatest && <button type="button" className="chat-latest" onClick={() => {
        const node = scrollRef.current;
        if (!node) return;
        shouldFollowOutputRef.current = true;
        node.scrollTop = node.scrollHeight;
        setShowLatest(false);
        useAppStore.getState().rememberHomeScroll(`chat:${conversationKey}`, -1);
      }}><ArrowDown size={15} aria-hidden="true" /> 回到最新消息</button>}
    </div>
  );
}

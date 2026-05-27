import type { Message } from '../api/types';
import { hasMarker, isFormatNudge } from './format';

export interface MessageView {
  role: string;
  label: string;
  flow: null | {
    from: string;
    packet: string;
    to: string;
    reverse?: boolean;
  };
}

export const isFormatNudgeMessage = (msg: Message): boolean =>
  msg?.role === 'user' && isFormatNudge(msg.content || '');

export const getMessageView = (msg: Message): MessageView => {
  const content = msg.content || '';
  const rawRole = msg.role || 'assistant';

  if (hasMarker(content, '完成')) return { role: 'final', label: '// Final Output', flow: null };

  if (hasMarker(content, '命令')) {
    return {
      role: 'protocol',
      label: '// Protocol Handshake',
      flow: { from: 'Agent', packet: 'COMMAND', to: 'Shell', reverse: false },
    };
  }

  if (hasMarker(content, '执行完成')) {
    return {
      role: 'protocol',
      label: '// Protocol Handshake',
      flow: { from: 'Shell', packet: 'DATA', to: 'Agent', reverse: true },
    };
  }

  if (isFormatNudge(content)) {
    return {
      role: 'protocol',
      label: '// Protocol Handshake',
      flow: { from: 'Runtime', packet: 'FORMAT ACK', to: 'Agent', reverse: true },
    };
  }

  if (rawRole === 'user') return { role: 'user', label: '// User Input', flow: null };

  return {
    role: rawRole,
    label: rawRole === 'assistant' ? '// Agent' : `// ${rawRole}`,
    flow: null,
  };
};

const markerLineIndex = (text: string, marker: string): number => {
  const escaped = marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = new RegExp(`(^|\\n)\\s*[\\[［]\\s*${escaped}\\s*[\\]］]`).exec(text || '');
  if (!match) return -1;
  return match.index + (match[1] ? match[1].length : 0);
};

export const splitMixedProtocolMessage = (msg: Message): Message[] => {
  const content = msg.content || '';
  if (!hasMarker(content, '命令')) return [msg];

  const finalIndex = markerLineIndex(content, '完成');
  if (finalIndex <= 0) return [msg];

  const commandContent = content.slice(0, finalIndex).trimEnd();
  const finalContent = content.slice(finalIndex).trimStart();
  return [
    { ...msg, content: commandContent },
    { ...msg, content: finalContent, usage: null },
  ].filter((item) => item.content);
};

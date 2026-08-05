import type { Message } from '../api/types';

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

export const getMessageView = (msg: Message): MessageView => {
  const role = msg.role || 'assistant';
  if (role === 'user') return { role: 'user', label: '// User Input', flow: null };
  if (role === 'assistant') return { role: 'final', label: '// Final Output', flow: null };
  return { role, label: `// ${role}`, flow: null };
};

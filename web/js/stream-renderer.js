import { els } from './dom.js';
import {
  appendMessageContent,
  createLlmHeader,
  createProtocolFlow,
  formatElapsed,
  getMessageView,
  renderMessageText,
  splitMixedProtocolMessage,
} from './message-rendering.js';

export const startStreamingAssistantMessage = ({
  iteration = 1,
  model = '',
  message_count: messageCount = 0,
} = {}) => {
  els.emptyState.style.display = 'none';

  const row = document.createElement('div');
  row.className = 'message-row assistant-row streaming-row';

  const header = createLlmHeader({
    iteration,
    model,
    message_count: messageCount,
    stateText: 'streaming',
    done: false,
  });

  const bubble = document.createElement('div');
  bubble.className = 'message assistant streaming';

  const textEl = document.createElement('div');
  textEl.className = 'message-text';
  bubble.appendChild(textEl);

  row.appendChild(header);
  row.appendChild(bubble);
  els.messageList.appendChild(row);
  els.chatWindow.scrollTop = els.chatWindow.scrollHeight;

  return {
    row,
    label: header,
    bubble,
    textEl,
    content: '',
    startedAt: Date.now(),
    model,
    iteration,
  };
};

export const appendStreamingAssistantDelta = (streamMessage, delta) => {
  if (!streamMessage || !delta) return;
  streamMessage.content += delta;
  streamMessage.textEl.textContent = streamMessage.content;
  els.chatWindow.scrollTop = els.chatWindow.scrollHeight;
};

export const finishStreamingAssistantMessage = (streamMessage, content = '') => {
  if (!streamMessage) return;
  streamMessage.content = content || streamMessage.content;

  const header = streamMessage.label;
  if (header && header.classList) {
    header.classList.remove('failed');
    header.classList.add('done');
    const stateText = header.querySelector('.req-state-text');
    if (stateText) stateText.textContent = 'done';
    const elapsedEl = header.querySelector('.req-elapsed');
    if (elapsedEl && streamMessage.startedAt) {
      const elapsed = Date.now() - streamMessage.startedAt;
      elapsedEl.textContent = ` · ${formatElapsed(elapsed)}`;
    }
  }

  const displayMessages = splitMixedProtocolMessage({
    role: 'assistant',
    content: streamMessage.content,
  });
  const firstDisplayMessage = displayMessages[0];
  const view = getMessageView(firstDisplayMessage);
  streamMessage.row.classList.remove('streaming-row');
  streamMessage.bubble.classList.remove('streaming');
  renderMessageText(streamMessage.textEl, firstDisplayMessage.content);
  if (view.flow) {
    streamMessage.row.insertBefore(createProtocolFlow(view.flow), streamMessage.bubble);
  }
  displayMessages.slice(1).forEach((displayMsg) => {
    const nextView = getMessageView(displayMsg);
    const row = document.createElement('div');
    row.className = `message-row ${nextView.role}-row`;

    const label = document.createElement('div');
    label.className = 'msg-label';
    label.textContent = nextView.label;

    const bubble = document.createElement('div');
    bubble.className = `message ${nextView.role}`;
    appendMessageContent(bubble, displayMsg);

    row.appendChild(label);
    if (nextView.flow) row.appendChild(createProtocolFlow(nextView.flow));
    row.appendChild(bubble);
    streamMessage.row.insertAdjacentElement('afterend', row);
  });
  els.chatWindow.scrollTop = els.chatWindow.scrollHeight;
};

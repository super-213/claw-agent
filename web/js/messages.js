import { els } from './dom.js';
import { state } from './state.js';
import { clearHighlights } from './context-highlight.js';
import { addBranchActionButton } from './message-branch-actions.js';
import {
  escapeHtml,
  extractCommandFromContent,
  extractToolOutput,
  isToolCallMessage,
  isToolResultMessage,
} from './utils.js';
import {
  appendMessageContent,
  createIterationDivider,
  createLlmHeader,
  createProtocolFlow,
  createToolCallCard,
  formatBytes,
  formatElapsed,
  formatUsage,
  getMessageView,
  isFormatNudgeMessage,
  splitMixedProtocolMessage,
} from './message-rendering.js';
export {
  appendStreamingAssistantDelta,
  finishStreamingAssistantMessage,
  startStreamingAssistantMessage,
} from './stream-renderer.js';
export {
  addBranchActionButton,
  initMessageContextMenu,
} from './message-branch-actions.js';

export const setStatus = (text, busy = false) => {
  els.statusText.textContent = text;
  els.statusBadge.classList.toggle('busy', busy);
  els.sendBtn.disabled = busy;
};

export const renderMessages = (messages) => {
  clearHighlights();
  state.messages = messages;
  const visibleMessages = messages.filter((message) => message.role !== 'system');
  els.emptyState.style.display = visibleMessages.length === 0 ? 'flex' : 'none';

  els.messageList.innerHTML = '';
  if (visibleMessages.length === 0) {
    els.messageList.appendChild(els.emptyState);
    return;
  }

  els.emptyState.style.display = 'none';
  els.messageList.appendChild(els.emptyState);

  let iteration = 0;
  let pendingToolCall = null;

  messages.forEach((msg) => {
    if (msg.role === 'system') return;

    if (isToolResultMessage(msg) && pendingToolCall) {
      const result = extractToolOutput(msg.content || '');
      updateToolCall(pendingToolCall, result);
      pendingToolCall = null;
      return;
    }

    if (isToolCallMessage(msg)) {
      iteration += 1;
      if (iteration > 1) {
        els.messageList.appendChild(createIterationDivider(iteration));
      }

      const displayMessages = splitMixedProtocolMessage(msg);
      const commandMessage = displayMessages[0];
      const row = document.createElement('div');
      row.className = 'message-row assistant-row';
      if (msg.node_id) {
        row.dataset.nodeId = msg.node_id;
      }
      row.appendChild(createLlmHeader({
        iteration,
        message_count: Math.max(0, messages.indexOf(msg)),
      }));

      const bubble = document.createElement('div');
      bubble.className = 'message protocol';
      appendMessageContent(bubble, commandMessage);
      row.appendChild(createProtocolFlow({
        from: 'Agent',
        packet: 'COMMAND',
        to: 'Shell',
        reverse: false,
      }));
      row.appendChild(bubble);
      els.messageList.appendChild(row);

      const usage = document.createElement('div');
      usage.className = 'msg-usage';
      usage.textContent = formatUsage(commandMessage.usage);
      if (usage.textContent) row.appendChild(usage);

      pendingToolCall = createToolCallCard({
        iteration,
        command: extractCommandFromContent(commandMessage.content || ''),
        label: 'shell',
      });
      els.messageList.appendChild(pendingToolCall.row);

      displayMessages.slice(1).forEach((displayMsg) => {
        const nextView = getMessageView(displayMsg);
        const nextRow = document.createElement('div');
        nextRow.className = `message-row ${nextView.role}-row`;
        if (msg.node_id) {
          nextRow.dataset.nodeId = msg.node_id;
          if (nextView.role === 'final') {
            addBranchActionButton(nextRow, msg.node_id);
          }
        }

        const label = document.createElement('div');
        label.className = 'msg-label';
        label.textContent = nextView.label;

        const nextBubble = document.createElement('div');
        nextBubble.className = `message ${nextView.role}`;
        appendMessageContent(nextBubble, displayMsg);

        nextRow.appendChild(label);
        if (nextView.flow) nextRow.appendChild(createProtocolFlow(nextView.flow));
        nextRow.appendChild(nextBubble);
        els.messageList.appendChild(nextRow);
      });
      return;
    }

    if (msg.role === 'assistant' && !isFormatNudgeMessage(msg)) {
      iteration += 1;
      if (iteration > 1) {
        els.messageList.appendChild(createIterationDivider(iteration));
      }

      splitMixedProtocolMessage(msg).forEach((displayMsg, index) => {
        const view = getMessageView(displayMsg);

        const row = document.createElement('div');
        row.className = `message-row ${view.role}-row`;
        if (msg.node_id) {
          row.dataset.nodeId = msg.node_id;
          if (view.role === 'final') {
            addBranchActionButton(row, msg.node_id);
          }
        }
        if (index === 0) {
          row.appendChild(createLlmHeader({
            iteration,
            message_count: Math.max(0, messages.indexOf(msg)),
          }));
        } else {
          const label = document.createElement('div');
          label.className = 'msg-label';
          label.textContent = view.label;
          row.appendChild(label);
        }

        const bubble = document.createElement('div');
        bubble.className = `message ${view.role}`;
        appendMessageContent(bubble, displayMsg);

        if (view.flow) row.appendChild(createProtocolFlow(view.flow));
        row.appendChild(bubble);

        const usage = document.createElement('div');
        usage.className = 'msg-usage';
        usage.textContent = formatUsage(displayMsg.usage);
        if (usage.textContent) row.appendChild(usage);
        els.messageList.appendChild(row);
      });
      pendingToolCall = null;
      return;
    }

    if (isFormatNudgeMessage(msg)) {
      return;
    }

    pendingToolCall = null;
    splitMixedProtocolMessage(msg).forEach((displayMsg) => {
      const view = getMessageView(displayMsg);

      const row = document.createElement('div');
      row.className = `message-row ${view.role}-row`;
      if (msg.node_id) {
        row.dataset.nodeId = msg.node_id;
      }

      const label = document.createElement('div');
      label.className = 'msg-label';
      label.textContent = view.label;

      const bubble = document.createElement('div');
      bubble.className = `message ${view.role}`;
      appendMessageContent(bubble, displayMsg);

      const usage = document.createElement('div');
      usage.className = 'msg-usage';
      usage.textContent = formatUsage(displayMsg.usage);

      row.appendChild(label);
      if (view.flow) row.appendChild(createProtocolFlow(view.flow));
      row.appendChild(bubble);
      if (usage.textContent) row.appendChild(usage);
      els.messageList.appendChild(row);
    });
  });

  els.chatWindow.scrollTop = els.chatWindow.scrollHeight;
};

export const appendOptimisticUserMessage = (text, media = {}) => {
  els.emptyState.style.display = 'none';

  const row = document.createElement('div');
  row.className = 'message-row user-row';

  const label = document.createElement('div');
  label.className = 'msg-label';
  label.textContent = '// You';

  const bubble = document.createElement('div');
  bubble.className = 'message user';
  appendMessageContent(bubble, {
    content: text,
    attachments: media.attachments || [],
    images: media.images || [],
  });

  row.appendChild(label);
  row.appendChild(bubble);
  els.messageList.appendChild(row);
  els.chatWindow.scrollTop = els.chatWindow.scrollHeight;
};

export const appendProcessStep = (text, detail = '') => {
  els.emptyState.style.display = 'none';

  const row = document.createElement('div');
  row.className = 'message-row process-row';

  const label = document.createElement('div');
  label.className = 'msg-label';
  label.textContent = '// Model Process';

  const bubble = document.createElement('div');
  bubble.className = 'message process';
  bubble.textContent = detail ? `${text}\n${detail}` : text;

  row.appendChild(label);
  row.appendChild(bubble);
  els.messageList.appendChild(row);
  els.chatWindow.scrollTop = els.chatWindow.scrollHeight;
};

export const appendToolCall = ({
  iteration = 1,
  command = '',
  label = 'shell',
} = {}) => {
  els.emptyState.style.display = 'none';

  const handle = createToolCallCard({
    iteration,
    command,
    label,
    running: true,
  });
  const { row } = handle;
  els.messageList.appendChild(row);
  els.chatWindow.scrollTop = els.chatWindow.scrollHeight;

  return handle;
};

export const updateToolCall = (handle, {
  output = '',
  returnCode = null,
  success = null,
  elapsed = null,
  error = '',
} = {}) => {
  if (!handle) return;

  // Status: failure when returnCode non-zero, or success=false, or error present
  let resolved = success;
  if (resolved == null) {
    if (error) resolved = false;
    else if (returnCode != null) resolved = Number(returnCode) === 0;
  }

  handle.card.classList.remove('running');
  if (resolved === false) handle.card.classList.add('failure');
  else if (resolved === true) handle.card.classList.add('success');

  const statusText = handle.head.querySelector('.tool-status-text');
  if (statusText) {
    if (resolved === false) statusText.textContent = 'failed';
    else if (resolved === true) statusText.textContent = 'done';
  }

  const text = String(output || error || '');
  if (text) {
    handle.output.textContent = text;
    handle.outputWrap.style.display = '';
  }

  const elapsedMs = elapsed != null
    ? Number(elapsed)
    : (handle.startedAt ? Date.now() - handle.startedAt : null);

  const parts = [];
  if (returnCode != null) {
    parts.push(`<span><span class="meta-key">rc</span><span class="meta-val rc">${escapeHtml(String(returnCode))}</span></span>`);
  }
  if (elapsedMs != null && Number.isFinite(elapsedMs)) {
    parts.push(`<span><span class="meta-key">took</span><span class="meta-val">${escapeHtml(formatElapsed(elapsedMs))}</span></span>`);
  }
  if (text) {
    const bytes = new Blob([text]).size;
    parts.push(`<span><span class="meta-key">size</span><span class="meta-val">${escapeHtml(formatBytes(bytes))}</span></span>`);
  }
  if (parts.length) {
    handle.meta.innerHTML = parts.join('');
    handle.meta.style.display = '';
  }

  els.chatWindow.scrollTop = els.chatWindow.scrollHeight;
};

export const appendIterationDivider = (iteration) => {
  els.emptyState.style.display = 'none';

  const divider = createIterationDivider(iteration);
  els.messageList.appendChild(divider);
  els.chatWindow.scrollTop = els.chatWindow.scrollHeight;
  return divider;
};

export const showThinking = () => {
  const row = document.createElement('div');
  row.className = 'message-row assistant-row';
  row.id = 'thinking-row';

  const label = document.createElement('div');
  label.className = 'msg-label';
  label.textContent = '// Agent';

  const dots = document.createElement('div');
  dots.className = 'thinking';
  dots.innerHTML = '<span></span><span></span><span></span>';

  row.appendChild(label);
  row.appendChild(dots);
  els.messageList.appendChild(row);
  els.chatWindow.scrollTop = els.chatWindow.scrollHeight;
};

export const hideThinking = () => {
  document.getElementById('thinking-row')?.remove();
};

import { els } from './dom.js';
import { state } from './state.js';
import {
  escapeHtml,
  formatUsage,
  hasMarker,
  imageSourceFrom,
  isFormatNudge,
  isImageAttachment,
  safeImageSrc,
} from './utils.js';

const getMessageView = (msg) => {
  const content = msg.content || '';
  const rawRole = msg.role || 'assistant';

  if (hasMarker(content, '完成')) {
    return { role: 'final', label: '// Final Output', flow: null };
  }

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

  if (rawRole === 'user') {
    return { role: 'user', label: '// User Input', flow: null };
  }

  return {
    role: rawRole,
    label: rawRole === 'assistant' ? '// Agent' : '// ' + rawRole,
    flow: null,
  };
};

const createProtocolFlow = (flow) => {
  const el = document.createElement('div');
  el.className = 'protocol-flow' + (flow.reverse ? ' reverse' : '');
  el.innerHTML = `
    <span class="protocol-endpoint">${escapeHtml(flow.from)}</span>
    <span class="protocol-wire"><span class="protocol-packet">${escapeHtml(flow.packet)}</span></span>
    <span class="protocol-endpoint">${escapeHtml(flow.to)}</span>
  `;
  return el;
};

const imageAltFrom = (item) => {
  if (!item || typeof item === 'string') return 'message image';
  return item.alt || item.title || item.name || 'message image';
};

const collectMessageImages = (msg) => {
  const images = Array.isArray(msg.images) ? msg.images : [];
  const attachments = Array.isArray(msg.attachments) ? msg.attachments : [];
  return [
    ...images,
    ...attachments.filter(isImageAttachment),
  ].map((item) => ({
    src: safeImageSrc(imageSourceFrom(item)),
    alt: imageAltFrom(item),
  })).filter((item) => item.src);
};

const appendMessageContent = (bubble, msg) => {
  const text = msg.content || '';
  if (text) {
    const textEl = document.createElement('div');
    textEl.className = 'message-text';
    textEl.textContent = text;
    bubble.appendChild(textEl);
  }

  const images = collectMessageImages(msg);
  if (!images.length) return;

  const gallery = document.createElement('div');
  gallery.className = 'message-images';
  images.forEach((image) => {
    const link = document.createElement('a');
    link.className = 'message-image-link';
    link.href = image.src;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';

    const img = document.createElement('img');
    img.src = image.src;
    img.alt = image.alt;
    img.loading = 'lazy';
    img.decoding = 'async';

    link.appendChild(img);
    gallery.appendChild(link);
  });
  bubble.appendChild(gallery);
};

export const setStatus = (text, busy = false) => {
  els.statusText.textContent = text;
  els.statusBadge.classList.toggle('busy', busy);
  els.sendBtn.disabled = busy;
};

export const renderMessages = (messages) => {
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

  messages.forEach((msg) => {
    if (msg.role === 'system') return;
    const view = getMessageView(msg);

    const row = document.createElement('div');
    row.className = `message-row ${view.role}-row`;

    const label = document.createElement('div');
    label.className = 'msg-label';
    label.textContent = view.label;

    const bubble = document.createElement('div');
    bubble.className = `message ${view.role}`;
    appendMessageContent(bubble, msg);

    const usage = document.createElement('div');
    usage.className = 'msg-usage';
    usage.textContent = formatUsage(msg.usage);

    row.appendChild(label);
    if (view.flow) row.appendChild(createProtocolFlow(view.flow));
    row.appendChild(bubble);
    if (usage.textContent) row.appendChild(usage);
    els.messageList.appendChild(row);
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

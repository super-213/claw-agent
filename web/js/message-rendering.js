import { markdownToHtml } from './markdown.js';
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

// 系统注入的格式纠正提醒 —— 不计入真实用户轮次，也不重置迭代号。
export const isFormatNudgeMessage = (msg) =>
  msg?.role === 'user' && isFormatNudge(msg.content || '');

export const getMessageView = (msg) => {
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

const markerLineIndex = (text, marker) => {
  const escaped = marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = new RegExp(`(^|\\n)\\s*[\\[［]\\s*${escaped}\\s*[\\]］]`).exec(text || '');
  if (!match) return -1;
  return match.index + (match[1] ? match[1].length : 0);
};

export const splitMixedProtocolMessage = (msg) => {
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

export const createProtocolFlow = (flow) => {
  const el = document.createElement('div');
  el.className = 'protocol-flow' + (flow.reverse ? ' reverse' : '');
  el.innerHTML = `
    <span class="protocol-endpoint">${escapeHtml(flow.from)}</span>
    <span class="protocol-wire"><span class="protocol-packet">${escapeHtml(flow.packet)}</span></span>
    <span class="protocol-endpoint">${escapeHtml(flow.to)}</span>
  `;
  return el;
};

export const createLlmHeader = ({
  iteration = 1,
  model = '',
  message_count: messageCount = 0,
  stateText = 'done',
  done = true,
  elapsed = '',
} = {}) => {
  const header = document.createElement('div');
  header.className = 'llm-req-header' + (done ? ' done' : '');
  header.innerHTML = `
    <span class="req-tag">LLM</span>
    <span class="req-iter">#${escapeHtml(String(iteration))}</span>
    <span class="req-model">${escapeHtml(model || state.config?.model || 'model')}</span>
    <span class="req-msgs">${escapeHtml(String(messageCount || 0))} msgs</span>
    <span class="req-state"><span class="dot"></span><span class="req-state-text">${escapeHtml(stateText)}</span><span class="req-elapsed">${escapeHtml(elapsed ? ` · ${elapsed}` : '')}</span></span>
  `;
  return header;
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

export const renderMessageText = (textEl, text) => {
  textEl.className = 'message-text markdown-body';
  textEl.innerHTML = markdownToHtml(text);
};

export const appendMessageContent = (bubble, msg) => {
  const text = msg.content || '';
  if (text) {
    const textEl = document.createElement('div');
    renderMessageText(textEl, text);
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

export const formatBytes = (bytes) => {
  const value = Number(bytes) || 0;
  if (value < 1024) return `${value}B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)}KB`;
  return `${(value / (1024 * 1024)).toFixed(1)}MB`;
};

export const formatElapsed = (ms) => {
  const value = Number(ms);
  if (!Number.isFinite(value) || value < 0) return '';
  if (value < 1000) return `${Math.round(value)}ms`;
  if (value < 60_000) return `${(value / 1000).toFixed(value < 10_000 ? 2 : 1)}s`;
  const minutes = Math.floor(value / 60_000);
  const seconds = Math.round((value % 60_000) / 1000);
  return `${minutes}m${seconds}s`;
};

export const createToolCallCard = ({
  iteration = 1,
  command = '',
  label = 'shell',
  running = false,
} = {}) => {
  const row = document.createElement('div');
  row.className = 'message-row tool-call-row';

  const card = document.createElement('div');
  card.className = 'tool-call-card' + (running ? ' running' : '');

  const head = document.createElement('div');
  head.className = 'tool-call-head';
  head.innerHTML = `
    <span class="tool-badge">${escapeHtml(String(label).toUpperCase())}</span>
    <span class="tool-iter">#${escapeHtml(String(iteration))}</span>
    <span class="tool-status"><span class="dot"></span><span class="tool-status-text">${running ? 'running' : 'done'}</span></span>
  `;

  const commandEl = document.createElement('div');
  commandEl.className = 'tool-call-command';
  commandEl.textContent = command || '';

  const outputWrap = document.createElement('div');
  outputWrap.className = 'tool-call-output-wrap';
  outputWrap.style.display = 'none';

  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'tool-call-output-toggle';
  toggle.innerHTML = `
    <span class="toggle-label">output</span>
    <span class="caret">▸</span>
  `;
  toggle.addEventListener('click', () => {
    outputWrap.classList.toggle('open');
  });

  const output = document.createElement('pre');
  output.className = 'tool-call-output';

  outputWrap.appendChild(toggle);
  outputWrap.appendChild(output);

  const meta = document.createElement('div');
  meta.className = 'tool-call-meta';
  meta.style.display = 'none';

  card.appendChild(head);
  card.appendChild(commandEl);
  card.appendChild(outputWrap);
  card.appendChild(meta);
  row.appendChild(card);

  return {
    row,
    card,
    head,
    commandEl,
    outputWrap,
    output,
    meta,
    startedAt: Date.now(),
    iteration,
  };
};

export const createIterationDivider = (iteration) => {
  const divider = document.createElement('div');
  divider.className = 'iteration-divider';
  divider.innerHTML = `<span>iteration #${escapeHtml(String(iteration))}</span>`;
  return divider;
};

export { formatUsage };

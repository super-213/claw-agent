import { branchApi } from './api.js';
import { els } from './dom.js';
import { markdownToHtml } from './markdown.js';
import { state } from './state.js';
import { clearHighlights } from './context-highlight.js';
import {
  escapeHtml,
  extractCommandFromContent,
  extractToolOutput,
  formatUsage,
  hasMarker,
  imageSourceFrom,
  isFormatNudge,
  isImageAttachment,
  isToolCallMessage,
  isToolResultMessage,
  safeImageSrc,
} from './utils.js';

// 系统注入的格式纠正提醒 —— 不计入真实用户轮次，也不重置迭代号。
const isFormatNudgeMessage = (msg) =>
  msg?.role === 'user' && isFormatNudge(msg.content || '');

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

const markerLineIndex = (text, marker) => {
  const escaped = marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = new RegExp(`(^|\\n)\\s*[\\[［]\\s*${escaped}\\s*[\\]］]`).exec(text || '');
  if (!match) return -1;
  return match.index + (match[1] ? match[1].length : 0);
};

const splitMixedProtocolMessage = (msg) => {
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

const createLlmHeader = ({
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

const appendMessageContent = (bubble, msg) => {
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

const renderMessageText = (textEl, text) => {
  textEl.className = 'message-text markdown-body';
  textEl.innerHTML = markdownToHtml(text);
};

const formatBytes = (bytes) => {
  const value = Number(bytes) || 0;
  if (value < 1024) return `${value}B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)}KB`;
  return `${(value / (1024 * 1024)).toFixed(1)}MB`;
};

const createToolCallCard = ({
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

const createIterationDivider = (iteration) => {
  const divider = document.createElement('div');
  divider.className = 'iteration-divider';
  divider.innerHTML = `<span>iteration #${escapeHtml(String(iteration))}</span>`;
  return divider;
};

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
        addBranchActionButton(row, msg.node_id);
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
          addBranchActionButton(row, msg.node_id);
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
        addBranchActionButton(row, msg.node_id);
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

const formatElapsed = (ms) => {
  const value = Number(ms);
  if (!Number.isFinite(value) || value < 0) return '';
  if (value < 1000) return `${Math.round(value)}ms`;
  if (value < 60_000) return `${(value / 1000).toFixed(value < 10_000 ? 2 : 1)}s`;
  const minutes = Math.floor(value / 60_000);
  const seconds = Math.round((value % 60_000) / 1000);
  return `${minutes}m${seconds}s`;
};

export const finishStreamingAssistantMessage = (streamMessage, content = '') => {
  if (!streamMessage) return;
  streamMessage.content = content || streamMessage.content;

  // Mark header as done and show elapsed time
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

// ─── 消息右键菜单：从此处创建分支 ─────────────────────────────────────────────────

/** 当前显示的上下文菜单元素 */
let _contextMenu = null;

/**
 * 关闭并移除当前上下文菜单
 */
const dismissContextMenu = () => {
  if (_contextMenu) {
    _contextMenu.remove();
    _contextMenu = null;
  }
};

/**
 * 创建分支操作：调用 API 并更新树状图
 * @param {string} nodeId - 分支点的 node_id
 */
const createBranchFromNode = async (nodeId) => {
  const sessionId = state.currentSessionId;
  if (!sessionId || !nodeId) return;

  try {
    const result = await branchApi.create(sessionId, nodeId);
    if (result && result.ok) {
      // 自动打开树状图面板，让用户看到新分支
      try {
        const { openTreePanel, getTreePanelBody } = await import('./tree-panel.js');
        openTreePanel();

        // 确保 SVG 容器已初始化，然后渲染树
        const { initSvg, setTreeData } = await import('./branch-tree.js');
        const panelBody = getTreePanelBody();
        if (panelBody) {
          initSvg(panelBody);
          const treeData = await branchApi.tree(sessionId);
          if (treeData && treeData.nodes) {
            setTreeData(treeData.nodes, treeData.active_node_id);
          }
        }
      } catch (treeError) {
        console.warn('[messages] 更新树状图失败:', treeError);
      }
    }
  } catch (error) {
    console.warn('[messages] 创建分支失败:', error);
    alert('创建分支失败: ' + (error.message || '未知错误'));
  }
};

/**
 * 显示消息上下文菜单
 * @param {MouseEvent} event - 右键事件
 * @param {string} nodeId - 消息的 node_id
 */
const showMessageContextMenu = (event, nodeId) => {
  dismissContextMenu();

  const menu = document.createElement('div');
  menu.className = 'message-context-menu';
  menu.innerHTML = `
    <button type="button" class="context-menu-item" data-action="create-branch">
      <span class="context-menu-icon">⑂</span>
      <span class="context-menu-label">从此处创建分支</span>
    </button>
  `;

  // 定位菜单
  menu.style.position = 'fixed';
  menu.style.left = `${event.clientX}px`;
  menu.style.top = `${event.clientY}px`;
  menu.style.zIndex = '9999';

  // 绑定菜单项点击
  menu.querySelector('[data-action="create-branch"]').addEventListener('click', () => {
    dismissContextMenu();
    createBranchFromNode(nodeId);
  });

  document.body.appendChild(menu);
  _contextMenu = menu;

  // 确保菜单不超出视口
  requestAnimationFrame(() => {
    const rect = menu.getBoundingClientRect();
    if (rect.right > window.innerWidth) {
      menu.style.left = `${window.innerWidth - rect.width - 8}px`;
    }
    if (rect.bottom > window.innerHeight) {
      menu.style.top = `${window.innerHeight - rect.height - 8}px`;
    }
  });
};

/**
 * 初始化消息区域的右键菜单监听
 * 应在 DOM 就绪后调用一次
 */
export const initMessageContextMenu = () => {
  // 点击任意位置关闭菜单
  document.addEventListener('click', dismissContextMenu);
  document.addEventListener('contextmenu', (event) => {
    // 如果右键点击的不是消息区域，关闭已有菜单
    if (!event.target.closest('.message-row[data-node-id]')) {
      dismissContextMenu();
    }
  });

  // 在消息列表上监听右键事件（事件委托）
  els.messageList.addEventListener('contextmenu', (event) => {
    const row = event.target.closest('.message-row[data-node-id]');
    if (!row) return;

    const nodeId = row.dataset.nodeId;
    if (!nodeId) return;

    event.preventDefault();
    showMessageContextMenu(event, nodeId);
  });
};

/**
 * 为消息行添加"创建分支"操作按钮（hover 时显示）
 * 在 renderMessages 中为每个带 data-node-id 的消息行调用
 * @param {HTMLElement} row - 消息行 DOM 元素
 * @param {string} nodeId - 消息的 node_id
 */
export const addBranchActionButton = (row, nodeId) => {
  if (!row || !nodeId) return;

  const actionsWrap = document.createElement('div');
  actionsWrap.className = 'message-actions';

  const branchBtn = document.createElement('button');
  branchBtn.type = 'button';
  branchBtn.className = 'message-action-btn branch-btn';
  branchBtn.title = '从此处创建分支';
  branchBtn.setAttribute('aria-label', '从此处创建分支');
  branchBtn.innerHTML = '<span class="action-icon">⑂</span>';

  branchBtn.addEventListener('click', (event) => {
    event.stopPropagation();
    createBranchFromNode(nodeId);
  });

  actionsWrap.appendChild(branchBtn);
  row.appendChild(actionsWrap);
};

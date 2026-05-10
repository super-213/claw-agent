import { branchApi, chatApi, sessionsApi } from './api.js';
import { initSvg, onSwitch, setTreeData } from './branch-tree.js';
import { applyHighlightsFromMessages } from './context-highlight.js';
import { els, fitMessageInput, isMobileLayout, setMobileSidebar } from './dom.js';
import {
  appendIterationDivider,
  appendOptimisticUserMessage,
  appendProcessStep,
  appendStreamingAssistantDelta,
  appendToolCall,
  finishStreamingAssistantMessage,
  renderMessages,
  setStatus,
  startStreamingAssistantMessage,
  updateToolCall,
} from './messages.js';
import {
  beginStream,
  endStream,
  getStream,
  hasAnyStream,
  isSessionBusy,
  state,
} from './state.js';
import { getTreePanelBody } from './tree-panel.js';
import { escapeHtml, formatTime, formatTokens } from './utils.js';

// ─── 分支切换回调 ─────────────────────────────────────────────────────────────
// 注册分支切换完成后的回调：用新路径的消息重新渲染消息列表。
// 上下文高亮的清除和重新应用已由 branch-tree.js 内部处理。
onSwitch((messages, activeNodeId) => {
  if (!messages) return;
  renderMessages(messages);
});

// 刷新顶部状态栏：按当前选中的会话单独判定 busy。
const refreshStatusForCurrentSession = () => {
  if (!state.currentSessionId) {
    setStatus(hasAnyStream() ? '后台生成中…' : '就绪', false);
    return;
  }
  if (isSessionBusy(state.currentSessionId)) {
    setStatus('处理中…', true);
  } else {
    setStatus(hasAnyStream() ? '后台生成中…' : '就绪', false);
  }
};

/**
 * 从消息列表中找到最后一条带 context_nodes 的 assistant 消息，
 * 并调用上下文高亮。如果会话存在 summarized_nodes 数据，则区分
 * "完整发送"和"已压缩为摘要"两种状态。
 *
 * @param {Array} messages - 当前会话的消息列表
 * @param {string[]} [summarizedNodes] - 已被压缩为摘要的节点 ID 列表
 */
const applyContextHighlight = (messages, summarizedNodes) => {
  applyHighlightsFromMessages(messages, summarizedNodes);
};

export const renderSessions = () => {
  els.sessionList.innerHTML = '';
  state.sessions.forEach((session) => {
    const busy = isSessionBusy(session.id);
    const item = document.createElement('div');
    item.className = 'session-item'
      + (session.id === state.currentSessionId ? ' active' : '')
      + (session.id === state.openMenuSessionId ? ' menu-open' : '')
      + (busy ? ' busy' : '');
    item.innerHTML = `
      <div class="session-content">
        <div class="session-title">${escapeHtml(session.title || '新对话')}${busy ? ' <span class="session-busy-dot" title="生成中"></span>' : ''}</div>
        <div class="session-time">${escapeHtml(formatTime(session.updated_at || session.created_at))} · ${escapeHtml(formatTokens(session.token_usage?.total_tokens))} tok</div>
      </div>
      <button class="session-more" type="button" title="更多操作" aria-label="更多操作">⋯</button>
      ${session.id === state.openMenuSessionId ? `
        <div class="session-menu">
          <button type="button" data-action="copy">复制会话</button>
          <button type="button" data-action="delete" class="danger">删除</button>
        </div>
      ` : ''}
    `;

    item.addEventListener('click', (event) => {
      if (event.target.closest('.session-more') || event.target.closest('.session-menu')) return;
      state.openMenuSessionId = null;
      if (isMobileLayout()) setMobileSidebar(false);
      openSession(session.id);
    });

    item.querySelector('.session-more').addEventListener('click', (event) => {
      event.stopPropagation();
      state.openMenuSessionId = state.openMenuSessionId === session.id ? null : session.id;
      renderSessions();
    });

    item.querySelectorAll('.session-menu button').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.stopPropagation();
        const action = button.dataset.action;
        if (action === 'copy') copySession(session.id);
        if (action === 'delete') deleteSession(session.id);
      });
    });

    els.sessionList.appendChild(item);
  });
};

export const loadSessions = async () => {
  try {
    state.sessions = await sessionsApi.list();
    renderSessions();
    if (!state.currentSessionId && state.sessions.length > 0) {
      await openSession(state.sessions[0].id);
    }
  } catch (error) {
    console.warn('loadSessions:', error);
  }
};

export const openSession = async (sessionId) => {
  state.currentSessionId = sessionId;
  renderSessions();
  try {
    const data = await sessionsApi.get(sessionId);
    const session = state.sessions.find((item) => item.id === sessionId);
    els.topbarTitle.textContent = session?.title || '新对话';
    els.tokenSummary.textContent = `Tokens ${formatTokens(data.token_usage?.total_tokens)} · Tool ${formatTokens(data.token_usage?.tool_tokens)}`;
    renderMessages(data.messages || []);
    applyContextHighlight(data.messages || [], data.summarized_nodes);

    // 加载树结构并渲染树状图
    loadAndRenderTree(sessionId);

    // 如果切回来的正好是仍在流式中的会话，补一个占位提示
    const stream = getStream(sessionId);
    if (stream) {
      if (stream.pendingUserMessage) {
        appendOptimisticUserMessage(stream.pendingUserMessage);
      }
      appendProcessStep('会话仍在后台生成中…', '完成后将自动刷新');
      setStatus('处理中…', true);
    } else {
      refreshStatusForCurrentSession();
    }
  } catch (error) {
    console.warn('openSession:', error);
  }
};

/**
 * 从后端加载会话的树结构并渲染到树状图面板。
 * 此操作为非阻塞（不 await），不影响主会话加载流程。
 *
 * @param {string} sessionId - 会话 ID
 */
export const loadAndRenderTree = async (sessionId) => {
  try {
    const treeData = await branchApi.tree(sessionId);

    // 确保在树数据返回时用户仍在查看同一会话
    if (state.currentSessionId !== sessionId) return;

    const panelBody = getTreePanelBody();
    if (!panelBody) return;

    // 初始化 SVG 容器（如果面板内容为空或需要重建）
    initSvg(panelBody);

    // 设置树数据并触发布局和渲染
    const nodes = treeData.nodes || [];
    const activeNodeId = treeData.active_node_id || null;
    setTreeData(nodes, activeNodeId);
  } catch (error) {
    console.warn('[sessions] loadAndRenderTree:', error);
  }
};

export const createSession = async () => {
  try {
    const data = await sessionsApi.create();
    state.currentSessionId = data.id;
    els.topbarTitle.textContent = '新对话';
    await loadSessions();
    await openSession(data.id);
    if (isMobileLayout()) setMobileSidebar(false);
  } catch (error) {
    console.warn('createSession:', error);
  }
};

export const deleteSession = async (sessionId) => {
  // 只挡删除正在流式的会话；其它会话可以随时删
  if (isSessionBusy(sessionId)) {
    alert('该会话正在生成中，请等生成完成后再删除');
    return;
  }

  const session = state.sessions.find((item) => item.id === sessionId);
  const title = session?.title || '新对话';
  if (!confirm(`删除「${title}」？此操作不可恢复。`)) return;

  try {
    const wasCurrent = state.currentSessionId === sessionId;
    await sessionsApi.delete(sessionId);
    state.openMenuSessionId = null;

    if (wasCurrent) {
      state.currentSessionId = null;
      els.topbarTitle.textContent = '新对话';
      renderMessages([]);
    }

    await loadSessions();
    if (!state.currentSessionId) {
      if (state.sessions.length > 0) {
        await openSession(state.sessions[0].id);
      } else {
        await createSession();
      }
    }
    if (isMobileLayout()) setMobileSidebar(false);
  } catch (error) {
    console.warn('deleteSession:', error);
  }
};

export const copySession = async (sessionId) => {
  // 复制正在生成的会话可能拿到不完整的快照，提示一下
  if (isSessionBusy(sessionId)) {
    if (!confirm('该会话仍在生成中，复制将只包含已保存的部分内容。继续？')) return;
  }

  try {
    const data = await sessionsApi.copy(sessionId);
    state.openMenuSessionId = null;
    state.currentSessionId = data.id;
    await loadSessions();
    await openSession(data.id);
    if (isMobileLayout()) setMobileSidebar(false);
  } catch (error) {
    console.warn('copySession:', error);
  }
};

export const sendMessage = async () => {
  // 允许其它会话并发发送；只禁止同一会话自己排队
  const streamSessionId = state.currentSessionId;
  if (streamSessionId && isSessionBusy(streamSessionId)) return;

  const text = els.messageInput.value.trim();
  if (!text) return;
  if (!streamSessionId) {
    await createSession();
  }

  // 会话可能被 createSession 切到新 id，这里重新取一次
  const targetSessionId = state.currentSessionId;
  if (!targetSessionId) return;
  if (isSessionBusy(targetSessionId)) return;

  beginStream(targetSessionId, text);
  renderSessions();
  // 是否在流式期间离开过流式会话（离开过就需要最终刷新一次以替换占位）
  let switchedAwayDuringStream = false;

  if (state.currentSessionId === targetSessionId) {
    setStatus('处理中…', true);
  }
  els.messageInput.value = '';
  fitMessageInput();
  if (state.currentSessionId === targetSessionId) {
    appendOptimisticUserMessage(text);
  }
  const streamMessages = new Map();
  const toolCalls = new Map();
  let lastIteration = 0;

  const isViewingStreamSession = () => state.currentSessionId === targetSessionId;

  const clipDetail = (value) => {
    const textValue = String(value || '').trim();
    if (textValue.length <= 4000) return textValue;
    return textValue.slice(0, 4000) + '\n...';
  };

  // Filter out low-signal process steps that duplicate info already shown in
  // the LLM / tool call cards.
  const NOISY_STAGES = new Set(['handler', 'conversation']);
  const NOISY_MESSAGES = [
    '解析模型回复',
    '命令结果已写回上下文',
  ];
  const isNoisyStep = (event) => {
    if (NOISY_STAGES.has(event.stage)) return true;
    const msg = String(event.message || '');
    return NOISY_MESSAGES.some((needle) => msg.includes(needle));
  };

  const maybeAppendIterationDivider = (iteration) => {
    const iter = Number(iteration) || 1;
    if (iter > 1 && iter !== lastIteration) {
      appendIterationDivider(iter);
    }
    lastIteration = iter;
  };

  const handleStreamEvent = (event) => {
    // 用户切到别的会话时不操作 DOM 和状态栏，避免把消息塞进别的会话视图
    if (!isViewingStreamSession()) {
      switchedAwayDuringStream = true;
      return;
    }

    if (event.type === 'step') {
      if (isNoisyStep(event)) {
        // Still drive status bar, but skip adding a noisy bubble.
        if (event.message) setStatus(event.message, true);
        return;
      }
      appendProcessStep(event.message || event.stage || '处理进度');
      setStatus(event.message || '处理中…', true);
      return;
    }

    if (event.type === 'model_start') {
      maybeAppendIterationDivider(event.iteration);
      streamMessages.set(
        event.iteration || 1,
        startStreamingAssistantMessage(event),
      );
      setStatus('模型生成中…', true);
      return;
    }

    if (event.type === 'model_delta') {
      appendStreamingAssistantDelta(
        streamMessages.get(event.iteration || 1),
        event.delta || '',
      );
      return;
    }

    if (event.type === 'model_done') {
      finishStreamingAssistantMessage(
        streamMessages.get(event.iteration || 1),
        event.content || '',
      );
      setStatus('解析模型回复…', true);
      return;
    }

    if (event.type === 'command_start') {
      const handle = appendToolCall({
        iteration: event.iteration || 1,
        command: event.command || '',
        label: 'shell',
      });
      toolCalls.set(event.iteration || 1, handle);
      setStatus('执行命令…', true);
      return;
    }

    if (event.type === 'command_result') {
      const handle = toolCalls.get(event.iteration || 1);
      if (handle) {
        updateToolCall(handle, {
          output: clipDetail(event.output || ''),
          returnCode: event.return_code,
          success: event.success,
        });
        toolCalls.delete(event.iteration || 1);
      } else {
        // Fallback: no paired command_start (shouldn't happen, but keep log).
        appendProcessStep(
          event.message || '命令执行完成',
          clipDetail(event.output || ''),
        );
      }
      setStatus(event.success === false ? '命令执行失败' : '命令结果写回上下文…', true);
      return;
    }

    if (event.type === 'error') {
      appendProcessStep('处理失败', event.message || '请求失败');
    }
  };

  try {
    const finalEvent = await chatApi.stream(
      { sessionId: targetSessionId, message: text },
      handleStreamEvent,
    );
    await loadSessions();

    if (state.currentSessionId === targetSessionId) {
      if (Array.isArray(finalEvent?.messages)) {
        state.messages = [...state.messages, ...finalEvent.messages];
      }
      const current = state.sessions.find((item) => item.id === targetSessionId);
      if (current) {
        els.topbarTitle.textContent = current.title || '新对话';
        els.tokenSummary.textContent = `Tokens ${formatTokens(current.token_usage?.total_tokens)} · Tool ${formatTokens(current.token_usage?.tool_tokens)}`;
      }
      // 流式完成后，根据最终消息中的 context_nodes 应用上下文高亮
      const summarizedFromEvent = finalEvent?.summarized_nodes;
      applyContextHighlight(state.messages, summarizedFromEvent);

      // 流式完成后更新树状图，追加新节点（用户消息 + 助手回复）
      loadAndRenderTree(targetSessionId);
    }
  } catch (error) {
    console.warn('sendMessage:', error);
    if (state.currentSessionId === targetSessionId) {
      appendProcessStep('请求失败', error.data?.message || error.message || '网络错误');
    }
  } finally {
    endStream(targetSessionId);
    renderSessions();
    refreshStatusForCurrentSession();
    // 流式期间离开过流式会话，现在又回到这个会话：视图是不完整占位，用最终数据重绘
    if (switchedAwayDuringStream && state.currentSessionId === targetSessionId) {
      try {
        const data = await sessionsApi.get(targetSessionId);
        renderMessages(data.messages || []);
        applyContextHighlight(data.messages || [], data.summarized_nodes);
        // 流式期间离开又回来，也需要刷新树状图
        loadAndRenderTree(targetSessionId);
      } catch (refreshError) {
        console.warn('refresh after stream:', refreshError);
      }
    }
  }
};

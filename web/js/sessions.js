import { adminApi, chatApi, sessionsApi } from './api.js';
import {
  applyContextHighlight,
  loadAndRenderTree,
} from './branch-controller.js';
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
import { escapeHtml, formatTime, formatTokens } from './utils.js';

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

const canManageShare = (session) => (
  state.currentUser?.role === 'admin' || session.owner_user_id === state.currentUser?.id
);

const canDeleteSession = (session) => (
  state.currentUser?.role === 'admin' || session.owner_user_id === state.currentUser?.id
);

let shareSessionId = null;

const renderShareUsers = (users, selectedIds = []) => {
  const selected = new Set(selectedIds);
  els.shareUserList.innerHTML = '';
  users
    .filter((user) => user.id !== state.currentUser?.id)
    .forEach((user) => {
      const label = document.createElement('label');
      label.className = 'share-user-item';
      label.innerHTML = `
        <input type="checkbox" value="${escapeHtml(user.id)}" ${selected.has(user.id) ? 'checked' : ''} />
        <span>${escapeHtml(user.display_name || user.username)} · ${escapeHtml(user.username)}</span>
      `;
      els.shareUserList.appendChild(label);
    });
};

export const openShareModal = async (sessionId) => {
  const session = state.sessions.find((item) => item.id === sessionId);
  if (!session || !canManageShare(session)) return;
  shareSessionId = sessionId;
  els.shareFormError.textContent = '';
  els.shareModal.classList.add('open');
  els.shareModal.setAttribute('aria-hidden', 'false');
  try {
    const [shareData, userData] = await Promise.all([
      sessionsApi.share(sessionId),
      adminApi.shareableUsers(),
    ]);
    const sharing = shareData.sharing || {};
    els.shareScopeInput.value = sharing.scope || 'private';
    els.sharePermissionInput.value = sharing.permission || 'write';
    renderShareUsers(userData.users || [], sharing.user_ids || []);
  } catch (error) {
    els.shareFormError.textContent = error.message || '读取共享设置失败';
  }
};

export const closeShareModal = () => {
  shareSessionId = null;
  els.shareModal.classList.remove('open');
  els.shareModal.setAttribute('aria-hidden', 'true');
};

export const submitShareForm = async (event) => {
  event.preventDefault();
  if (!shareSessionId) return;
  els.shareFormError.textContent = '';
  const userIds = Array.from(els.shareUserList.querySelectorAll('input:checked'))
    .map((input) => input.value);
  try {
    await sessionsApi.updateShare(shareSessionId, {
      scope: els.shareScopeInput.value,
      permission: els.sharePermissionInput.value,
      user_ids: userIds,
    });
    closeShareModal();
    await loadSessions();
  } catch (error) {
    els.shareFormError.textContent = error.data?.error || error.message || '保存失败';
  }
};

export const renderSessions = () => {
  els.sessionList.innerHTML = '';
  state.sessions.forEach((session) => {
    const busy = isSessionBusy(session.id);
    const sharing = session.sharing || {};
    const scopeLabel = sharing.scope === 'all' ? 'ALL' : sharing.scope === 'selected' ? 'SHARED' : '';
    const owned = session.owner_user_id === state.currentUser?.id || state.currentUser?.role === 'admin';
    const item = document.createElement('div');
    item.className = 'session-item'
      + (session.id === state.currentSessionId ? ' active' : '')
      + (session.id === state.openMenuSessionId ? ' menu-open' : '')
      + (busy ? ' busy' : '');
    item.innerHTML = `
      <div class="session-content">
        <div class="session-title">${escapeHtml(session.title || '新对话')}${scopeLabel ? ` <span class="session-scope">${scopeLabel}</span>` : ''}${busy ? ' <span class="session-busy-dot" title="生成中"></span>' : ''}</div>
        <div class="session-time">${escapeHtml(formatTime(session.updated_at || session.created_at))} · ${escapeHtml(formatTokens(session.token_usage?.total_tokens))} tok</div>
      </div>
      <button class="session-more" type="button" title="更多操作" aria-label="更多操作">⋯</button>
      ${session.id === state.openMenuSessionId ? `
        <div class="session-menu">
          <button type="button" data-action="copy">复制会话</button>
          ${canManageShare(session) ? '<button type="button" data-action="share">共享设置</button>' : ''}
          ${canDeleteSession(session) && owned ? '<button type="button" data-action="delete" class="danger">删除</button>' : ''}
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
        if (action === 'share') openShareModal(session.id);
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

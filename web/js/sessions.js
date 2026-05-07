import { chatApi, sessionsApi } from './api.js';
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
import { state } from './state.js';
import { escapeHtml, formatTime, formatTokens } from './utils.js';

export const renderSessions = () => {
  els.sessionList.innerHTML = '';
  state.sessions.forEach((session) => {
    const item = document.createElement('div');
    item.className = 'session-item'
      + (session.id === state.currentSessionId ? ' active' : '')
      + (session.id === state.openMenuSessionId ? ' menu-open' : '');
    item.innerHTML = `
      <div class="session-content">
        <div class="session-title">${escapeHtml(session.title || '新对话')}</div>
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
  if (state.busy) return;

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
  if (state.busy) return;

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
  if (state.busy) return;

  const text = els.messageInput.value.trim();
  if (!text) return;
  if (!state.currentSessionId) await createSession();

  state.busy = true;
  setStatus('处理中…', true);
  els.messageInput.value = '';
  fitMessageInput();
  appendOptimisticUserMessage(text);
  const streamMessages = new Map();
  const toolCalls = new Map();
  let lastIteration = 0;

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
      { sessionId: state.currentSessionId, message: text },
      handleStreamEvent,
    );
    if (Array.isArray(finalEvent?.messages)) {
      state.messages = [...state.messages, ...finalEvent.messages];
    }
    await loadSessions();
    const current = state.sessions.find((item) => item.id === state.currentSessionId);
    if (current) {
      els.topbarTitle.textContent = current.title || '新对话';
      els.tokenSummary.textContent = `Tokens ${formatTokens(current.token_usage?.total_tokens)} · Tool ${formatTokens(current.token_usage?.tool_tokens)}`;
    }
  } catch (error) {
    console.warn('sendMessage:', error);
    appendProcessStep('请求失败', error.data?.message || error.message || '网络错误');
  } finally {
    state.busy = false;
    setStatus('就绪', false);
  }
};

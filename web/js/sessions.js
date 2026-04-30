import { chatApi, sessionsApi } from './api.js';
import { els, fitMessageInput, isMobileLayout, setMobileSidebar } from './dom.js';
import {
  appendOptimisticUserMessage,
  hideThinking,
  renderMessages,
  setStatus,
  showThinking,
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
  showThinking();

  try {
    await chatApi.send({ sessionId: state.currentSessionId, message: text });
    await openSession(state.currentSessionId);
    await loadSessions();
  } catch (error) {
    console.warn('sendMessage:', error);
  } finally {
    hideThinking();
    state.busy = false;
    setStatus('就绪', false);
  }
};

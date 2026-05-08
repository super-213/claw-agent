export const state = {
  sessions: [],
  skills: [],
  config: null,
  currentSessionId: null,
  messages: [],
  openMenuSessionId: null,
  // 每个会话独立的流式状态，按 sessionId 索引；值形如：
  //   { busy: true, pendingUserMessage: '...' }
  // 这样不同会话可以同时发送请求、互不阻塞。
  streams: Object.create(null),
};

export const getStream = (sessionId) => (sessionId ? state.streams[sessionId] || null : null);

export const beginStream = (sessionId, pendingUserMessage) => {
  if (!sessionId) return null;
  const entry = { busy: true, pendingUserMessage: pendingUserMessage || '' };
  state.streams[sessionId] = entry;
  return entry;
};

export const endStream = (sessionId) => {
  if (!sessionId) return;
  delete state.streams[sessionId];
};

export const isSessionBusy = (sessionId) => Boolean(getStream(sessionId));
export const hasAnyStream = () => Object.keys(state.streams).length > 0;

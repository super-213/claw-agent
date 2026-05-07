export const state = {
  sessions: [],
  skills: [],
  config: null,
  currentSessionId: null,
  busy: false,
  messages: [],
  openMenuSessionId: null,
  // 当前正在流式输出的会话 id（与 currentSessionId 可能不同：用户切走后仍在后台生成）
  activeStreamSessionId: null,
  // 本次流式请求用户发出的原始消息，用于切回时恢复气泡
  pendingUserMessage: null,
};

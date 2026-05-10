/**
 * context-highlight.js — 上下文路径高亮模块
 *
 * 负责在对话视图中高亮标记大模型实际使用的历史消息上下文：
 * - 从 assistant 消息的 context_nodes 字段读取上下文节点列表
 * - 在消息列表中为对应消息 DOM 添加高亮 CSS 类
 * - 区分"完整发送"和"已压缩为摘要"两种状态
 * - 分支切换时清除旧高亮
 */

// ─── 常量 ───────────────────────────────────────────────────────────────────

/** 高亮相关的 CSS 类名 */
export const HIGHLIGHT_CLASSES = {
  /** 上下文路径中完整发送的消息 */
  contextFull: 'context-highlight-full',
  /** 上下文路径中被压缩为摘要的消息 */
  contextSummarized: 'context-highlight-summarized',
  /** 通用上下文高亮（不区分状态时使用） */
  contextGeneric: 'context-highlight',
};

/** 消息 DOM 上用于标识节点的 data 属性名 */
export const NODE_ID_ATTR = 'data-node-id';

// ─── 模块内部状态 ─────────────────────────────────────────────────────────────

const _state = {
  /** @type {Set<string>} 当前高亮的完整发送节点 ID 集合 */
  fullNodeIds: new Set(),
  /** @type {Set<string>} 当前高亮的已压缩节点 ID 集合 */
  summarizedNodeIds: new Set(),
};

// ─── 内部辅助函数 ─────────────────────────────────────────────────────────────

/**
 * 查询消息列表中所有带 data-node-id 属性的 DOM 元素
 * @returns {NodeListOf<Element>}
 */
const queryMessageElements = () => {
  return document.querySelectorAll(`[${NODE_ID_ATTR}]`);
};

/**
 * 移除单个元素上的所有上下文高亮 CSS 类
 * @param {Element} el - 目标 DOM 元素
 */
const removeHighlightClasses = (el) => {
  el.classList.remove(HIGHLIGHT_CLASSES.contextFull);
  el.classList.remove(HIGHLIGHT_CLASSES.contextSummarized);
  el.classList.remove(HIGHLIGHT_CLASSES.contextGeneric);
};

// ─── 公共 API ─────────────────────────────────────────────────────────────────

/**
 * 清除所有上下文高亮
 *
 * 移除消息列表中所有消息 DOM 上的高亮 CSS 类，并重置内部状态。
 * 在分支切换时调用，确保旧分支的高亮被清除。
 */
export const clearHighlights = () => {
  const elements = queryMessageElements();
  for (const el of elements) {
    removeHighlightClasses(el);
  }
  _state.fullNodeIds.clear();
  _state.summarizedNodeIds.clear();
};

/**
 * 高亮上下文路径中的消息
 *
 * 根据 context_nodes 列表，为消息列表中对应的 DOM 元素添加高亮 CSS 类。
 * 所有节点统一使用 contextFull 类（不区分压缩状态）。
 *
 * @param {string[]} contextNodeIds - 本次请求中实际发送给模型的节点 ID 列表
 */
export const highlightContextNodes = (contextNodeIds) => {
  // 先清除已有高亮
  clearHighlights();

  if (!contextNodeIds || contextNodeIds.length === 0) return;

  const nodeIdSet = new Set(contextNodeIds);
  _state.fullNodeIds = new Set(nodeIdSet);

  const elements = queryMessageElements();
  for (const el of elements) {
    const nodeId = el.getAttribute(NODE_ID_ATTR);
    if (nodeId && nodeIdSet.has(nodeId)) {
      el.classList.add(HIGHLIGHT_CLASSES.contextFull);
      el.classList.add(HIGHLIGHT_CLASSES.contextGeneric);
    }
  }
};

/**
 * 高亮上下文路径中的消息（区分完整发送和已压缩状态）
 *
 * 根据 context_nodes 和 summarized_nodes 列表，为消息 DOM 添加不同的高亮样式：
 * - 完整发送的消息：添加 contextFull 类
 * - 被压缩为摘要的消息：添加 contextSummarized 类
 *
 * @param {string[]} contextNodeIds - 本次请求中实际发送给模型的所有节点 ID
 * @param {string[]} summarizedNodeIds - 其中被压缩为摘要发送的节点 ID
 */
export const highlightContextWithCompression = (contextNodeIds, summarizedNodeIds) => {
  // 先清除已有高亮
  clearHighlights();

  if (!contextNodeIds || contextNodeIds.length === 0) return;

  const contextSet = new Set(contextNodeIds);
  const summarizedSet = new Set(summarizedNodeIds || []);

  // 完整发送的节点 = 在上下文中但不在压缩列表中
  const fullSet = new Set();
  for (const id of contextSet) {
    if (!summarizedSet.has(id)) {
      fullSet.add(id);
    }
  }

  _state.fullNodeIds = fullSet;
  _state.summarizedNodeIds = new Set(
    [...summarizedSet].filter((id) => contextSet.has(id)),
  );

  const elements = queryMessageElements();
  for (const el of elements) {
    const nodeId = el.getAttribute(NODE_ID_ATTR);
    if (!nodeId || !contextSet.has(nodeId)) continue;

    el.classList.add(HIGHLIGHT_CLASSES.contextGeneric);

    if (summarizedSet.has(nodeId)) {
      el.classList.add(HIGHLIGHT_CLASSES.contextSummarized);
    } else {
      el.classList.add(HIGHLIGHT_CLASSES.contextFull);
    }
  }
};

/**
 * 从消息列表中提取最后一条 assistant 消息的 context_nodes 并应用高亮
 *
 * 在分支切换完成后调用，根据新分支路径上最后一条 assistant 消息的
 * context_nodes 重新标记上下文高亮。如果没有找到带 context_nodes 的
 * assistant 消息，则清除所有高亮。
 *
 * @param {Array} messages - 当前分支路径上的消息列表
 * @param {string[]} [summarizedNodeIds] - 已被压缩为摘要的节点 ID 列表（可选）
 */
export const applyHighlightsFromMessages = (messages, summarizedNodeIds) => {
  if (!messages || messages.length === 0) {
    clearHighlights();
    return;
  }

  // 从后往前找最后一条带 context_nodes 的 assistant 消息
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (msg.role === 'assistant' && Array.isArray(msg.context_nodes) && msg.context_nodes.length > 0) {
      if (Array.isArray(summarizedNodeIds) && summarizedNodeIds.length > 0) {
        highlightContextWithCompression(msg.context_nodes, summarizedNodeIds);
      } else {
        highlightContextNodes(msg.context_nodes);
      }
      return;
    }
  }

  // 没有找到带 context_nodes 的消息，清除高亮
  clearHighlights();
};

/**
 * 获取当前高亮状态（供外部模块或测试使用）
 *
 * @returns {{ fullNodeIds: string[], summarizedNodeIds: string[] }}
 */
export const getHighlightState = () => ({
  fullNodeIds: [..._state.fullNodeIds],
  summarizedNodeIds: [..._state.summarizedNodeIds],
});

/**
 * 判断指定节点是否处于高亮状态
 *
 * @param {string} nodeId - 节点 ID
 * @returns {'full'|'summarized'|null} 高亮类型，null 表示未高亮
 */
export const getNodeHighlightType = (nodeId) => {
  if (_state.fullNodeIds.has(nodeId)) return 'full';
  if (_state.summarizedNodeIds.has(nodeId)) return 'summarized';
  return null;
};

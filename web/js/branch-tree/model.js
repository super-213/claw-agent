/**
 * @typedef {Object} TreeNode
 * @property {string} nodeId
 * @property {string|null} parentId
 * @property {string} role
 * @property {string} summary
 * @property {boolean} isActive
 * @property {number} childCount
 * @property {number} x
 * @property {number} y
 * @property {TreeNode[]} children
 * @property {string[]} [nodeIds]
 * @property {string} [userSummary]
 * @property {string} [toolSummary]
 * @property {string} [modelSummary]
 * @property {number} [toolCount]
 */

/**
 * 计算从根节点到指定活跃节点的路径上所有节点 ID。
 * @param {Map<string, TreeNode>} nodeMap
 * @param {string|null} activeNodeId
 * @returns {Set<string>}
 */
export const computeActivePath = (nodeMap, activeNodeId) => {
  const activeSet = new Set();
  if (!activeNodeId || !nodeMap.has(activeNodeId)) {
    return activeSet;
  }

  let current = nodeMap.get(activeNodeId);
  while (current) {
    activeSet.add(current.nodeId);
    if (current.parentId == null) break;
    current = nodeMap.get(current.parentId);
  }

  return activeSet;
};

/**
 * 将活跃路径标记应用到节点上。
 * @param {Map<string, TreeNode>} nodeMap
 * @param {Set<string>} activePathSet
 */
export const markActivePath = (nodeMap, activePathSet) => {
  for (const node of nodeMap.values()) {
    node.isActive = activePathSet.has(node.nodeId);
  }
};

/**
 * 从 API 响应构建内部树结构。
 * @param {Array} apiNodes
 * @param {string|null} activeNodeId
 * @returns {{ root: TreeNode|null, nodeMap: Map<string, TreeNode> }}
 */
export const buildTree = (apiNodes, activeNodeId) => {
  if (!apiNodes || apiNodes.length === 0) {
    return { root: null, nodeMap: new Map() };
  }

  const nodeMap = new Map();

  for (const n of apiNodes) {
    nodeMap.set(n.node_id, {
      nodeId: n.node_id,
      parentId: n.parent_id,
      role: n.role,
      summary: n.summary || '',
      isActive: false,
      childCount: n.child_count || 0,
      x: 0,
      y: 0,
      children: [],
    });
  }

  let root = null;
  for (const node of nodeMap.values()) {
    if (node.parentId == null) {
      root = node;
    } else {
      const parent = nodeMap.get(node.parentId);
      if (parent) {
        parent.children.push(node);
      }
    }
  }

  const activePathSet = computeActivePath(nodeMap, activeNodeId);
  markActivePath(nodeMap, activePathSet);

  return { root, nodeMap };
};

const hasContent = (node) => Boolean((node?.summary || '').trim());

const isToolCallNode = (node) => (
  node?.role === 'assistant' && (node.summary || '').trim().startsWith('[命令]')
);

const isToolResultNode = (node) => (
  node?.role === 'user' && (node.summary || '').trim().startsWith('[执行完成]')
);

const isPlaceholderNode = (node) => node?.role === 'user' && !hasContent(node);

const isUserInputNode = (node) => (
  node?.role === 'user' && hasContent(node) && !isToolResultNode(node)
);

const createDisplayNode = ({
  nodeId,
  parentId,
  role,
  summary,
  isActive,
  nodeIds,
  userSummary = '',
  toolSummary = '',
  modelSummary = '',
  toolCount = 0,
}) => ({
  nodeId,
  parentId,
  role,
  summary,
  isActive,
  childCount: 0,
  x: 0,
  y: 0,
  children: [],
  nodeIds,
  userSummary,
  toolSummary,
  modelSummary,
  toolCount,
});

export const markDisplayNodeActive = (displayNode, rawNodeMap) => {
  displayNode.isActive = displayNode.nodeIds.some((nodeId) => rawNodeMap.get(nodeId)?.isActive);
};

const collectTurnBlock = (userNode, parentDisplayId, rawNodeMap) => {
  const members = [userNode];
  let terminal = userNode;
  let cursor = userNode;
  let toolCount = 0;
  let modelSummary = '';
  let nextChildren = userNode.children;

  while (cursor.children.length === 1) {
    const child = cursor.children[0];

    if (isToolCallNode(child)) {
      toolCount += 1;
      members.push(child);
      terminal = child;
      cursor = child;
      nextChildren = child.children;
      continue;
    }

    if (isToolResultNode(child)) {
      members.push(child);
      terminal = child;
      cursor = child;
      nextChildren = child.children;
      continue;
    }

    if (child.role === 'assistant') {
      members.push(child);
      terminal = child;
      modelSummary = child.summary || '';
      nextChildren = child.children;
    }
    break;
  }

  const displayNode = createDisplayNode({
    nodeId: terminal.nodeId,
    parentId: parentDisplayId,
    role: 'turn',
    summary: modelSummary || userNode.summary || '',
    isActive: false,
    nodeIds: members.map((node) => node.nodeId),
    userSummary: userNode.summary || '',
    toolSummary: toolCount > 0 ? `工具调用 x${toolCount}` : '工具调用：无',
    modelSummary: modelSummary || '等待模型输出',
    toolCount,
  });
  markDisplayNodeActive(displayNode, rawNodeMap);

  return { displayNode, nextChildren };
};

/**
 * 将原始消息树折叠成用于展示的流程块树。
 * @param {TreeNode|null} rawRoot
 * @param {Map<string, TreeNode>} rawNodeMap
 * @returns {{ root: TreeNode|null, nodeMap: Map<string, TreeNode> }}
 */
export const buildDisplayTree = (rawRoot, rawNodeMap) => {
  if (!rawRoot) {
    return { root: null, nodeMap: new Map() };
  }

  const displayMap = new Map();

  const appendNode = (node) => {
    displayMap.set(node.nodeId, node);
    return node;
  };

  const buildMany = (rawNodes, parentDisplayId) => {
    const displayNodes = [];
    for (const rawNode of rawNodes) {
      displayNodes.push(...buildOne(rawNode, parentDisplayId));
    }
    return displayNodes;
  };

  const buildOne = (rawNode, parentDisplayId) => {
    if (isPlaceholderNode(rawNode)) {
      return buildMany(rawNode.children, parentDisplayId);
    }

    if (rawNode.role === 'system') {
      const displayNode = appendNode(createDisplayNode({
        nodeId: rawNode.nodeId,
        parentId: parentDisplayId,
        role: 'system',
        summary: rawNode.summary || '',
        isActive: rawNode.isActive,
        nodeIds: [rawNode.nodeId],
        modelSummary: rawNode.summary || '',
      }));
      displayNode.children = buildMany(rawNode.children, displayNode.nodeId);
      displayNode.childCount = displayNode.children.length;
      return [displayNode];
    }

    if (isUserInputNode(rawNode)) {
      const { displayNode, nextChildren } = collectTurnBlock(rawNode, parentDisplayId, rawNodeMap);
      appendNode(displayNode);
      displayNode.children = buildMany(nextChildren, displayNode.nodeId);
      displayNode.childCount = displayNode.children.length;
      return [displayNode];
    }

    const displayNode = appendNode(createDisplayNode({
      nodeId: rawNode.nodeId,
      parentId: parentDisplayId,
      role: rawNode.role || 'message',
      summary: rawNode.summary || '',
      isActive: rawNode.isActive,
      nodeIds: [rawNode.nodeId],
      modelSummary: rawNode.summary || '',
    }));
    displayNode.children = buildMany(rawNode.children, displayNode.nodeId);
    displayNode.childCount = displayNode.children.length;
    return [displayNode];
  };

  const roots = buildOne(rawRoot, null);
  return { root: roots[0] || null, nodeMap: displayMap };
};

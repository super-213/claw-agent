import {
  EDGE_STYLES,
  NODE_COLORS,
  SVG_NS,
  TREE_CONSTANTS,
} from './constants.js';

let nodeClickHandler = null;

export const setNodeClickHandler = (handler) => {
  nodeClickHandler = typeof handler === 'function' ? handler : null;
};

/**
 * 截取消息摘要文本（用于 tooltip 显示）。
 * @param {string} text
 * @param {number} [maxLen=30]
 * @returns {string}
 */
export const truncateSummary = (text, maxLen = 30) => {
  if (!text) return '';
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + '…';
};

/**
 * 获取节点填充颜色（根据角色）。
 * @param {string} role
 * @returns {string}
 */
export const getNodeColor = (role) => {
  return NODE_COLORS[role] || NODE_COLORS.system;
};

/**
 * 获取节点描边颜色（根据是否在活跃路径上）。
 * @param {boolean} isActive
 * @returns {string}
 */
export const getNodeBorderColor = (isActive) => {
  return isActive ? NODE_COLORS.activeBorder : NODE_COLORS.defaultBorder;
};

const getRoleLabel = (role) => {
  if (role === 'assistant') return 'model';
  if (role === 'tool') return 'tool';
  if (role === 'system') return 'system';
  return 'user';
};

const createTextElement = (text, x, y, className) => {
  const el = document.createElementNS(SVG_NS, 'text');
  el.setAttribute('x', String(x));
  el.setAttribute('y', String(y));
  el.setAttribute('class', className);
  el.textContent = text;
  return el;
};

const createMessageCardElement = (node) => {
  const card = document.createElementNS(SVG_NS, 'g');
  card.setAttribute('class', `branch-message-card role-${node.role}${node.isActive ? ' active' : ''}`);

  const x = (TREE_CONSTANTS.nodeWidth - TREE_CONSTANTS.messageWidth) / 2;

  const appendSlot = ({ role, label, text, y, muted = false }) => {
    const slot = document.createElementNS(SVG_NS, 'g');
    slot.setAttribute('class', `branch-message-slot role-${role}${muted ? ' muted' : ''}`);

    const rect = document.createElementNS(SVG_NS, 'rect');
    rect.setAttribute('x', String(x));
    rect.setAttribute('y', String(y));
    rect.setAttribute('width', String(TREE_CONSTANTS.messageWidth));
    rect.setAttribute('height', String(TREE_CONSTANTS.messageHeight));
    rect.setAttribute('rx', '7');
    rect.setAttribute('class', 'branch-message-rect');

    const roleLabel = createTextElement(`${label}:`, x + 14, y + 19, 'branch-message-role');
    const summary = createTextElement(
      truncateSummary(text || 'empty', 15),
      x + 78,
      y + 19,
      'branch-message-summary',
    );

    slot.appendChild(rect);
    slot.appendChild(roleLabel);
    slot.appendChild(summary);
    card.appendChild(slot);
  };

  if (node.role === 'turn') {
    appendSlot({ role: 'user', label: 'user', text: node.userSummary, y: 22 });
    appendSlot({
      role: 'tool',
      label: 'tool',
      text: node.toolSummary,
      y: 61,
      muted: !node.toolCount,
    });
    appendSlot({ role: 'assistant', label: 'model', text: node.modelSummary, y: 100 });
  } else {
    appendSlot({
      role: node.role || 'system',
      label: getRoleLabel(node.role),
      text: node.modelSummary || node.summary,
      y: (TREE_CONSTANTS.nodeHeight - TREE_CONSTANTS.messageHeight) / 2,
    });
  }

  return card;
};

/**
 * 创建单个节点的 SVG 组元素。
 * @param {import('./model.js').TreeNode} node
 * @returns {SVGGElement}
 */
export const createNodeElement = (node) => {
  const group = document.createElementNS(SVG_NS, 'g');
  group.setAttribute('class', `branch-tree-node${node.isActive ? ' active' : ' inactive'}`);
  group.setAttribute('data-node-id', node.nodeId);
  group.setAttribute('data-delete-node-id', node.role === 'turn' ? node.nodeIds[0] : node.nodeId);
  group.setAttribute('transform', `translate(${node.x}, ${node.y})`);

  const block = document.createElementNS(SVG_NS, 'rect');
  block.setAttribute('width', String(TREE_CONSTANTS.nodeWidth));
  block.setAttribute('height', String(TREE_CONSTANTS.nodeHeight));
  block.setAttribute('rx', '18');
  block.setAttribute('fill', 'transparent');
  block.setAttribute('stroke', getNodeBorderColor(node.isActive));
  block.setAttribute('stroke-width', node.isActive ? '2.6' : '1.8');
  block.setAttribute('class', `branch-block role-${node.role}${node.isActive ? ' active' : ''}`);
  block.style.cursor = 'pointer';

  group.appendChild(block);
  group.appendChild(createMessageCardElement(node));

  const title = document.createElementNS(SVG_NS, 'title');
  if (node.role === 'turn') {
    title.textContent = [
      `user: ${truncateSummary(node.userSummary, 80)}`,
      `tool: ${node.toolSummary}`,
      `model: ${truncateSummary(node.modelSummary, 80)}`,
    ].join('\n');
  } else {
    title.textContent = `${getRoleLabel(node.role)}: ${truncateSummary(node.summary, 80)}`;
  }
  group.appendChild(title);

  group.addEventListener('click', (event) => {
    event.stopPropagation();
    if (nodeClickHandler) {
      nodeClickHandler(node.nodeId);
    }
  });

  return group;
};

/**
 * 渲染所有节点到 SVG 根组中。
 * @param {import('./model.js').TreeNode|null} root
 * @param {SVGGElement|null} rootGroup
 * @returns {SVGGElement|null}
 */
export const renderNodes = (root, rootGroup) => {
  if (!root || !rootGroup) return null;

  const nodesLayer = document.createElementNS(SVG_NS, 'g');
  nodesLayer.setAttribute('class', 'branch-tree-nodes-layer');

  const traverse = (node) => {
    const nodeElement = createNodeElement(node);
    nodesLayer.appendChild(nodeElement);
    for (const child of node.children) {
      traverse(child);
    }
  };

  traverse(root);
  rootGroup.appendChild(nodesLayer);

  return nodesLayer;
};

/**
 * 清除已渲染的节点层。
 * @param {SVGGElement|null} rootGroup
 */
export const clearNodes = (rootGroup) => {
  if (!rootGroup) return;

  const existing = rootGroup.querySelector('.branch-tree-nodes-layer');
  if (existing) {
    rootGroup.removeChild(existing);
  }
};

/**
 * 生成连接父节点底部到子节点顶部的三次贝塞尔曲线路径字符串。
 * @param {import('./model.js').TreeNode} parent
 * @param {import('./model.js').TreeNode} child
 * @returns {string}
 */
export const computeEdgePath = (parent, child) => {
  const x1 = parent.x + TREE_CONSTANTS.nodeWidth / 2;
  const y1 = parent.y + TREE_CONSTANTS.nodeHeight;
  const x2 = child.x + TREE_CONSTANTS.nodeWidth / 2;
  const y2 = child.y;
  const midY = (y1 + y2) / 2;

  return `M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`;
};

/**
 * 获取连线颜色（根据父子节点是否都在活跃路径上）。
 * @param {import('./model.js').TreeNode} parent
 * @param {import('./model.js').TreeNode} child
 * @returns {string}
 */
export const getEdgeColor = (parent, child) => {
  return parent.isActive && child.isActive ? EDGE_STYLES.activeColor : EDGE_STYLES.color;
};

/**
 * 创建单条连线的 SVG path 元素。
 * @param {import('./model.js').TreeNode} parent
 * @param {import('./model.js').TreeNode} child
 * @returns {SVGPathElement}
 */
export const createEdgeElement = (parent, child) => {
  const isActiveEdge = parent.isActive && child.isActive;
  const path = document.createElementNS(SVG_NS, 'path');
  path.setAttribute('d', computeEdgePath(parent, child));
  path.setAttribute('fill', 'none');
  path.setAttribute('stroke', getEdgeColor(parent, child));
  path.setAttribute('stroke-width', isActiveEdge ? String(EDGE_STYLES.width + 1) : String(EDGE_STYLES.width));
  path.setAttribute('class', `branch-tree-edge${isActiveEdge ? ' active' : ''}`);
  path.setAttribute('data-from', parent.nodeId);
  path.setAttribute('data-to', child.nodeId);
  return path;
};

/**
 * 渲染所有连线到 SVG 根组中。
 * @param {import('./model.js').TreeNode|null} root
 * @param {SVGGElement|null} rootGroup
 * @returns {SVGGElement|null}
 */
export const renderEdges = (root, rootGroup) => {
  if (!root || !rootGroup) return null;

  const edgesLayer = document.createElementNS(SVG_NS, 'g');
  edgesLayer.setAttribute('class', 'branch-tree-edges-layer');

  const traverse = (node) => {
    for (const child of node.children) {
      const edgeElement = createEdgeElement(node, child);
      edgesLayer.appendChild(edgeElement);
      traverse(child);
    }
  };

  traverse(root);
  rootGroup.appendChild(edgesLayer);

  return edgesLayer;
};

/**
 * 清除已渲染的连线层。
 * @param {SVGGElement|null} rootGroup
 */
export const clearEdges = (rootGroup) => {
  if (!rootGroup) return;

  const existing = rootGroup.querySelector('.branch-tree-edges-layer');
  if (existing) {
    rootGroup.removeChild(existing);
  }
};

export const updateRenderedActivePath = (rootGroup, nodeMap) => {
  if (!rootGroup) return;

  const nodeElements = rootGroup.querySelectorAll('.branch-tree-node');
  for (const nodeEl of nodeElements) {
    const nodeId = nodeEl.getAttribute('data-node-id');
    const node = nodeMap.get(nodeId);
    if (!node) continue;

    nodeEl.classList.toggle('active', node.isActive);
    nodeEl.classList.toggle('inactive', !node.isActive);

    const block = nodeEl.querySelector('.branch-block');
    if (block) {
      block.setAttribute('stroke', getNodeBorderColor(node.isActive));
      block.setAttribute('stroke-width', node.isActive ? '2.6' : '1.8');
      block.classList.toggle('active', node.isActive);
    }

    const messageCard = nodeEl.querySelector('.branch-message-card');
    if (messageCard) {
      messageCard.classList.toggle('active', node.isActive);
    }
  }

  const edgeElements = rootGroup.querySelectorAll('.branch-tree-edge');
  for (const edgeEl of edgeElements) {
    const fromId = edgeEl.getAttribute('data-from');
    const toId = edgeEl.getAttribute('data-to');
    const fromNode = nodeMap.get(fromId);
    const toNode = nodeMap.get(toId);
    if (!fromNode || !toNode) continue;

    const isActiveEdge = fromNode.isActive && toNode.isActive;
    edgeEl.setAttribute('stroke', isActiveEdge ? EDGE_STYLES.activeColor : EDGE_STYLES.color);
    edgeEl.setAttribute('stroke-width', isActiveEdge ? String(EDGE_STYLES.width + 1) : String(EDGE_STYLES.width));
    edgeEl.classList.toggle('active', isActiveEdge);
  }
};

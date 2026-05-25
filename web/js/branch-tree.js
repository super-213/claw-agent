/**
 * branch-tree.js — 会话分支树状图控制器和兼容导出入口。
 *
 * 数据构建、布局算法、SVG 节点/连线渲染已经拆到 web/js/branch-tree/*
 * 下。本文件保留外部调用 API，并负责 SVG 生命周期、缩放/平移和分支操作。
 */

import { branchApi } from './api.js';
import { clearHighlights, applyHighlightsFromMessages } from './context-highlight.js';
import { state } from './state.js';
import {
  SVG_NS,
  TREE_CONSTANTS,
  ZOOM_CONSTANTS,
} from './branch-tree/constants.js';
import {
  buildDisplayTree,
  buildTree,
  computeActivePath,
  markActivePath,
  markDisplayNodeActive,
} from './branch-tree/model.js';
import { calculateLayout } from './branch-tree/layout.js';
import {
  clearEdges,
  clearNodes,
  renderEdges,
  renderNodes,
  setNodeClickHandler,
  updateRenderedActivePath,
} from './branch-tree/renderer.js';

export {
  EDGE_STYLES,
  NODE_COLORS,
  TREE_CONSTANTS,
  ZOOM_CONSTANTS,
} from './branch-tree/constants.js';
export {
  buildDisplayTree,
  buildTree,
  computeActivePath,
  markActivePath,
} from './branch-tree/model.js';
export { calculateLayout } from './branch-tree/layout.js';
export {
  clearEdges,
  clearNodes,
  computeEdgePath,
  createEdgeElement,
  createNodeElement,
  getEdgeColor,
  getNodeBorderColor,
  getNodeColor,
  renderEdges,
  renderNodes,
  truncateSummary,
} from './branch-tree/renderer.js';

/** 模块内部状态 */
const _state = {
  /** @type {SVGSVGElement|null} */
  svg: null,
  /** @type {SVGGElement|null} 主绘图组（用于缩放/平移变换） */
  rootGroup: null,
  /** @type {HTMLElement|null} 容器 DOM 元素 */
  container: null,
  /** @type {ResizeObserver|null} */
  resizeObserver: null,
  /** @type {import('./branch-tree/model.js').TreeNode|null} 当前树的根节点 */
  treeRoot: null,
  /** @type {Map<string, import('./branch-tree/model.js').TreeNode>} 节点索引 */
  nodeMap: new Map(),
  /** @type {Map<string, import('./branch-tree/model.js').TreeNode>} 原始消息节点索引 */
  rawNodeMap: new Map(),
  /** @type {string|null} 当前活跃节点 ID */
  activeNodeId: null,
  /** @type {number} 当前树布局所需宽度 */
  contentWidth: TREE_CONSTANTS.minWidth,
  /** @type {number} 当前树布局所需高度 */
  contentHeight: TREE_CONSTANTS.minHeight,
  /** @type {boolean} 是否正在切换分支（防止重复点击） */
  switching: false,
  /** @type {Function|null} 外部注册的节点点击回调 */
  onSwitchCallback: null,
  scale: ZOOM_CONSTANTS.defaultScale,
  panX: 0,
  panY: 0,
  isPanning: false,
  panStartX: 0,
  panStartY: 0,
  panStartOffsetX: 0,
  panStartOffsetY: 0,
  didPan: false,
  touchStartDist: null,
  touchStartScale: null,
};

let _treeContextMenu = null;

const createSvgElement = (width, height) => {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('width', '100%');
  svg.setAttribute('height', '100%');
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('class', 'branch-tree-svg');
  svg.style.display = 'block';
  svg.style.overflow = 'hidden';
  return svg;
};

const createRootGroup = () => {
  const group = document.createElementNS(SVG_NS, 'g');
  group.setAttribute('class', 'branch-tree-root');
  return group;
};

const handleResize = (width, height) => {
  if (!_state.svg) return;
  const w = Math.max(width || TREE_CONSTANTS.minWidth, _state.contentWidth, TREE_CONSTANTS.minWidth);
  const h = Math.max(height || TREE_CONSTANTS.minHeight, _state.contentHeight, TREE_CONSTANTS.minHeight);
  _state.svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
};

/**
 * 初始化 SVG 容器，挂载到指定 DOM 元素。
 * @param {HTMLElement} container
 */
export const initSvg = (container) => {
  if (!container) {
    console.warn('[branch-tree] initSvg: container is null');
    return;
  }

  cleanup();

  _state.container = container;
  setNodeClickHandler(handleNodeClick);

  const emptyHint = container.querySelector('.tree-panel-empty');
  if (emptyHint) {
    emptyHint.style.display = 'none';
  }

  const rect = container.getBoundingClientRect();
  const width = Math.max(rect.width || TREE_CONSTANTS.minWidth, TREE_CONSTANTS.minWidth);
  const height = Math.max(rect.height || TREE_CONSTANTS.minHeight, TREE_CONSTANTS.minHeight);

  _state.svg = createSvgElement(width, height);
  _state.rootGroup = createRootGroup();
  _state.svg.appendChild(_state.rootGroup);
  container.appendChild(_state.svg);

  _state.resizeObserver = new ResizeObserver((entries) => {
    for (const entry of entries) {
      handleResize(entry.contentRect.width, entry.contentRect.height);
    }
  });
  _state.resizeObserver.observe(container);

  bindZoomPanEvents();
  bindContextMenuEvents();
};

const applyTransform = () => {
  if (!_state.rootGroup) return;
  _state.rootGroup.setAttribute(
    'transform',
    `translate(${_state.panX}, ${_state.panY}) scale(${_state.scale})`,
  );
};

/** 重置缩放和平移到默认状态。 */
export const resetZoomPan = () => {
  _state.scale = ZOOM_CONSTANTS.defaultScale;
  _state.panX = 0;
  _state.panY = 0;
  applyTransform();
};

/** 获取当前缩放/平移状态。 */
export const getZoomPanState = () => ({
  scale: _state.scale,
  panX: _state.panX,
  panY: _state.panY,
});

const handleWheel = (event) => {
  event.preventDefault();

  const oldScale = _state.scale;
  const factor = -event.deltaY > 0
    ? (1 + ZOOM_CONSTANTS.zoomFactor)
    : (1 - ZOOM_CONSTANTS.zoomFactor);

  let newScale = oldScale * factor;
  newScale = Math.max(ZOOM_CONSTANTS.minScale, Math.min(ZOOM_CONSTANTS.maxScale, newScale));
  if (newScale === oldScale) return;

  const svgRect = _state.svg.getBoundingClientRect();
  const mouseX = event.clientX - svgRect.left;
  const mouseY = event.clientY - svgRect.top;

  _state.panX = mouseX - (mouseX - _state.panX) * (newScale / oldScale);
  _state.panY = mouseY - (mouseY - _state.panY) * (newScale / oldScale);
  _state.scale = newScale;

  applyTransform();
};

const handleMouseDown = (event) => {
  if (event.button !== 0 && event.button !== 1) return;

  const target = event.target;
  if (target.closest && target.closest('.branch-tree-node')) return;

  _state.isPanning = true;
  _state.didPan = false;
  _state.panStartX = event.clientX;
  _state.panStartY = event.clientY;
  _state.panStartOffsetX = _state.panX;
  _state.panStartOffsetY = _state.panY;

  if (_state.svg) {
    _state.svg.style.cursor = 'grabbing';
  }

  event.preventDefault();
};

const handleMouseMove = (event) => {
  if (!_state.isPanning) return;

  const dx = event.clientX - _state.panStartX;
  const dy = event.clientY - _state.panStartY;
  if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
    _state.didPan = true;
  }

  _state.panX = _state.panStartOffsetX + dx;
  _state.panY = _state.panStartOffsetY + dy;
  applyTransform();
};

const handleMouseUp = () => {
  if (!_state.isPanning) return;

  _state.isPanning = false;
  if (_state.svg) {
    _state.svg.style.cursor = 'grab';
  }
};

const getTouchDistance = (t1, t2) => {
  const dx = t1.clientX - t2.clientX;
  const dy = t1.clientY - t2.clientY;
  return Math.sqrt(dx * dx + dy * dy);
};

const handleTouchStart = (event) => {
  if (event.touches.length === 1) {
    const target = event.target;
    if (target.closest && target.closest('.branch-tree-node')) return;

    _state.isPanning = true;
    _state.didPan = false;
    _state.panStartX = event.touches[0].clientX;
    _state.panStartY = event.touches[0].clientY;
    _state.panStartOffsetX = _state.panX;
    _state.panStartOffsetY = _state.panY;
  } else if (event.touches.length === 2) {
    event.preventDefault();
    _state.isPanning = false;
    _state.touchStartDist = getTouchDistance(event.touches[0], event.touches[1]);
    _state.touchStartScale = _state.scale;
  }
};

const handleTouchMove = (event) => {
  if (event.touches.length === 1 && _state.isPanning) {
    event.preventDefault();
    const dx = event.touches[0].clientX - _state.panStartX;
    const dy = event.touches[0].clientY - _state.panStartY;

    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
      _state.didPan = true;
    }

    _state.panX = _state.panStartOffsetX + dx;
    _state.panY = _state.panStartOffsetY + dy;
    applyTransform();
  } else if (event.touches.length === 2 && _state.touchStartDist != null) {
    event.preventDefault();
    const currentDist = getTouchDistance(event.touches[0], event.touches[1]);
    const ratio = currentDist / _state.touchStartDist;

    let newScale = _state.touchStartScale * ratio;
    newScale = Math.max(ZOOM_CONSTANTS.minScale, Math.min(ZOOM_CONSTANTS.maxScale, newScale));

    const svgRect = _state.svg.getBoundingClientRect();
    const centerX = (event.touches[0].clientX + event.touches[1].clientX) / 2 - svgRect.left;
    const centerY = (event.touches[0].clientY + event.touches[1].clientY) / 2 - svgRect.top;
    const oldScale = _state.scale;

    _state.panX = centerX - (centerX - _state.panX) * (newScale / oldScale);
    _state.panY = centerY - (centerY - _state.panY) * (newScale / oldScale);
    _state.scale = newScale;

    applyTransform();
  }
};

const handleTouchEnd = (event) => {
  if (event.touches.length < 2) {
    _state.touchStartDist = null;
    _state.touchStartScale = null;
  }
  if (event.touches.length === 0) {
    _state.isPanning = false;
  }
};

const bindZoomPanEvents = () => {
  if (!_state.svg) return;

  _state.svg.addEventListener('wheel', handleWheel, { passive: false });
  _state.svg.addEventListener('mousedown', handleMouseDown);
  document.addEventListener('mousemove', handleMouseMove);
  document.addEventListener('mouseup', handleMouseUp);
  _state.svg.addEventListener('touchstart', handleTouchStart, { passive: false });
  _state.svg.addEventListener('touchmove', handleTouchMove, { passive: false });
  _state.svg.addEventListener('touchend', handleTouchEnd);
  _state.svg.style.cursor = 'grab';
};

const unbindZoomPanEvents = () => {
  if (_state.svg) {
    _state.svg.removeEventListener('wheel', handleWheel);
    _state.svg.removeEventListener('mousedown', handleMouseDown);
    _state.svg.removeEventListener('touchstart', handleTouchStart);
    _state.svg.removeEventListener('touchmove', handleTouchMove);
    _state.svg.removeEventListener('touchend', handleTouchEnd);
  }
  document.removeEventListener('mousemove', handleMouseMove);
  document.removeEventListener('mouseup', handleMouseUp);
};

/** 获取当前 SVG 元素。 */
export const getSvg = () => _state.svg;

/** 获取主绘图组。 */
export const getRootGroup = () => _state.rootGroup;

/**
 * 设置树数据并触发布局计算。
 * @param {Array} apiNodes
 * @param {string|null} activeNodeId
 * @returns {{ root: import('./branch-tree/model.js').TreeNode|null, width: number, height: number }}
 */
export const setTreeData = (apiNodes, activeNodeId) => {
  const { root: rawRoot, nodeMap: rawNodeMap } = buildTree(apiNodes, activeNodeId);
  const { root, nodeMap } = buildDisplayTree(rawRoot, rawNodeMap);
  _state.treeRoot = root;
  _state.nodeMap = nodeMap;
  _state.rawNodeMap = rawNodeMap;
  _state.activeNodeId = activeNodeId;

  const { width, height } = calculateLayout(root);
  _state.contentWidth = width;
  _state.contentHeight = height;

  if (_state.svg) {
    const rect = _state.container?.getBoundingClientRect();
    const viewWidth = Math.max(rect?.width || 0, width);
    const viewHeight = Math.max(rect?.height || 0, height);
    _state.svg.setAttribute('viewBox', `0 0 ${viewWidth} ${viewHeight}`);
  }

  _state.scale = ZOOM_CONSTANTS.defaultScale;
  _state.panX = 0;
  _state.panY = 0;

  clearEdges(_state.rootGroup);
  clearNodes(_state.rootGroup);
  renderEdges(root, _state.rootGroup);
  renderNodes(root, _state.rootGroup);
  applyTransform();

  return { root, width, height };
};

/** 获取当前树的根节点。 */
export const getTreeRoot = () => _state.treeRoot;

/** 获取节点索引 Map。 */
export const getNodeMap = () => _state.nodeMap;

/** 获取当前活跃节点 ID。 */
export const getActiveNodeId = () => _state.activeNodeId;

/**
 * 更新活跃路径高亮。
 * @param {string} newActiveNodeId
 */
export const updateActivePath = (newActiveNodeId) => {
  if (!_state.rawNodeMap || _state.rawNodeMap.size === 0) return;

  _state.activeNodeId = newActiveNodeId;
  const activePathSet = computeActivePath(_state.rawNodeMap, newActiveNodeId);
  markActivePath(_state.rawNodeMap, activePathSet);
  for (const displayNode of _state.nodeMap.values()) {
    markDisplayNodeActive(displayNode, _state.rawNodeMap);
  }
  updateRenderedActivePath(_state.rootGroup, _state.nodeMap);
};

/**
 * 注册分支切换完成后的回调函数。
 * @param {Function} callback
 */
export const onSwitch = (callback) => {
  _state.onSwitchCallback = callback;
};

const handleNodeClick = (nodeId) => {
  if (_state.switching || nodeId === _state.activeNodeId) return;

  const sessionId = state.currentSessionId;
  if (!sessionId) {
    console.warn('[branch-tree] handleNodeClick: no current session');
    return;
  }

  switchBranch(sessionId, nodeId);
};

/**
 * 调用 switch API 切换分支，并更新树状图高亮和消息列表。
 * @param {string} sessionId
 * @param {string} targetNodeId
 * @returns {Promise<void>}
 */
export const switchBranch = async (sessionId, targetNodeId) => {
  if (_state.switching) return;
  _state.switching = true;
  clearHighlights();

  try {
    const result = await branchApi.switch(sessionId, targetNodeId);

    if (result.ok) {
      updateActivePath(result.active_node_id);
      if (_state.onSwitchCallback) {
        _state.onSwitchCallback(result.messages, result.active_node_id);
      }
      applyHighlightsFromMessages(result.messages);
    }
  } catch (error) {
    console.error('[branch-tree] switchBranch failed:', error);
  } finally {
    _state.switching = false;
  }
};

const dismissTreeContextMenu = () => {
  if (_treeContextMenu) {
    _treeContextMenu.remove();
    _treeContextMenu = null;
  }
};

const deleteBranchFromNode = async (nodeId) => {
  const sessionId = state.currentSessionId;
  if (!sessionId || !nodeId) return;

  try {
    const result = await branchApi.delete(sessionId, nodeId);
    if (result && result.ok) {
      const treeData = await branchApi.tree(sessionId);
      if (treeData && treeData.nodes) {
        setTreeData(treeData.nodes, treeData.active_node_id);
      }
    }
  } catch (error) {
    console.warn('[branch-tree] 删除分支失败:', error);
    const msg = error.data?.message || error.message || '未知错误';
    alert('删除分支失败: ' + msg);
  }
};

const showTreeNodeContextMenu = (event, nodeId) => {
  dismissTreeContextMenu();

  const menu = document.createElement('div');
  menu.className = 'tree-node-context-menu';
  menu.innerHTML = `
    <button type="button" class="context-menu-item danger" data-action="delete-branch">
      <span class="context-menu-icon">🗑</span>
      <span class="context-menu-label">删除分支</span>
    </button>
  `;

  menu.style.position = 'fixed';
  menu.style.left = `${event.clientX}px`;
  menu.style.top = `${event.clientY}px`;
  menu.style.zIndex = '10000';

  menu.querySelector('[data-action="delete-branch"]').addEventListener('click', () => {
    dismissTreeContextMenu();
    if (confirm('确定要删除此分支及其所有子分支吗？此操作不可恢复。')) {
      deleteBranchFromNode(nodeId);
    }
  });

  document.body.appendChild(menu);
  _treeContextMenu = menu;

  const rect = menu.getBoundingClientRect();
  if (rect.right > window.innerWidth) {
    menu.style.left = `${window.innerWidth - rect.width - 4}px`;
  }
  if (rect.bottom > window.innerHeight) {
    menu.style.top = `${window.innerHeight - rect.height - 4}px`;
  }
};

const handleSvgContextMenu = (event) => {
  const nodeGroup = event.target.closest('.branch-tree-node');
  if (!nodeGroup) {
    dismissTreeContextMenu();
    return;
  }

  event.preventDefault();
  const nodeId = nodeGroup.getAttribute('data-delete-node-id') || nodeGroup.getAttribute('data-node-id');
  if (nodeId) {
    showTreeNodeContextMenu(event, nodeId);
  }
};

const bindContextMenuEvents = () => {
  document.addEventListener('click', dismissTreeContextMenu);
  if (_state.svg) {
    _state.svg.addEventListener('contextmenu', handleSvgContextMenu);
  }
};

const unbindContextMenuEvents = () => {
  document.removeEventListener('click', dismissTreeContextMenu);
  if (_state.svg) {
    _state.svg.removeEventListener('contextmenu', handleSvgContextMenu);
  }
  dismissTreeContextMenu();
};

/** 清理模块资源：移除 SVG、断开 ResizeObserver、解绑事件、重置状态。 */
export const cleanup = () => {
  unbindZoomPanEvents();
  unbindContextMenuEvents();
  setNodeClickHandler(null);

  if (_state.resizeObserver) {
    _state.resizeObserver.disconnect();
    _state.resizeObserver = null;
  }
  if (_state.svg && _state.svg.parentNode) {
    _state.svg.parentNode.removeChild(_state.svg);
  }
  if (_state.container) {
    const emptyHint = _state.container.querySelector('.tree-panel-empty');
    if (emptyHint) {
      emptyHint.style.display = '';
    }
  }

  _state.svg = null;
  _state.rootGroup = null;
  _state.container = null;
  _state.treeRoot = null;
  _state.nodeMap = new Map();
  _state.rawNodeMap = new Map();
  _state.activeNodeId = null;
  _state.contentWidth = TREE_CONSTANTS.minWidth;
  _state.contentHeight = TREE_CONSTANTS.minHeight;
  _state.switching = false;
  _state.scale = ZOOM_CONSTANTS.defaultScale;
  _state.panX = 0;
  _state.panY = 0;
  _state.isPanning = false;
  _state.didPan = false;
  _state.touchStartDist = null;
  _state.touchStartScale = null;
};

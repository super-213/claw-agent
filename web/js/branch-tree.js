/**
 * branch-tree.js — 会话分支树状图模块
 *
 * 负责 SVG 渲染会话的分支树结构：
 * - SVG 容器创建与管理
 * - 树布局计算基础设施（Reingold-Tilford 算法在 5.2 中实现）
 * - 节点/连线数据结构
 * - 节点点击交互（调用 switch API 切换分支）
 * - 初始化与清理
 */

import { branchApi } from './api.js';
import { clearHighlights, applyHighlightsFromMessages } from './context-highlight.js';
import { state } from './state.js';

// ─── 常量 ───────────────────────────────────────────────────────────────────

/** SVG 命名空间 */
const SVG_NS = 'http://www.w3.org/2000/svg';

/** 节点尺寸与间距 */
export const TREE_CONSTANTS = {
  /** 兼容旧测试/调用方的节点半径，块状视图不再直接使用 */
  nodeRadius: 14,
  /** 分支块宽度 */
  nodeWidth: 240,
  /** 分支块高度 */
  nodeHeight: 128,
  /** 分支块内部消息条宽度 */
  messageWidth: 176,
  /** 分支块内部消息条高度 */
  messageHeight: 34,
  /** 同层节点水平间距 */
  siblingSpacing: 320,
  /** 层级间垂直间距 */
  levelSpacing: 190,
  /** 树的内边距 */
  padding: 36,
  /** 最小 SVG 宽度 */
  minWidth: 320,
  /** 最小 SVG 高度 */
  minHeight: 260,
};

/** 节点颜色（按角色区分） */
export const NODE_COLORS = {
  user: '#75a7ff',
  assistant: '#52d987',
  tool: '#f5a623',
  system: '#8e8e93',
  /** 活跃路径上的节点描边色 */
  activeBorder: '#00e5c8',
  /** 默认描边色 */
  defaultBorder: 'rgba(122, 143, 168, 0.5)',
};

/** 连线样式 */
export const EDGE_STYLES = {
  /** 默认连线颜色 */
  color: 'rgba(122, 143, 168, 0.36)',
  /** 活跃路径连线颜色 */
  activeColor: '#00e5c8',
  /** 连线宽度 */
  width: 2,
};

// ─── 数据结构 ─────────────────────────────────────────────────────────────────

/**
 * 内部树节点结构（从 API 数据转换而来）
 * @typedef {Object} TreeNode
 * @property {string} nodeId - 节点唯一标识
 * @property {string|null} parentId - 父节点标识
 * @property {string} role - 消息角色 (user|assistant|system)
 * @property {string} summary - 消息摘要文本
 * @property {boolean} isActive - 是否在当前活跃路径上
 * @property {number} childCount - 子节点数量
 * @property {number} x - 布局计算后的 x 坐标
 * @property {number} y - 布局计算后的 y 坐标
 * @property {TreeNode[]} children - 子节点引用列表
 */

/**
 * 计算从根节点到指定活跃节点的路径上所有节点 ID
 *
 * 从 activeNodeId 向上回溯 parentId 直到根节点，收集路径上所有节点。
 * 这确保即使 API 未提供 is_active 字段，前端也能正确计算活跃路径。
 *
 * @param {Map<string, TreeNode>} nodeMap - 节点索引
 * @param {string|null} activeNodeId - 当前活跃节点 ID
 * @returns {Set<string>} 活跃路径上所有节点的 ID 集合
 */
export const computeActivePath = (nodeMap, activeNodeId) => {
  const activeSet = new Set();
  if (!activeNodeId || !nodeMap.has(activeNodeId)) {
    return activeSet;
  }

  // 从活跃节点向上回溯到根节点
  let current = nodeMap.get(activeNodeId);
  while (current) {
    activeSet.add(current.nodeId);
    if (current.parentId == null) break;
    current = nodeMap.get(current.parentId);
  }

  return activeSet;
};

/**
 * 将活跃路径标记应用到节点上
 * @param {Map<string, TreeNode>} nodeMap - 节点索引
 * @param {Set<string>} activePathSet - 活跃路径节点 ID 集合
 */
export const markActivePath = (nodeMap, activePathSet) => {
  for (const node of nodeMap.values()) {
    node.isActive = activePathSet.has(node.nodeId);
  }
};

/**
 * 从 API 响应构建内部树结构
 *
 * 构建树后，会基于 activeNodeId 计算活跃路径并标记节点的 isActive 属性。
 * 这确保活跃路径高亮始终与当前 activeNodeId 一致，不依赖 API 的 is_active 字段。
 *
 * @param {Array} apiNodes - GET /api/sessions/<id>/tree 返回的 nodes 数组
 * @param {string} activeNodeId - 当前活跃节点 ID
 * @returns {{ root: TreeNode|null, nodeMap: Map<string, TreeNode> }}
 */
export const buildTree = (apiNodes, activeNodeId) => {
  if (!apiNodes || apiNodes.length === 0) {
    return { root: null, nodeMap: new Map() };
  }

  const nodeMap = new Map();

  // 第一遍：创建所有 TreeNode
  for (const n of apiNodes) {
    nodeMap.set(n.node_id, {
      nodeId: n.node_id,
      parentId: n.parent_id,
      role: n.role,
      summary: n.summary || '',
      isActive: false, // 初始为 false，后续由 computeActivePath 计算
      childCount: n.child_count || 0,
      x: 0,
      y: 0,
      children: [],
    });
  }

  // 第二遍：建立父子关系，找到根节点
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

  // 第三遍：计算活跃路径并标记节点
  const activePathSet = computeActivePath(nodeMap, activeNodeId);
  markActivePath(nodeMap, activePathSet);

  return { root, nodeMap };
};

// ─── SVG 容器管理 ─────────────────────────────────────────────────────────────

/** 缩放/平移常量 */
export const ZOOM_CONSTANTS = {
  /** 最小缩放比例 */
  minScale: 0.2,
  /** 最大缩放比例 */
  maxScale: 5,
  /** 每次滚轮缩放的步进因子 */
  zoomFactor: 0.1,
  /** 初始缩放比例 */
  defaultScale: 1,
};

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
  /** @type {TreeNode|null} 当前树的根节点 */
  treeRoot: null,
  /** @type {Map<string, TreeNode>} 节点索引 */
  nodeMap: new Map(),
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
  // ─── 缩放/平移状态 ───
  /** @type {number} 当前缩放比例 */
  scale: 1,
  /** @type {number} 当前平移 X 偏移 */
  panX: 0,
  /** @type {number} 当前平移 Y 偏移 */
  panY: 0,
  /** @type {boolean} 是否正在拖拽平移 */
  isPanning: false,
  /** @type {number} 拖拽起始鼠标 X */
  panStartX: 0,
  /** @type {number} 拖拽起始鼠标 Y */
  panStartY: 0,
  /** @type {number} 拖拽起始时的 panX */
  panStartOffsetX: 0,
  /** @type {number} 拖拽起始时的 panY */
  panStartOffsetY: 0,
  /** @type {boolean} 拖拽过程中是否发生了移动（用于区分点击和拖拽） */
  didPan: false,
  // ─── 触摸缩放状态 ───
  /** @type {number|null} 双指触摸初始距离 */
  touchStartDist: null,
  /** @type {number|null} 双指触摸初始缩放比例 */
  touchStartScale: null,
};

/**
 * 创建 SVG 元素
 * @param {number} width
 * @param {number} height
 * @returns {SVGSVGElement}
 */
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

/**
 * 创建主绘图组（所有节点和连线绘制在此组内，方便整体变换）
 * @returns {SVGGElement}
 */
const createRootGroup = () => {
  const g = document.createElementNS(SVG_NS, 'g');
  g.setAttribute('class', 'branch-tree-root');
  return g;
};

/**
 * 初始化 SVG 容器，挂载到指定 DOM 元素
 * @param {HTMLElement} container - 树状图的容器元素
 */
export const initSvg = (container) => {
  if (!container) {
    console.warn('[branch-tree] initSvg: container is null');
    return;
  }

  // 清理已有内容
  cleanup();

  _state.container = container;

  // 隐藏占位提示（如果存在）
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

  // 监听容器尺寸变化
  _state.resizeObserver = new ResizeObserver((entries) => {
    for (const entry of entries) {
      handleResize(entry.contentRect.width, entry.contentRect.height);
    }
  });
  _state.resizeObserver.observe(container);

  // 绑定缩放和平移事件
  bindZoomPanEvents();

  // 绑定右键菜单事件
  bindContextMenuEvents();
};

/**
 * 处理容器尺寸变化，更新 SVG viewBox
 * @param {number} width
 * @param {number} height
 */
const handleResize = (width, height) => {
  if (!_state.svg) return;
  const w = Math.max(width || TREE_CONSTANTS.minWidth, _state.contentWidth, TREE_CONSTANTS.minWidth);
  const h = Math.max(height || TREE_CONSTANTS.minHeight, _state.contentHeight, TREE_CONSTANTS.minHeight);
  _state.svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
};

// ─── 缩放与平移 ─────────────────────────────────────────────────────────────

/**
 * 将当前 scale/panX/panY 应用到 rootGroup 的 transform 属性
 */
const applyTransform = () => {
  if (!_state.rootGroup) return;
  _state.rootGroup.setAttribute(
    'transform',
    `translate(${_state.panX}, ${_state.panY}) scale(${_state.scale})`,
  );
};

/**
 * 重置缩放和平移到默认状态
 */
export const resetZoomPan = () => {
  _state.scale = ZOOM_CONSTANTS.defaultScale;
  _state.panX = 0;
  _state.panY = 0;
  applyTransform();
};

/**
 * 获取当前缩放/平移状态（供外部或测试使用）
 * @returns {{ scale: number, panX: number, panY: number }}
 */
export const getZoomPanState = () => ({
  scale: _state.scale,
  panX: _state.panX,
  panY: _state.panY,
});

/**
 * 鼠标滚轮缩放处理
 *
 * 以鼠标指针位置为中心进行缩放，确保缩放时鼠标下方的内容保持不动。
 * 缩放比例限制在 [minScale, maxScale] 范围内。
 *
 * @param {WheelEvent} event
 */
const handleWheel = (event) => {
  event.preventDefault();

  const oldScale = _state.scale;
  const delta = -event.deltaY;
  const factor = delta > 0
    ? (1 + ZOOM_CONSTANTS.zoomFactor)
    : (1 - ZOOM_CONSTANTS.zoomFactor);

  let newScale = oldScale * factor;
  newScale = Math.max(ZOOM_CONSTANTS.minScale, Math.min(ZOOM_CONSTANTS.maxScale, newScale));

  if (newScale === oldScale) return;

  // 获取鼠标相对于 SVG 容器的位置
  const svgRect = _state.svg.getBoundingClientRect();
  const mouseX = event.clientX - svgRect.left;
  const mouseY = event.clientY - svgRect.top;

  // 以鼠标位置为中心缩放：调整平移使鼠标下方的点保持不动
  // 公式：newPan = mousePos - (mousePos - oldPan) * (newScale / oldScale)
  _state.panX = mouseX - (mouseX - _state.panX) * (newScale / oldScale);
  _state.panY = mouseY - (mouseY - _state.panY) * (newScale / oldScale);
  _state.scale = newScale;

  applyTransform();
};

/**
 * 鼠标按下：开始拖拽平移
 * @param {MouseEvent} event
 */
const handleMouseDown = (event) => {
  // 只响应左键（button === 0）或中键（button === 1）
  if (event.button !== 0 && event.button !== 1) return;

  // 如果点击的是节点元素，不启动平移（让节点点击事件处理）
  const target = event.target;
  if (target.closest && target.closest('.branch-tree-node')) return;

  _state.isPanning = true;
  _state.didPan = false;
  _state.panStartX = event.clientX;
  _state.panStartY = event.clientY;
  _state.panStartOffsetX = _state.panX;
  _state.panStartOffsetY = _state.panY;

  // 改变光标样式
  if (_state.svg) {
    _state.svg.style.cursor = 'grabbing';
  }

  event.preventDefault();
};

/**
 * 鼠标移动：执行平移
 * @param {MouseEvent} event
 */
const handleMouseMove = (event) => {
  if (!_state.isPanning) return;

  const dx = event.clientX - _state.panStartX;
  const dy = event.clientY - _state.panStartY;

  // 如果移动超过 3px 阈值，标记为真正的拖拽（区分点击和拖拽）
  if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
    _state.didPan = true;
  }

  _state.panX = _state.panStartOffsetX + dx;
  _state.panY = _state.panStartOffsetY + dy;

  applyTransform();
};

/**
 * 鼠标松开：结束拖拽平移
 * @param {MouseEvent} event
 */
const handleMouseUp = (event) => {
  if (!_state.isPanning) return;

  _state.isPanning = false;

  // 恢复光标样式
  if (_state.svg) {
    _state.svg.style.cursor = 'grab';
  }
};

// ─── 触摸支持（移动端） ──────────────────────────────────────────────────────────

/**
 * 计算两个触摸点之间的距离
 * @param {Touch} t1
 * @param {Touch} t2
 * @returns {number}
 */
const getTouchDistance = (t1, t2) => {
  const dx = t1.clientX - t2.clientX;
  const dy = t1.clientY - t2.clientY;
  return Math.sqrt(dx * dx + dy * dy);
};

/**
 * 触摸开始事件处理
 * @param {TouchEvent} event
 */
const handleTouchStart = (event) => {
  if (event.touches.length === 1) {
    // 单指：开始平移（但不阻止节点点击）
    const target = event.target;
    if (target.closest && target.closest('.branch-tree-node')) return;

    _state.isPanning = true;
    _state.didPan = false;
    _state.panStartX = event.touches[0].clientX;
    _state.panStartY = event.touches[0].clientY;
    _state.panStartOffsetX = _state.panX;
    _state.panStartOffsetY = _state.panY;
  } else if (event.touches.length === 2) {
    // 双指：开始缩放
    event.preventDefault();
    _state.isPanning = false;
    _state.touchStartDist = getTouchDistance(event.touches[0], event.touches[1]);
    _state.touchStartScale = _state.scale;
  }
};

/**
 * 触摸移动事件处理
 * @param {TouchEvent} event
 */
const handleTouchMove = (event) => {
  if (event.touches.length === 1 && _state.isPanning) {
    // 单指平移
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
    // 双指缩放
    event.preventDefault();
    const currentDist = getTouchDistance(event.touches[0], event.touches[1]);
    const ratio = currentDist / _state.touchStartDist;

    let newScale = _state.touchStartScale * ratio;
    newScale = Math.max(ZOOM_CONSTANTS.minScale, Math.min(ZOOM_CONSTANTS.maxScale, newScale));

    // 以双指中点为缩放中心
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

/**
 * 触摸结束事件处理
 * @param {TouchEvent} event
 */
const handleTouchEnd = (event) => {
  if (event.touches.length < 2) {
    _state.touchStartDist = null;
    _state.touchStartScale = null;
  }
  if (event.touches.length === 0) {
    _state.isPanning = false;
  }
};

/**
 * 绑定缩放和平移事件监听器到 SVG 元素
 * 在 initSvg 中调用
 */
const bindZoomPanEvents = () => {
  if (!_state.svg) return;

  // 鼠标滚轮缩放
  _state.svg.addEventListener('wheel', handleWheel, { passive: false });

  // 鼠标拖拽平移
  _state.svg.addEventListener('mousedown', handleMouseDown);
  // mousemove 和 mouseup 绑定到 document，以便鼠标移出 SVG 区域时仍能响应
  document.addEventListener('mousemove', handleMouseMove);
  document.addEventListener('mouseup', handleMouseUp);

  // 触摸事件（移动端）
  _state.svg.addEventListener('touchstart', handleTouchStart, { passive: false });
  _state.svg.addEventListener('touchmove', handleTouchMove, { passive: false });
  _state.svg.addEventListener('touchend', handleTouchEnd);

  // 设置默认光标
  _state.svg.style.cursor = 'grab';
};

/**
 * 解绑缩放和平移事件监听器
 * 在 cleanup 中调用
 */
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

/**
 * 获取当前 SVG 元素（供外部模块使用）
 * @returns {SVGSVGElement|null}
 */
export const getSvg = () => _state.svg;

/**
 * 获取主绘图组
 * @returns {SVGGElement|null}
 */
export const getRootGroup = () => _state.rootGroup;

// ─── 布局计算 ─────────────────────────────────────────────────────────────────

/**
 * Reingold-Tilford 树布局算法
 *
 * 产生美观的树布局：
 * 1. 自底向上分配初步 x 坐标（firstWalk）
 * 2. 使用轮廓（contour）检测子树重叠并分离
 * 3. 父节点居中于子节点之上
 * 4. 自顶向下应用修正量（secondWalk）确定最终坐标
 *
 * @param {TreeNode|null} root - 树的根节点
 * @returns {{ width: number, height: number }} 布局所需的画布尺寸
 */
export const calculateLayout = (root) => {
  if (!root) {
    return { width: TREE_CONSTANTS.minWidth, height: TREE_CONSTANTS.minHeight };
  }

  const spacing = TREE_CONSTANTS.siblingSpacing;

  // 临时布局属性存储（避免污染原始节点过多字段）
  const meta = new Map();

  const getMeta = (node) => {
    if (!meta.has(node)) {
      meta.set(node, { prelim: 0, mod: 0, thread: null, ancestor: node });
    }
    return meta.get(node);
  };

  /**
   * 第一遍：自底向上，为每个节点计算初步 x 坐标（prelim）和修正量（mod）
   */
  const firstWalk = (node, leftSibling) => {
    const m = getMeta(node);

    if (node.children.length === 0) {
      // 叶节点：如果有左兄弟，则 prelim = 左兄弟的 prelim + spacing
      if (leftSibling) {
        m.prelim = getMeta(leftSibling).prelim + spacing;
      } else {
        m.prelim = 0;
      }
    } else {
      // 内部节点：递归处理子节点
      let defaultAncestor = node.children[0];

      for (let i = 0; i < node.children.length; i++) {
        const child = node.children[i];
        const childLeftSibling = i > 0 ? node.children[i - 1] : null;
        firstWalk(child, childLeftSibling);
        defaultAncestor = apportion(child, defaultAncestor, node);
      }

      executeShifts(node);

      // 父节点居中于第一个和最后一个子节点之间
      const firstChild = node.children[0];
      const lastChild = node.children[node.children.length - 1];
      const midpoint = (getMeta(firstChild).prelim + getMeta(lastChild).prelim) / 2;

      if (leftSibling) {
        m.prelim = getMeta(leftSibling).prelim + spacing;
        m.mod = m.prelim - midpoint;
      } else {
        m.prelim = midpoint;
      }
    }
  };

  /**
   * 轮廓合并：确保子树之间不重叠
   * 这是 Reingold-Tilford 算法的核心部分
   */
  const apportion = (node, defaultAncestor, parentNode) => {
    const nodeIndex = parentNode.children.indexOf(node);
    const leftSibling = nodeIndex > 0 ? parentNode.children[nodeIndex - 1] : null;

    if (!leftSibling) return defaultAncestor;

    // 四个指针：内右、外右、内左、外左
    let vInnerRight = node;
    let vOuterRight = node;
    let vInnerLeft = leftSibling;
    let vOuterLeft = parentNode.children[0];

    let sInnerRight = getMeta(vInnerRight).mod;
    let sOuterRight = getMeta(vOuterRight).mod;
    let sInnerLeft = getMeta(vInnerLeft).mod;
    let sOuterLeft = getMeta(vOuterLeft).mod;

    while (nextRight(vInnerLeft) && nextLeft(vInnerRight)) {
      vInnerLeft = nextRight(vInnerLeft);
      vInnerRight = nextLeft(vInnerRight);
      vOuterLeft = nextLeft(vOuterLeft);
      vOuterRight = nextRight(vOuterRight);

      getMeta(vOuterRight).ancestor = node;

      const shift =
        getMeta(vInnerLeft).prelim +
        sInnerLeft -
        (getMeta(vInnerRight).prelim + sInnerRight) +
        spacing;

      if (shift > 0) {
        moveSubtree(ancestor(vInnerLeft, node, defaultAncestor, parentNode), node, shift, parentNode);
        sInnerRight += shift;
        sOuterRight += shift;
      }

      sInnerLeft += getMeta(vInnerLeft).mod;
      sInnerRight += getMeta(vInnerRight).mod;
      sOuterLeft += getMeta(vOuterLeft).mod;
      sOuterRight += getMeta(vOuterRight).mod;
    }

    // 设置线程（thread）以便后续轮廓遍历
    if (nextRight(vInnerLeft) && !nextRight(vOuterRight)) {
      getMeta(vOuterRight).thread = nextRight(vInnerLeft);
      getMeta(vOuterRight).mod += sInnerLeft - sOuterRight;
    }

    if (nextLeft(vInnerRight) && !nextLeft(vOuterLeft)) {
      getMeta(vOuterLeft).thread = nextLeft(vInnerRight);
      getMeta(vOuterLeft).mod += sInnerRight - sOuterLeft;
      defaultAncestor = node;
    }

    return defaultAncestor;
  };

  /**
   * 获取节点左轮廓的下一个节点
   */
  const nextLeft = (node) => {
    if (node.children.length > 0) return node.children[0];
    return getMeta(node).thread;
  };

  /**
   * 获取节点右轮廓的下一个节点
   */
  const nextRight = (node) => {
    if (node.children.length > 0) return node.children[node.children.length - 1];
    return getMeta(node).thread;
  };

  /**
   * 移动子树：记录位移量，由 executeShifts 统一应用
   */
  const moveSubtree = (wl, wr, shift, parentNode) => {
    const wlIndex = parentNode.children.indexOf(wl);
    const wrIndex = parentNode.children.indexOf(wr);
    const subtrees = wrIndex - wlIndex;

    if (subtrees <= 0) return;

    const mWr = getMeta(wr);

    mWr.shift = (mWr.shift || 0) + shift;
    mWr.change = (mWr.change || 0) - shift / subtrees;

    const mWl = getMeta(wl);
    mWl.change = (mWl.change || 0) + shift / subtrees;

    mWr.prelim += shift;
    mWr.mod += shift;
  };

  /**
   * 执行累积的位移：从右到左累加 shift 和 change
   */
  const executeShifts = (node) => {
    let shift = 0;
    let change = 0;
    for (let i = node.children.length - 1; i >= 0; i--) {
      const child = node.children[i];
      const m = getMeta(child);
      m.prelim += shift;
      m.mod += shift;
      change += m.change || 0;
      shift += m.shift || 0;
      shift += change;
    }
  };

  /**
   * 确定祖先节点（用于 apportion 中的子树移动）
   */
  const ancestor = (vInnerLeft, node, defaultAncestor, parentNode) => {
    const a = getMeta(vInnerLeft).ancestor;
    if (parentNode.children.includes(a)) {
      return a;
    }
    return defaultAncestor;
  };

  /**
   * 第二遍：自顶向下，累加 mod 值得到最终 x 坐标
   */
  const secondWalk = (node, modSum, depth) => {
    const m = getMeta(node);
    node.x = m.prelim + modSum + TREE_CONSTANTS.padding;
    node.y = TREE_CONSTANTS.padding + depth * TREE_CONSTANTS.levelSpacing;

    for (const child of node.children) {
      secondWalk(child, modSum + m.mod, depth + 1);
    }
  };

  // ─── 执行算法 ───

  // 第一遍：自底向上计算初步坐标
  firstWalk(root, null);

  // 第二遍：自顶向下确定最终坐标
  secondWalk(root, 0, 0);

  // 计算边界并归一化（确保所有 x >= padding）
  let minX = Infinity;
  let maxX = -Infinity;
  let maxDepth = 0;

  const collectBounds = (node, depth) => {
    if (node.x < minX) minX = node.x;
    if (node.x > maxX) maxX = node.x;
    if (depth > maxDepth) maxDepth = depth;
    for (const child of node.children) {
      collectBounds(child, depth + 1);
    }
  };
  collectBounds(root, 0);

  // 如果最小 x 小于 padding，平移所有节点使最左节点位于 padding 处
  if (minX < TREE_CONSTANTS.padding) {
    const offsetX = TREE_CONSTANTS.padding - minX;
    const shiftAll = (node) => {
      node.x += offsetX;
      for (const child of node.children) {
        shiftAll(child);
      }
    };
    shiftAll(root);
    maxX += offsetX;
  }

  const totalWidth = Math.max(
    maxX + TREE_CONSTANTS.nodeWidth + TREE_CONSTANTS.padding,
    TREE_CONSTANTS.minWidth,
  );
  const totalHeight = Math.max(
    maxDepth * TREE_CONSTANTS.levelSpacing + TREE_CONSTANTS.nodeHeight + TREE_CONSTANTS.padding * 2,
    TREE_CONSTANTS.minHeight,
  );

  return { width: totalWidth, height: totalHeight };
};

// ─── 节点渲染 ─────────────────────────────────────────────────────────────────

/**
 * 截取消息摘要文本（用于 tooltip 显示）
 * @param {string} text - 原始消息文本
 * @param {number} [maxLen=30] - 最大字符数
 * @returns {string} 截取后的摘要
 */
export const truncateSummary = (text, maxLen = 30) => {
  if (!text) return '';
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + '…';
};

/**
 * 获取节点填充颜色（根据角色）
 * @param {string} role - 消息角色 (user|assistant|system)
 * @returns {string} 颜色值
 */
export const getNodeColor = (role) => {
  return NODE_COLORS[role] || NODE_COLORS.system;
};

/**
 * 获取节点描边颜色（根据是否在活跃路径上）
 * @param {boolean} isActive - 是否在活跃路径上
 * @returns {string} 描边颜色值
 */
export const getNodeBorderColor = (isActive) => {
  return isActive ? NODE_COLORS.activeBorder : NODE_COLORS.defaultBorder;
};

/**
 * 获取节点角色在分支块里的显示名称
 * @param {string} role - 消息角色
 * @returns {string}
 */
const getRoleLabel = (role) => {
  if (role === 'assistant') return 'model';
  if (role === 'tool') return 'tool';
  if (role === 'system') return 'system';
  return 'user';
};

/**
 * 创建 SVG 文本元素
 * @param {string} text
 * @param {number} x
 * @param {number} y
 * @param {string} className
 * @returns {SVGTextElement}
 */
const createTextElement = (text, x, y, className) => {
  const el = document.createElementNS(SVG_NS, 'text');
  el.setAttribute('x', String(x));
  el.setAttribute('y', String(y));
  el.setAttribute('class', className);
  el.textContent = text;
  return el;
};

/**
 * 创建单个消息条，放在分支块内部
 * @param {TreeNode} node - 树节点数据
 * @returns {SVGGElement}
 */
const createMessageCardElement = (node) => {
  const card = document.createElementNS(SVG_NS, 'g');
  card.setAttribute('class', `branch-message-card role-${node.role}${node.isActive ? ' active' : ''}`);

  const x = (TREE_CONSTANTS.nodeWidth - TREE_CONSTANTS.messageWidth) / 2;
  const y = (TREE_CONSTANTS.nodeHeight - TREE_CONSTANTS.messageHeight) / 2;

  const rect = document.createElementNS(SVG_NS, 'rect');
  rect.setAttribute('x', String(x));
  rect.setAttribute('y', String(y));
  rect.setAttribute('width', String(TREE_CONSTANTS.messageWidth));
  rect.setAttribute('height', String(TREE_CONSTANTS.messageHeight));
  rect.setAttribute('rx', '7');
  rect.setAttribute('class', 'branch-message-rect');

  const roleLabel = createTextElement(`${getRoleLabel(node.role)}:`, x + 18, y + 22, 'branch-message-role');
  const summary = createTextElement(
    truncateSummary(node.summary || 'empty', 18),
    x + 82,
    y + 22,
    'branch-message-summary',
  );

  card.appendChild(rect);
  card.appendChild(roleLabel);
  card.appendChild(summary);
  return card;
};

/**
 * 创建单个节点的 SVG 组元素（分支块 + 消息摘要 + tooltip）
 * @param {TreeNode} node - 树节点数据
 * @returns {SVGGElement} 节点的 SVG 组元素
 */
export const createNodeElement = (node) => {
  const group = document.createElementNS(SVG_NS, 'g');
  group.setAttribute('class', `branch-tree-node${node.isActive ? ' active' : ' inactive'}`);
  group.setAttribute('data-node-id', node.nodeId);
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

  // Tooltip（SVG title 元素，浏览器原生 tooltip）
  const title = document.createElementNS(SVG_NS, 'title');
  title.textContent = `${getRoleLabel(node.role)}: ${truncateSummary(node.summary, 80)}`;
  group.appendChild(title);

  // 点击事件：触发分支切换
  group.addEventListener('click', (event) => {
    event.stopPropagation();
    handleNodeClick(node.nodeId);
  });

  return group;
};

/**
 * 渲染所有节点到 SVG 根组中
 * 遍历树结构，为每个节点创建 SVG 元素并添加到绘图组
 * @param {TreeNode|null} root - 树的根节点
 * @param {SVGGElement|null} rootGroup - SVG 绘图组（如果为 null 则使用内部状态的 rootGroup）
 * @returns {SVGGElement|null} 包含所有节点的 SVG 组，如果无法渲染则返回 null
 */
export const renderNodes = (root, rootGroup) => {
  const group = rootGroup || _state.rootGroup;
  if (!root || !group) return null;

  // 创建节点层组（确保节点在连线之上）
  const nodesLayer = document.createElementNS(SVG_NS, 'g');
  nodesLayer.setAttribute('class', 'branch-tree-nodes-layer');

  // 深度优先遍历，渲染所有节点
  const traverse = (node) => {
    const nodeElement = createNodeElement(node);
    nodesLayer.appendChild(nodeElement);
    for (const child of node.children) {
      traverse(child);
    }
  };

  traverse(root);
  group.appendChild(nodesLayer);

  return nodesLayer;
};

/**
 * 清除已渲染的节点层
 * @param {SVGGElement|null} rootGroup - SVG 绘图组（如果为 null 则使用内部状态的 rootGroup）
 */
export const clearNodes = (rootGroup) => {
  const group = rootGroup || _state.rootGroup;
  if (!group) return;

  const existing = group.querySelector('.branch-tree-nodes-layer');
  if (existing) {
    group.removeChild(existing);
  }
};

// ─── 连线渲染（贝塞尔曲线） ──────────────────────────────────────────────────────

/**
 * 生成连接父节点底部到子节点顶部的三次贝塞尔曲线路径字符串
 *
 * 曲线从父分支块底部中心出发，到达子分支块顶部中心。
 * 控制点在垂直方向中点处，使曲线平滑过渡。
 *
 * @param {TreeNode} parent - 父节点（已有布局坐标）
 * @param {TreeNode} child - 子节点（已有布局坐标）
 * @returns {string} SVG path 的 d 属性值
 */
export const computeEdgePath = (parent, child) => {
  // 起点：父分支块底部中心
  const x1 = parent.x + TREE_CONSTANTS.nodeWidth / 2;
  const y1 = parent.y + TREE_CONSTANTS.nodeHeight;

  // 终点：子分支块顶部中心
  const x2 = child.x + TREE_CONSTANTS.nodeWidth / 2;
  const y2 = child.y;

  // 控制点：垂直方向中点，水平方向分别对齐起点和终点
  const midY = (y1 + y2) / 2;
  const cp1x = x1;
  const cp1y = midY;
  const cp2x = x2;
  const cp2y = midY;

  return `M ${x1} ${y1} C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${x2} ${y2}`;
};

/**
 * 获取连线颜色（根据父子节点是否都在活跃路径上）
 * @param {TreeNode} parent - 父节点
 * @param {TreeNode} child - 子节点
 * @returns {string} 连线颜色值
 */
export const getEdgeColor = (parent, child) => {
  return parent.isActive && child.isActive ? EDGE_STYLES.activeColor : EDGE_STYLES.color;
};

/**
 * 创建单条连线的 SVG path 元素
 * @param {TreeNode} parent - 父节点
 * @param {TreeNode} child - 子节点
 * @returns {SVGPathElement} SVG path 元素
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
 * 渲染所有连线到 SVG 根组中
 * 遍历树结构，为每对父子节点创建贝塞尔曲线连线
 * 连线层在节点层之前添加，确保连线渲染在节点之下
 *
 * @param {TreeNode|null} root - 树的根节点
 * @param {SVGGElement|null} rootGroup - SVG 绘图组（如果为 null 则使用内部状态的 rootGroup）
 * @returns {SVGGElement|null} 包含所有连线的 SVG 组，如果无法渲染则返回 null
 */
export const renderEdges = (root, rootGroup) => {
  const group = rootGroup || _state.rootGroup;
  if (!root || !group) return null;

  // 创建连线层组（在节点层之前添加，确保 z-order 正确）
  const edgesLayer = document.createElementNS(SVG_NS, 'g');
  edgesLayer.setAttribute('class', 'branch-tree-edges-layer');

  // 深度优先遍历，为每对父子关系创建连线
  const traverse = (node) => {
    for (const child of node.children) {
      const edgeElement = createEdgeElement(node, child);
      edgesLayer.appendChild(edgeElement);
      traverse(child);
    }
  };

  traverse(root);
  group.appendChild(edgesLayer);

  return edgesLayer;
};

/**
 * 清除已渲染的连线层
 * @param {SVGGElement|null} rootGroup - SVG 绘图组（如果为 null 则使用内部状态的 rootGroup）
 */
export const clearEdges = (rootGroup) => {
  const group = rootGroup || _state.rootGroup;
  if (!group) return;

  const existing = group.querySelector('.branch-tree-edges-layer');
  if (existing) {
    group.removeChild(existing);
  }
};

// ─── 公共 API ─────────────────────────────────────────────────────────────────

/**
 * 设置树数据并触发布局计算
 * @param {Array} apiNodes - API 返回的节点数组
 * @param {string} activeNodeId - 当前活跃节点 ID
 * @returns {{ root: TreeNode|null, width: number, height: number }}
 */
export const setTreeData = (apiNodes, activeNodeId) => {
  const { root, nodeMap } = buildTree(apiNodes, activeNodeId);
  _state.treeRoot = root;
  _state.nodeMap = nodeMap;
  _state.activeNodeId = activeNodeId;

  const { width, height } = calculateLayout(root);
  _state.contentWidth = width;
  _state.contentHeight = height;

  // 更新 SVG viewBox 以适应布局
  if (_state.svg) {
    const rect = _state.container?.getBoundingClientRect();
    const viewWidth = Math.max(rect?.width || 0, width);
    const viewHeight = Math.max(rect?.height || 0, height);
    _state.svg.setAttribute('viewBox', `0 0 ${viewWidth} ${viewHeight}`);
  }

  // 重置缩放/平移状态（新树数据从默认视图开始）
  _state.scale = ZOOM_CONSTANTS.defaultScale;
  _state.panX = 0;
  _state.panY = 0;

  // 清除旧内容并重新渲染（连线先于节点，确保 z-order 正确）
  clearEdges(null);
  clearNodes(null);
  renderEdges(root, null);
  renderNodes(root, null);

  // 应用初始变换（确保 rootGroup 有 transform 属性）
  applyTransform();

  return { root, width, height };
};

/**
 * 获取当前树的根节点
 * @returns {TreeNode|null}
 */
export const getTreeRoot = () => _state.treeRoot;

/**
 * 获取节点索引 Map
 * @returns {Map<string, TreeNode>}
 */
export const getNodeMap = () => _state.nodeMap;

/**
 * 获取当前活跃节点 ID
 * @returns {string|null}
 */
export const getActiveNodeId = () => _state.activeNodeId;

/**
 * 更新活跃路径高亮
 *
 * 当 active_node_id 变化时（如分支切换后），调用此方法重新计算活跃路径
 * 并更新 SVG 中节点和连线的视觉样式，无需重建整棵树。
 *
 * @param {string} newActiveNodeId - 新的活跃节点 ID
 */
export const updateActivePath = (newActiveNodeId) => {
  if (!_state.nodeMap || _state.nodeMap.size === 0) return;

  _state.activeNodeId = newActiveNodeId;

  // 重新计算活跃路径
  const activePathSet = computeActivePath(_state.nodeMap, newActiveNodeId);
  markActivePath(_state.nodeMap, activePathSet);

  // 更新 SVG 中的节点样式
  if (_state.rootGroup) {
    const nodeElements = _state.rootGroup.querySelectorAll('.branch-tree-node');
    for (const nodeEl of nodeElements) {
      const nodeId = nodeEl.getAttribute('data-node-id');
      const node = _state.nodeMap.get(nodeId);
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

    // 更新 SVG 中的连线样式
    const edgeElements = _state.rootGroup.querySelectorAll('.branch-tree-edge');
    for (const edgeEl of edgeElements) {
      const fromId = edgeEl.getAttribute('data-from');
      const toId = edgeEl.getAttribute('data-to');
      const fromNode = _state.nodeMap.get(fromId);
      const toNode = _state.nodeMap.get(toId);
      if (!fromNode || !toNode) continue;

      const isActiveEdge = fromNode.isActive && toNode.isActive;
      edgeEl.setAttribute('stroke', isActiveEdge ? EDGE_STYLES.activeColor : EDGE_STYLES.color);
      // 活跃连线稍粗以增强视觉区分
      edgeEl.setAttribute('stroke-width', isActiveEdge ? String(EDGE_STYLES.width + 1) : String(EDGE_STYLES.width));
      if (isActiveEdge) {
        edgeEl.classList.add('active');
      } else {
        edgeEl.classList.remove('active');
      }
    }
  }
};

// ─── 节点点击交互 ─────────────────────────────────────────────────────────────

/**
 * 注册分支切换完成后的回调函数
 *
 * 外部模块（如 sessions.js）可通过此方法注册回调，
 * 在分支切换成功后接收新的消息列表以更新对话视图。
 *
 * @param {Function} callback - 回调函数，签名为 (messages: Array, activeNodeId: string) => void
 */
export const onSwitch = (callback) => {
  _state.onSwitchCallback = callback;
};

/**
 * 处理节点点击事件
 *
 * 如果点击的节点已经是当前活跃路径上的叶节点，则忽略。
 * 否则调用 switch API 切换分支。
 *
 * @param {string} nodeId - 被点击的节点 ID
 */
const handleNodeClick = (nodeId) => {
  // 如果正在切换中，忽略点击
  if (_state.switching) return;

  // 如果点击的就是当前活跃节点，不做任何操作
  if (nodeId === _state.activeNodeId) return;

  // 需要当前会话 ID 来调用 API
  const sessionId = state.currentSessionId;
  if (!sessionId) {
    console.warn('[branch-tree] handleNodeClick: no current session');
    return;
  }

  switchBranch(sessionId, nodeId);
};

/**
 * 调用 switch API 切换分支，并更新树状图高亮和消息列表
 *
 * 切换时立即清除旧的上下文高亮，切换成功后根据新分支的消息
 * 重新应用上下文高亮。
 *
 * @param {string} sessionId - 当前会话 ID
 * @param {string} targetNodeId - 目标节点 ID
 * @returns {Promise<void>}
 */
export const switchBranch = async (sessionId, targetNodeId) => {
  if (_state.switching) return;
  _state.switching = true;

  // 立即清除旧分支的上下文高亮
  clearHighlights();

  try {
    const result = await branchApi.switch(sessionId, targetNodeId);

    if (result.ok) {
      // 更新树状图的活跃路径高亮
      updateActivePath(result.active_node_id);

      // 通知外部模块（如 sessions.js）更新消息列表
      if (_state.onSwitchCallback) {
        _state.onSwitchCallback(result.messages, result.active_node_id);
      }

      // 根据新分支路径上的最后一条 assistant 消息重新应用上下文高亮
      applyHighlightsFromMessages(result.messages);
    }
  } catch (error) {
    console.error('[branch-tree] switchBranch failed:', error);
  } finally {
    _state.switching = false;
  }
};

// ─── 右键上下文菜单（分支删除） ──────────────────────────────────────────────────

/** 当前显示的树节点上下文菜单元素 */
let _treeContextMenu = null;

/**
 * 关闭并移除当前树节点上下文菜单
 */
const dismissTreeContextMenu = () => {
  if (_treeContextMenu) {
    _treeContextMenu.remove();
    _treeContextMenu = null;
  }
};

/**
 * 删除分支操作：调用 DELETE API 并刷新树状图
 * @param {string} nodeId - 要删除的分支节点 ID
 */
const deleteBranchFromNode = async (nodeId) => {
  const sessionId = state.currentSessionId;
  if (!sessionId || !nodeId) return;

  try {
    const result = await branchApi.delete(sessionId, nodeId);
    if (result && result.ok) {
      // 删除成功，重新加载并渲染树状图
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

/**
 * 显示树节点右键上下文菜单
 * @param {MouseEvent} event - 右键事件
 * @param {string} nodeId - 节点的 node_id
 */
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

  // 定位菜单到鼠标位置
  menu.style.position = 'fixed';
  menu.style.left = `${event.clientX}px`;
  menu.style.top = `${event.clientY}px`;
  menu.style.zIndex = '10000';

  // 绑定菜单项点击
  menu.querySelector('[data-action="delete-branch"]').addEventListener('click', () => {
    dismissTreeContextMenu();
    if (confirm('确定要删除此分支及其所有子分支吗？此操作不可恢复。')) {
      deleteBranchFromNode(nodeId);
    }
  });

  document.body.appendChild(menu);
  _treeContextMenu = menu;

  // 确保菜单不超出视口
  const rect = menu.getBoundingClientRect();
  if (rect.right > window.innerWidth) {
    menu.style.left = `${window.innerWidth - rect.width - 4}px`;
  }
  if (rect.bottom > window.innerHeight) {
    menu.style.top = `${window.innerHeight - rect.height - 4}px`;
  }
};

/**
 * 初始化树节点右键菜单的全局监听器
 * 在 initSvg 中调用
 */
const bindContextMenuEvents = () => {
  // 点击任意位置关闭菜单
  document.addEventListener('click', dismissTreeContextMenu);

  // 在 SVG 上监听右键事件（事件委托）
  if (_state.svg) {
    _state.svg.addEventListener('contextmenu', (event) => {
      const nodeGroup = event.target.closest('.branch-tree-node');
      if (!nodeGroup) {
        dismissTreeContextMenu();
        return;
      }

      event.preventDefault();
      const nodeId = nodeGroup.getAttribute('data-node-id');
      if (nodeId) {
        showTreeNodeContextMenu(event, nodeId);
      }
    });
  }
};

/**
 * 解绑右键菜单事件
 */
const unbindContextMenuEvents = () => {
  document.removeEventListener('click', dismissTreeContextMenu);
  dismissTreeContextMenu();
};

/**
 * 清理模块资源：移除 SVG、断开 ResizeObserver、解绑事件、重置状态
 */
export const cleanup = () => {
  // 解绑缩放/平移事件
  unbindZoomPanEvents();
  // 解绑右键菜单事件
  unbindContextMenuEvents();

  if (_state.resizeObserver) {
    _state.resizeObserver.disconnect();
    _state.resizeObserver = null;
  }
  if (_state.svg && _state.svg.parentNode) {
    _state.svg.parentNode.removeChild(_state.svg);
  }
  // 恢复占位提示显示
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
  _state.activeNodeId = null;
  _state.contentWidth = TREE_CONSTANTS.minWidth;
  _state.contentHeight = TREE_CONSTANTS.minHeight;
  _state.switching = false;
  // 重置缩放/平移状态
  _state.scale = 1;
  _state.panX = 0;
  _state.panY = 0;
  _state.isPanning = false;
  _state.didPan = false;
  _state.touchStartDist = null;
  _state.touchStartScale = null;
};

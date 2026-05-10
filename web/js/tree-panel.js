/**
 * tree-panel.js — 树状图面板 UI 控制模块
 *
 * 负责树状图面板的显示/隐藏、拖拽调整宽度（桌面端）、
 * 底部抽屉上滑展开（移动端）等交互逻辑。
 *
 * 面板内容（SVG 树状图）由 branch-tree.js 模块渲染，
 * 本模块仅管理面板容器的 UI 行为。
 */

// ─── DOM 引用 ────────────────────────────────────────────────────────────────

const panel = document.getElementById('treePanel');
const toggleBtn = document.getElementById('treePanelToggle');
const closeBtn = document.getElementById('treePanelClose');
const resizeHandle = document.getElementById('treePanelResize');
const panelBody = document.getElementById('treePanelBody');

// ─── 状态 ─────────────────────────────────────────────────────────────────────

const _state = {
  /** 面板是否打开 */
  isOpen: false,
  /** 桌面端面板宽度（px） */
  panelWidth: 320,
  /** 移动端面板高度（vh 百分比，40-70） */
  panelHeight: 40,
  /** 是否正在拖拽调整尺寸 */
  isResizing: false,
  /** 拖拽起始鼠标位置 */
  resizeStartPos: 0,
  /** 拖拽起始面板尺寸 */
  resizeStartSize: 0,
};

// ─── 工具函数 ──────────────────────────────────────────────────────────────────

const isMobile = () => window.matchMedia('(max-width: 860px)').matches;

// ─── 面板开关 ──────────────────────────────────────────────────────────────────

/**
 * 打开树状图面板
 */
export const openTreePanel = () => {
  _state.isOpen = true;
  panel.classList.add('open');
  panel.setAttribute('aria-hidden', 'false');
  toggleBtn.setAttribute('aria-expanded', 'true');

  if (!isMobile()) {
    panel.style.width = _state.panelWidth + 'px';
  }
};

/**
 * 关闭树状图面板
 */
export const closeTreePanel = () => {
  _state.isOpen = false;
  panel.classList.remove('open');
  panel.setAttribute('aria-hidden', 'true');
  toggleBtn.setAttribute('aria-expanded', 'false');
};

/**
 * 切换树状图面板的显示/隐藏
 */
export const toggleTreePanel = () => {
  if (_state.isOpen) {
    closeTreePanel();
  } else {
    openTreePanel();
  }
};

/**
 * 获取面板是否打开
 * @returns {boolean}
 */
export const isTreePanelOpen = () => _state.isOpen;

/**
 * 获取面板内容容器（供 branch-tree.js 挂载 SVG）
 * @returns {HTMLElement|null}
 */
export const getTreePanelBody = () => panelBody;

// ─── 桌面端拖拽调整宽度 ──────────────────────────────────────────────────────

const handleResizeMouseDown = (event) => {
  if (isMobile()) return;
  event.preventDefault();

  _state.isResizing = true;
  _state.resizeStartPos = event.clientX;
  _state.resizeStartSize = panel.getBoundingClientRect().width;

  resizeHandle.classList.add('dragging');
  document.body.style.cursor = 'col-resize';
  document.body.style.userSelect = 'none';

  document.addEventListener('mousemove', handleResizeMouseMove);
  document.addEventListener('mouseup', handleResizeMouseUp);
};

const handleResizeMouseMove = (event) => {
  if (!_state.isResizing) return;

  // Panel is on the right, so dragging left increases width
  const delta = _state.resizeStartPos - event.clientX;
  let newWidth = _state.resizeStartSize + delta;

  // Clamp width between 200px and 50% of viewport
  const maxWidth = window.innerWidth * 0.5;
  newWidth = Math.max(200, Math.min(maxWidth, newWidth));

  _state.panelWidth = newWidth;
  panel.style.width = newWidth + 'px';
};

const handleResizeMouseUp = () => {
  _state.isResizing = false;
  resizeHandle.classList.remove('dragging');
  document.body.style.cursor = '';
  document.body.style.userSelect = '';

  document.removeEventListener('mousemove', handleResizeMouseMove);
  document.removeEventListener('mouseup', handleResizeMouseUp);
};

// ─── 移动端拖拽调整高度（上滑展开/下滑收起） ─────────────────────────────────

let touchStartY = 0;
let touchStartHeight = 0;

const handleDrawerTouchStart = (event) => {
  if (!isMobile()) return;

  const touch = event.touches[0];
  touchStartY = touch.clientY;
  touchStartHeight = panel.getBoundingClientRect().height;

  resizeHandle.classList.add('dragging');
  document.addEventListener('touchmove', handleDrawerTouchMove, { passive: false });
  document.addEventListener('touchend', handleDrawerTouchEnd);
};

const handleDrawerTouchMove = (event) => {
  event.preventDefault();
  const touch = event.touches[0];
  const delta = touchStartY - touch.clientY;
  let newHeight = touchStartHeight + delta;

  // Clamp height
  const minH = 180;
  const maxH = window.innerHeight * 0.7;
  newHeight = Math.max(minH, Math.min(maxH, newHeight));

  panel.style.height = newHeight + 'px';
};

const handleDrawerTouchEnd = () => {
  resizeHandle.classList.remove('dragging');
  document.removeEventListener('touchmove', handleDrawerTouchMove);
  document.removeEventListener('touchend', handleDrawerTouchEnd);

  // If dragged below threshold, close the panel
  const currentHeight = panel.getBoundingClientRect().height;
  if (currentHeight < 120) {
    closeTreePanel();
    panel.style.height = '';
  }
};

// ─── 初始化 ───────────────────────────────────────────────────────────────────

/**
 * 初始化树状图面板的事件绑定
 * 在 app.js 中调用
 */
export const initTreePanel = () => {
  if (!panel || !toggleBtn || !closeBtn || !resizeHandle) {
    console.warn('[tree-panel] Missing DOM elements, skipping init');
    return;
  }

  // Toggle button
  toggleBtn.addEventListener('click', toggleTreePanel);

  // Close button
  closeBtn.addEventListener('click', closeTreePanel);

  // Desktop resize
  resizeHandle.addEventListener('mousedown', handleResizeMouseDown);

  // Mobile drawer drag
  resizeHandle.addEventListener('touchstart', handleDrawerTouchStart, { passive: true });

  // Close panel on Escape
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && _state.isOpen) {
      closeTreePanel();
    }
  });

  // On window resize, if switching from mobile to desktop (or vice versa),
  // reset inline styles that may conflict
  window.addEventListener('resize', () => {
    if (!isMobile()) {
      // Remove mobile-specific inline height
      panel.style.height = '';
      if (_state.isOpen) {
        panel.style.width = _state.panelWidth + 'px';
      }
    } else {
      // Remove desktop-specific inline width
      panel.style.width = '';
    }
  });
};

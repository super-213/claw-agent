import { branchApi } from './api.js';
import { els } from './dom.js';
import { hasAnyStream, isSessionBusy, state } from './state.js';

/** 当前显示的上下文菜单元素 */
let _contextMenu = null;
/** 正在创建分支的节点，防止重复点击 */
const _branchCreatePendingNodes = new Set();
let _branchStatusTimer = null;

const setStatus = (text, busy = false) => {
  els.statusText.textContent = text;
  els.statusBadge.classList.toggle('busy', busy);
  els.sendBtn.disabled = busy;
};

const restoreCurrentStatus = () => {
  if (state.currentSessionId && isSessionBusy(state.currentSessionId)) {
    setStatus('处理中…', true);
    return;
  }
  setStatus(hasAnyStream() ? '后台生成中…' : '就绪', false);
};

const setBranchStatus = (text, resetDelay = 1200) => {
  const busy = state.currentSessionId ? isSessionBusy(state.currentSessionId) : false;
  setStatus(text, busy);

  if (_branchStatusTimer) {
    clearTimeout(_branchStatusTimer);
  }
  if (resetDelay === null) {
    _branchStatusTimer = null;
    return;
  }
  _branchStatusTimer = setTimeout(() => {
    _branchStatusTimer = null;
    restoreCurrentStatus();
  }, resetDelay);
};

const resetBranchButtonFeedback = (button) => {
  if (!button) return;

  button.classList.remove('is-pending', 'is-success', 'is-error');
  button.disabled = false;
  button.removeAttribute('aria-busy');
  button.title = '从此处创建分支';
  button.setAttribute('aria-label', '从此处创建分支');

  const icon = button.querySelector('.action-icon');
  if (icon) icon.textContent = '⑂';
};

const setBranchButtonFeedback = (button, feedbackState) => {
  if (!button) return;

  button.classList.remove('is-pending', 'is-success', 'is-error');
  const icon = button.querySelector('.action-icon');

  if (feedbackState === 'pending') {
    button.classList.add('is-pending');
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    button.title = '正在创建分支';
    button.setAttribute('aria-label', '正在创建分支');
    if (icon) icon.textContent = '…';
    return;
  }

  if (feedbackState === 'success') {
    button.classList.add('is-success');
    button.disabled = true;
    button.removeAttribute('aria-busy');
    button.title = '分支已创建';
    button.setAttribute('aria-label', '分支已创建');
    if (icon) icon.textContent = '✓';
    setTimeout(() => resetBranchButtonFeedback(button), 1200);
    return;
  }

  if (feedbackState === 'error') {
    button.classList.add('is-error');
    button.disabled = false;
    button.removeAttribute('aria-busy');
    button.title = '创建分支失败，点击重试';
    button.setAttribute('aria-label', '创建分支失败，点击重试');
    if (icon) icon.textContent = '!';
    setTimeout(() => resetBranchButtonFeedback(button), 1600);
  }
};

const dismissContextMenu = () => {
  if (_contextMenu) {
    _contextMenu.remove();
    _contextMenu = null;
  }
};

const refreshBranchTree = async (sessionId) => {
  const { openTreePanel, getTreePanelBody } = await import('./tree-panel.js');
  openTreePanel();

  const { initSvg, setTreeData } = await import('./branch-tree.js');
  const panelBody = getTreePanelBody();
  if (!panelBody) return;

  initSvg(panelBody);
  const treeData = await branchApi.tree(sessionId);
  if (treeData && treeData.nodes) {
    setTreeData(treeData.nodes, treeData.active_node_id);
  }
};

const createBranchFromNode = async (nodeId, triggerEl = null) => {
  const sessionId = state.currentSessionId;
  if (!sessionId || !nodeId) return;
  if (_branchCreatePendingNodes.has(nodeId)) return;

  _branchCreatePendingNodes.add(nodeId);
  setBranchButtonFeedback(triggerEl, 'pending');
  setBranchStatus('正在创建分支…', null);

  try {
    const result = await branchApi.create(sessionId, nodeId);
    if (!result || !result.ok) {
      throw new Error(result?.message || '创建分支失败');
    }

    try {
      await refreshBranchTree(sessionId);
    } catch (treeError) {
      console.warn('[message-branch-actions] 更新树状图失败:', treeError);
    }

    setBranchButtonFeedback(triggerEl, 'success');
    setBranchStatus('分支已创建');
  } catch (error) {
    console.warn('[message-branch-actions] 创建分支失败:', error);
    setBranchButtonFeedback(triggerEl, 'error');
    setBranchStatus('创建分支失败', 1800);
    alert('创建分支失败: ' + (error.message || '未知错误'));
  } finally {
    _branchCreatePendingNodes.delete(nodeId);
  }
};

const showMessageContextMenu = (event, nodeId) => {
  dismissContextMenu();

  const menu = document.createElement('div');
  menu.className = 'message-context-menu';
  menu.innerHTML = `
    <button type="button" class="context-menu-item" data-action="create-branch">
      <span class="context-menu-icon">⑂</span>
      <span class="context-menu-label">从此处创建分支</span>
    </button>
  `;

  menu.style.position = 'fixed';
  menu.style.left = `${event.clientX}px`;
  menu.style.top = `${event.clientY}px`;
  menu.style.zIndex = '9999';

  menu.querySelector('[data-action="create-branch"]').addEventListener('click', (event) => {
    dismissContextMenu();
    createBranchFromNode(nodeId, event.currentTarget);
  });

  document.body.appendChild(menu);
  _contextMenu = menu;

  requestAnimationFrame(() => {
    const rect = menu.getBoundingClientRect();
    if (rect.right > window.innerWidth) {
      menu.style.left = `${window.innerWidth - rect.width - 8}px`;
    }
    if (rect.bottom > window.innerHeight) {
      menu.style.top = `${window.innerHeight - rect.height - 8}px`;
    }
  });
};

export const initMessageContextMenu = () => {
  document.addEventListener('click', dismissContextMenu);
  document.addEventListener('contextmenu', (event) => {
    if (!event.target.closest('.message-row[data-node-id][data-branchable="true"]')) {
      dismissContextMenu();
    }
  });

  els.messageList.addEventListener('contextmenu', (event) => {
    const row = event.target.closest('.message-row[data-node-id][data-branchable="true"]');
    if (!row) return;

    const nodeId = row.dataset.nodeId;
    if (!nodeId) return;

    event.preventDefault();
    showMessageContextMenu(event, nodeId);
  });
};

export const addBranchActionButton = (row, nodeId) => {
  if (!row || !nodeId) return;

  row.dataset.branchable = 'true';

  const actionsWrap = document.createElement('div');
  actionsWrap.className = 'message-actions';

  const branchBtn = document.createElement('button');
  branchBtn.type = 'button';
  branchBtn.className = 'message-action-btn branch-btn';
  branchBtn.title = '从此处创建分支';
  branchBtn.setAttribute('aria-label', '从此处创建分支');
  branchBtn.innerHTML = '<span class="action-icon">⑂</span>';

  branchBtn.addEventListener('click', (event) => {
    event.stopPropagation();
    createBranchFromNode(nodeId, branchBtn);
  });

  actionsWrap.appendChild(branchBtn);
  row.appendChild(actionsWrap);
};

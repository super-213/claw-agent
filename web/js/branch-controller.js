import { branchApi } from './api.js';
import {
  initSvg,
  onBranchDelete,
  onNodeSelect,
  setTreeData,
  updateActivePath,
} from './branch-tree.js';
import { applyHighlightsFromMessages, clearHighlights } from './context-highlight.js';
import { renderMessages } from './messages.js';
import { state } from './state.js';
import { getTreePanelBody } from './tree-panel.js';

let initialized = false;

export const applyContextHighlight = (messages, summarizedNodes) => {
  applyHighlightsFromMessages(messages, summarizedNodes);
};

const renderBranchTree = (treeData) => {
  const panelBody = getTreePanelBody();
  if (!panelBody) return;

  initSvg(panelBody);
  setTreeData(treeData?.nodes || [], treeData?.active_node_id || null);
};

const switchBranchForCurrentSession = async (targetNodeId) => {
  const sessionId = state.currentSessionId;
  if (!sessionId || !targetNodeId) return;

  clearHighlights();

  try {
    const result = await branchApi.switch(sessionId, targetNodeId);
    if (state.currentSessionId !== sessionId) return;
    if (!result || !result.ok) return;

    updateActivePath(result.active_node_id);
    renderMessages(result.messages || []);
    applyContextHighlight(result.messages || [], result.summarized_nodes);
  } catch (error) {
    console.error('[branch-controller] switchBranchForCurrentSession:', error);
  }
};

const deleteBranchForCurrentSession = async (nodeId) => {
  const sessionId = state.currentSessionId;
  if (!sessionId || !nodeId) return;

  try {
    const result = await branchApi.delete(sessionId, nodeId);
    if (state.currentSessionId !== sessionId) return;
    if (!result || !result.ok) return;

    const treeData = await branchApi.tree(sessionId);
    if (state.currentSessionId !== sessionId) return;
    renderBranchTree(treeData);
  } catch (error) {
    console.warn('[branch-controller] deleteBranchForCurrentSession:', error);
    const msg = error.data?.message || error.message || '未知错误';
    alert('删除分支失败: ' + msg);
  }
};

export const loadAndRenderTree = async (sessionId) => {
  try {
    const treeData = await branchApi.tree(sessionId);

    // 确保在树数据返回时用户仍在查看同一会话
    if (state.currentSessionId !== sessionId) return;
    renderBranchTree(treeData);
  } catch (error) {
    console.warn('[branch-controller] loadAndRenderTree:', error);
  }
};

export const initBranchController = () => {
  if (initialized) return;
  onNodeSelect((targetNodeId) => switchBranchForCurrentSession(targetNodeId));
  onBranchDelete((nodeId) => deleteBranchForCurrentSession(nodeId));
  initialized = true;
};

initBranchController();

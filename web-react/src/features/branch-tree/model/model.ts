import type { BranchApiNode } from '../../../api/types';

export interface TreeNode {
  nodeId: string;
  parentId: string | null;
  role: string;
  summary: string;
  isActive: boolean;
  childCount: number;
  x: number;
  y: number;
  children: TreeNode[];
  nodeIds: string[];
  userSummary?: string;
  toolSummary?: string;
  modelSummary?: string;
  toolCount?: number;
}

export const computeActivePath = (nodeMap: Map<string, TreeNode>, activeNodeId?: string | null): Set<string> => {
  const activeSet = new Set<string>();
  if (!activeNodeId || !nodeMap.has(activeNodeId)) return activeSet;

  let current: TreeNode | undefined = nodeMap.get(activeNodeId);
  while (current) {
    activeSet.add(current.nodeId);
    if (current.parentId == null) break;
    current = nodeMap.get(current.parentId);
  }

  return activeSet;
};

export const markActivePath = (nodeMap: Map<string, TreeNode>, activePathSet: Set<string>): void => {
  for (const node of nodeMap.values()) {
    node.isActive = activePathSet.has(node.nodeId);
  }
};

export const buildTree = (
  apiNodes: BranchApiNode[],
  activeNodeId?: string | null,
): { root: TreeNode | null; nodeMap: Map<string, TreeNode> } => {
  if (!apiNodes || apiNodes.length === 0) return { root: null, nodeMap: new Map() };

  const nodeMap = new Map<string, TreeNode>();
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
      nodeIds: [n.node_id],
    });
  }

  let root: TreeNode | null = null;
  for (const node of nodeMap.values()) {
    if (node.parentId == null) {
      root = node;
    } else {
      nodeMap.get(node.parentId)?.children.push(node);
    }
  }

  markActivePath(nodeMap, computeActivePath(nodeMap, activeNodeId));
  return { root, nodeMap };
};

const hasContent = (node?: TreeNode) => Boolean((node?.summary || '').trim());
const isToolCallNode = (node?: TreeNode) => node?.role === 'assistant' && (node.summary || '').trim().startsWith('[命令]');
const isToolResultNode = (node?: TreeNode) => node?.role === 'user' && (node.summary || '').trim().startsWith('[执行完成]');
const isPlaceholderNode = (node?: TreeNode) => node?.role === 'user' && !hasContent(node);
const isUserInputNode = (node?: TreeNode) => node?.role === 'user' && hasContent(node) && !isToolResultNode(node);

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
}: Partial<TreeNode> & Pick<TreeNode, 'nodeId' | 'parentId' | 'role' | 'summary' | 'isActive' | 'nodeIds'>): TreeNode => ({
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

export const markDisplayNodeActive = (displayNode: TreeNode, rawNodeMap: Map<string, TreeNode>): void => {
  displayNode.isActive = displayNode.nodeIds.some((nodeId) => rawNodeMap.get(nodeId)?.isActive);
};

const collectTurnBlock = (
  userNode: TreeNode,
  parentDisplayId: string | null,
  rawNodeMap: Map<string, TreeNode>,
): { displayNode: TreeNode; nextChildren: TreeNode[] } => {
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

export const buildDisplayTree = (
  rawRoot: TreeNode | null,
  rawNodeMap: Map<string, TreeNode>,
): { root: TreeNode | null; nodeMap: Map<string, TreeNode> } => {
  if (!rawRoot) return { root: null, nodeMap: new Map() };

  const displayMap = new Map<string, TreeNode>();
  const appendNode = (node: TreeNode) => {
    displayMap.set(node.nodeId, node);
    return node;
  };

  const buildMany = (rawNodes: TreeNode[], parentDisplayId: string | null): TreeNode[] =>
    rawNodes.flatMap((rawNode) => buildOne(rawNode, parentDisplayId));

  const buildOne = (rawNode: TreeNode, parentDisplayId: string | null): TreeNode[] => {
    if (isPlaceholderNode(rawNode)) return buildMany(rawNode.children, parentDisplayId);

    if (rawNode.role === 'system') {
      const displayNode = appendNode(
        createDisplayNode({
          nodeId: rawNode.nodeId,
          parentId: parentDisplayId,
          role: 'system',
          summary: rawNode.summary || '',
          isActive: rawNode.isActive,
          nodeIds: [rawNode.nodeId],
          modelSummary: rawNode.summary || '',
        }),
      );
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

    const displayNode = appendNode(
      createDisplayNode({
        nodeId: rawNode.nodeId,
        parentId: parentDisplayId,
        role: rawNode.role || 'message',
        summary: rawNode.summary || '',
        isActive: rawNode.isActive,
        nodeIds: [rawNode.nodeId],
        modelSummary: rawNode.summary || '',
      }),
    );
    displayNode.children = buildMany(rawNode.children, displayNode.nodeId);
    displayNode.childCount = displayNode.children.length;
    return [displayNode];
  };

  const roots = buildOne(rawRoot, null);
  return { root: roots[0] || null, nodeMap: displayMap };
};

import type { BranchTree } from '../../../api/types';
import { calculateLayout } from './layout';
import { buildDisplayTree, buildTree, type TreeNode } from './model';

export interface BuiltBranchTree {
  root: TreeNode | null;
  nodes: TreeNode[];
  edges: Array<{ from: TreeNode; to: TreeNode }>;
  width: number;
  height: number;
}

export const buildBranchTree = (tree: BranchTree | null | undefined): BuiltBranchTree => {
  const { root: rawRoot, nodeMap: rawNodeMap } = buildTree(tree?.nodes || [], tree?.active_node_id || null);
  const { root } = buildDisplayTree(rawRoot, rawNodeMap);
  const size = calculateLayout(root);
  const nodes: TreeNode[] = [];
  const edges: Array<{ from: TreeNode; to: TreeNode }> = [];

  const traverse = (node: TreeNode | null) => {
    if (!node) return;
    nodes.push(node);
    for (const child of node.children) {
      edges.push({ from: node, to: child });
      traverse(child);
    }
  };
  traverse(root);

  return { root, nodes, edges, ...size };
};

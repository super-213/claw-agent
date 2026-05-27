import { TREE_CONSTANTS } from './constants';
import type { TreeNode } from './model';

interface LayoutMeta {
  prelim: number;
  mod: number;
  thread: TreeNode | null;
  ancestor: TreeNode;
  shift?: number;
  change?: number;
}

export const calculateLayout = (root: TreeNode | null): { width: number; height: number } => {
  if (!root) return { width: TREE_CONSTANTS.minWidth, height: TREE_CONSTANTS.minHeight };

  const spacing = TREE_CONSTANTS.siblingSpacing;
  const meta = new Map<TreeNode, LayoutMeta>();

  const getMeta = (node: TreeNode): LayoutMeta => {
    if (!meta.has(node)) {
      meta.set(node, { prelim: 0, mod: 0, thread: null, ancestor: node });
    }
    return meta.get(node) as LayoutMeta;
  };

  const nextLeft = (node: TreeNode): TreeNode | null => (node.children.length > 0 ? node.children[0] : getMeta(node).thread);
  const nextRight = (node: TreeNode): TreeNode | null =>
    node.children.length > 0 ? node.children[node.children.length - 1] : getMeta(node).thread;

  const moveSubtree = (wl: TreeNode, wr: TreeNode, shift: number, parentNode: TreeNode) => {
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

  const ancestor = (vInnerLeft: TreeNode, _node: TreeNode, defaultAncestor: TreeNode, parentNode: TreeNode) => {
    const a = getMeta(vInnerLeft).ancestor;
    return parentNode.children.includes(a) ? a : defaultAncestor;
  };

  const executeShifts = (node: TreeNode) => {
    let shift = 0;
    let change = 0;
    for (let i = node.children.length - 1; i >= 0; i -= 1) {
      const child = node.children[i];
      const m = getMeta(child);
      m.prelim += shift;
      m.mod += shift;
      change += m.change || 0;
      shift += m.shift || 0;
      shift += change;
    }
  };

  const apportion = (node: TreeNode, defaultAncestor: TreeNode, parentNode: TreeNode): TreeNode => {
    const nodeIndex = parentNode.children.indexOf(node);
    const leftSibling = nodeIndex > 0 ? parentNode.children[nodeIndex - 1] : null;
    if (!leftSibling) return defaultAncestor;

    let vInnerRight: TreeNode = node;
    let vOuterRight: TreeNode = node;
    let vInnerLeft: TreeNode = leftSibling;
    let vOuterLeft: TreeNode = parentNode.children[0];
    let nextInnerLeft = nextRight(vInnerLeft);
    let nextInnerRight = nextLeft(vInnerRight);

    let sInnerRight = getMeta(vInnerRight).mod;
    let sOuterRight = getMeta(vOuterRight).mod;
    let sInnerLeft = getMeta(vInnerLeft).mod;
    let sOuterLeft = getMeta(vOuterLeft).mod;

    while (nextInnerLeft && nextInnerRight) {
      vInnerLeft = nextInnerLeft;
      vInnerRight = nextInnerRight;
      const nextOuterLeft = nextLeft(vOuterLeft);
      const nextOuterRight = nextRight(vOuterRight);
      if (nextOuterLeft) vOuterLeft = nextOuterLeft;
      if (nextOuterRight) vOuterRight = nextOuterRight;

      getMeta(vOuterRight).ancestor = node;
      const shift = getMeta(vInnerLeft).prelim + sInnerLeft - (getMeta(vInnerRight).prelim + sInnerRight) + spacing;
      if (shift > 0) {
        moveSubtree(ancestor(vInnerLeft, node, defaultAncestor, parentNode), node, shift, parentNode);
        sInnerRight += shift;
        sOuterRight += shift;
      }

      sInnerLeft += getMeta(vInnerLeft).mod;
      sInnerRight += getMeta(vInnerRight).mod;
      sOuterLeft += getMeta(vOuterLeft).mod;
      sOuterRight += getMeta(vOuterRight).mod;
      nextInnerLeft = nextRight(vInnerLeft);
      nextInnerRight = nextLeft(vInnerRight);
    }

    if (nextInnerLeft && !nextRight(vOuterRight)) {
      getMeta(vOuterRight).thread = nextInnerLeft;
      getMeta(vOuterRight).mod += sInnerLeft - sOuterRight;
    }

    if (nextInnerRight && !nextLeft(vOuterLeft)) {
      getMeta(vOuterLeft).thread = nextInnerRight;
      getMeta(vOuterLeft).mod += sInnerRight - sOuterLeft;
      return node;
    }

    return defaultAncestor;
  };

  const firstWalk = (node: TreeNode, leftSibling: TreeNode | null) => {
    const m = getMeta(node);
    if (node.children.length === 0) {
      m.prelim = leftSibling ? getMeta(leftSibling).prelim + spacing : 0;
      return;
    }

    let defaultAncestor = node.children[0];
    for (let i = 0; i < node.children.length; i += 1) {
      const child = node.children[i];
      firstWalk(child, i > 0 ? node.children[i - 1] : null);
      defaultAncestor = apportion(child, defaultAncestor, node);
    }

    executeShifts(node);
    const firstChild = node.children[0];
    const lastChild = node.children[node.children.length - 1];
    const midpoint = (getMeta(firstChild).prelim + getMeta(lastChild).prelim) / 2;
    if (leftSibling) {
      m.prelim = getMeta(leftSibling).prelim + spacing;
      m.mod = m.prelim - midpoint;
    } else {
      m.prelim = midpoint;
    }
  };

  const secondWalk = (node: TreeNode, modSum: number, depth: number) => {
    const m = getMeta(node);
    node.x = m.prelim + modSum + TREE_CONSTANTS.padding;
    node.y = TREE_CONSTANTS.padding + depth * TREE_CONSTANTS.levelSpacing;
    for (const child of node.children) secondWalk(child, modSum + m.mod, depth + 1);
  };

  firstWalk(root, null);
  secondWalk(root, 0, 0);

  let minX = Infinity;
  let maxX = -Infinity;
  let maxDepth = 0;
  const collectBounds = (node: TreeNode, depth: number) => {
    minX = Math.min(minX, node.x);
    maxX = Math.max(maxX, node.x);
    maxDepth = Math.max(maxDepth, depth);
    for (const child of node.children) collectBounds(child, depth + 1);
  };
  collectBounds(root, 0);

  if (minX < TREE_CONSTANTS.padding) {
    const offsetX = TREE_CONSTANTS.padding - minX;
    const shiftAll = (node: TreeNode) => {
      node.x += offsetX;
      for (const child of node.children) shiftAll(child);
    };
    shiftAll(root);
    maxX += offsetX;
  }

  return {
    width: Math.max(maxX + TREE_CONSTANTS.nodeWidth + TREE_CONSTANTS.padding, TREE_CONSTANTS.minWidth),
    height: Math.max(
      maxDepth * TREE_CONSTANTS.levelSpacing + TREE_CONSTANTS.nodeHeight + TREE_CONSTANTS.padding * 2,
      TREE_CONSTANTS.minHeight,
    ),
  };
};

import { TREE_CONSTANTS } from './constants.js';

/**
 * Reingold-Tilford 树布局算法。
 * @param {import('./model.js').TreeNode|null} root
 * @returns {{ width: number, height: number }}
 */
export const calculateLayout = (root) => {
  if (!root) {
    return { width: TREE_CONSTANTS.minWidth, height: TREE_CONSTANTS.minHeight };
  }

  const spacing = TREE_CONSTANTS.siblingSpacing;
  const meta = new Map();

  const getMeta = (node) => {
    if (!meta.has(node)) {
      meta.set(node, { prelim: 0, mod: 0, thread: null, ancestor: node });
    }
    return meta.get(node);
  };

  const firstWalk = (node, leftSibling) => {
    const m = getMeta(node);

    if (node.children.length === 0) {
      if (leftSibling) {
        m.prelim = getMeta(leftSibling).prelim + spacing;
      } else {
        m.prelim = 0;
      }
    } else {
      let defaultAncestor = node.children[0];

      for (let i = 0; i < node.children.length; i++) {
        const child = node.children[i];
        const childLeftSibling = i > 0 ? node.children[i - 1] : null;
        firstWalk(child, childLeftSibling);
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
    }
  };

  const apportion = (node, defaultAncestor, parentNode) => {
    const nodeIndex = parentNode.children.indexOf(node);
    const leftSibling = nodeIndex > 0 ? parentNode.children[nodeIndex - 1] : null;

    if (!leftSibling) return defaultAncestor;

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

  const nextLeft = (node) => {
    if (node.children.length > 0) return node.children[0];
    return getMeta(node).thread;
  };

  const nextRight = (node) => {
    if (node.children.length > 0) return node.children[node.children.length - 1];
    return getMeta(node).thread;
  };

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

  const ancestor = (vInnerLeft, node, defaultAncestor, parentNode) => {
    const a = getMeta(vInnerLeft).ancestor;
    if (parentNode.children.includes(a)) {
      return a;
    }
    return defaultAncestor;
  };

  const secondWalk = (node, modSum, depth) => {
    const m = getMeta(node);
    node.x = m.prelim + modSum + TREE_CONSTANTS.padding;
    node.y = TREE_CONSTANTS.padding + depth * TREE_CONSTANTS.levelSpacing;

    for (const child of node.children) {
      secondWalk(child, modSum + m.mod, depth + 1);
    }
  };

  firstWalk(root, null);
  secondWalk(root, 0, 0);

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

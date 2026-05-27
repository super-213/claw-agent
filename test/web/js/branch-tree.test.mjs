/**
 * 测试 Reingold-Tilford 树布局算法 + 活跃路径高亮
 * 运行: node test/web/js/branch-tree.test.mjs
 */

import { calculateLayout, buildTree, buildDisplayTree, computeActivePath, markActivePath, TREE_CONSTANTS } from '../../../web/js/branch-tree.js';

let passed = 0;
let failed = 0;

function assert(condition, message) {
  if (condition) {
    passed++;
  } else {
    failed++;
    console.error(`  FAIL: ${message}`);
  }
}

function makeNode(id, parentId, children = []) {
  return {
    nodeId: id,
    parentId,
    role: 'user',
    summary: `Node ${id}`,
    isActive: false,
    childCount: children.length,
    x: 0,
    y: 0,
    children,
  };
}

// ─── Test 1: null root ───
console.log('Test 1: null root returns min dimensions');
{
  const result = calculateLayout(null);
  assert(result.width === TREE_CONSTANTS.minWidth, 'width should be minWidth');
  assert(result.height === TREE_CONSTANTS.minHeight, 'height should be minHeight');
}

// ─── Test 2: single node ───
console.log('Test 2: single node');
{
  const root = makeNode('root', null);
  const result = calculateLayout(root);
  assert(root.x === TREE_CONSTANTS.padding, `single node x should be padding (${TREE_CONSTANTS.padding}), got ${root.x}`);
  assert(root.y === TREE_CONSTANTS.padding, `single node y should be padding (${TREE_CONSTANTS.padding}), got ${root.y}`);
  assert(result.width >= TREE_CONSTANTS.minWidth, 'width >= minWidth');
  assert(result.height >= TREE_CONSTANTS.minHeight, 'height >= minHeight');
}

// ─── Test 3: linear chain (no branches) ───
console.log('Test 3: linear chain');
{
  const n3 = makeNode('n3', 'n2');
  const n2 = makeNode('n2', 'n1', [n3]);
  const n1 = makeNode('n1', null, [n2]);
  const result = calculateLayout(n1);

  // All nodes should have the same x (single path)
  assert(n1.x === n2.x, `linear chain: n1.x (${n1.x}) === n2.x (${n2.x})`);
  assert(n2.x === n3.x, `linear chain: n2.x (${n2.x}) === n3.x (${n3.x})`);

  // Y should increase by levelSpacing
  assert(n2.y - n1.y === TREE_CONSTANTS.levelSpacing, `y spacing: ${n2.y - n1.y} === ${TREE_CONSTANTS.levelSpacing}`);
  assert(n3.y - n2.y === TREE_CONSTANTS.levelSpacing, `y spacing: ${n3.y - n2.y} === ${TREE_CONSTANTS.levelSpacing}`);
}

// ─── Test 4: simple binary tree ───
console.log('Test 4: simple binary tree (root with 2 children)');
{
  const left = makeNode('left', 'root');
  const right = makeNode('right', 'root');
  const root = makeNode('root', null, [left, right]);
  calculateLayout(root);

  // Parent should be centered over children
  const midpoint = (left.x + right.x) / 2;
  assert(Math.abs(root.x - midpoint) < 0.001, `root centered: root.x (${root.x}) === midpoint (${midpoint})`);

  // Children should be separated by siblingSpacing
  assert(Math.abs(right.x - left.x - TREE_CONSTANTS.siblingSpacing) < 0.001,
    `sibling spacing: ${right.x - left.x} === ${TREE_CONSTANTS.siblingSpacing}`);

  // Y coordinates
  assert(root.y === TREE_CONSTANTS.padding, `root.y === padding`);
  assert(left.y === TREE_CONSTANTS.padding + TREE_CONSTANTS.levelSpacing, `left.y at level 1`);
  assert(right.y === left.y, `right.y === left.y`);
}

// ─── Test 5: no overlapping subtrees ───
console.log('Test 5: subtrees do not overlap');
{
  // Build a tree where left subtree is deep and right subtree is wide
  //       root
  //      /    \
  //     A      B
  //    / \    / \
  //   C   D  E   F
  //  /
  // G
  const G = makeNode('G', 'C');
  const C = makeNode('C', 'A', [G]);
  const D = makeNode('D', 'A');
  const E = makeNode('E', 'B');
  const F = makeNode('F', 'B');
  const A = makeNode('A', 'root', [C, D]);
  const B = makeNode('B', 'root', [E, F]);
  const root = makeNode('root', null, [A, B]);
  calculateLayout(root);

  // Check no nodes at the same level overlap (x distance >= siblingSpacing)
  // Level 1: A, B
  assert(B.x - A.x >= TREE_CONSTANTS.siblingSpacing - 0.001,
    `A and B separated: ${B.x - A.x} >= ${TREE_CONSTANTS.siblingSpacing}`);

  // Level 2: C, D, E, F
  const level2 = [C, D, E, F].sort((a, b) => a.x - b.x);
  for (let i = 0; i < level2.length - 1; i++) {
    const gap = level2[i + 1].x - level2[i].x;
    assert(gap >= TREE_CONSTANTS.siblingSpacing - 0.001,
      `level 2 nodes ${level2[i].nodeId} and ${level2[i+1].nodeId} separated: ${gap} >= ${TREE_CONSTANTS.siblingSpacing}`);
  }
}

// ─── Test 6: wide tree with many siblings ───
console.log('Test 6: wide tree with many siblings');
{
  const children = [];
  for (let i = 0; i < 10; i++) {
    children.push(makeNode(`child${i}`, 'root'));
  }
  const root = makeNode('root', null, children);
  calculateLayout(root);

  // All children should be evenly spaced
  for (let i = 0; i < children.length - 1; i++) {
    const gap = children[i + 1].x - children[i].x;
    assert(Math.abs(gap - TREE_CONSTANTS.siblingSpacing) < 0.001,
      `children ${i} and ${i+1} spacing: ${gap} === ${TREE_CONSTANTS.siblingSpacing}`);
  }

  // Root should be centered
  const mid = (children[0].x + children[children.length - 1].x) / 2;
  assert(Math.abs(root.x - mid) < 0.001, `root centered over ${children.length} children`);
}

// ─── Test 7: all x coordinates >= padding ───
console.log('Test 7: all coordinates >= padding after normalization');
{
  // Asymmetric tree that might produce negative coordinates before normalization
  const c1 = makeNode('c1', 'a');
  const c2 = makeNode('c2', 'a');
  const c3 = makeNode('c3', 'a');
  const a = makeNode('a', 'root', [c1, c2, c3]);
  const b = makeNode('b', 'root');
  const root = makeNode('root', null, [a, b]);
  calculateLayout(root);

  const allNodes = [root, a, b, c1, c2, c3];
  for (const node of allNodes) {
    assert(node.x >= TREE_CONSTANTS.padding, `${node.nodeId}.x (${node.x}) >= padding (${TREE_CONSTANTS.padding})`);
    assert(node.y >= TREE_CONSTANTS.padding, `${node.nodeId}.y (${node.y}) >= padding (${TREE_CONSTANTS.padding})`);
  }
}

// ─── Test 8: returned dimensions contain all nodes ───
console.log('Test 8: returned dimensions contain all nodes');
{
  const children = [];
  for (let i = 0; i < 5; i++) {
    children.push(makeNode(`child${i}`, 'root'));
  }
  const root = makeNode('root', null, children);
  const { width, height } = calculateLayout(root);

  const allNodes = [root, ...children];
  for (const node of allNodes) {
    assert(node.x < width, `${node.nodeId}.x (${node.x}) < width (${width})`);
    assert(node.y < height, `${node.nodeId}.y (${node.y}) < height (${height})`);
  }
}

// ─── Test 9: computeActivePath - basic linear path ───
console.log('Test 9: computeActivePath - linear path from root to leaf');
{
  const apiNodes = [
    { node_id: 'root', parent_id: null, role: 'system', summary: 'sys' },
    { node_id: 'n1', parent_id: 'root', role: 'user', summary: 'u1' },
    { node_id: 'n2', parent_id: 'n1', role: 'assistant', summary: 'a1' },
    { node_id: 'n3', parent_id: 'n2', role: 'user', summary: 'u2' },
  ];
  const { nodeMap } = buildTree(apiNodes, 'n3');
  const activePath = computeActivePath(nodeMap, 'n3');

  assert(activePath.size === 4, `active path should have 4 nodes, got ${activePath.size}`);
  assert(activePath.has('root'), 'root should be on active path');
  assert(activePath.has('n1'), 'n1 should be on active path');
  assert(activePath.has('n2'), 'n2 should be on active path');
  assert(activePath.has('n3'), 'n3 should be on active path');
}

// ─── Test 10: computeActivePath - branching tree ───
console.log('Test 10: computeActivePath - only active branch nodes are marked');
{
  // Tree:  root -> n1 -> n2 (active leaf)
  //                   -> n3 (inactive branch)
  const apiNodes = [
    { node_id: 'root', parent_id: null, role: 'system', summary: 'sys' },
    { node_id: 'n1', parent_id: 'root', role: 'user', summary: 'u1' },
    { node_id: 'n2', parent_id: 'n1', role: 'assistant', summary: 'a1' },
    { node_id: 'n3', parent_id: 'n1', role: 'user', summary: 'u2 branch' },
  ];
  const { nodeMap } = buildTree(apiNodes, 'n2');
  const activePath = computeActivePath(nodeMap, 'n2');

  assert(activePath.size === 3, `active path should have 3 nodes, got ${activePath.size}`);
  assert(activePath.has('root'), 'root should be on active path');
  assert(activePath.has('n1'), 'n1 should be on active path');
  assert(activePath.has('n2'), 'n2 should be on active path');
  assert(!activePath.has('n3'), 'n3 should NOT be on active path');
}

// ─── Test 11: computeActivePath - null/invalid activeNodeId ───
console.log('Test 11: computeActivePath - null or invalid activeNodeId returns empty set');
{
  const apiNodes = [
    { node_id: 'root', parent_id: null, role: 'system', summary: 'sys' },
    { node_id: 'n1', parent_id: 'root', role: 'user', summary: 'u1' },
  ];
  const { nodeMap } = buildTree(apiNodes, null);

  const emptyPath = computeActivePath(nodeMap, null);
  assert(emptyPath.size === 0, 'null activeNodeId should return empty set');

  const invalidPath = computeActivePath(nodeMap, 'nonexistent');
  assert(invalidPath.size === 0, 'invalid activeNodeId should return empty set');
}

// ─── Test 12: buildTree marks isActive correctly ───
console.log('Test 12: buildTree marks isActive on nodes based on activeNodeId');
{
  // Tree:  root -> n1 -> n2 (active leaf)
  //                   -> n3 -> n4
  const apiNodes = [
    { node_id: 'root', parent_id: null, role: 'system', summary: 'sys' },
    { node_id: 'n1', parent_id: 'root', role: 'user', summary: 'u1' },
    { node_id: 'n2', parent_id: 'n1', role: 'assistant', summary: 'a1' },
    { node_id: 'n3', parent_id: 'n1', role: 'user', summary: 'u2' },
    { node_id: 'n4', parent_id: 'n3', role: 'assistant', summary: 'a2' },
  ];
  const { nodeMap } = buildTree(apiNodes, 'n2');

  assert(nodeMap.get('root').isActive === true, 'root should be active');
  assert(nodeMap.get('n1').isActive === true, 'n1 should be active');
  assert(nodeMap.get('n2').isActive === true, 'n2 should be active');
  assert(nodeMap.get('n3').isActive === false, 'n3 should NOT be active');
  assert(nodeMap.get('n4').isActive === false, 'n4 should NOT be active');
}

// ─── Test 13: markActivePath updates all nodes ───
console.log('Test 13: markActivePath correctly updates isActive for all nodes');
{
  const apiNodes = [
    { node_id: 'root', parent_id: null, role: 'system', summary: 'sys' },
    { node_id: 'n1', parent_id: 'root', role: 'user', summary: 'u1' },
    { node_id: 'n2', parent_id: 'n1', role: 'assistant', summary: 'a1' },
    { node_id: 'n3', parent_id: 'n1', role: 'user', summary: 'u2' },
  ];
  // Initially active path is to n2
  const { nodeMap } = buildTree(apiNodes, 'n2');

  assert(nodeMap.get('n2').isActive === true, 'n2 initially active');
  assert(nodeMap.get('n3').isActive === false, 'n3 initially inactive');

  // Switch active path to n3
  const newActivePath = computeActivePath(nodeMap, 'n3');
  markActivePath(nodeMap, newActivePath);

  assert(nodeMap.get('root').isActive === true, 'root still active after switch');
  assert(nodeMap.get('n1').isActive === true, 'n1 still active after switch');
  assert(nodeMap.get('n2').isActive === false, 'n2 should be inactive after switch');
  assert(nodeMap.get('n3').isActive === true, 'n3 should be active after switch');
}

// ─── Test 14: computeActivePath - single root node ───
console.log('Test 14: computeActivePath - single root node as active');
{
  const apiNodes = [
    { node_id: 'root', parent_id: null, role: 'system', summary: 'sys' },
  ];
  const { nodeMap } = buildTree(apiNodes, 'root');
  const activePath = computeActivePath(nodeMap, 'root');

  assert(activePath.size === 1, `single root active path should have 1 node, got ${activePath.size}`);
  assert(activePath.has('root'), 'root should be on active path');
  assert(nodeMap.get('root').isActive === true, 'root node should be marked active');
}

// ─── Test 15: buildTree ignores API is_active field ───
console.log('Test 15: buildTree computes active path independently of API is_active field');
{
  // API says n3 is active, but activeNodeId points to n2
  const apiNodes = [
    { node_id: 'root', parent_id: null, role: 'system', summary: 'sys', is_active: false },
    { node_id: 'n1', parent_id: 'root', role: 'user', summary: 'u1', is_active: false },
    { node_id: 'n2', parent_id: 'n1', role: 'assistant', summary: 'a1', is_active: false },
    { node_id: 'n3', parent_id: 'n1', role: 'user', summary: 'u2', is_active: true },
  ];
  const { nodeMap } = buildTree(apiNodes, 'n2');

  // Should follow activeNodeId, not API's is_active
  assert(nodeMap.get('root').isActive === true, 'root should be active (computed from activeNodeId)');
  assert(nodeMap.get('n1').isActive === true, 'n1 should be active (computed from activeNodeId)');
  assert(nodeMap.get('n2').isActive === true, 'n2 should be active (computed from activeNodeId)');
  assert(nodeMap.get('n3').isActive === false, 'n3 should NOT be active (despite API is_active=true)');
}

// ─── Test 16: buildDisplayTree groups one conversation flow into a single block ───
console.log('Test 16: buildDisplayTree groups user/tool/model flow into one block');
{
  const apiNodes = [
    { node_id: 'root', parent_id: null, role: 'system', summary: 'sys' },
    { node_id: 'u1', parent_id: 'root', role: 'user', summary: 'list files' },
    { node_id: 'cmd1', parent_id: 'u1', role: 'assistant', summary: '[命令] ls' },
    { node_id: 'res1', parent_id: 'cmd1', role: 'user', summary: '[执行完成] ok' },
    { node_id: 'a1', parent_id: 'res1', role: 'assistant', summary: '[完成] done' },
  ];
  const { root, nodeMap } = buildTree(apiNodes, 'a1');
  const display = buildDisplayTree(root, nodeMap);
  const turn = display.root.children[0];

  assert(display.root.role === 'system', 'system remains its own display block');
  assert(display.root.children.length === 1, 'system has one turn child');
  assert(turn.role === 'turn', 'conversation flow is a turn block');
  assert(turn.nodeId === 'a1', 'turn target node is the final model output');
  assert(turn.nodeIds.join(',') === 'u1,cmd1,res1,a1', 'turn contains user, tool call, tool result, and model nodes');
  assert(turn.userSummary === 'list files', 'turn keeps user input summary');
  assert(turn.toolCount === 1, 'turn counts one tool call');
  assert(turn.modelSummary === '[完成] done', 'turn keeps final model summary');
}

// ─── Test 17: buildDisplayTree keeps sibling branches as turn blocks ───
console.log('Test 17: buildDisplayTree keeps sibling branches as separate turn blocks');
{
  const apiNodes = [
    { node_id: 'root', parent_id: null, role: 'system', summary: 'sys' },
    { node_id: 'u1', parent_id: 'root', role: 'user', summary: '2+3' },
    { node_id: 'a1', parent_id: 'u1', role: 'assistant', summary: '[完成] 5' },
    { node_id: 'u2', parent_id: 'a1', role: 'user', summary: '再加5' },
    { node_id: 'a2', parent_id: 'u2', role: 'assistant', summary: '[完成] 10' },
    { node_id: 'blank', parent_id: 'a1', role: 'user', summary: '' },
    { node_id: 'u3', parent_id: 'blank', role: 'user', summary: '再加7' },
    { node_id: 'a3', parent_id: 'u3', role: 'assistant', summary: '[完成] 12' },
  ];
  const { root, nodeMap } = buildTree(apiNodes, 'a2');
  const display = buildDisplayTree(root, nodeMap);
  const firstTurn = display.root.children[0];
  const branchIds = firstTurn.children.map((node) => node.nodeId).sort();

  assert(firstTurn.nodeId === 'a1', 'first turn ends at first model output');
  assert(firstTurn.children.length === 2, 'first turn has two branch turn children');
  assert(branchIds.join(',') === 'a2,a3', `branch turn ids should be a2,a3, got ${branchIds.join(',')}`);
  assert(display.nodeMap.get('a2').isActive === true, 'active branch turn is highlighted');
  assert(display.nodeMap.get('a3').isActive === false, 'inactive branch turn is subdued');
}

// ─── Summary ───
console.log(`\n${'─'.repeat(40)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
} else {
  console.log('All tests passed!');
}

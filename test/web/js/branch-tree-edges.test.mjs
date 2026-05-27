/**
 * 测试连线渲染（贝塞尔曲线）
 * 运行: node test/web/js/branch-tree-edges.test.mjs
 */

import {
  computeEdgePath,
  getEdgeColor,
  createEdgeElement,
  renderEdges,
  clearEdges,
  TREE_CONSTANTS,
  EDGE_STYLES,
  calculateLayout,
} from '../../../web/js/branch-tree.js';

// ─── Minimal DOM shim for SVG element creation ───
class MockElement {
  constructor(tag) {
    this.tagName = tag;
    this.attributes = {};
    this.children = [];
    this.style = {};
    this.textContent = '';
    this.parentNode = null;
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return this.attributes[name] || null; }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  removeChild(child) {
    const idx = this.children.indexOf(child);
    if (idx >= 0) { this.children.splice(idx, 1); child.parentNode = null; }
    return child;
  }
  querySelector(selector) {
    // Simple class selector support
    const className = selector.startsWith('.') ? selector.slice(1) : selector;
    const search = (el) => {
      if (el.attributes && el.attributes['class'] && el.attributes['class'].includes(className)) return el;
      for (const child of (el.children || [])) {
        const found = search(child);
        if (found) return found;
      }
      return null;
    };
    return search(this);
  }
}

// Shim global document for SVG element creation
globalThis.document = {
  createElementNS: (ns, tag) => new MockElement(tag),
};

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

function makeNode(id, parentId, opts = {}) {
  return {
    nodeId: id,
    parentId,
    role: opts.role || 'user',
    summary: `Node ${id}`,
    isActive: opts.isActive || false,
    childCount: 0,
    x: opts.x || 0,
    y: opts.y || 0,
    children: opts.children || [],
  };
}

// ─── Test 1: computeEdgePath generates valid SVG path ───
console.log('Test 1: computeEdgePath generates valid cubic Bézier path');
{
  const parent = makeNode('p', null, { x: 100, y: 30 });
  const child = makeNode('c', 'p', { x: 150, y: 100 });

  const path = computeEdgePath(parent, child);

  // Should start with M (moveto) and contain C (cubic Bézier)
  assert(path.startsWith('M '), `path starts with M: "${path}"`);
  assert(path.includes(' C '), `path contains C command: "${path}"`);

  // Parse coordinates
  const expectedStartX = parent.x + TREE_CONSTANTS.nodeWidth / 2;
  const expectedStartY = parent.y + TREE_CONSTANTS.nodeHeight;
  const expectedEndX = child.x + TREE_CONSTANTS.nodeWidth / 2;
  const expectedEndY = child.y;

  assert(path.includes(`M ${expectedStartX} ${expectedStartY}`),
    `path starts at parent bottom (${expectedStartX}, ${expectedStartY})`);
  assert(path.endsWith(`${expectedEndX} ${expectedEndY}`),
    `path ends at child top (${expectedEndX}, ${expectedEndY})`);
}

// ─── Test 2: computeEdgePath control points at vertical midpoint ───
console.log('Test 2: computeEdgePath control points at vertical midpoint');
{
  const parent = makeNode('p', null, { x: 50, y: 30 });
  const child = makeNode('c', 'p', { x: 120, y: 100 });

  const path = computeEdgePath(parent, child);
  const x1 = parent.x + TREE_CONSTANTS.nodeWidth / 2;
  const x2 = child.x + TREE_CONSTANTS.nodeWidth / 2;
  const y1 = parent.y + TREE_CONSTANTS.nodeHeight;
  const y2 = child.y;
  const midY = (y1 + y2) / 2;

  // Control points should use midY
  // Path format: M x1 y1 C cp1x cp1y, cp2x cp2y, x2 y2
  assert(path.includes(`${x1} ${midY}`), `first control point at (parent center, midY)`);
  assert(path.includes(`${x2} ${midY}`), `second control point at (child center, midY)`);
}

// ─── Test 3: computeEdgePath for vertically aligned nodes ───
console.log('Test 3: computeEdgePath for vertically aligned nodes (same x)');
{
  const parent = makeNode('p', null, { x: 80, y: 30 });
  const child = makeNode('c', 'p', { x: 80, y: 100 });

  const path = computeEdgePath(parent, child);
  // When x is the same, the curve should be a straight vertical line
  // (control points have same x as start/end)
  const x = parent.x + TREE_CONSTANTS.nodeWidth / 2;
  const y1 = parent.y + TREE_CONSTANTS.nodeHeight;
  const y2 = child.y;
  const midY = (y1 + y2) / 2;

  assert(path === `M ${x} ${y1} C ${x} ${midY}, ${x} ${midY}, ${x} ${y2}`,
    `straight vertical path when x aligned: "${path}"`);
}

// ─── Test 4: getEdgeColor returns active color when both nodes active ───
console.log('Test 4: getEdgeColor returns correct colors');
{
  const activeParent = makeNode('p', null, { isActive: true });
  const activeChild = makeNode('c', 'p', { isActive: true });
  const inactiveChild = makeNode('c2', 'p', { isActive: false });
  const inactiveParent = makeNode('p2', null, { isActive: false });

  assert(getEdgeColor(activeParent, activeChild) === EDGE_STYLES.activeColor,
    'both active → activeColor');
  assert(getEdgeColor(activeParent, inactiveChild) === EDGE_STYLES.color,
    'parent active, child inactive → default color');
  assert(getEdgeColor(inactiveParent, activeChild) === EDGE_STYLES.color,
    'parent inactive, child active → default color');
  assert(getEdgeColor(inactiveParent, inactiveChild) === EDGE_STYLES.color,
    'both inactive → default color');
}

// ─── Test 5: createEdgeElement creates proper SVG path element ───
console.log('Test 5: createEdgeElement creates SVG path with correct attributes');
{
  const parent = makeNode('p1', null, { x: 50, y: 30, isActive: true });
  const child = makeNode('c1', 'p1', { x: 80, y: 100, isActive: true });

  const el = createEdgeElement(parent, child);

  assert(el.tagName === 'path', 'element is a path');
  assert(el.attributes['fill'] === 'none', 'fill is none');
  assert(el.attributes['stroke'] === EDGE_STYLES.activeColor, 'stroke is activeColor for active edge');
  assert(el.attributes['stroke-width'] === String(EDGE_STYLES.width + 1), 'active stroke-width is emphasized');
  assert(el.attributes['class'].includes('branch-tree-edge'), 'has edge class');
  assert(el.attributes['class'].includes('active'), 'has active class');
  assert(el.attributes['data-from'] === 'p1', 'data-from is parent nodeId');
  assert(el.attributes['data-to'] === 'c1', 'data-to is child nodeId');
  assert(el.attributes['d'].startsWith('M '), 'd attribute is a valid path');
}

// ─── Test 6: createEdgeElement for inactive edge ───
console.log('Test 6: createEdgeElement for inactive edge');
{
  const parent = makeNode('p1', null, { x: 50, y: 30, isActive: false });
  const child = makeNode('c1', 'p1', { x: 80, y: 100, isActive: false });

  const el = createEdgeElement(parent, child);

  assert(el.attributes['stroke'] === EDGE_STYLES.color, 'stroke is default color for inactive edge');
  assert(!el.attributes['class'].includes('active'), 'no active class for inactive edge');
}

// ─── Test 7: renderEdges creates edges layer with correct number of edges ───
console.log('Test 7: renderEdges creates edges for all parent-child pairs');
{
  // Build a small tree: root -> [A, B], A -> [C]
  const C = makeNode('C', 'A', { x: 30, y: 170 });
  const A = makeNode('A', 'root', { x: 30, y: 100, children: [C] });
  const B = makeNode('B', 'root', { x: 80, y: 100 });
  const root = makeNode('root', null, { x: 55, y: 30, children: [A, B] });

  const mockGroup = new MockElement('g');
  const edgesLayer = renderEdges(root, mockGroup);

  assert(edgesLayer !== null, 'renderEdges returns edges layer');
  assert(edgesLayer.attributes['class'] === 'branch-tree-edges-layer', 'layer has correct class');
  // Should have 3 edges: root->A, root->B, A->C
  assert(edgesLayer.children.length === 3, `3 edges created, got ${edgesLayer.children.length}`);

  // Verify edge data attributes
  const edges = edgesLayer.children;
  const edgePairs = edges.map(e => `${e.attributes['data-from']}->${e.attributes['data-to']}`);
  assert(edgePairs.includes('root->A'), 'edge root->A exists');
  assert(edgePairs.includes('root->B'), 'edge root->B exists');
  assert(edgePairs.includes('A->C'), 'edge A->C exists');
}

// ─── Test 8: renderEdges returns null for null root ───
console.log('Test 8: renderEdges returns null for null root');
{
  const mockGroup = new MockElement('g');
  const result = renderEdges(null, mockGroup);
  assert(result === null, 'renderEdges(null) returns null');
}

// ─── Test 9: renderEdges returns null for null group ───
console.log('Test 9: renderEdges returns null for null group');
{
  const root = makeNode('root', null, { x: 50, y: 30 });
  const result = renderEdges(root, null);
  assert(result === null, 'renderEdges with null group returns null');
}

// ─── Test 10: clearEdges removes edges layer ───
console.log('Test 10: clearEdges removes edges layer');
{
  const root = makeNode('root', null, { x: 50, y: 30, children: [
    makeNode('c', 'root', { x: 50, y: 100 })
  ]});

  const mockGroup = new MockElement('g');
  renderEdges(root, mockGroup);

  assert(mockGroup.querySelector('.branch-tree-edges-layer') !== null, 'edges layer exists before clear');
  clearEdges(mockGroup);
  assert(mockGroup.querySelector('.branch-tree-edges-layer') === null, 'edges layer removed after clear');
}

// ─── Test 11: renderEdges for single node (no edges) ───
console.log('Test 11: renderEdges for single node produces empty layer');
{
  const root = makeNode('root', null, { x: 50, y: 30 });
  const mockGroup = new MockElement('g');
  const edgesLayer = renderEdges(root, mockGroup);

  assert(edgesLayer !== null, 'edges layer created');
  assert(edgesLayer.children.length === 0, 'no edges for single node');
}

// ─── Test 12: edges rendered before nodes in z-order ───
console.log('Test 12: integration - edges layer added before nodes layer');
{
  // Simulate the rendering order used in setTreeData
  const child = makeNode('c', 'root', { x: 50, y: 100 });
  const root = makeNode('root', null, { x: 50, y: 30, children: [child] });

  const mockGroup = new MockElement('g');

  // Render in the same order as setTreeData: edges first, then nodes
  renderEdges(root, mockGroup);

  // Simulate renderNodes by adding a nodes layer
  const nodesLayer = new MockElement('g');
  nodesLayer.setAttribute('class', 'branch-tree-nodes-layer');
  mockGroup.appendChild(nodesLayer);

  // Edges layer should be first child (rendered behind nodes)
  assert(mockGroup.children[0].attributes['class'] === 'branch-tree-edges-layer',
    'edges layer is first child (behind nodes)');
  assert(mockGroup.children[1].attributes['class'] === 'branch-tree-nodes-layer',
    'nodes layer is second child (in front of edges)');
}

// ─── Summary ───
console.log(`\n${'─'.repeat(40)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
} else {
  console.log('All tests passed!');
}

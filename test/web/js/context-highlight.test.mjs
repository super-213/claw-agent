/**
 * 测试 context-highlight.js — 上下文高亮模块（含压缩状态标记）
 * 运行: node test/web/js/context-highlight.test.mjs
 */

import { JSDOM } from 'jsdom';

// Set up a minimal DOM environment before importing the module
const dom = new JSDOM('<!DOCTYPE html><html><body><div id="messages"></div></body></html>');
global.document = dom.window.document;

// Dynamic import after DOM is set up
const {
  HIGHLIGHT_CLASSES,
  NODE_ID_ATTR,
  clearHighlights,
  highlightContextNodes,
  highlightContextWithCompression,
  getHighlightState,
  getNodeHighlightType,
  applyHighlightsFromMessages,
} = await import('../../../web/js/context-highlight.js');

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

/** Helper: create message-row elements with data-node-id */
function setupMessages(nodeIds) {
  const container = document.getElementById('messages');
  container.innerHTML = '';
  nodeIds.forEach((id) => {
    const row = document.createElement('div');
    row.className = 'message-row';
    row.setAttribute(NODE_ID_ATTR, id);
    const bubble = document.createElement('div');
    bubble.className = 'message assistant';
    row.appendChild(bubble);
    container.appendChild(row);
  });
}

// ─── Test 1: HIGHLIGHT_CLASSES constants ───
console.log('Test 1: HIGHLIGHT_CLASSES has correct values');
{
  assert(HIGHLIGHT_CLASSES.contextFull === 'context-highlight-full', 'contextFull class name');
  assert(HIGHLIGHT_CLASSES.contextSummarized === 'context-highlight-summarized', 'contextSummarized class name');
  assert(HIGHLIGHT_CLASSES.contextGeneric === 'context-highlight', 'contextGeneric class name');
}

// ─── Test 2: highlightContextNodes applies full class to all ───
console.log('Test 2: highlightContextNodes marks all nodes as full');
{
  setupMessages(['n1', 'n2', 'n3', 'n4']);
  highlightContextNodes(['n1', 'n2', 'n3']);

  const n1 = document.querySelector(`[${NODE_ID_ATTR}="n1"]`);
  const n2 = document.querySelector(`[${NODE_ID_ATTR}="n2"]`);
  const n3 = document.querySelector(`[${NODE_ID_ATTR}="n3"]`);
  const n4 = document.querySelector(`[${NODE_ID_ATTR}="n4"]`);

  assert(n1.classList.contains(HIGHLIGHT_CLASSES.contextFull), 'n1 has contextFull');
  assert(n1.classList.contains(HIGHLIGHT_CLASSES.contextGeneric), 'n1 has contextGeneric');
  assert(n2.classList.contains(HIGHLIGHT_CLASSES.contextFull), 'n2 has contextFull');
  assert(n3.classList.contains(HIGHLIGHT_CLASSES.contextFull), 'n3 has contextFull');
  assert(!n4.classList.contains(HIGHLIGHT_CLASSES.contextFull), 'n4 does NOT have contextFull');
  assert(!n4.classList.contains(HIGHLIGHT_CLASSES.contextGeneric), 'n4 does NOT have contextGeneric');
}

// ─── Test 3: highlightContextWithCompression distinguishes full vs summarized ───
console.log('Test 3: highlightContextWithCompression applies different classes');
{
  setupMessages(['n1', 'n2', 'n3', 'n4', 'n5']);

  // n1, n2 are summarized; n3, n4 are full; n5 is not in context
  highlightContextWithCompression(['n1', 'n2', 'n3', 'n4'], ['n1', 'n2']);

  const n1 = document.querySelector(`[${NODE_ID_ATTR}="n1"]`);
  const n2 = document.querySelector(`[${NODE_ID_ATTR}="n2"]`);
  const n3 = document.querySelector(`[${NODE_ID_ATTR}="n3"]`);
  const n4 = document.querySelector(`[${NODE_ID_ATTR}="n4"]`);
  const n5 = document.querySelector(`[${NODE_ID_ATTR}="n5"]`);

  // Summarized nodes
  assert(n1.classList.contains(HIGHLIGHT_CLASSES.contextSummarized), 'n1 has contextSummarized');
  assert(n1.classList.contains(HIGHLIGHT_CLASSES.contextGeneric), 'n1 has contextGeneric');
  assert(!n1.classList.contains(HIGHLIGHT_CLASSES.contextFull), 'n1 does NOT have contextFull');

  assert(n2.classList.contains(HIGHLIGHT_CLASSES.contextSummarized), 'n2 has contextSummarized');
  assert(!n2.classList.contains(HIGHLIGHT_CLASSES.contextFull), 'n2 does NOT have contextFull');

  // Full nodes
  assert(n3.classList.contains(HIGHLIGHT_CLASSES.contextFull), 'n3 has contextFull');
  assert(n3.classList.contains(HIGHLIGHT_CLASSES.contextGeneric), 'n3 has contextGeneric');
  assert(!n3.classList.contains(HIGHLIGHT_CLASSES.contextSummarized), 'n3 does NOT have contextSummarized');

  assert(n4.classList.contains(HIGHLIGHT_CLASSES.contextFull), 'n4 has contextFull');
  assert(!n4.classList.contains(HIGHLIGHT_CLASSES.contextSummarized), 'n4 does NOT have contextSummarized');

  // Not in context
  assert(!n5.classList.contains(HIGHLIGHT_CLASSES.contextGeneric), 'n5 has no highlight');
  assert(!n5.classList.contains(HIGHLIGHT_CLASSES.contextFull), 'n5 has no full');
  assert(!n5.classList.contains(HIGHLIGHT_CLASSES.contextSummarized), 'n5 has no summarized');
}

// ─── Test 4: getHighlightState returns correct sets ───
console.log('Test 4: getHighlightState reflects compression state');
{
  setupMessages(['a', 'b', 'c']);
  highlightContextWithCompression(['a', 'b', 'c'], ['a']);

  const state = getHighlightState();
  assert(state.fullNodeIds.includes('b'), 'b is in fullNodeIds');
  assert(state.fullNodeIds.includes('c'), 'c is in fullNodeIds');
  assert(!state.fullNodeIds.includes('a'), 'a is NOT in fullNodeIds');
  assert(state.summarizedNodeIds.includes('a'), 'a is in summarizedNodeIds');
  assert(!state.summarizedNodeIds.includes('b'), 'b is NOT in summarizedNodeIds');
}

// ─── Test 5: getNodeHighlightType returns correct type ───
console.log('Test 5: getNodeHighlightType returns full/summarized/null');
{
  setupMessages(['x', 'y', 'z']);
  highlightContextWithCompression(['x', 'y'], ['x']);

  assert(getNodeHighlightType('x') === 'summarized', 'x is summarized');
  assert(getNodeHighlightType('y') === 'full', 'y is full');
  assert(getNodeHighlightType('z') === null, 'z is null (not highlighted)');
}

// ─── Test 6: clearHighlights removes all classes and resets state ───
console.log('Test 6: clearHighlights removes all highlight classes');
{
  setupMessages(['m1', 'm2']);
  highlightContextWithCompression(['m1', 'm2'], ['m1']);

  clearHighlights();

  const m1 = document.querySelector(`[${NODE_ID_ATTR}="m1"]`);
  const m2 = document.querySelector(`[${NODE_ID_ATTR}="m2"]`);

  assert(!m1.classList.contains(HIGHLIGHT_CLASSES.contextSummarized), 'm1 cleared summarized');
  assert(!m1.classList.contains(HIGHLIGHT_CLASSES.contextGeneric), 'm1 cleared generic');
  assert(!m2.classList.contains(HIGHLIGHT_CLASSES.contextFull), 'm2 cleared full');
  assert(!m2.classList.contains(HIGHLIGHT_CLASSES.contextGeneric), 'm2 cleared generic');

  const state = getHighlightState();
  assert(state.fullNodeIds.length === 0, 'fullNodeIds cleared');
  assert(state.summarizedNodeIds.length === 0, 'summarizedNodeIds cleared');
}

// ─── Test 7: summarized_nodes not in context are ignored ───
console.log('Test 7: summarized_nodes not in context_nodes are ignored');
{
  setupMessages(['p1', 'p2', 'p3']);
  // p3 is in summarized list but NOT in context list
  highlightContextWithCompression(['p1', 'p2'], ['p3']);

  const state = getHighlightState();
  assert(state.fullNodeIds.includes('p1'), 'p1 is full');
  assert(state.fullNodeIds.includes('p2'), 'p2 is full');
  assert(!state.summarizedNodeIds.includes('p3'), 'p3 not in summarizedNodeIds (not in context)');
}

// ─── Test 8: empty context_nodes does nothing ───
console.log('Test 8: empty contextNodeIds clears highlights');
{
  setupMessages(['q1', 'q2']);
  highlightContextNodes(['q1', 'q2']);
  highlightContextWithCompression([], ['q1']);

  const q1 = document.querySelector(`[${NODE_ID_ATTR}="q1"]`);
  assert(!q1.classList.contains(HIGHLIGHT_CLASSES.contextFull), 'q1 not highlighted after empty context');

  const state = getHighlightState();
  assert(state.fullNodeIds.length === 0, 'no full nodes');
  assert(state.summarizedNodeIds.length === 0, 'no summarized nodes');
}

// ─── Test 9: applyHighlightsFromMessages finds last assistant with context_nodes ───
console.log('Test 9: applyHighlightsFromMessages applies highlights from last assistant message');
{
  setupMessages(['n1', 'n2', 'n3', 'n4']);
  const messages = [
    { role: 'user', node_id: 'n1', content: 'Hello' },
    { role: 'assistant', node_id: 'n2', content: 'Hi', context_nodes: ['n1'] },
    { role: 'user', node_id: 'n3', content: 'More' },
    { role: 'assistant', node_id: 'n4', content: 'Sure', context_nodes: ['n1', 'n3'] },
  ];

  applyHighlightsFromMessages(messages);

  const n1 = document.querySelector(`[${NODE_ID_ATTR}="n1"]`);
  const n3 = document.querySelector(`[${NODE_ID_ATTR}="n3"]`);
  const n2 = document.querySelector(`[${NODE_ID_ATTR}="n2"]`);
  const n4 = document.querySelector(`[${NODE_ID_ATTR}="n4"]`);

  // Last assistant message (n4) has context_nodes: ['n1', 'n3']
  assert(n1.classList.contains(HIGHLIGHT_CLASSES.contextFull), 'n1 highlighted from last assistant');
  assert(n3.classList.contains(HIGHLIGHT_CLASSES.contextFull), 'n3 highlighted from last assistant');
  assert(!n2.classList.contains(HIGHLIGHT_CLASSES.contextFull), 'n2 not in context_nodes of last assistant');
  assert(!n4.classList.contains(HIGHLIGHT_CLASSES.contextFull), 'n4 not in its own context_nodes');
}

// ─── Test 10: applyHighlightsFromMessages with summarizedNodeIds ───
console.log('Test 10: applyHighlightsFromMessages with summarized nodes');
{
  setupMessages(['s1', 's2', 's3']);
  const messages = [
    { role: 'user', node_id: 's1', content: 'Hello' },
    { role: 'user', node_id: 's2', content: 'More' },
    { role: 'assistant', node_id: 's3', content: 'Reply', context_nodes: ['s1', 's2'] },
  ];

  applyHighlightsFromMessages(messages, ['s1']);

  const s1 = document.querySelector(`[${NODE_ID_ATTR}="s1"]`);
  const s2 = document.querySelector(`[${NODE_ID_ATTR}="s2"]`);

  assert(s1.classList.contains(HIGHLIGHT_CLASSES.contextSummarized), 's1 is summarized');
  assert(!s1.classList.contains(HIGHLIGHT_CLASSES.contextFull), 's1 not full');
  assert(s2.classList.contains(HIGHLIGHT_CLASSES.contextFull), 's2 is full');
}

// ─── Test 11: applyHighlightsFromMessages clears when no context_nodes found ───
console.log('Test 11: applyHighlightsFromMessages clears highlights when no assistant has context_nodes');
{
  setupMessages(['t1', 't2']);
  // First apply some highlights
  highlightContextNodes(['t1', 't2']);
  assert(document.querySelector(`[${NODE_ID_ATTR}="t1"]`).classList.contains(HIGHLIGHT_CLASSES.contextFull), 't1 initially highlighted');

  // Now apply from messages with no context_nodes
  const messages = [
    { role: 'user', node_id: 't1', content: 'Hello' },
    { role: 'assistant', node_id: 't2', content: 'Hi' },  // no context_nodes
  ];

  applyHighlightsFromMessages(messages);

  const t1 = document.querySelector(`[${NODE_ID_ATTR}="t1"]`);
  const t2 = document.querySelector(`[${NODE_ID_ATTR}="t2"]`);
  assert(!t1.classList.contains(HIGHLIGHT_CLASSES.contextFull), 't1 cleared');
  assert(!t2.classList.contains(HIGHLIGHT_CLASSES.contextFull), 't2 cleared');
}

// ─── Test 12: applyHighlightsFromMessages with empty/null messages clears ───
console.log('Test 12: applyHighlightsFromMessages with empty/null messages clears highlights');
{
  setupMessages(['u1']);
  highlightContextNodes(['u1']);

  applyHighlightsFromMessages([]);
  assert(!document.querySelector(`[${NODE_ID_ATTR}="u1"]`).classList.contains(HIGHLIGHT_CLASSES.contextFull), 'cleared with empty array');

  highlightContextNodes(['u1']);
  applyHighlightsFromMessages(null);
  assert(!document.querySelector(`[${NODE_ID_ATTR}="u1"]`).classList.contains(HIGHLIGHT_CLASSES.contextFull), 'cleared with null');
}

// ─── Test 13: clearHighlights followed by applyHighlightsFromMessages simulates branch switch ───
console.log('Test 13: branch switch simulation - clear then re-apply');
{
  setupMessages(['b1', 'b2', 'b3']);

  // Simulate old branch highlights
  highlightContextNodes(['b1', 'b2']);
  assert(document.querySelector(`[${NODE_ID_ATTR}="b1"]`).classList.contains(HIGHLIGHT_CLASSES.contextFull), 'b1 highlighted on old branch');
  assert(document.querySelector(`[${NODE_ID_ATTR}="b2"]`).classList.contains(HIGHLIGHT_CLASSES.contextFull), 'b2 highlighted on old branch');

  // Simulate branch switch: clear old highlights
  clearHighlights();
  assert(!document.querySelector(`[${NODE_ID_ATTR}="b1"]`).classList.contains(HIGHLIGHT_CLASSES.contextFull), 'b1 cleared after switch');
  assert(!document.querySelector(`[${NODE_ID_ATTR}="b2"]`).classList.contains(HIGHLIGHT_CLASSES.contextFull), 'b2 cleared after switch');

  // Simulate new branch reply with different context
  const newBranchMessages = [
    { role: 'user', node_id: 'b1', content: 'Hello' },
    { role: 'assistant', node_id: 'b3', content: 'New reply', context_nodes: ['b1'] },
  ];
  applyHighlightsFromMessages(newBranchMessages);

  assert(document.querySelector(`[${NODE_ID_ATTR}="b1"]`).classList.contains(HIGHLIGHT_CLASSES.contextFull), 'b1 re-highlighted on new branch');
  assert(!document.querySelector(`[${NODE_ID_ATTR}="b2"]`).classList.contains(HIGHLIGHT_CLASSES.contextFull), 'b2 not highlighted on new branch');
}

// ─── Summary ───
console.log(`\n${'─'.repeat(40)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
} else {
  console.log('All tests passed!');
}

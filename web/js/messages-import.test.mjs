/**
 * Smoke tests for messages.js facade and split-out renderers.
 * Run: node web/js/messages-import.test.mjs
 */

import { JSDOM } from 'jsdom';

const dom = new JSDOM(`
  <!DOCTYPE html>
  <html>
    <body>
      <div id="messageList"></div>
      <div id="chatWindow"></div>
      <div id="emptyState"></div>
      <span id="statusText"></span>
      <div id="statusBadge"></div>
      <button id="sendBtn"></button>
    </body>
  </html>
`);

global.document = dom.window.document;
global.window = dom.window;
global.requestAnimationFrame = (callback) => callback();
global.alert = () => {};

const {
  appendStreamingAssistantDelta,
  finishStreamingAssistantMessage,
  renderMessages,
  setStatus,
  startStreamingAssistantMessage,
} = await import('./messages.js');

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

console.log('Test 1: messages.js facade imports and status updates');
{
  setStatus('处理中…', true);
  assert(document.getElementById('statusText').textContent === '处理中…', 'status text updated');
  assert(document.getElementById('statusBadge').classList.contains('busy'), 'busy class set');
  assert(document.getElementById('sendBtn').disabled === true, 'send button disabled');
}

console.log('Test 2: renderMessages marks final rows branchable after mixed protocol split');
{
  renderMessages([
    { role: 'system', content: 'system' },
    { role: 'user', content: 'hello', node_id: 'n1' },
    {
      role: 'assistant',
      content: '[命令]\necho ok\n[完成]\nDone',
      node_id: 'n2',
    },
  ]);

  const finalRow = document.querySelector('.final-row[data-node-id="n2"]');
  assert(Boolean(finalRow), 'final row rendered');
  assert(finalRow.dataset.branchable === 'true', 'final row is branchable');
  assert(Boolean(finalRow.querySelector('.branch-btn')), 'branch action button rendered');
}

console.log('Test 3: stream renderer finalizes markdown and split protocol rows');
{
  const stream = startStreamingAssistantMessage({ iteration: 1, model: 'test-model' });
  appendStreamingAssistantDelta(stream, '[命令]\necho ok\n');
  appendStreamingAssistantDelta(stream, '[完成]\n**Done**');
  finishStreamingAssistantMessage(stream);

  assert(!stream.row.classList.contains('streaming-row'), 'streaming row finalized');
  assert(Boolean(stream.textEl.closest('.markdown-body')), 'stream text promoted to markdown body');
  assert(Boolean(document.querySelector('.final-row strong')), 'split final row rendered markdown');
}

console.log('\n────────────────────────────────────────');
console.log(`Results: ${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exitCode = 1;
} else {
  console.log('All tests passed!');
}

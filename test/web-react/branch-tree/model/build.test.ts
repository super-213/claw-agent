import { describe, expect, it } from 'vitest';
import { buildBranchTree } from '../../../../web-react/src/features/branch-tree/model/build';

describe('buildBranchTree', () => {
  it('folds a user/tool/model turn into a display node', () => {
    const tree = buildBranchTree({
      active_node_id: 'a2',
      nodes: [
        { node_id: 'root', parent_id: null, role: 'system', summary: 'system' },
        { node_id: 'u1', parent_id: 'root', role: 'user', summary: 'run tests' },
        { node_id: 'cmd1', parent_id: 'u1', role: 'assistant', summary: '', has_tool_calls: true, tool_names: ['shell_execute'] },
        { node_id: 'res1', parent_id: 'cmd1', role: 'tool', summary: '{"status":"success"}' },
        { node_id: 'a2', parent_id: 'res1', role: 'assistant', summary: 'done' },
      ],
    });

    expect(tree.root?.role).toBe('system');
    expect(tree.nodes.some((node) => node.role === 'turn' && node.toolCount === 1)).toBe(true);
    expect(tree.nodes.some((node) => node.isActive)).toBe(true);
    expect(tree.width).toBeGreaterThan(0);
    expect(tree.height).toBeGreaterThan(0);
  });
});

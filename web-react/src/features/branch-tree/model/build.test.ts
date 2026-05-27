import { describe, expect, it } from 'vitest';
import { buildBranchTree } from './build';

describe('buildBranchTree', () => {
  it('folds a user/tool/model turn into a display node', () => {
    const tree = buildBranchTree({
      active_node_id: 'a2',
      nodes: [
        { node_id: 'root', parent_id: null, role: 'system', summary: 'system' },
        { node_id: 'u1', parent_id: 'root', role: 'user', summary: 'run tests' },
        { node_id: 'cmd1', parent_id: 'u1', role: 'assistant', summary: '[命令]\npytest' },
        { node_id: 'res1', parent_id: 'cmd1', role: 'user', summary: '[执行完成]\nok' },
        { node_id: 'a2', parent_id: 'res1', role: 'assistant', summary: '[完成]\ndone' },
      ],
    });

    expect(tree.root?.role).toBe('system');
    expect(tree.nodes.some((node) => node.role === 'turn' && node.toolCount === 1)).toBe(true);
    expect(tree.nodes.some((node) => node.isActive)).toBe(true);
    expect(tree.width).toBeGreaterThan(0);
    expect(tree.height).toBeGreaterThan(0);
  });
});

import { X } from 'lucide-react';
import type { BranchTree as BranchTreePayload } from '../../api/types';
import { BranchTree } from './BranchTree';

interface BranchTreePanelProps {
  open: boolean;
  tree: BranchTreePayload | null;
  onClose: () => void;
  onSelectNode: (nodeId: string) => void | Promise<void>;
  onDeleteBranch: (nodeId: string) => void | Promise<void>;
}

export function BranchTreePanel({ open, tree, onClose, onSelectNode, onDeleteBranch }: BranchTreePanelProps) {
  const nodeCount = tree?.nodes.length || 0;
  return (
    <aside className={`tree-panel${open ? ' open' : ''}`} aria-label="分支树状图" aria-hidden={!open}>
      <div className="tree-panel-resize" aria-hidden="true" />
      <div className="tree-panel-header">
        <div>
          <span className="tree-panel-kicker">上下文</span>
          <h2 className="tree-panel-title">分支树</h2>
        </div>
        <span className="tree-panel-count">{nodeCount} 节点</span>
        <button className="tree-panel-close" type="button" aria-label="关闭分支树面板" onClick={onClose}>
          <X size={18} />
        </button>
      </div>
      <div className="tree-panel-body">
        <BranchTree tree={tree} onSelectNode={onSelectNode} onDeleteBranch={onDeleteBranch} />
      </div>
    </aside>
  );
}

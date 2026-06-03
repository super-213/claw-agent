import { useMemo, useState } from 'react';
import type React from 'react';
import type { BranchTree as BranchTreePayload } from '../../api/types';
import { EDGE_STYLES, NODE_COLORS, TREE_CONSTANTS, ZOOM_CONSTANTS } from './model/constants';
import { buildBranchTree } from './model/build';
import type { TreeNode } from './model/model';

interface BranchTreeProps {
  tree: BranchTreePayload | null;
  onSelectNode: (nodeId: string) => void | Promise<void>;
  onDeleteBranch: (nodeId: string) => void | Promise<void>;
}

const truncateSummary = (text: string | undefined, maxLen = 30) => {
  if (!text) return '';
  return text.length <= maxLen ? text : `${text.slice(0, maxLen)}...`;
};

const edgePath = (parent: TreeNode, child: TreeNode) => {
  const x1 = parent.x + TREE_CONSTANTS.nodeWidth / 2;
  const y1 = parent.y + TREE_CONSTANTS.nodeHeight;
  const x2 = child.x + TREE_CONSTANTS.nodeWidth / 2;
  const y2 = child.y;
  const midY = (y1 + y2) / 2;
  return `M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`;
};

function MessageSlot({
  role,
  label,
  text,
  y,
  muted = false,
}: {
  role: string;
  label: string;
  text?: string;
  y: number;
  muted?: boolean;
}) {
  const x = (TREE_CONSTANTS.nodeWidth - TREE_CONSTANTS.messageWidth) / 2;
  return (
    <g className={`branch-message-slot role-${role}${muted ? ' muted' : ''}`}>
      <rect
        x={x}
        y={y}
        width={TREE_CONSTANTS.messageWidth}
        height={TREE_CONSTANTS.messageHeight}
        rx="7"
        className="branch-message-rect"
      />
      <text x={x + 14} y={y + 19} className="branch-message-role">
        {label}:
      </text>
      <text x={x + 78} y={y + 19} className="branch-message-summary">
        {truncateSummary(text || 'empty', 15)}
      </text>
    </g>
  );
}

function NodeBlock({
  node,
  activeNodeId,
  onSelectNode,
  onDeleteBranch,
}: {
  node: TreeNode;
  activeNodeId?: string | null;
  onSelectNode: (nodeId: string) => void | Promise<void>;
  onDeleteBranch: (nodeId: string) => void | Promise<void>;
}) {
  const deleteNodeId = node.role === 'turn' ? node.nodeIds[0] : node.nodeId;
  const roleLabel = node.role === 'assistant' ? 'model' : node.role === 'turn' ? 'turn' : node.role || 'system';

  const contextMenu = (event: React.MouseEvent<SVGGElement>) => {
    event.preventDefault();
    event.stopPropagation();
    if (confirm('确定要删除此分支及其所有子分支吗？此操作不可恢复。')) {
      void onDeleteBranch(deleteNodeId);
    }
  };

  return (
    <g
      className={`branch-tree-node${node.isActive ? ' active' : ' inactive'}`}
      data-node-id={node.nodeId}
      data-delete-node-id={deleteNodeId}
      transform={`translate(${node.x}, ${node.y})`}
      onClick={(event) => {
        event.stopPropagation();
        if (node.nodeId !== activeNodeId) void onSelectNode(node.nodeId);
      }}
      onContextMenu={contextMenu}
    >
      <rect
        width={TREE_CONSTANTS.nodeWidth}
        height={TREE_CONSTANTS.nodeHeight}
        rx="18"
        fill="transparent"
        stroke={node.isActive ? NODE_COLORS.activeBorder : NODE_COLORS.defaultBorder}
        strokeWidth={node.isActive ? 2.6 : 1.8}
        className={`branch-block role-${node.role}${node.isActive ? ' active' : ''}`}
        style={{ cursor: 'pointer' }}
      />
      <g className={`branch-message-card role-${node.role}${node.isActive ? ' active' : ''}`}>
        {node.role === 'turn' ? (
          <>
            <MessageSlot role="user" label="user" text={node.userSummary} y={22} />
            <MessageSlot role="tool" label="tool" text={node.toolSummary} y={61} muted={!node.toolCount} />
            <MessageSlot role="assistant" label="model" text={node.modelSummary} y={100} />
          </>
        ) : (
          <MessageSlot
            role={node.role || 'system'}
            label={roleLabel}
            text={node.modelSummary || node.summary}
            y={(TREE_CONSTANTS.nodeHeight - TREE_CONSTANTS.messageHeight) / 2}
          />
        )}
      </g>
      <title>
        {node.role === 'turn'
          ? [`user: ${truncateSummary(node.userSummary, 80)}`, `tool: ${node.toolSummary}`, `model: ${truncateSummary(node.modelSummary, 80)}`].join(
              '\n',
            )
          : `${roleLabel}: ${truncateSummary(node.summary, 80)}`}
      </title>
    </g>
  );
}

export function BranchTree({ tree, onSelectNode, onDeleteBranch }: BranchTreeProps) {
  const built = useMemo(() => buildBranchTree(tree), [tree]);
  const [transform, setTransform] = useState({ scale: 1, panX: 0, panY: 0 });
  const [panning, setPanning] = useState<null | { x: number; y: number; panX: number; panY: number }>(null);

  if (!built.root) {
    return (
      <div className="tree-panel-empty">
        <span>暂无分支数据</span>
      </div>
    );
  }

  const wheel = (event: React.WheelEvent<SVGSVGElement>) => {
    event.preventDefault();
    const oldScale = transform.scale;
    const factor = -event.deltaY > 0 ? 1 + ZOOM_CONSTANTS.zoomFactor : 1 - ZOOM_CONSTANTS.zoomFactor;
    const newScale = Math.max(ZOOM_CONSTANTS.minScale, Math.min(ZOOM_CONSTANTS.maxScale, oldScale * factor));
    if (newScale === oldScale) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const mouseX = event.clientX - rect.left;
    const mouseY = event.clientY - rect.top;
    setTransform({
      scale: newScale,
      panX: mouseX - (mouseX - transform.panX) * (newScale / oldScale),
      panY: mouseY - (mouseY - transform.panY) * (newScale / oldScale),
    });
  };

  return (
    <svg
      className="branch-tree-svg"
      width="100%"
      height="100%"
      viewBox={`0 0 ${Math.max(built.width, TREE_CONSTANTS.minWidth)} ${Math.max(built.height, TREE_CONSTANTS.minHeight)}`}
      onWheel={wheel}
      onMouseDown={(event) => {
        if (event.button !== 0 && event.button !== 1) return;
        setPanning({ x: event.clientX, y: event.clientY, panX: transform.panX, panY: transform.panY });
      }}
      onMouseMove={(event) => {
        if (!panning) return;
        setTransform((current) => ({
          ...current,
          panX: panning.panX + event.clientX - panning.x,
          panY: panning.panY + event.clientY - panning.y,
        }));
      }}
      onMouseUp={() => setPanning(null)}
      onMouseLeave={() => setPanning(null)}
      style={{ cursor: panning ? 'grabbing' : 'grab' }}
    >
      <g className="branch-tree-root" transform={`translate(${transform.panX}, ${transform.panY}) scale(${transform.scale})`}>
        <g className="branch-tree-edges-layer">
          {built.edges.map(({ from, to }) => {
            const active = from.isActive && to.isActive;
            return (
              <path
                key={`${from.nodeId}-${to.nodeId}`}
                d={edgePath(from, to)}
                fill="none"
                stroke={active ? EDGE_STYLES.activeColor : EDGE_STYLES.color}
                strokeWidth={active ? EDGE_STYLES.width + 1 : EDGE_STYLES.width}
                className={`branch-tree-edge${active ? ' active' : ''}`}
                data-from={from.nodeId}
                data-to={to.nodeId}
              />
            );
          })}
        </g>
        <g className="branch-tree-nodes-layer">
          {built.nodes.map((node) => (
            <NodeBlock
              key={node.nodeId}
              node={node}
              activeNodeId={tree?.active_node_id}
              onSelectNode={onSelectNode}
              onDeleteBranch={onDeleteBranch}
            />
          ))}
        </g>
      </g>
    </svg>
  );
}

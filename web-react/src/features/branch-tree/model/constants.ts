export const TREE_CONSTANTS = {
  nodeRadius: 14,
  nodeWidth: 240,
  nodeHeight: 152,
  messageWidth: 204,
  messageHeight: 30,
  siblingSpacing: 320,
  levelSpacing: 220,
  padding: 36,
  minWidth: 320,
  minHeight: 260,
};

export const NODE_COLORS = {
  user: '#75a7ff',
  assistant: '#52d987',
  tool: '#f5a623',
  system: '#8e8e93',
  activeBorder: '#00e5c8',
  defaultBorder: 'rgba(122, 143, 168, 0.5)',
} as const;

export const EDGE_STYLES = {
  color: 'rgba(122, 143, 168, 0.36)',
  activeColor: '#00e5c8',
  width: 2,
};

export const ZOOM_CONSTANTS = {
  minScale: 0.2,
  maxScale: 5,
  zoomFactor: 0.1,
  defaultScale: 1,
};

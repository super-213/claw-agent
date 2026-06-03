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
  user: '#007aff',
  assistant: '#34c759',
  tool: '#ff9500',
  system: '#8e8e93',
  activeBorder: '#007aff',
  defaultBorder: 'rgba(110, 110, 115, 0.38)',
} as const;

export const EDGE_STYLES = {
  color: 'rgba(110, 110, 115, 0.28)',
  activeColor: '#007aff',
  width: 2,
};

export const ZOOM_CONSTANTS = {
  minScale: 0.2,
  maxScale: 5,
  zoomFactor: 0.1,
  defaultScale: 1,
};

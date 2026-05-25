/** SVG 命名空间 */
export const SVG_NS = 'http://www.w3.org/2000/svg';

/** 节点尺寸与间距 */
export const TREE_CONSTANTS = {
  /** 兼容旧测试/调用方的节点半径，块状视图不再直接使用 */
  nodeRadius: 14,
  /** 分支块宽度 */
  nodeWidth: 240,
  /** 分支块高度 */
  nodeHeight: 152,
  /** 分支块内部消息条宽度 */
  messageWidth: 204,
  /** 分支块内部消息条高度 */
  messageHeight: 30,
  /** 同层节点水平间距 */
  siblingSpacing: 320,
  /** 层级间垂直间距 */
  levelSpacing: 220,
  /** 树的内边距 */
  padding: 36,
  /** 最小 SVG 宽度 */
  minWidth: 320,
  /** 最小 SVG 高度 */
  minHeight: 260,
};

/** 节点颜色（按角色区分） */
export const NODE_COLORS = {
  user: '#75a7ff',
  assistant: '#52d987',
  tool: '#f5a623',
  system: '#8e8e93',
  /** 活跃路径上的节点描边色 */
  activeBorder: '#00e5c8',
  /** 默认描边色 */
  defaultBorder: 'rgba(122, 143, 168, 0.5)',
};

/** 连线样式 */
export const EDGE_STYLES = {
  /** 默认连线颜色 */
  color: 'rgba(122, 143, 168, 0.36)',
  /** 活跃路径连线颜色 */
  activeColor: '#00e5c8',
  /** 连线宽度 */
  width: 2,
};

/** 缩放/平移常量 */
export const ZOOM_CONSTANTS = {
  /** 最小缩放比例 */
  minScale: 0.2,
  /** 最大缩放比例 */
  maxScale: 5,
  /** 每次滚轮缩放的步进因子 */
  zoomFactor: 0.1,
  /** 初始缩放比例 */
  defaultScale: 1,
};

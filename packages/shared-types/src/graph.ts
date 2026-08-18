/** 拓樸圖 / 社群子圖 / 社群關係 meta-graph 的共用型別。 */

/** 資料庫 `nodes.idx`;pipeline 產生的穩定整數 ID(不是維基百科 pageid)。 */
export type NodeIdx = number;

/** 社群偵測(Infomap)產生的社群編號。 */
export type CommunityId = number;

/** 拓樸圖節點:主畫面整張圖的一個條目。 */
export interface TopologyNode {
  idx: NodeIdx;
  /** 顯示用的台灣繁體標題(pipeline 端用 OpenCC 轉好的)。 */
  title: string;
  community: CommunityId;
  /** 節點大小依此值縮放。 */
  pagerank: number;
  betweenness: number;
  authority: number;
  hub: number;
  averagePageviews: number | null;
}

/** 拓樸圖的邊(社群關係 meta-graph 層級,已做 top-N 裁切)。 */
export interface TopologyEdge {
  sourceIdx: NodeIdx;
  targetIdx: NodeIdx;
  /** 兩端之間的實際連結數,作為邊粗細。 */
  connectionsNum: number;
  betweenness: number;
}

export interface TopologyGraph {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
}

/** 單一社群展開後的子圖節點。 */
export interface SubgraphNode {
  idx: NodeIdx;
  title: string;
  community: CommunityId;
  pagerank: number;
  betweenness: number;
  authority: number;
  hub: number;
  /** 由 pipeline 標記的特殊角色(hub / authority / betweenness / bridge)。 */
  specialRoles?: SpecialNodeRole[];
}

export type SpecialNodeRole = 'hub' | 'authority' | 'betweenness' | 'bridge';

export interface SubgraphEdge {
  sourceIdx: NodeIdx;
  targetIdx: NodeIdx;
  community: CommunityId;
  betweenness: number;
}

export interface CommunitySubgraph {
  community: CommunityId;
  nodes: SubgraphNode[];
  edges: SubgraphEdge[];
}

/** 節點詳情面板需要的條目內容。 */
export interface NodeDetail {
  idx: NodeIdx;
  /** 顯示用的台灣繁體標題。 */
  title: string;
  /** 維基的正式標題,用來組 https://zh.wikipedia.org/wiki/<canonicalTitle> 連結。 */
  canonicalTitle: string;
  introduction: string | null;
  community: CommunityId;
  averagePageviews: number | null;
}

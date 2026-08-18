/**
 * Neon(Postgres + pgvector)schema。
 *
 * 改編自舊版 `web_wiki/drizzle/schema.ts`,主要差異:
 * - 表/檢視名稱不再綁定繪圖庫(`topology_relation_cytoscape_*` → `topology_view_*`)
 * - 捨棄 v1 用不到的向量相似度圖(`vector_relation_graph_*`、`vector_graph_edges`、
 *   `subgraph_edges_cosine_similarity`)與 `nodes_query_vector`
 *   (查詢 embedding 現在由 Worker 即時呼叫 Workers AI 產生,不預存)
 * - 補上舊版沒有、但社群子圖 UI 需要的 `community_special_nodes`
 */
import { sql } from 'drizzle-orm';
import {
  date,
  doublePrecision,
  index,
  integer,
  pgTable,
  pgView,
  primaryKey,
  real,
  text,
  unique,
  vector,
} from 'drizzle-orm/pg-core';
import { EMBEDDING_DIMENSIONS } from './config.js';

/** 條目本體。idx 是 pipeline 產生的穩定整數 ID(非 Wikipedia pageid)。 */
export const nodes = pgTable('nodes', {
  idx: integer('idx').primaryKey().notNull(),
  title: text('title').notNull(),
  introduction: text('introduction'),
  averagePageviews: real('average_pageviews'),
});

/** 條目簡介的段落向量。與 EMBEDDING_MODEL 綁定。 */
export const nodesPassageVector = pgTable(
  'nodes_passage_vector',
  {
    idx: integer('idx')
      .primaryKey()
      .notNull()
      .references(() => nodes.idx, { onDelete: 'cascade' }),
    passageEmbedding: vector('passage_embedding', { dimensions: EMBEDDING_DIMENSIONS }).notNull(),
  },
  (t) => [
    index('nodes_passage_vector_hnsw_idx').using(
      'hnsw',
      t.passageEmbedding.op('vector_cosine_ops'),
    ),
  ],
);

/* ---------------------------------------------------------------- 拓樸圖 */

/** 全圖節點 + 中心性指標 + Infomap 第一層社群。 */
export const topologyNodes = pgTable(
  'topology_nodes',
  {
    idx: integer('idx')
      .primaryKey()
      .notNull()
      .references(() => nodes.idx, { onDelete: 'cascade' }),
    community: integer('community').notNull(),
    pagerank: doublePrecision('pagerank').notNull(),
    betweenness: doublePrecision('betweenness').notNull(),
    authority: doublePrecision('authority').notNull(),
    hub: doublePrecision('hub').notNull(),
  },
  (t) => [index('topology_nodes_community_idx').on(t.community)],
);

/** 全圖邊。connections_num 為兩端之間的連結數(邊粗細)。 */
export const topologyEdges = pgTable(
  'topology_edges',
  {
    sourceIdx: integer('source_idx').notNull(),
    targetIdx: integer('target_idx').notNull(),
    connectionsNum: integer('connections_num').notNull(),
    betweenness: doublePrecision('betweenness').notNull(),
  },
  (t) => [
    primaryKey({ columns: [t.sourceIdx, t.targetIdx] }),
    index('topology_edges_connections_num_idx').on(t.connectionsNum),
  ],
);

/* ------------------------------------------------------------ 社群子圖 */

/** 單一社群展開後的子圖節點(第二層社群偵測結果)。 */
export const communitySubgraphNodes = pgTable(
  'community_subgraph_nodes',
  {
    idx: integer('idx')
      .primaryKey()
      .notNull()
      .references(() => nodes.idx, { onDelete: 'cascade' }),
    community: integer('community').notNull(),
    pagerank: doublePrecision('pagerank').notNull(),
    betweenness: doublePrecision('betweenness').notNull(),
    authority: doublePrecision('authority').notNull(),
    hub: doublePrecision('hub').notNull(),
  },
  (t) => [index('community_subgraph_nodes_community_idx').on(t.community)],
);

export const communitySubgraphEdges = pgTable(
  'community_subgraph_edges',
  {
    sourceIdx: integer('source_idx').notNull(),
    targetIdx: integer('target_idx').notNull(),
    community: integer('community').notNull(),
    betweenness: doublePrecision('betweenness').notNull(),
  },
  (t) => [
    primaryKey({ columns: [t.sourceIdx, t.targetIdx] }),
    index('community_subgraph_edges_community_idx').on(t.community),
  ],
);

/** hub / authority / betweenness / bridge 四種特殊節點標記(每個社群各一組)。 */
export const communitySpecialNodes = pgTable(
  'community_special_nodes',
  {
    community: integer('community').notNull(),
    role: text('role').notNull(),
    idx: integer('idx')
      .notNull()
      .references(() => nodes.idx, { onDelete: 'cascade' }),
  },
  (t) => [primaryKey({ columns: [t.community, t.role, t.idx] })],
);

/* -------------------------------------------------------------- 瀏覽量 */

export const pageviews = pgTable(
  'pageviews',
  {
    idx: integer('idx')
      .notNull()
      .references(() => nodes.idx, { onDelete: 'cascade' }),
    date: date('date').notNull(),
    pageviews: integer('pageviews').notNull(),
  },
  (t) => [primaryKey({ columns: [t.idx, t.date] }), index('pageviews_date_idx').on(t.date)],
);

/** 半月彙總,用於長區間圖表(資料點少一個量級)。 */
export const pageviewsHalfMonth = pgTable(
  'pageviews_half_month',
  {
    idx: integer('idx')
      .notNull()
      .references(() => nodes.idx, { onDelete: 'cascade' }),
    date: date('date').notNull(),
    pageviews: integer('pageviews').notNull(),
  },
  (t) => [primaryKey({ columns: [t.idx, t.date] })],
);

/** 整個社群的每日瀏覽量加總。 */
export const pageviewsCommunity = pgTable(
  'pageviews_community',
  {
    community: integer('community').notNull(),
    date: date('date').notNull(),
    pageviews: integer('pageviews').notNull(),
  },
  (t) => [primaryKey({ columns: [t.community, t.date] })],
);

/**
 * Pipeline 預先算好的異常瀏覽量(全資料集 z-score 表)。
 * 與 Worker 的「即時互動式」異常偵測是不同用途:這張表是給異常總覽分頁表格用的。
 */
export const anomalyPageviews = pgTable(
  'anomaly_pageviews',
  {
    idx: integer('idx')
      .notNull()
      .references(() => nodes.idx, { onDelete: 'cascade' }),
    anomalyDate: date('anomaly_date').notNull(),
    pageviews: integer('pageviews').notNull(),
    zscore: doublePrecision('zscore').notNull(),
  },
  (t) => [
    unique('anomaly_pageviews_unique').on(t.idx, t.anomalyDate),
    index('anomaly_pageviews_zscore_idx').on(t.zscore),
  ],
);

/* ---------------------------------------------------------------- 檢視 */

/** 前端主畫面用:節點 + 標題 + 平均瀏覽量,依 pagerank 由大到小。 */
export const topologyViewNodes = pgView('topology_view_nodes', {
  idx: integer('idx'),
  title: text('title'),
  community: integer('community'),
  pagerank: doublePrecision('pagerank'),
  betweenness: doublePrecision('betweenness'),
  authority: doublePrecision('authority'),
  hub: doublePrecision('hub'),
  averagePageviews: real('average_pageviews'),
}).as(
  sql`SELECT t.idx, n.title, t.community, t.pagerank, t.betweenness, t.authority, t.hub, n.average_pageviews
      FROM topology_nodes t JOIN nodes n ON t.idx = n.idx
      ORDER BY t.pagerank DESC`,
);

/**
 * 前端主畫面用的裁切後邊集合:每個節點保留連結數最多的 3 條,
 * 其餘依連結數補到總數 1000 條上限,避免 payload 過大。
 */
export const topologyViewEdges = pgView('topology_view_edges', {
  sourceIdx: integer('source_idx'),
  targetIdx: integer('target_idx'),
  connectionsNum: integer('connections_num'),
  betweenness: doublePrecision('betweenness'),
}).as(
  sql`WITH top3 AS (
        SELECT source_idx, target_idx, connections_num, betweenness
        FROM (
          SELECT source_idx, target_idx, connections_num, betweenness,
                 row_number() OVER (PARTITION BY source_idx ORDER BY connections_num DESC) AS rn
          FROM topology_edges
        ) t WHERE t.rn <= 3
      ), others AS (
        SELECT source_idx, target_idx, connections_num, betweenness
        FROM topology_edges
        WHERE (source_idx, target_idx) NOT IN (SELECT source_idx, target_idx FROM top3)
        ORDER BY connections_num DESC
        LIMIT GREATEST(0::bigint, 1000 - (SELECT count(*) FROM top3))
      )
      SELECT * FROM top3 UNION ALL SELECT * FROM others`,
);

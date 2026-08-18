import { pgTable, index, text, bigint, real, integer, doublePrecision, vector, date, jsonb, unique, primaryKey, foreignKey, pgView } from "drizzle-orm/pg-core"
import { sql } from "drizzle-orm"



export const subgraphEdges = pgTable("subgraph_edges", {
	type: text(),
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	community: bigint({ mode: "number" }),
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	sourceIdx: bigint("source_idx", { mode: "number" }).notNull(),
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	targetIdx: bigint("target_idx", { mode: "number" }).notNull(),
	betweenness: real(),
	distance: real(),
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	connectionNum: bigint("connection_num", { mode: "number" }),
}, (table) => [
	index("idx_subgraph_edges_type_subgraph_id").using("btree", table.type.asc().nullsLast().op("int8_ops"), table.community.asc().nullsLast().op("int8_ops")),
]);

export const topologySubgraphNodes = pgTable("topology_subgraph_nodes", {
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	idx: bigint({ mode: "number" }).primaryKey().notNull(),
	community: integer().notNull(),
	pagerank: doublePrecision().notNull(),
	betweenness: doublePrecision().notNull(),
	authority: doublePrecision().notNull(),
	hub: doublePrecision().notNull(),
}, (table) => [
	index("community_1748878746197_index").using("btree", table.community.asc().nullsLast().op("int4_ops")),
]);

export const nodes = pgTable("nodes", {
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	idx: bigint({ mode: "number" }).primaryKey().notNull(),
	title: text(),
	introduction: text(),
	averagePageviews: real("average_pageviews"),
}, (table) => [
	index("idx_idx").using("btree", table.idx.asc().nullsLast().op("int8_ops")),
]);

export const nodesPassageVector = pgTable("nodes_passage_vector", {
	idx: integer().primaryKey().notNull(),
	passageEmbedding: vector("passage_embedding", { dimensions: 1024 }),
}, (table) => [
	index("nodes_passage_vector_passage_embedding_idx").using("hnsw", table.passageEmbedding.asc().nullsLast().op("vector_cosine_ops")),
]);

export const pageviews = pgTable("pageviews", {
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	idx: bigint({ mode: "number" }).notNull(),
	date: date(),
	pageviews: integer(),
}, (table) => [
	index("idx_pageviews_idx_date").using("btree", table.idx.asc().nullsLast().op("date_ops"), table.date.asc().nullsLast().op("date_ops")),
]);

export const nodesQueryVector = pgTable("nodes_query_vector", {
	idx: integer().primaryKey().notNull(),
	queryEmbedding: vector("query_embedding", { dimensions: 1024 }),
}, (table) => [
	index("nodes_query_vector_query_embedding_idx").using("hnsw", table.queryEmbedding.asc().nullsLast().op("vector_cosine_ops")),
]);

export const vectorRelationGraphNodes = pgTable("vector_relation_graph_nodes", {
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	idx: bigint({ mode: "number" }).primaryKey().notNull(),
	community: integer().notNull(),
	tag: jsonb(),
	flow: doublePrecision().notNull(),
});

export const pageviewsHalfMonth = pgTable("pageviews_half_month", {
	idx: integer().notNull(),
	date: date(),
	pageviews: integer(),
}, (table) => [
	unique("pageviews_half_month_unique").on(table.idx, table.date),
]);

export const anomalyPageviews = pgTable("anomaly_pageviews", {
	idx: integer().notNull(),
	anomalyDate: date("anomaly_date"),
	pageviews: integer(),
	zscore: doublePrecision(),
}, (table) => [
	index("anomaly_pageviews_idx_idx").using("btree", table.idx.asc().nullsLast().op("int4_ops")),
	unique("anomaly_unique").on(table.idx, table.anomalyDate),
]);

export const pageviewsCommunity = pgTable("pageviews_community", {
	community: integer().notNull(),
	dateDaily: date("date_daily"),
	pageviewsDaily: integer("pageviews_daily"),
});

export const topologyRelationGraphNodes = pgTable("topology_relation_graph_nodes", {
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	idx: bigint({ mode: "number" }).primaryKey().notNull(),
	community: integer().notNull(),
	pagerank: doublePrecision().notNull(),
	betweenness: doublePrecision().notNull(),
	authority: doublePrecision().notNull(),
	hub: doublePrecision().notNull(),
});

export const subgraphEdgesCosineSimilarity = pgTable("subgraph_edges_cosine_similarity", {
	sourceIdx: integer("source_idx").notNull(),
	targetIdx: integer("target_idx").notNull(),
	cosineSimilarity: doublePrecision("cosine_similarity").notNull(),
}, (table) => [
	primaryKey({ columns: [table.sourceIdx, table.targetIdx], name: "subgraph_edges_cosine_similarity_pkey"}),
]);

export const vectorGraphEdges = pgTable("vector_graph_edges", {
	sourceIdx: integer("source_idx").notNull(),
	targetIdx: integer("target_idx").notNull(),
	cosineSimilarity: doublePrecision("cosine_similarity"),
}, (table) => [
	primaryKey({ columns: [table.sourceIdx, table.targetIdx], name: "vector_graph_edges_pkey"}),
]);

export const vectorRelationGraphEdges = pgTable("vector_relation_graph_edges", {
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	sourceIdx: bigint("source_idx", { mode: "number" }).notNull(),
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	targetIdx: bigint("target_idx", { mode: "number" }).notNull(),
	connectionsNum: integer("connections_num").notNull(),
}, (table) => [
	foreignKey({
			columns: [table.sourceIdx],
			foreignColumns: [vectorRelationGraphNodes.idx],
			name: "vector_relation_graph_edges_source_idx_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.targetIdx],
			foreignColumns: [vectorRelationGraphNodes.idx],
			name: "vector_relation_graph_edges_target_idx_fkey"
		}).onDelete("cascade"),
	primaryKey({ columns: [table.sourceIdx, table.targetIdx], name: "vector_relation_graph_edges_pkey"}),
]);

export const topologySubgraphEdges = pgTable("topology_subgraph_edges", {
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	sourceIdx: bigint("source_idx", { mode: "number" }).notNull(),
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	targetIdx: bigint("target_idx", { mode: "number" }).notNull(),
	community: integer().notNull(),
	betweenness: doublePrecision().notNull(),
}, (table) => [
	index("community_1748878759082_index").using("btree", table.community.asc().nullsLast().op("int4_ops")),
	primaryKey({ columns: [table.sourceIdx, table.targetIdx], name: "topology_subgraph_edges_pkey"}),
]);

export const topologyRelationGraphEdges = pgTable("topology_relation_graph_edges", {
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	sourceIdx: bigint("source_idx", { mode: "number" }).notNull(),
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	targetIdx: bigint("target_idx", { mode: "number" }).notNull(),
	connectionsNum: integer("connections_num").notNull(),
	betweenness: doublePrecision().notNull(),
}, (table) => [
	primaryKey({ columns: [table.sourceIdx, table.targetIdx], name: "topology_relation_graph_edges_pkey"}),
]);
export const topologyRelationCytoscapeNodes = pgView("topology_relation_cytoscape_nodes", {	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	idx: bigint({ mode: "number" }),
	title: text(),
	community: integer(),
	pagerank: doublePrecision(),
	betweenness: doublePrecision(),
	authority: doublePrecision(),
	hub: doublePrecision(),
	averagePageviews: real("average_pageviews"),
}).as(sql`SELECT v.idx, n.title, v.community, v.pagerank, v.betweenness, v.authority, v.hub, n.average_pageviews FROM topology_relation_graph_nodes v JOIN nodes n ON v.idx = n.idx ORDER BY v.pagerank DESC`);

export const topologyRelationCytoscapeEdges = pgView("topology_relation_cytoscape_edges", {	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	sourceIdx: bigint("source_idx", { mode: "number" }),
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	targetIdx: bigint("target_idx", { mode: "number" }),
	connectionsNum: integer("connections_num"),
	betweenness: doublePrecision(),
}).as(sql`WITH top3 AS ( SELECT t.source_idx, t.target_idx, t.connections_num, t.betweenness FROM ( SELECT topology_relation_graph_edges.source_idx, topology_relation_graph_edges.target_idx, topology_relation_graph_edges.connections_num, topology_relation_graph_edges.betweenness, row_number() OVER (PARTITION BY topology_relation_graph_edges.source_idx ORDER BY topology_relation_graph_edges.connections_num DESC) AS rn FROM topology_relation_graph_edges) t WHERE t.rn <= 3 ), others AS ( SELECT topology_relation_graph_edges.source_idx, topology_relation_graph_edges.target_idx, topology_relation_graph_edges.connections_num, topology_relation_graph_edges.betweenness FROM topology_relation_graph_edges WHERE NOT ((topology_relation_graph_edges.source_idx, topology_relation_graph_edges.target_idx) IN ( SELECT top3.source_idx, top3.target_idx FROM top3)) ORDER BY topology_relation_graph_edges.connections_num DESC LIMIT GREATEST(0::bigint, 1000 - (( SELECT count(*) AS count FROM top3))) ) SELECT top3.source_idx, top3.target_idx, top3.connections_num, top3.betweenness FROM top3 UNION ALL SELECT others.source_idx, others.target_idx, others.connections_num, others.betweenness FROM others`);
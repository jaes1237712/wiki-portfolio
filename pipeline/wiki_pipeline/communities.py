"""Phase 2c — 兩層社群偵測、有效子圖、特殊節點、社群關係 meta-graph。

改寫自 `docs/legacy/data_factory/analyze.py` 的
`config_infomap` / `config_G_list_two_level_effective_subgraphs` /
`config_two_level_special_nodes` / `config_G_two_level_community_relation`。

**多層(multi-level)社群不移植** —— 舊版 `config_G_list_multi_level_subgraphs` 算出子圖後
直接丟掉、level 2/3 根本沒有程式碼路徑,而且唯一能參考的 UI 只用到兩層。

與舊版的差異:
- 舊版在 `config_infomap` 裡直接 `plt.hist(...)` + `plt.show()`(批次 pipeline 裡跳圖表視窗),
  這裡只回傳統計數字,要畫圖是呼叫端的事。
- 舊版 `min_node_num` / `max_node_num` 寫死 50 / 500,小型測試種子會被濾光;改由
  `CommunityConfig` 帶入。
- meta-graph 的最短路徑,舊版對每組社群配對各跑一次 `get_shortest_path`(O(C²) 次 BFS),
  這裡改成一次 `graph.distances(...)` 算完整個矩陣。
- 舊版對「所有」社群配對都建邊,沒有連結的邊 distance 設成 `inf`;這裡只建
  connections_num > 0 的邊 —— 資訊完全相同,但 pagerank/betweenness 的權重不會出現
  0 與 inf 這種會讓演算法失去意義的值。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import igraph as ig
import numpy as np

from .config import CommunityConfig

log = logging.getLogger(__name__)

#: 每個有效社群都會標出這四個角色。
ROLES = ("hub", "authority", "center", "bridge")

#: 角色說明(給 UI / 文件用)。
ROLE_LABELS = {
    "hub": "指向最多重要條目的節點(hub score 最高)",
    "authority": "被最多重要條目指到的節點(authority score 最高)",
    "center": "社群內最常出現在最短路徑上的節點(betweenness 最高)",
    "bridge": "對社群外連結最多的節點,社群之間的橋",
}


@dataclass
class CommunityDetection:
    """Infomap 兩層社群偵測的結果。"""

    membership: list[int]
    codelength: float
    community_sizes: dict[int, int] = field(default_factory=dict)


@dataclass
class CommunitySubgraph:
    """一個有效社群展開後的子圖。

    頂點屬性:`idx`、`title`、`title_display`、`flow`(子圖內 pagerank)、`betweenness`
    邊屬性:`source_idx`、`target_idx`、`betweenness`(子圖內 edge betweenness)
    """

    community: int
    graph: ig.Graph


@dataclass
class SpecialNodes:
    """一個社群的四個特殊節點,`roles[role] = 條目 idx`。"""

    community: int
    roles: dict[str, int]


def detect_communities(graph: ig.Graph, trials: int = 5) -> CommunityDetection:
    """跑 Infomap(igraph 內建)兩層社群偵測,並把 `community` 寫進頂點屬性。"""
    if graph.vcount() == 0:
        graph.vs["community"] = []
        return CommunityDetection(membership=[], codelength=0.0)
    if "weight" not in graph.es.attributes() and graph.ecount() > 0:
        raise ValueError("請先跑 assign_topology_weights() 產生邊權重")

    weights = graph.es["weight"] if graph.ecount() > 0 else None
    partition = graph.community_infomap(edge_weights=weights, trials=trials)
    membership = [int(c) for c in partition.membership]
    graph.vs["community"] = membership

    sizes: dict[int, int] = {}
    for community in membership:
        sizes[community] = sizes.get(community, 0) + 1
    log.info(
        "社群偵測完成:%d 個社群,codelength %.4f,最大社群 %d 個節點",
        len(sizes),
        partition.codelength,
        max(sizes.values(), default=0),
    )
    return CommunityDetection(
        membership=membership, codelength=float(partition.codelength), community_sizes=sizes
    )


def effective_subgraphs(graph: ig.Graph, config: CommunityConfig) -> list[CommunitySubgraph]:
    """取出「有效社群」的子圖:節點數在 (min_node_num, max_node_num] 之間。

    區間沿用舊版:下界不含、上界含。
    """
    if "community" not in graph.vs.attributes():
        raise ValueError("請先跑 detect_communities()")

    members: dict[int, list[int]] = {}
    for vertex_id, community in enumerate(graph.vs["community"]):
        members.setdefault(int(community), []).append(vertex_id)

    subgraphs: list[CommunitySubgraph] = []
    for community in sorted(members):
        vertex_ids = members[community]
        if not (config.min_node_num < len(vertex_ids) <= config.max_node_num):
            continue
        subgraph = graph.induced_subgraph(vertex_ids)
        subgraph.vs["flow"] = subgraph.pagerank(directed=True, weights="weight")
        subgraph.vs["betweenness"] = subgraph.betweenness()

        edge_betweenness = subgraph.edge_betweenness()
        subgraph.es["source_idx"] = [e.source_vertex["idx"] for e in subgraph.es]
        subgraph.es["target_idx"] = [e.target_vertex["idx"] for e in subgraph.es]
        subgraph.es["betweenness"] = edge_betweenness
        for attr in subgraph.es.attributes():
            if attr not in ("source_idx", "target_idx", "betweenness"):
                del subgraph.es[attr]

        subgraphs.append(CommunitySubgraph(community=community, graph=subgraph))

    log.info(
        "有效社群:%d / %d 個(門檻 %d < n <= %d)",
        len(subgraphs),
        len(members),
        config.min_node_num,
        config.max_node_num,
    )
    return subgraphs


def mark_special_nodes(graph: ig.Graph, subgraphs: list[CommunitySubgraph]) -> list[SpecialNodes]:
    """標出每個有效社群的 hub / authority / center / bridge。

    `bridge` 沿用舊版定義:對社群**外**的出邊最多的節點(全圖出度 − 子圖內出度)。
    """
    out_degree_by_idx = {
        int(idx): degree
        for idx, degree in zip(graph.vs["idx"], graph.outdegree(), strict=True)
    }

    specials: list[SpecialNodes] = []
    for item in subgraphs:
        subgraph = item.graph
        hub_scores = subgraph.hub_score()
        authority_scores = subgraph.authority_score()
        betweenness_scores = subgraph.vs["betweenness"]
        inner_out_degree = subgraph.outdegree()
        exit_edges = [
            out_degree_by_idx[int(subgraph.vs[i]["idx"])] - inner_out_degree[i]
            for i in range(subgraph.vcount())
        ]

        roles = {
            "hub": int(subgraph.vs[int(np.argmax(hub_scores))]["idx"]),
            "authority": int(subgraph.vs[int(np.argmax(authority_scores))]["idx"]),
            "center": int(subgraph.vs[int(np.argmax(betweenness_scores))]["idx"]),
            "bridge": int(subgraph.vs[int(np.argmax(exit_edges))]["idx"]),
        }
        specials.append(SpecialNodes(community=item.community, roles=roles))

    log.info("特殊節點完成:%d 個社群 × %d 個角色", len(specials), len(ROLES))
    return specials


def _connection_counts(
    graph: ig.Graph, communities: set[int]
) -> dict[tuple[int, int], int]:
    """統計有效社群之間的跨社群連結數(只算兩端都是有效社群的邊)。"""
    membership = graph.vs["community"]
    counts: dict[tuple[int, int], int] = {}
    for edge in graph.es:
        source = int(membership[edge.source])
        target = int(membership[edge.target])
        if source == target or source not in communities or target not in communities:
            continue
        key = (source, target)
        counts[key] = counts.get(key, 0) + 1
    return counts


def build_community_relation(graph: ig.Graph, specials: list[SpecialNodes]) -> ig.Graph:
    """建出社群關係 meta-graph(前端主畫面看到的那張圖)。

    頂點:每個有效社群的四個特殊節點。只有 `bridge` 之間有邊 —— 社群與社群的關係由
    bridge 代表;其餘三個角色是同一個社群的補充資訊,沿用該社群 bridge 的 flow/betweenness。

    頂點屬性:`idx`、`community`、`role`、`title`、`title_display`、`flow`、`betweenness`
    邊屬性:`source_idx`、`target_idx`、`connections_num`、`distance`、`betweenness`
        - `connections_num`:兩個社群之間實際的連結數(邊粗細)
        - `distance`:兩個社群 center 節點在全圖上的最短路徑長度(跳數)
        - `betweenness`:meta-graph 上以 distance 為權重的 edge betweenness
    """
    relation = ig.Graph(directed=True)
    if not specials:
        return relation

    by_idx = {int(idx): i for i, idx in enumerate(graph.vs["idx"])}
    titles = graph.vs["title"]
    display_titles = graph.vs["title_display"]
    communities = {item.community for item in specials}
    counts = _connection_counts(graph, communities)

    # --- 頂點:每個社群一個 bridge ---
    bridge_specials = [item for item in specials if "bridge" in item.roles]
    relation.add_vertices(len(bridge_specials))
    relation.vs["idx"] = [item.roles["bridge"] for item in bridge_specials]
    relation.vs["community"] = [item.community for item in bridge_specials]
    relation.vs["role"] = ["bridge"] * len(bridge_specials)
    relation.vs["title"] = [titles[by_idx[item.roles["bridge"]]] for item in bridge_specials]
    relation.vs["title_display"] = [
        display_titles[by_idx[item.roles["bridge"]]] for item in bridge_specials
    ]
    row_of_community = {item.community: i for i, item in enumerate(bridge_specials)}

    # --- 邊:只建真的有跨社群連結的方向 ---
    edges = [
        (row_of_community[source], row_of_community[target])
        for (source, target) in counts
        if source in row_of_community and target in row_of_community
    ]
    connections = [
        counts[(source, target)]
        for (source, target) in counts
        if source in row_of_community and target in row_of_community
    ]
    relation.add_edges(edges)
    relation.es["connections_num"] = connections
    relation.es["source_idx"] = [e.source_vertex["idx"] for e in relation.es]
    relation.es["target_idx"] = [e.target_vertex["idx"] for e in relation.es]

    # --- distance:全圖上兩個社群 center 的最短跳數 ---
    center_vertices = [by_idx[item.roles["center"]] for item in bridge_specials]
    hop_matrix = graph.distances(source=center_vertices, target=center_vertices, mode="out")
    finite = [d for row in hop_matrix for d in row if np.isfinite(d) and d > 0]
    unreachable_distance = (max(finite) + 1) if finite else 1.0
    distances = []
    for edge in relation.es:
        hops = hop_matrix[edge.source][edge.target]
        # center 之間走不到(有向圖可能單向不可達)時給一個比最遠還遠的有限值,
        # 用 inf 會讓加權 betweenness 失去意義。
        distances.append(float(hops) if np.isfinite(hops) and hops > 0 else unreachable_distance)
    relation.es["distance"] = distances

    # --- meta-graph 上的中心性 ---
    if relation.ecount() > 0:
        relation.vs["flow"] = relation.pagerank(directed=True, weights="connections_num")
        relation.vs["betweenness"] = relation.betweenness(directed=True, weights="distance")
        relation.es["betweenness"] = relation.edge_betweenness(directed=True, weights="distance")
    else:
        relation.vs["flow"] = [1.0 / relation.vcount()] * relation.vcount()
        relation.vs["betweenness"] = [0.0] * relation.vcount()

    # --- 其餘三個角色:同社群的補充節點,沿用 bridge 的 flow/betweenness ---
    extra_attrs: list[dict[str, object]] = []
    for item in bridge_specials:
        bridge_row = row_of_community[item.community]
        for role in ROLES:
            if role == "bridge":
                continue
            idx = item.roles.get(role)
            if idx is None or idx == item.roles["bridge"]:
                # 同一個節點同時是 bridge 又是別的角色時不重複建點
                continue
            extra_attrs.append(
                {
                    "idx": idx,
                    "community": item.community,
                    "role": role,
                    "title": titles[by_idx[idx]],
                    "title_display": display_titles[by_idx[idx]],
                    "flow": relation.vs[bridge_row]["flow"],
                    "betweenness": relation.vs[bridge_row]["betweenness"],
                }
            )
    for attrs in extra_attrs:
        relation.add_vertex(**attrs)

    log.info(
        "社群關係圖完成:%d 個頂點 / %d 條邊(%d 個社群)",
        relation.vcount(),
        relation.ecount(),
        len(bridge_specials),
    )
    return relation

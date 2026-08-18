"""Phase 2 的測試:建圖、邊權重、社群偵測、有效子圖、特殊節點、社群關係圖。

用固定的合成圖(兩個各 5 個節點的團,只靠一對邊相連),不依賴真實維基資料,
社群結構才有明確的預期答案。
"""

from __future__ import annotations

import pytest

from wiki_pipeline.communities import (
    ROLES,
    build_community_relation,
    detect_communities,
    effective_subgraphs,
    mark_special_nodes,
)
from wiki_pipeline.config import CommunityConfig
from wiki_pipeline.graph_build import ArticleRecord, build_graph
from wiki_pipeline.weighting import MIN_WEIGHT, assign_topology_weights, neighbor_sets, topology_similarity

CLUSTER_A = [1, 2, 3, 4, 5]
CLUSTER_B = [6, 7, 8, 9, 10]
# 5 與 6 是唯一有跨團連結的節點 → 它們一定是各自社群的 bridge
CROSS_LINKS = {5: [6], 6: [5]}


def _records() -> list[ArticleRecord]:
    records = []
    for cluster in (CLUSTER_A, CLUSTER_B):
        for idx in cluster:
            targets = [other for other in cluster if other != idx]
            targets += CROSS_LINKS.get(idx, [])
            records.append(
                ArticleRecord(
                    idx=idx,
                    title=f"條目{idx}",
                    title_display=f"條目{idx}",
                    directed_index=targets,
                )
            )
    return records


@pytest.fixture
def graph():
    g = build_graph(_records())
    assign_topology_weights(g)
    return g


@pytest.fixture
def config() -> CommunityConfig:
    # 小圖:每個社群 5 個節點,門檻必須調低才留得住
    return CommunityConfig(min_node_num=3, max_node_num=200)


# --- 建圖 -------------------------------------------------------------------


def test_build_graph_shapes_and_attributes() -> None:
    g = build_graph(_records())
    assert g.is_directed()
    assert g.vcount() == 10
    assert g.ecount() == 5 * 4 * 2 + 2  # 兩個團各 20 條有向邊 + 2 條跨團邊
    assert set(g.vs["idx"]) == set(CLUSTER_A + CLUSTER_B)
    assert g.vs[0]["title_display"] == "條目1"


def test_build_graph_drops_self_loops_and_duplicates() -> None:
    records = [
        ArticleRecord(1, "甲", "甲", [1, 2, 2]),  # 自環 + 重複邊
        ArticleRecord(2, "乙", "乙", [1]),
    ]
    g = build_graph(records)
    assert g.ecount() == 2  # 1→2、2→1
    assert not any(e.source == e.target for e in g.es)


def test_build_graph_ignores_targets_outside_dataset() -> None:
    records = [ArticleRecord(1, "甲", "甲", [2, 999]), ArticleRecord(2, "乙", "乙", [])]
    g = build_graph(records)
    assert g.ecount() == 1


# --- 邊權重 -----------------------------------------------------------------


def test_topology_similarity_is_asymmetric() -> None:
    """分母只看 target 的鄰居數,所以兩個方向的權重不同 —— 這是舊版的行為,要保留。"""
    # a 的鄰居 {c, d};b 的鄰居 {c};共同鄰居 {c}
    neighbors = [{2, 3}, {2}, set(), set()]
    forward = topology_similarity(neighbors, 0, 1)  # |{c}| / |{c}| = 1
    backward = topology_similarity(neighbors, 1, 0)  # |{c}| / |{c,d}| = 0.5
    assert forward == pytest.approx(1.0)
    assert backward == pytest.approx(0.5)
    assert forward != backward


def test_topology_similarity_floor_when_no_common_neighbor() -> None:
    neighbors = [{2}, {3}, set(), set()]
    assert topology_similarity(neighbors, 0, 1) == MIN_WEIGHT


def test_all_weights_are_positive(graph) -> None:
    """Infomap 的邊權重必須是正數,0 會讓那條邊等於不存在。"""
    assert graph.ecount() > 0
    assert all(w > 0 for w in graph.es["weight"])


def test_weights_match_manual_similarity(graph) -> None:
    neighbors = neighbor_sets(graph)
    edge = graph.es[0]
    assert edge["weight"] == pytest.approx(topology_similarity(neighbors, edge.source, edge.target))


# --- 社群偵測 ---------------------------------------------------------------


def test_detect_communities_finds_the_two_clusters(graph) -> None:
    result = detect_communities(graph, trials=10)
    assert len(result.membership) == graph.vcount()
    assert all(c is not None for c in graph.vs["community"])

    by_idx = {int(v["idx"]): v["community"] for v in graph.vs}
    assert len({by_idx[i] for i in CLUSTER_A}) == 1
    assert len({by_idx[i] for i in CLUSTER_B}) == 1
    assert by_idx[1] != by_idx[6]
    assert result.community_sizes == {by_idx[1]: 5, by_idx[6]: 5}


def test_detect_communities_requires_weights() -> None:
    g = build_graph(_records())
    with pytest.raises(ValueError, match="assign_topology_weights"):
        detect_communities(g)


# --- 有效子圖 ---------------------------------------------------------------


def test_effective_subgraphs_respect_thresholds(graph, config) -> None:
    detect_communities(graph, trials=10)
    subgraphs = effective_subgraphs(graph, config)
    assert len(subgraphs) == 2
    assert {s.graph.vcount() for s in subgraphs} == {5}

    # 上界卡住 → 兩個社群都被濾掉
    assert effective_subgraphs(graph, CommunityConfig(min_node_num=3, max_node_num=4)) == []
    # 下界卡住(區間是「不含下界」)→ 同樣濾掉
    assert effective_subgraphs(graph, CommunityConfig(min_node_num=5, max_node_num=200)) == []


def test_subgraph_carries_expected_attributes(graph, config) -> None:
    detect_communities(graph, trials=10)
    subgraph = effective_subgraphs(graph, config)[0].graph
    assert {"idx", "title", "title_display", "flow", "betweenness"} <= set(
        subgraph.vs.attributes()
    )
    assert set(subgraph.es.attributes()) == {"source_idx", "target_idx", "betweenness"}
    assert sum(subgraph.vs["flow"]) == pytest.approx(1.0)


# --- 特殊節點 ---------------------------------------------------------------


def test_special_nodes_cover_all_roles(graph, config) -> None:
    detect_communities(graph, trials=10)
    subgraphs = effective_subgraphs(graph, config)
    specials = mark_special_nodes(graph, subgraphs)

    assert len(specials) == 2
    for special in specials:
        assert set(special.roles) == set(ROLES)


def test_bridge_is_the_node_with_most_external_links(graph, config) -> None:
    detect_communities(graph, trials=10)
    subgraphs = effective_subgraphs(graph, config)
    specials = mark_special_nodes(graph, subgraphs)

    bridges = {special.roles["bridge"] for special in specials}
    assert bridges == {5, 6}  # 只有這兩個節點有跨團連結


# --- 社群關係 meta-graph ----------------------------------------------------


def test_community_relation_graph_structure(graph, config) -> None:
    detect_communities(graph, trials=10)
    subgraphs = effective_subgraphs(graph, config)
    specials = mark_special_nodes(graph, subgraphs)
    relation = build_community_relation(graph, specials)

    bridges = [v for v in relation.vs if v["role"] == "bridge"]
    assert len(bridges) == 2
    assert {v["idx"] for v in bridges} == {5, 6}

    # 兩個社群互相有一條跨社群連結 → 兩個方向各一條邊
    assert relation.ecount() == 2
    for edge in relation.es:
        assert edge["connections_num"] == 1
        assert edge["distance"] > 0
        assert edge["betweenness"] is not None

    # 其餘角色也在圖上,且沿用同社群 bridge 的 flow
    roles = {v["role"] for v in relation.vs}
    assert roles <= set(ROLES)
    assert all(v["flow"] is not None for v in relation.vs)


def test_community_relation_is_empty_without_specials(graph) -> None:
    assert build_community_relation(graph, []).vcount() == 0

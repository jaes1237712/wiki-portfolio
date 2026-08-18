"""Phase 2b — 邊權重(拓樸相似度)。

改寫自 `docs/legacy/data_factory/analyze.py` 的 `config_weight_topology` 與
`graph_utils.get_similarity_topology`(第 968 行)。

權重定義(**刻意保留舊版的非對稱性**):

    w(u → v) = |N(u) ∩ N(v)| / |N(v)|

兩個條目共用的鄰居越多、而且 v 本身鄰居越少,這條邊就越重。因為分母只看 v,
所以 w(u→v) ≠ w(v→u) —— 這是原本就有的行為,移植時不要「順手修正」成對稱版本,
否則 Infomap 分出來的社群會跟舊版對不起來。

兩個要注意的地方:
- `N(·)` 是**全部**鄰居(進+出)。舊版 docstring 寫「出邊」,但程式用的是
  `G.neighbors()`,igraph 預設 mode="all";這裡照實際行為走。
- 共同鄰居為 0 時給 0.0001 而不是 0:Infomap 的邊權重必須是正數,0 會讓那條邊等於不存在。

效能:舊版對「每條邊」都重新呼叫 `G.neighbors()` 兩次(O(E·deg));這裡先把每個節點的
鄰居集合算好一次,之後只做集合交集。
"""

from __future__ import annotations

import logging

import igraph as ig

log = logging.getLogger(__name__)

#: 沒有共同鄰居時的最小權重(必須 > 0,Infomap 才會把這條邊當成存在)。
MIN_WEIGHT = 0.0001


def neighbor_sets(graph: ig.Graph) -> list[set[int]]:
    """每個節點的鄰居集合(含進出邊,與舊版 `G.neighbors()` 預設一致)。"""
    return [set(graph.neighbors(v, mode="all")) for v in range(graph.vcount())]


def topology_similarity(neighbors: list[set[int]], source: int, target: int) -> float:
    """`|N(source) ∩ N(target)| / |N(target)|`,沒有共同鄰居時回 `MIN_WEIGHT`。"""
    source_neighbors = neighbors[source]
    target_neighbors = neighbors[target]
    if not source_neighbors or not target_neighbors:
        return MIN_WEIGHT
    common = len(source_neighbors & target_neighbors)
    if common == 0:
        return MIN_WEIGHT
    return common / len(target_neighbors)


def assign_topology_weights(graph: ig.Graph) -> ig.Graph:
    """在原圖上寫入 `weight` 邊屬性,回傳同一張圖。"""
    if graph.ecount() == 0:
        graph.es["weight"] = []
        return graph

    neighbors = neighbor_sets(graph)
    graph.es["weight"] = [
        topology_similarity(neighbors, edge.source, edge.target) for edge in graph.es
    ]
    weights = graph.es["weight"]
    log.info(
        "邊權重完成:%d 條邊,平均 %.4f,最大 %.4f",
        len(weights),
        sum(weights) / len(weights),
        max(weights),
    )
    return graph

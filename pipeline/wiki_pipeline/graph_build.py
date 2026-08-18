"""Phase 2a — 從爬取結果建出 igraph 有向圖。

改寫自 `docs/legacy/data_factory/analyze.py` 的 `WikiNetwork.create_network` / `_load_network`。

與舊版的差異:
- 舊版用 `data.iterrows()` 逐列建邊(慢),這裡直接從 SQLite 一次撈出所有邊。
- 舊版把「目標節點不在資料集內」當成要處理的情況;新版爬蟲保證每個連結目標都會建成節點,
  但仍保留過濾,因為之後做子集(例如只取重要條目)時還是可能出現懸空的邊。
- 節點屬性多帶 `title_display`(台灣繁體顯示標題),讓後續階段不必再回查資料庫。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import igraph as ig

from .state import StateStore

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ArticleRecord:
    """一個條目與它的外連(對應 `wiki_network.json` 的一筆)。"""

    idx: int
    title: str
    title_display: str
    directed_index: Sequence[int]


def load_records(path: Path | str) -> list[ArticleRecord]:
    """讀 `wiki_network.json`(Phase 1 的輸出)。"""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        ArticleRecord(
            idx=item["Index"],
            title=item["Title"],
            title_display=item.get("Title_Display") or item["Title"],
            directed_index=item.get("Directed_Index", []),
        )
        for item in raw
    ]


def records_from_store(store: StateStore) -> list[ArticleRecord]:
    """直接從 checkpoint 取資料,省去 JSON 來回。"""
    return [
        ArticleRecord(idx=idx, title=title, title_display=display, directed_index=store.outgoing(idx))
        for idx, title, display in store.iter_articles_full()
    ]


def build_graph(records: Iterable[ArticleRecord]) -> ig.Graph:
    """建出有向圖。頂點屬性:`idx`、`title`、`title_display`。

    自環與重複邊都會被移除(Infomap 與中心性指標都不該被自環影響)。
    """
    records = list(records)
    idx_to_vertex = {record.idx: i for i, record in enumerate(records)}

    graph = ig.Graph(directed=True)
    graph.add_vertices(len(records))
    graph.vs["idx"] = [record.idx for record in records]
    graph.vs["title"] = [record.title for record in records]
    graph.vs["title_display"] = [record.title_display for record in records]

    edges: list[tuple[int, int]] = []
    dangling = 0
    for record in records:
        source = idx_to_vertex[record.idx]
        for target_idx in record.directed_index:
            target = idx_to_vertex.get(target_idx)
            if target is None:
                dangling += 1
                continue
            edges.append((source, target))
    graph.add_edges(edges)

    before = graph.ecount()
    graph.simplify(multiple=True, loops=True)
    log.info(
        "建圖完成:%d 節點 / %d 邊(去掉 %d 條重複或自環,忽略 %d 條指向資料集外的邊)",
        graph.vcount(),
        graph.ecount(),
        before - graph.ecount(),
        dangling,
    )
    return graph


def build_graph_from_store(store: StateStore) -> ig.Graph:
    return build_graph(records_from_store(store))


def vertex_by_idx(graph: ig.Graph) -> dict[int, int]:
    """`idx` → igraph 內部 vertex id 的對照表。"""
    return {int(idx): i for i, idx in enumerate(graph.vs["idx"])}

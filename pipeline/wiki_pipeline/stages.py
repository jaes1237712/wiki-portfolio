"""把各階段串起來的執行進入點(CLI 用)。

每個階段都會把中繼產物寫進 `output/`,下一個階段可以直接讀,不必重跑上一階段:

    scrape       → output/wiki_network.json          (Phase 1)
    graph        → output/graph.graphml              (Phase 2a+2b:建圖 + 邊權重)
    communities  → output/community_relation.graphml (Phase 2c:社群偵測 + 子圖 + 特殊節點)
                   output/subgraphs/community_<id>.graphml
                   output/communities.json

GraphML 沿用舊版當除錯用中繼格式:即使最終資料是進 Postgres,能用 Gephi/igraph 直接打開
一張圖來看,對排查「社群怎麼分成這樣」非常有用。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import igraph as ig

from .communities import (
    CommunityDetection,
    CommunitySubgraph,
    SpecialNodes,
    build_community_relation,
    detect_communities,
    effective_subgraphs,
    mark_special_nodes,
)
from .config import PipelineConfig
from .graph_build import build_graph_from_store, load_records, build_graph
from .state import StateStore
from .weighting import assign_topology_weights

log = logging.getLogger(__name__)

GRAPH_FILE = "graph.graphml"
RELATION_FILE = "community_relation.graphml"
SUBGRAPH_DIR = "subgraphs"
SUMMARY_FILE = "communities.json"


@dataclass
class CommunityArtifacts:
    graph: ig.Graph
    detection: CommunityDetection
    subgraphs: list[CommunitySubgraph]
    specials: list[SpecialNodes]
    relation: ig.Graph


def run_graph_stage(config: PipelineConfig) -> ig.Graph:
    """Phase 2a+2b:從 checkpoint(或 wiki_network.json)建圖並算邊權重。"""
    state_db = config.state_dir / "pipeline.sqlite"
    network_json = config.output_dir / "wiki_network.json"

    if state_db.exists():
        with StateStore(state_db) as store:
            graph = build_graph_from_store(store)
    elif network_json.exists():
        graph = build_graph(load_records(network_json))
    else:
        raise FileNotFoundError(f"找不到 {state_db} 或 {network_json},請先跑 run-stage scrape")

    assign_topology_weights(graph)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    graph.write_graphml(str(config.output_dir / GRAPH_FILE))
    return graph


def load_weighted_graph(config: PipelineConfig) -> ig.Graph:
    """讀 graph 階段的產物;沒有的話就當場重建一次。"""
    path = config.output_dir / GRAPH_FILE
    if not path.exists():
        log.info("找不到 %s,先跑 graph 階段", path)
        return run_graph_stage(config)
    graph = ig.Graph.Read_GraphML(str(path))
    # GraphML 會把數值屬性讀成字串以外的型別不一定一致,idx 一律轉回 int
    graph.vs["idx"] = [int(v) for v in graph.vs["idx"]]
    return graph


def run_communities_stage(config: PipelineConfig) -> CommunityArtifacts:
    """Phase 2c:社群偵測 → 有效子圖 → 特殊節點 → 社群關係 meta-graph。"""
    graph = load_weighted_graph(config)
    detection = detect_communities(graph, trials=5)
    subgraphs = effective_subgraphs(graph, config.community)
    specials = mark_special_nodes(graph, subgraphs)
    relation = build_community_relation(graph, specials)

    write_community_artifacts(
        CommunityArtifacts(graph, detection, subgraphs, specials, relation), config.output_dir
    )
    return CommunityArtifacts(graph, detection, subgraphs, specials, relation)


def write_community_artifacts(artifacts: CommunityArtifacts, output_dir: Path) -> list[Path]:
    """寫出 meta-graph、每個社群的子圖,以及一份人看得懂的摘要 JSON。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    if artifacts.relation.vcount() > 0:
        relation_path = output_dir / RELATION_FILE
        artifacts.relation.write_graphml(str(relation_path))
        written.append(relation_path)

    subgraph_dir = output_dir / SUBGRAPH_DIR
    subgraph_dir.mkdir(parents=True, exist_ok=True)
    for item in artifacts.subgraphs:
        path = subgraph_dir / f"community_{item.community}.graphml"
        item.graph.write_graphml(str(path))
        written.append(path)

    titles = {int(v["idx"]): v["title_display"] for v in artifacts.graph.vs}
    summary = {
        "codelength": artifacts.detection.codelength,
        "community_count": len(artifacts.detection.community_sizes),
        "effective_community_count": len(artifacts.subgraphs),
        "community_sizes": artifacts.detection.community_sizes,
        "communities": [
            {
                "community": special.community,
                "size": next(
                    s.graph.vcount() for s in artifacts.subgraphs if s.community == special.community
                ),
                "special_nodes": {
                    role: {"idx": idx, "title": titles.get(idx)}
                    for role, idx in special.roles.items()
                },
            }
            for special in artifacts.specials
        ],
    }
    summary_path = output_dir / SUMMARY_FILE
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    written.append(summary_path)
    return written
